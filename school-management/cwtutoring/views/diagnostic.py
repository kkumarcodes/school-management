from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListCreateAPIView, UpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework import status

from cwcommon.mixins import AdminContextMixin, CSVMixin
from cwcommon.models import FileUpload
from cwtasks.models import Task
from cwtutoring.models import (
    Diagnostic,
    DiagnosticGroupTutoringSessionRegistration,
    DiagnosticResult,
    Location,
    TestResult,
)
from cwtutoring.serializers.diagnostics import (
    DiagnosticRegistrationCounselorSerializer,
    DiagnosticRegistrationSerializer,
    DiagnosticResultSerializer,
    DiagnosticSerializer,
    TestResultSerializer,
)
from cwtutoring.serializers.tutoring_sessions import LocationSerializer
from cwtutoring.utilities.diagnostic_result_manager import DiagnosticResultManager
from cwusers.mixins import AccessStudentPermission
from cwusers.models import Administrator, Counselor, Parent, Student, Tutor


class LocationViewset(ModelViewSet):
    serializer_class = LocationSerializer
    permission_classes = (IsAuthenticated,)
    queryset = Location.objects.all()

    def check_permissions(self, request):
        if request.method.lower() != "get" and not hasattr(request.user, "administrator"):
            self.permission_denied(request, message="Cannot alter location objects")
        return super(LocationViewset, self).check_permissions(request)


class DiagnosticViewset(ModelViewSet, AccessStudentPermission):
    serializer_class = DiagnosticSerializer
    permission_classes = (AllowAny,)  # We return self-assignable diags to landing page, so no auth required
    queryset = Diagnostic.objects.all()

    def filter_queryset(self, queryset):
        if not self.request.user.is_authenticated:
            return queryset.filter(can_self_assign=True)
        # Admins, tutors, counselors get everything
        if (
            hasattr(self.request.user, "administrator")
            or hasattr(self.request.user, "tutor")
            or hasattr(self.request.user, "counselor")
        ):
            return queryset

        if hasattr(self.request.user, "student"):
            return queryset.filter(Q(can_self_assign=True) | Q(tasks__for_user=self.request.user)).distinct()
        if hasattr(self.request.user, "parent"):
            students = self.request.user.parent.students.all()
            return queryset.filter(Q(can_self_assign=True) | Q(tasks__for_user__student__in=students)).distinct()
        return Diagnostic.objects.none()

    def check_permissions(self, request):
        """ Only admins can create or update. All users can GET any object """
        super(DiagnosticViewset, self).check_permissions(request)
        if request.method.lower() != "get" and not (
            request.user.is_authenticated and hasattr(request.user, "administrator")
        ):
            self.permission_denied(request)

    def check_object_permissions(self, request, obj):
        """ Students can only retrieve diagnostics that are self-assignable OR
            are assigned to the student
        """
        super(DiagnosticViewset, self).check_object_permissions(request, obj)
        if not request.user.is_authenticated:
            self.permission_denied(request)
        if (
            obj.can_self_assign
            or (
                hasattr(request.user, "administrator")
                or hasattr(request.user, "tutor")
                or hasattr(request.user, "counselor")
            )
            or Task.objects.filter(diagnostic=obj)
            .filter(Q(for_user=request.user) | Q(for_user__parent__student__user=request.user))
            .exists()
        ):
            return True
        self.permission_denied(request)

    def perform_destroy(self, instance):
        """ We archive diagnostics instead of deleting """
        instance.archived = True
        instance.save()

    @action(methods=["GET"], detail=False, url_path="assigned", url_name="assigned")
    def get_assigned(self, request, *args, **kwargs):
        """ Retrieve the diagnostics that have already been assigned to a student
            Query Params:
                ?student {PK} Student to get completed diagnostics for
        """
        student = get_object_or_404(Student, pk=request.query_params.get("student"))
        if not self.has_access_to_student(student):
            self.permission_denied(request)
        diagnostics = Diagnostic.objects.filter(tasks__for_user=student.user, tasks__archived=None).distinct()
        return Response(self.get_serializer(diagnostics, many=True).data)


