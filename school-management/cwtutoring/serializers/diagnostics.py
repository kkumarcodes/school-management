from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from cwcommon.serializers.base import AdminModelSerializer
from cwcommon.serializers.file_upload import UpdateFileUploadsSerializer
from cwresources.serializers import ResourceSerializer
from cwtasks.models import Task
from cwtasks.utilities.task_manager import TaskManager
from cwtutoring.models import (
    Diagnostic,
    DiagnosticGroupTutoringSessionRegistration,
    DiagnosticResult,
    GroupTutoringSession,
    TestResult,
)
from cwtutoring.utilities.tutoring_session_manager import TutoringSessionManager
from snusers.models import Counselor, Parent, Student
from snusers.utilities.managers import StudentManager
from snusers.serializers.users import ParentSerializer, StudentSerializer


class DiagnosticRegistrationSerializer(serializers.ModelSerializer):
    """ This is a very special serializer, used by a family filling out the diagnostic registration form
        to register for a diagnostic.
        When saved, this serializer creates a DiagnosticRegistration object. It also:
            - Saves entire registration JSON payload on that object
            - Gets or creates student and parent as needed
            - Registers student for diagnostic session(s) which sends notifications
    """

    # We "write" student using their email address, so this field is read-only
    student = serializers.PrimaryKeyRelatedField(read_only=True)

    # We copy accommodations to student's accommodations field
    accommodations = serializers.CharField(write_only=True, required=False)

    # Fields not on model that we validate. Required by default
    student_email = serializers.EmailField(source="student.invitation_email")
    student_name = serializers.CharField(source="student.invitation_name")
    parent_email = serializers.EmailField(source="student.parent.invitation_email", required=False, allow_null=True)
    parent_name = serializers.CharField(source="student.parent.invitation_name", required=False, allow_null=True)
    program_advisor = serializers.CharField(source="student.program_advisor", read_only=True)

    group_tutoring_sessions = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        queryset=GroupTutoringSession.objects.filter(set_charge_student_duration=0, title__icontains="diagnostic"),
    )

    self_assigned_diagnostics = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Diagnostic.objects.filter(can_self_assign=True), required=False
    )

    # List of names of admins and/or tutors assigned to review student's DiagnosticResults
    assigned_evaluators = serializers.SerializerMethodField()

    class Meta:
        model = DiagnosticGroupTutoringSessionRegistration
        non_model_fields = (
            "student_email",
            "student_name",
            "parent_email",
            "parent_name",
            "accommodations",
        )
        fields = (
            "pk",
            "slug",
            "created",
            "student",
            "group_tutoring_sessions",
            "registration_data",
            "registration_type",
            "accommodations",
            "assigned_evaluators",
            "self_assigned_diagnostics",
            "program_advisor",
        ) + non_model_fields

    def validate(self, attrs):
        # If our view got a student slug to create registration for, we don't validate student/parent
        if self.context.get("student_slug"):
            return attrs
        existing_student = Student.objects.filter(
            user__username=attrs.get("student", {}).get("invitation_email")
        ).first()
        existing_parent = Parent.objects.filter(
            user__username=attrs.get("student", {}).get("parent", {}).get("invitation_email")
        ).first()

        if existing_student and not existing_parent:
            raise ValidationError(
                "Invalid student/parent. Be sure you are using the email address on file with UMS "
            )

        if existing_student and existing_student.parent and existing_student.parent != existing_parent:
            raise ValidationError(
                "Invalid student/parent. Be sure you are using the email address on file with UMS "
            )

        return attrs

    def create(self, validated_data):
        # Get or create student and parent
        parent = Parent.objects.filter(
            user__username=validated_data.get("student", {}).get("parent", {}).get("invitation_email")
        ).first()
        if not parent and not self.context.get("student_slug"):
            split_name = validated_data.get("student", {}).get("parent", {}).get("invitation_name").split(" ")
            parent_serializer = ParentSerializer(
                data={
                    "email": validated_data.get("student", {}).get("parent", {}).get("invitation_email"),
                    "first_name": split_name[0],
                    "last_name": split_name[1] if len(split_name) > 1 else "",
                    "invite": True,
                    "set_timezone": validated_data["registration_data"].get("parent_timezone"),
                }
            )
            if not parent_serializer.is_valid():
                raise ValidationError(parent_serializer.errors)
            parent = parent_serializer.save()

        student: Student = Student.objects.filter(user__username=validated_data["student"]["invitation_email"]).first()
        if not student:
            split_name = validated_data["student"]["invitation_name"].split(" ")
            student_serializer = StudentSerializer(
                data={
                    "email": validated_data["student"]["invitation_email"],
                    "first_name": split_name[0],
                    "last_name": split_name[1] if len(split_name) > 1 else "",
                    # Note that accommodations only get saved if we're creating a new student, so previous
                    # accommodations cannot be overwritten
                    "accommodations": validated_data.get("accommodations", ""),
                    "invite": True,
                    "set_timezone": validated_data["registration_data"].get("student_timezone"),
                }
            )
            if not student_serializer.is_valid():
                raise ValidationError(student_serializer.errors)
            student = student_serializer.save()

        if not student.program_advisor:
            student.program_advisor = validated_data["registration_data"].get("program_advisor", "")

        # Don't change parent when creating data by slug (security risk)
        if not self.context.get("student_slug"):
            student_manager = StudentManager(student)
            student = student_manager.set_parent(parent)
        student.save()

        # Mmkay, now we can just save like normal
        validated_data["student"] = student

        # Remove all of the fields that aren't on the diag registration model
        [validated_data.pop(x, None) for x in self.Meta.non_model_fields]
        registration: DiagnosticGroupTutoringSessionRegistration = super().create(validated_data)

        # And now we enroll student in GTS and send them notifications and what have you
        for gts in registration.group_tutoring_sessions.exclude(student_tutoring_sessions__student=student):
            TutoringSessionManager.enroll_student_in_gts(student, gts)

        # And we create tasks for diagnostics that are self assigned, then send notification
        self_assign_diag: Diagnostic
        for self_assign_diag in registration.self_assigned_diagnostics.all():
            task: Task = Task.objects.create(
                for_user=student.user,
                diagnostic=self_assign_diag,
                title=self_assign_diag.title,
                require_file_submission=True,
                allow_content_submission=True,
            )
            student.visible_resources.add(*self_assign_diag.resources.all())
            task_manager = TaskManager(task)
            task_manager.send_task_created_notification()
            task_manager.send_self_assigned_admin_notification()

        # Finally, we try and associate student with counselor if they already exist
        if registration.registration_data.get("counselor_pk") and not student.counselor:
            student.counselor = Counselor.objects.filter(pk=registration.registration_data.get("counselor_pk")).first()
            student.save()

        return registration

    def get_assigned_evaluators(self, obj: DiagnosticGroupTutoringSessionRegistration):
        return ", ".join(
            [
                x.assigned_to.get_full_name()
                for x in obj.student.diagnostic_results.filter(assigned_to__isnull=False).select_related("assigned_to")
            ]
        )


