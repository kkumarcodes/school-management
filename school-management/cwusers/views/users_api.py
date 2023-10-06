"""
    This module contains CRUD views for all cwusers user types
    as well as special actions:
"""

from django.http.response import HttpResponseRedirect
from cwcommon.mixins import AdminContextMixin, CSVMixin
from cwnotifications.generator import create_notification
from cwresources.utilities.resource_permission_manager import get_resources_for_user
from cwusers.mixins import AccessStudentPermission
from cwusers.models import Administrator, Counselor, Parent, Student, StudentHighSchoolCourse, Tutor, get_cw_user
from cwusers.serializers.users import (
    AdminListStudentSerializer,
    MODEL_TO_SERIALIZER,
    AdministratorSerializer,
    CounselorSerializer,
    ParentSerializer,
    StudentHighSchoolCourseSerializer,
    StudentLastPaidMeetingSerializer,
    StudentSerializer,
    StudentSerializerCounseling,
    TutorSerializer,
)
from cwusers.utilities.zoom_manager import PRO_ZOOM_URLS, ZoomManager, ZoomManagerException
from django.contrib.auth.models import User
from django.db.models import Q, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet


class StudentHighSchoolCourseViewset(ModelViewSet, AccessStudentPermission):
    """ Manipulate StudentHighSchoolCourse objects.
        LIST:
            ?student query param required. User must have access to student
        CREATE/UPDATE/DELETE:
            User must have access to student. Changing student field not supported for update
    """

    serializer_class = StudentHighSchoolCourseSerializer
    permission_classes = (IsAuthenticated,)
    queryset = StudentHighSchoolCourse.objects.all()

    def list(self, request, *args, **kwargs):
        """ Filter for student (student query param required) """
        if request.query_params.get("student"):
            student = get_object_or_404(Student, pk=request.query_params.get("student"))
            return Response(
                self.serializer_class(
                    student.high_school_courses.all(), context=self.get_serializer_context(), many=True,
                ).data
            )
        if hasattr(request.user, "student"):
            return Response(
                self.serializer_class(
                    request.user.student.high_school_courses.all(), context=self.get_serializer_context(), many=True,
                ).data
            )

        return HttpResponseBadRequest("Student query param required")

    def check_object_permissions(self, request, obj):
        super(StudentHighSchoolCourseViewset, self).check_object_permissions(request, obj)
        if not self.has_access_to_student(obj.student):
            self.permission_denied(request)

    def check_permissions(self, request):
        super(StudentHighSchoolCourseViewset, self).check_permissions(request)
        student = None
        if request.method.lower() == "post":
            student = get_object_or_404(Student, pk=request.data.get("student"))
        elif request.query_params.get("student"):
            student = get_object_or_404(Student, pk=request.query_params.get("student"))
        if student and not self.has_access_to_student(student):
            self.permission_denied(request)