class DiagnosticResultViewset(ModelViewSet, AdminContextMixin, AccessStudentPermission):
    """ LIST:
            If admin: All results not visible to students are returned. Most recent 100 returned to students are also
                included. Admin fields on serializer are also returned for convenience:
                student_name, recommender_name, submitted_by
            If counselor or tutor: Results are returned for their students
            If student: Results for only this student are returned

            Can filter further with query params:
                ?student {Student PK}

    """

    serializer_class = DiagnosticResultSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        # Override queryset to only allow records for students that user has access to
        admin = Administrator.objects.filter(user=self.request.user).first()
        tutor = Tutor.objects.filter(user=self.request.user).first()
        if admin or (tutor and tutor.is_diagnostic_evaluator):
            # Tutor evaluators get their own students plus DRs that they are assigned
            queryset = DiagnosticResult.objects.all()
            if tutor:
                queryset = queryset.filter(Q(assigned_to=tutor.user) | Q(student__tutors=tutor)).distinct()
            return queryset

        counselor = Counselor.objects.filter(user=self.request.user).first()
        # If counselor or tutor, we return test results for all of their students
        if counselor or tutor:
            kwargs = {}
            if counselor:
                kwargs["student__counselor"] = counselor
            if tutor:
                kwargs["student__tutors"] = tutor
            return DiagnosticResult.objects.filter(**kwargs)
        student = Student.objects.filter(user=self.request.user).first()
        if student:
            return student.diagnostic_results.filter(state=DiagnosticResult.STATE_VISIBLE_TO_STUDENT)
        parent = Parent.objects.filter(user=self.request.user).first()
        if parent:
            return DiagnosticResult.objects.filter(
                state=DiagnosticResult.STATE_VISIBLE_TO_STUDENT, student__parent=parent
            )

        return DiagnosticResult.objects.none()

    def get_serializer_context(self):
        """ We consider tutors who can evaluate to be admins (so they get admin serializer fields) """
        ctx = super().get_serializer_context()
        if (
            hasattr(self.request, "administrator")
            or Tutor.objects.filter(is_diagnostic_evaluator=True, user=self.request.user).exists()
        ):
            ctx["admin"] = True
        return ctx

    def filter_queryset(self, queryset):
        """ Filter for student """
        super().filter_queryset(queryset)
        if self.request.query_params.get("student"):
            queryset = queryset.filter(student__pk=self.request.query_params["student"])
        elif hasattr(self.request.user, "administrator"):
            # All unreturned, plus 50 most recently returned to student (Unless we're filtering for a specific student)
            queryset = (
                DiagnosticResult.objects.exclude(state=DiagnosticResult.STATE_VISIBLE_TO_STUDENT)
                | DiagnosticResult.objects.filter(state=DiagnosticResult.STATE_VISIBLE_TO_STUDENT).order_by("-created")[
                    :60
                ]
            )
        return queryset

    def check_object_permissions(self, request, obj):
        """ Ensure current user has access to TestResult """
        super().check_object_permissions(request, obj)
        if not (
            self.has_access_to_student(obj.student, request=request)
            or Tutor.objects.filter(is_diagnostic_evaluator=True, user=request.user).exists()
        ):
            self.permission_denied(request)

    def check_permissions(self, request):
        """ Make sure that user has access to student when creating TestResult """
        super(DiagnosticResultViewset, self).check_permissions(request)
        if request.method.lower() == "post":
            student = get_object_or_404(Student, pk=request.data.get("student"))
            if not (student and self.has_access_to_student(student, request=request)):
                self.permission_denied(request)
        if request.query_params.get("student"):
            student = get_object_or_404(Student, pk=request.query_params["student"])
            if not self.has_access_to_student(student, request=request):
                self.permission_denied(request)

    def perform_create(self, serializer):
        """ We automatically complete related task(s) """
        diagnostic_result = serializer.save()
        manager = DiagnosticResultManager(diagnostic_result)
        return manager.create()

    """ We use dedicated routes for each of the actions in DiagnosticResultManager, which transition
        a DiagnosticResult's state
    """

    @action(methods=["PATCH"], detail=True, url_path="reassign", url_name="reassign")
    def reassign(self, request, *args, **kwargs):
        """ Reassign a DiagnosticResult, and then send notification(s)
        """
        diagnostic_result: DiagnosticResult = self.get_object()
        assignee: User = get_object_or_404(User, pk=request.data.get("assigned_to"))
        if not (
            hasattr(assignee, "administrator")
            or Tutor.objects.filter(is_diagnostic_evaluator=True, user=assignee).exists()
        ):
            raise ValidationError("Invalid Assignee")

        mgr = DiagnosticResultManager(diagnostic_result)
        diagnostic_result = mgr.reassign(assignee)
        mgr.send_notifications()
        return Response(self.get_serializer(instance=diagnostic_result).data)

    @action(
        methods=["PATCH"], detail=True, url_path="transition-state", url_name="transition_state",
    )
    def transition_state(self, request, pk=None):
        """ Transition state of DiagnosticResult.
            Arguments:
                state {One of Diagnostic.STATES} (ps, pr, pe, v)
                score {optional; number}
                recommendation_file_upload {optional; UploadFile Slug!}
                return_to_student {optiona; default false.} If transitioning to PENDING_RETURN,
                    this flag can be used to make DiagnosticResult immediately visible to student,
                    bypassing counselor approval

            Returns: Updated DiagnosticReesult
        """
        obj = self.get_object()
        mgr = DiagnosticResultManager(obj)

        # Validate request.data
        file_upload = None
        if request.data.get("recommendation_file_upload"):
            file_upload = get_object_or_404(FileUpload, slug=request.data.get("recommendation_file_upload"))
        updated_obj = mgr.transition_to_state(
            request.data.get("state"),
            score=request.data.get("score"),
            return_to_student=request.data.get("return_to_student", False),
            recommendation_file_upload=file_upload,
        )
        ser = self.serializer_class(updated_obj, context=self.get_serializer_context())
        return Response(ser.data)