class TestResultSerializer(UpdateFileUploadsSerializer, serializers.ModelSerializer):
    related_name_field = "test_result"
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())

    class Meta:
        model = TestResult
        fields = (
            "pk",
            "slug",
            "title",
            "test_date",
            "test_type",
            "student",
            "score",
            "file_uploads",
            "update_file_uploads",
            "reading",
            "reading_sub",
            "writing",
            "writing_sub",
            "math",
            "math_sub",
            "english",
            "science",
            "speaking",
            "listening",
        )


class DiagnosticSerializer(AdminModelSerializer):
    resources = ResourceSerializer(read_only=True, many=True)

    class Meta:
        model = Diagnostic
        admin_fields = (
            "created_by",
            "updated_by",
        )
        fields = (
            "pk",
            "slug",
            "title",
            "description",
            "created",
            "resources",
            "form_specification",
            "can_self_assign",
        ) + admin_fields

    def get_file_uploads(self, obj):
        return list(obj.file_uploads.values_list("slug", flat=True))


class DiagnosticResultSerializer(UpdateFileUploadsSerializer, AdminModelSerializer):
    related_name_field = "diagnostic_result"
    student_name = serializers.CharField(read_only=True, source="student.name")
    student_accommodations = serializers.CharField(read_only=True, source="student.accommodations")
    recommender_name = serializers.CharField(read_only=True, source="feedback_provided_by.get_full_name")
    # Slug of recommendation FileUpload
    recommendation = serializers.CharField(read_only=True, source="recommendation.slug")
    diagnostic_title = serializers.CharField(read_only=True, source="diagnostic.title")

    # Whether or not student has multiple unreturned diagnostic results (shows warning on frontend)
    student_has_multiple_unreturned = serializers.SerializerMethodField()

    # Admins can view active (unarchived, incomplete) tasks associated with diag result
    tasks = serializers.SerializerMethodField()

    # Registration data from the last time student registered for diagnostic(s) via diag landing page
    registration_data = serializers.SerializerMethodField()
    counselor = serializers.PrimaryKeyRelatedField(read_only=True, source="student.counselor")
    program_advisor = serializers.CharField(read_only=True, source="student.program_advisor")

    class Meta:
        model = DiagnosticResult
        admin_fields = (
            "submitted_by",
            "student_name",
            "recommender_name",
            "student_accommodations",
            "admin_note",
            "updated",
            "tasks",
        )
        fields = (
            "pk",
            "submission_note",
            "diagnostic_title",
            "state",
            "score",
            "feedback",
            "feedback_provided",
            "feedback_provided_by",
            "diagnostic",
            "counselor",
            "program_advisor",
            "task",
            "student",
            "file_uploads",
            "update_file_uploads",
            "recommendation",
            "created",
            "assigned_to",
            "student_has_multiple_unreturned",
            "registration_data",
            "program_advisor",
            "counselor",
        ) + admin_fields

    def get_registration_data(self, obj: DiagnosticResult):
        last_reg = (
            DiagnosticGroupTutoringSessionRegistration.objects.filter(student=obj.student).order_by("created").last()
        )
        return last_reg.registration_data if last_reg else None

    def get_tasks(self, obj):
        from cwtasks.serializers import TaskSerializer

        return TaskSerializer(
            Task.objects.filter(
                related_object_content_type=ContentType.objects.get_for_model(DiagnosticResult),
                related_object_pk=obj.pk,
                archived=None,
                completed=None,
            ),
            context=self.context,
            many=True,
        ).data

    def get_student_has_multiple_unreturned(self, obj: DiagnosticResult):
        """ We figure out how many unique diagnostics have open diag result or pending task for student """
        unreturned_results = DiagnosticResult.objects.filter(student=obj.student,).exclude(
            state=DiagnosticResult.STATE_VISIBLE_TO_STUDENT
        )
        open_tasks = Task.objects.filter(for_user=obj.student.user, diagnostic__isnull=False, archived=None)
        return (
            Diagnostic.objects.filter(Q(diagnostic_results__in=unreturned_results) | Q(tasks__in=open_tasks))
            .distinct()
            .count()
            > 1
        )


class DiagnosticRegistrationCounselorSerializer(serializers.ModelSerializer):
    """
        Returns all active counselors with pk, name and slug specifically for Diagnostic registration landing page. Only the data needed for the counselor select dropdown is returned.
    """

    class Meta:
        model = Counselor
        fields = (
            "pk",
            "name",
            "slug",
        )