class StudentViewset(CSVMixin, ModelViewSet, AccessStudentPermission):
    """ Note that this viewset supports two serializers: StudentSerializer and StudentSerializerCounseling
        StudentSerializer is the default.
        StudentSerializerCounseling is used if ?platform=counseling is included as query param. This serializer should
            be used (by both counselors and students) on the counseling platform, and by admins on the admin platform
    """

    permission_classes = (IsAuthenticated,)

    @action(
        detail=False, methods=["GET"], url_path="last-paid-meeting", url_name="last_paid_meeting",
    )
    def last_paid_meeting(self, request, *args, **kwargs):
        if not hasattr(request.user, "administrator"):
            self.permission_denied(request)
        return Response(StudentLastPaidMeetingSerializer(Student.objects.all(), many=True).data)

    def get_serializer_class(self):
        """ We have different serializers for counseling and CAS platforms """
        if hasattr(self.request.user, "administrator") and self.request.query_params.get("condensed"):
            return AdminListStudentSerializer
        if self.request.query_params.get("platform") == "tutoring" and hasattr(self.request.user, "counselor"):
            return StudentSerializer
        if self.request.query_params.get("platform") == "counseling" or hasattr(self.request.user, "counselor"):
            return StudentSerializerCounseling
        if self.request.query_params.get("platform") == "tutoring" or hasattr(self.request.user, "tutor"):
            return StudentSerializer
        if hasattr(self.request.user, "student") and len(self.request.user.student.counseling_student_types_list) > 0:
            return StudentSerializerCounseling
        return StudentSerializer

    def check_permissions(self, request):
        super(StudentViewset, self).check_permissions(request)
        if request.method.lower() == "post" and not (
            hasattr(request.user, "administrator") or hasattr(request.user, "counselor")
        ):
            self.permission_denied(request)

        if request.method.lower() == "post" and request.data.get("visible_resources"):
            # Ensure user has access to all resources
            if (
                len(request.data["visible_resources"])
                > get_resources_for_user(request.user, include_archived_resources=True).count()
            ):
                self.permission_denied("No access to resource(s)")

    def check_object_permissions(self, request, obj):
        super(StudentViewset, self).check_object_permissions(request, obj)
        if not (self.has_access_to_student(obj) or hasattr(request.user, "administrator")):
            self.permission_denied(request)

        if request.data.get("visible_resources"):
            new_resources = set(request.data["visible_resources"]).difference(
                obj.visible_resources.values_list("pk", flat=True)
            )
            if len(new_resources) > get_resources_for_user(request.user, include_archived_resources=True).count():
                self.permission_denied(request, message="No access to resource(s)")

    def get_serializer_context(self):
        """ Need to add tutor to context (when applicable) so we get proper next and last meeting dates from serializer
        """
        context = super(StudentViewset, self).get_serializer_context()
        if self.request.query_params.get("tutor"):
            context["tutor"] = get_object_or_404(Tutor, pk=self.request.query_params["tutor"])
        context["admin"] = Administrator.objects.filter(user=self.request.user).first()
        return context

    @action(
        detail=True, methods=["GET"], url_path="cpp-notes", url_name="cpp_notes",
    )
    def cpp_notes(self, request, *args, **kwargs):
        """ Redirect to the latest and greatest CPP notes for student (or 404) """
        student: Student = self.get_object()
        if not student.cpp_notes:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return HttpResponseRedirect(student.cpp_notes.url)

    def update(self, request, *args, **kwargs):
        """Override to update is_active field on user """
        old_student: Student = self.get_object()
        has_cap_access = old_student.has_access_to_cap
        serializer = self.get_serializer(old_student, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        student: Student = serializer.save()
        if "is_active" in request.data:
            student.user.is_active = request.data["is_active"]
            student.user.save()
        if (
            student.accepted_invite
            and student.counseling_student_types_list
            and student.has_access_to_cap
            and not has_cap_access
        ):
            # We send cap invite notification
            create_notification(student.user, notification_type="invite")
            if student.parent:
                create_notification(student.parent.user, notification_type="invite")
        return Response(self.get_serializer(student).data)

    def get_queryset(self):
        if self.request.query_params.get("tutor"):
            tutor: Tutor = get_object_or_404(Tutor, pk=self.request.query_params["tutor"])
            if not (hasattr(self.request.user, "administrator") or tutor.user == self.request.user):
                self.permission_denied(self.request)
            return tutor.students.all()
        if self.request.query_params.get("counselor"):
            counselor = get_object_or_404(Counselor, pk=self.request.query_params["counselor"])
            if not (hasattr(self.request.user, "counselor") or counselor.user == self.request.user):
                self.permission_denied(self.request)
            return counselor.students.all()
        if hasattr(self.request.user, "administrator"):
            return Student.objects.all()

        return (
            Student.objects.filter(
                Q(tutors__user=self.request.user)
                | Q(counselor__user=self.request.user)
                | Q(user=self.request.user)
                | Q(parent__user=self.request.user)
            )
            .select_related("user", "user__notification_recipient", "parent__user", "counselor__user")
            .prefetch_related("visible_resources", "visible_resource_groups", "tutors")
            .annotate(purchased_hours=Sum("tutoring_package_purchases__tutoring_package__group_test_prep_hours"),)
            .distinct()
        )


class CounselorViewset(CSVMixin, AdminContextMixin, ModelViewSet):
    serializer_class = CounselorSerializer
    permission_classes = (IsAuthenticated,)
    queryset = Counselor.objects.all().select_related("user")

    def check_permissions(self, request):
        super(CounselorViewset, self).check_permissions(request)
        if hasattr(request.user, "administrator"):
            return True
        # Only admins can create
        if request.method.lower() == "post":
            self.permission_denied(request)
        # Tutors and counselors can list
        if not self.kwargs.get("pk") and not (hasattr(request.user, "tutor") or hasattr(request.user, "counselor")):
            self.permission_denied(request)
        # Other permissions fall through to object permission

    def check_object_permissions(self, request, obj):
        if request.method.lower() != "get" and not hasattr(request.user, "administrator") and obj.user != request.user:
            self.permission_denied(request)
        if (
            hasattr(request.user, "counselor")
            or hasattr(request.user, "tutor")
            or hasattr(request.user, "administrator")
        ):
            return True
        # Must be student or parent of student for counselor
        if (
            not Counselor.objects.filter(pk=obj.pk)
            .filter(Q(students__user=request.user) | Q(students__parent__user=request.user))
            .exists()
        ):
            self.permission_denied(request)


class AdministratorViewset(CSVMixin, AdminContextMixin, ModelViewSet):
    serializer_class = AdministratorSerializer
    permission_classes = (IsAuthenticated,)
    queryset = Administrator.objects.all()

    def check_permissions(self, request):
        super().check_permissions(request)
        if hasattr(request.user, "administrator"):
            return True
        if request.method.lower() == "get":
            return hasattr(request.user, "counselor") or hasattr(request.user, "tutor")
        self.permission_denied(request)


class TutorViewset(CSVMixin, AdminContextMixin, ModelViewSet):
    """ Typical CRUD viewset. See serializer for fields.
        One addition:
            Optional create_zoom_account boolean in data. If included, then we'll
            attempt to create a Zoom account for the new user.
    """

    serializer_class = TutorSerializer
    permission_classes = (IsAuthenticated,)
    queryset = Tutor.objects.all()

    def check_object_permissions(self, request, obj):
        # Is tutor's student, or their parent, or a counselor
        valid = False
        if not (Administrator.objects.filter(user=request.user) or Counselor.objects.filter(user=request.user)):
            if hasattr(request.user, "student"):
                valid = valid or request.user.student.tutors.filter(pk=obj.pk).exists()
            elif hasattr(request.user, "tutor"):
                valid = (
                    valid
                    or request.user.tutor == obj
                    or Student.objects.filter(tutors=request.user.tutor).filter(tutors=obj).exists()
                )
            elif hasattr(request.user, "parent"):
                valid = valid or request.user.parent.students.filter(tutors=obj).exists
        else:
            valid = True
        if not valid:
            self.permission_denied(request, message="No access to tutor")

    @action(
        detail=True, methods=["POST"], url_path="invite-zoom", url_name="invite_zoom",
    )
    def invite_zoom(self, request, pk=None):
        """ Use this view to send a zoom invite to a tutor. Returns 400 if user already has zoom pmi
            Returns: Tutor (will be updated if it turns out zoom account already existed)
        """
        tutor = self.get_object()
        if tutor.zoom_url:
            return HttpResponseBadRequest("Tutor already has Zoom URL")
        mgr = ZoomManager()
        tutor = mgr.create_zoom_user(tutor)
        return Response(self.serializer_class(tutor, context=self.get_serializer_context()).data)

    def create(self, request, *args, **kwargs):
        """ Override create  to attempt to create Zoom account for user if needed """
        create_zoom_account = request.data.pop("create_zoom_account", False)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        tutor = Tutor.objects.get(pk=serializer.data["pk"])
        headers = self.get_success_headers(serializer.data)
        if create_zoom_account:
            # Attempt to create zoom account. if Zoom account for tutor already exists, zoom fields on tutor
            # obj will get udpated
            zoom_manager = ZoomManager()

            try:
                tutor = zoom_manager.create_zoom_user(tutor)

            except ZoomManagerException:
                return Response(
                    {
                        "tutor": self.serializer_class(tutor, context=self.get_serializer_context()).data,
                        "zoom_error": "Failed to create zoom user.",
                    },
                    status=status.HTTP_207_MULTI_STATUS,
                    headers=headers,
                )

        return Response(
            {"tutor": self.serializer_class(tutor, context=self.get_serializer_context()).data, "zoom_error": "",},
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def update(self, request, *args, **kwargs):
        """Override to update is_active field on user """
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        tutor: Tutor = serializer.save()
        if "is_active" in request.data:
            tutor.user.is_active = request.data["is_active"]
            tutor.user.save()
        return Response(self.get_serializer(tutor).data)


class ParentViewset(CSVMixin, AdminContextMixin, ModelViewSet):
    serializer_class = ParentSerializer
    permission_classes = (IsAuthenticated,)
    queryset = (
        Parent.objects.all()
        .select_related("user", "user__notification_recipient")
        .prefetch_related("students")
        .distinct()
    )

    def filter_queryset(self, queryset):
        if hasattr(self.request.user, "counselor"):
            return queryset.filter(students__counselor=self.request.user.counselor)
        elif hasattr(self.request.user, "tutor"):
            return queryset.filter(students__tutors=self.request.user.tutor).distinct()
        elif hasattr(self.request.user, "student"):
            return queryset.filter(students=self.request.user.student)
        elif hasattr(self.request.user, "parent"):
            return queryset.filter(pk=self.request.user.parent.pk)
        return queryset

    def check_object_permissions(self, request, obj):
        valid = False
        if request.user == obj.user:
            valid = True
        if hasattr(request.user, "administrator"):
            valid = True
        if hasattr(request.user, "student") and request.user.student.parent == obj:
            valid = True
        if hasattr(request.user, "tutor") and request.user.tutor.students.filter(parent=obj).exists():
            valid = True
        if hasattr(request.user, "counselor") and request.user.counselor.students.filter(parent=obj).exists():
            valid = True
        if not valid:
            self.permission_denied(request, message="No access to this data")

    def update(self, request, *args, **kwargs):
        """Override to update is_active field on user """
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        parent: Parent = serializer.save()
        if "is_active" in request.data:
            parent.user.is_active = request.data["is_active"]
            parent.user.save()
        return Response(self.get_serializer(parent).data)

    def create(self, request, *args, **kwargs):
        """ We actually get or create based on email address """
        existing_parent = Parent.objects.filter(user__username__iexact=request.data.get("email")).first()
        if existing_parent:
            serializer = self.get_serializer(existing_parent, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
        else:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)

        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if not existing_parent else status.HTTP_200_OK,
            headers=headers,
        )


class SendInviteView(AccessStudentPermission, APIView):
    """This view creates an invite Notification for uninvited users. It will return
        400 if user has usable password (has accepted invite).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        """Arguments:
                uuid: UUID (slug) for Student, COunselor, Parent, Tutor, or Administrator
            Returns:
                200 on success
                4xx with user-readable error on failure (prob because user has a
                    usable pwd already)
        """
        uuid = request.data.get("uuid")
        user = User.objects.filter(
            Q(student__slug=uuid)
            | Q(parent__slug=uuid)
            | Q(tutor__slug=uuid)
            | Q(counselor__slug=uuid)
            | Q(administrator__slug=uuid)
        ).first()
        # Permissions - must be admin or someone with access to student to re-invite them
        if user and not (request.user.is_staff or hasattr(user, "parent")):
            cwuser = get_cw_user(user)
            if not isinstance(cwuser, Student) or not self.has_access_to_student(cwuser):
                self.permission_denied(request)

        if not user:
            return Response({}, status=404)
        if user.has_usable_password():
            return HttpResponseBadRequest("User has password set")
        create_notification(user, notification_type="invite")
        cwuser = get_cw_user(user)
        cwuser.last_invited = timezone.now()
        cwuser.save()
        # We try to return serialized user obj
        serializer_class = None
        if isinstance(cwuser, Student):
            serializer_class = (
                StudentSerializer if not hasattr(request.user, "counselor") else StudentSerializerCounseling
            )
        elif type(cwuser) in MODEL_TO_SERIALIZER:
            serializer_class = MODEL_TO_SERIALIZER[type(cwuser)]
        if serializer_class:
            context = {"admin": Administrator.objects.filter(user=request.user).first(), "request": request}
            return Response(serializer_class(cwuser, context=context).data, status=200,)
        return Response({}, status=200)


class ZoomURLView(APIView):
    """ Simple view that returns array of pro zoom urls from zoom_manager.PRO_ZOOM_URLS
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request, *args, **kwargs):
        if not hasattr(request.user, "administrator"):
            self.permission_denied(request)
        return Response(data=PRO_ZOOM_URLS)