class TestResultViewset(ModelViewSet, AccessStudentPermission):
    serializer_class = TestResultSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        # Override queryset to only allow records for students that user has access to
        admin = Administrator.objects.filter(user=self.request.user).first()
        if admin:
            return TestResult.objects.all()
        counselor = Counselor.objects.filter(user=self.request.user).first()
        tutor = Tutor.objects.filter(user=self.request.user).first()
        parent = Parent.objects.filter(user=self.request.user).first()

        # If counselor, tutor or parent, we return test results for all of their students
        if counselor or tutor or parent:
            kwargs = {}
            if counselor:
                kwargs["student__counselor"] = counselor
            if tutor:
                kwargs["student__tutors"] = tutor
            if parent:
                kwargs["student__parent"] = parent
            return TestResult.objects.filter(**kwargs)
        student = Student.objects.filter(user=self.request.user).first()
        if student:
            return student.test_results.all()
        return TestResult.objects.none()

    def check_object_permissions(self, request, obj):
        """ Ensure current user has access to TestResult """
        super(TestResultViewset, self).check_object_permissions(request, obj)
        if not self.has_access_to_student(obj.student, request=request):
            self.permission_denied(request)

    def check_permissions(self, request):
        """ Make sure that user has access to student when creating TestResult """
        super(TestResultViewset, self).check_permissions(request)

        if request.method.lower() == "post":
            student = get_object_or_404(Student, pk=request.data.get("student"))
            if not student and self.has_access_to_student(student, request=request):
                self.permission_denied(request)


class DiagnosticGroupTutoringSessionRegistrationViewset(CSVMixin, ListCreateAPIView, UpdateAPIView):
    """ Create or list DiagnosticGroupTutoringSessionRegistration objects
        This is where DiagnosticRegistrations from diag landing page are posted
        CREATE
            See DiagnosticRegistrationSerializer for required fields. Of note: student name/email and parent
            name/email are super required. As is group_tutoring_sessions (PKs of sessions student is registering
            for).
            Users will be validated (based on email).
            There will be a bunch of fields that are specific to the frontend form that do not have dedicated
                fields in the database. These fields are treated as metadata and should all be included in a top-leve
                registration_data field (which is saved as a JSONField on the model)
    """

    permission_classes = (AllowAny,)
    serializer_class = DiagnosticRegistrationSerializer
    queryset = DiagnosticGroupTutoringSessionRegistration.objects.all()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["student_slug"] = self.request.data.get("student_slug")
        return ctx

    def create(self, request, *args, **kwargs):
        """ We override create so that we can set student and parent data if student_slug is set """
        data = request.data.copy()
        if request.data.get("student_slug"):
            student = get_object_or_404(Student, slug=request.data["student_slug"])
            data["student_email"] = student.invitation_email
            data["student_name"] = student.name
            if student.parent:
                data["parent_email"] = student.parent.invitation_email
                data["parent_name"] = student.parent.name
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method.lower() != "post" and not hasattr(request.user, "administrator"):
            self.permission_denied(request)


class DiagnosticLandingPageView(TemplateView):
    """ Landing page view for users to register for diagnostics
        Context:
            student_slug for student if and only if ?s query param is provided and is valid slug for a student
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        student = None
        if self.request.GET.get("s"):
            student = Student.objects.filter(slug=self.request.GET["s"]).first()
        context["student_slug"] = str(student.slug) if student else None
        return context

    template_name = "cwtutoring/diagnostic_landing_page.html"


class DiagnosticRegistrationCounselorViewset(ModelViewSet):
    serializer_class = DiagnosticRegistrationCounselorSerializer
    queryset = Counselor.objects.all()
