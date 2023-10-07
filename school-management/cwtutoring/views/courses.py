""" Views related to Courses, including CRUD operations and enrollment
"""
from datetime import timedelta

from django.db.models import Q
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from cwtutoring.models import Course
from cwtutoring.serializers.tutoring_sessions import CourseSerializer
from cwtutoring.utilities.tutoring_session_manager import (
    TutoringSessionManager,
    TutoringSessionManagerException,
)
from snusers.models import Student
from snusers.serializers.users import StudentSerializer
from snusers.mixins import AccessStudentPermission
from cwcommon.mixins import CSVMixin


class CourseViewset(AccessStudentPermission, CSVMixin, ModelViewSet):
    serializer_class = CourseSerializer
    queryset = (
        Course.objects.all()
        .order_by("-created")
        .select_related("location")
        .prefetch_related("group_tutoring_sessions")
        .distinct()
    )
    # This endpoint is publicly accessible because it's used on landing page
    permission_classes = (AllowAny,)

    def get_serializer_context(self):
        ctxt = super().get_serializer_context()
        if self.request.user.is_authenticated and hasattr(self.request.user, "administrator"):
            ctxt["admin"] = self.request.user.administrator
        ctxt["landing"] = self.request.query_params.get("landing")
        return ctxt

    def filter_queryset(self, queryset):
        """ Supported filters
            ?landing -- Only future courses that are to be displayed on landing page are returned
        """
        # Unauthenticated users only have access to active courses on landing page
        if (not self.request.user.is_authenticated) or self.request.query_params.get("landing"):
            filter_start = timezone.now() + timedelta(days=2)
            return (
                queryset.filter(available=True, display_on_landing_page=True)
                .exclude(group_tutoring_sessions__start__lt=filter_start)
                .filter(group_tutoring_sessions__start__gt=filter_start)
                .distinct()
            )
        elif any([hasattr(self.request.user, x) for x in ("administrator", "tutor", "counselor")]):
            return queryset
        else:
            # Authenticated students/parents get to see courses they're enrolled in as well
            # as courses that are displayed on landing page
            return (
                queryset.filter(
                    Q(students__user=self.request.user)
                    | Q(students__parent__user=self.request.user)
                    | Q(available=True, display_on_landing_page=True)
                )
                .exclude(group_tutoring_sessions__start__lt=timezone.now())
                .distinct()
            )

    def check_permissions(self, request):
        if request.method.lower() == "get":
            return True
        elif self.action != "enroll" and not hasattr(self.request.user, "administrator"):
            self.permission_denied(request)

    def perform_destroy(self, course: Course):
        """ When destroying a course, we cancel the constituent GTS (so notifications are sent)
            and then delete the actual Course object (the GTS will remain, but they'll be marked
            cancelled)
        """
        for gts in course.group_tutoring_sessions.filter(cancelled=False, start__gt=timezone.now()):
            TutoringSessionManager.cancel_group_tutoring_session(gts)
        return super().perform_destroy(course)

    @action(methods=["post"], detail=True)
    def enroll(self, request, *args, **kwarags):
        """ Enroll a student in the course. Registeres student for all GroupTutoringSessions on the Course
            Arguments (in request data):
                student {number} PK of student to enroll in course
                purchase {boolean} Whether or not student should be charged for the package associated with the
                    course. Must be True if the current user is not an admin
            Returns updated Student
        """
        # Must be admin
        student: Student = get_object_or_404(Student, pk=request.data.get("student"))
        if not self.has_access_to_student(student):
            self.permission_denied(request)
        course: Course = self.get_object()
        purchase = request.data.get("purchase", True)
        if not hasattr(request.user, "administrator") and not purchase:
            self.permission_denied(request)
        elif purchase and not student.last_paygo_purchase_id:
            raise ValidationError(detail="No payment information on file")
        elif purchase and (not course.package or not course.display_on_landing_page):
            raise ValidationError(detail="This course cannot be purchased")

        try:
            TutoringSessionManager.enroll_student_in_course(student, course, purchase=purchase)
            student.refresh_from_db()
            serializer = StudentSerializer(student)
            return Response(data=serializer.data)
        except TutoringSessionManagerException:
            raise ValidationError(detail="Course and student not valid")

    @action(methods=["post"], detail=True)
    def unenroll(self, request, *args, **kwargs):
        """ Unenroll a student from a course. Cancels upcoming GroupTutoringSessions that student is registered for
            (that is, cancels StudentTutoringSessions)
            Returns updated Student
        """
        if not hasattr(request.user, "administrator"):
            self.permission_denied(request)
        student = get_object_or_404(Student, pk=request.data.get("student"))
        course = self.get_object()
        try:
            TutoringSessionManager.unenroll_student_from_course(student, course)
            student.refresh_from_db()
            serializer = StudentSerializer(student)
            return Response(data=serializer.data)
        except TutoringSessionManagerException:
            raise ValidationError(detail="Course and student not valid")


class CourseLandingPageView(TemplateView):
    template_name = "cwtutoring/course_landing_page.html"
