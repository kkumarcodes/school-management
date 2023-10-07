import pytz
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import reverse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from cwcommon.models import FileUpload
from cwcommon.serializers.base import AdminModelSerializer
from cwcommon.serializers.file_upload import FileUploadSerializer
from cwresources.models import Resource, ResourceGroup
from cwtutoring.models import Course, Location, StudentTutoringSession, TutoringService
from cwtutoring.serializers.tutoring_sessions import LocationSerializer
from cwtutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager
from cwuniversities.models import StudentUniversityDecision, University
from snusers.models import Administrator, Counselor, Parent, Student, StudentHighSchoolCourse, Tutor
from snusers.utilities.managers import StudentManager, USER_MANAGERS_BY_USER_CLASS

# Fields on every user model
BASE_FIELDS = (
    "pk",
    "slug",
    "first_name",
    "last_name",
    "email",
    "user_type",
    "user_id",
    "timezone",
    "set_timezone",
    "account_is_created",
    "notification_recipient",
    "calendar_url",
    "invite",  # Write Only
    "phone",
    "last_invited",
    "profile_picture",
    "update_profile_picture",  # Read  # Write
)

BASE_ADMIN_FIELDS = (
    "accepted_invite",
    "accept_invite_url",
)  # Read Only

ZOOM_FIELDS = ("zoom_pmi", "zoom_url", "zoom_phone", "zoom_user_id", "zoom_type")


class CWUserSerializer(AdminModelSerializer):
    """ We add methods to validate and update instance.user details
        Note that timezone field is read-only (and will be pulled from location associated with user,
        applicable)
    """

    # These fields are common to all user serializers
    slug = serializers.CharField(read_only=True)
    first_name = serializers.CharField(source="user.first_name", required=False)
    # If provided, first name can't be blank but last name can be
    last_name = serializers.CharField(source="user.last_name", required=False, allow_blank=True)
    email = serializers.CharField(source="user.email")
    phone = serializers.CharField(source="user.notification_recipient.phone_number", read_only=True)
    user_id = serializers.IntegerField(source="user.pk", read_only=True)
    account_is_created = serializers.BooleanField(source="user.has_usable_password", read_only=True)
    notification_recipient = serializers.IntegerField(source="user.notification_recipient.pk", read_only=True)
    timezone = serializers.CharField(read_only=True)

    # Write (specifically: create) only
    invite = serializers.BooleanField(write_only=True, required=False)

    # Some read only admin fields RE invitations
    last_invited = serializers.DateTimeField(read_only=True)
    accepted_invite = serializers.DateTimeField(read_only=True)
    accept_invite_url = serializers.SerializerMethodField()

    calendar_url = serializers.SerializerMethodField()
    has_connected_outlook = serializers.SerializerMethodField()

    profile_picture = serializers.SerializerMethodField()
    update_profile_picture = serializers.SlugRelatedField(
        source="profile_picture",
        slug_field="slug",
        allow_null=True,
        queryset=FileUpload.objects.all(),
        write_only=True,
        required=False,
    )

    def get_profile_picture(self, obj):
        return obj.profile_picture.url if obj.profile_picture_id else ""

    def get_has_connected_outlook(self, obj):
        # Whether or not user has a connected outlook calendar that we use to sync events
        return hasattr(obj, "microsoft_refresh") and (
            obj.microsoft_refresh is not None and obj.microsoft_refresh is not ""
        )

    def get_accept_invite_url(self, obj):
        return f'{settings.SITE_URL}{reverse("register_get", kwargs={"uuid": str(obj.slug)})}'

    def get_calendar_url(self, obj):
        return f'{settings.SITE_URL}{reverse("calendar", kwargs={"slug": str(obj.slug)})}'

    def validate(self, attrs):
        """Override validate to make sure they aren't changing email to
            username of another user.
        """
        if (
            User.objects.filter(username__iexact=attrs.get("user", {}).get("email"))
            .exclude(pk=self.instance.user.pk if self.instance and self.instance.user else None)
            .exists()
        ):
            if self.context.get("request") and any(
                [
                    hasattr(self.context["request"].user, x)
                    for x in ("counselor", "tutor", "administrator", "parent", "student")
                ]
            ):
                raise ValidationError("Invalid Email Address: This email is in use on an existing UMS account")
            else:
                raise ValidationError("Invalid Email Address")
        return attrs

    def validate_set_timezone(self, value):
        """ Ensure that - if set - new timezone is valid """
        if value:
            try:
                pytz.timezone(value)
            except pytz.UnknownTimeZoneError:
                raise serializers.ValidationError(detail="Invalid Timezone")
        return value

    def update(self, instance, validated_data):
        if instance.user and validated_data.get("user"):
            user_data = validated_data.pop("user")
            User.objects.filter(pk=instance.user.pk).update(
                first_name=user_data.get("first_name", instance.user.first_name),
                last_name=user_data.get("last_name", instance.user.last_name),
                email=user_data.get("email", instance.user.email),
                username=user_data.get("email", instance.user.username),
            )
            instance.refresh_from_db()
        return super(CWUserSerializer, self).update(instance, validated_data)

    def create(self, validated_data):
        """ Create a new cw user, send an invite """
        # First we create our Django User
        user_data = validated_data.pop("user")
        invite = validated_data.pop("invite", False)
        validated_data["invitation_name"] = user_data.get("first_name") + " " + user_data.get("last_name")
        validated_data["invitation_email"] = user_data.get("email")
        validated_data["user"] = User.objects.create_user(
            user_data.get("email"),
            email=user_data.get("email"),
            first_name=user_data.get("first_name"),
            last_name=user_data.get("last_name"),
        )
        # Then we create our cw user
        obj, created = USER_MANAGERS_BY_USER_CLASS[self.Meta.model].create(invite=invite, **validated_data)
        return obj


class StudentHighSchoolCourseSerializer(serializers.ModelSerializer):
    """ Serializer for StudentHighSchoolCourse
    """

    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())

    class Meta:
        model = StudentHighSchoolCourse
        fields = (
            "pk",
            "slug",
            "student",
            "course_level",
            "school_year",
            "grading_scale",
            "schedule",
            "high_school",
            "subject",
            "grades",
            "credits",
            "credits_na",
            "name",
            "planned_course",
            "course_notes",
            "cw_equivalent_grades",
            "include_in_cw_gpa",
        )

    def validate(self, attrs):
        """ Validate update
        """
        if self.instance and attrs.get("student") and attrs.get("student").pk != self.instance.student.pk:
            raise ValidationError("Cannot change student on StudentHighSchoolCourse")
        return attrs


class StudentSerializerCounseling(CWUserSerializer):
    """ Serializer for students for the counseling platform. Leaves behind all of the useless tutoring data
    """

    counselor = serializers.PrimaryKeyRelatedField(queryset=Counselor.objects.all(), required=False, allow_null=True)
    counselor_name = serializers.CharField(read_only=True, source="counselor.name")
    tutors = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.all(), required=False, many=True)
    visible_resources = serializers.PrimaryKeyRelatedField(queryset=Resource.objects.all(), many=True, required=False)
    visible_resource_groups = serializers.PrimaryKeyRelatedField(
        queryset=ResourceGroup.objects.all(), many=True, required=False
    )
    location_id = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), source="location", required=False, allow_null=True,
    )
    school_count = serializers.SerializerMethodField()
    overdue_task_count = serializers.SerializerMethodField()
    # See method for definition of this field's data
    next_counselor_meeting = serializers.SerializerMethodField()

    cw_gpa = serializers.SerializerMethodField()
    is_cas_student = serializers.SerializerMethodField()
    # Roadmaps that have been applied to student. Determined through meetings
    roadmaps = serializers.SerializerMethodField()
    file_uploads = serializers.SerializerMethodField()
    cpp_notes = serializers.SerializerMethodField()

    class Meta:
        model = Student
        admin_fields = ("counselor_pay_rate",)
        fields = (
            BASE_FIELDS
            + (
                "counselor",
                "parent",
                "graduation_year",
                "tutors",
                "location_id",
                "visible_resources",
                "visible_resource_groups",
                "accommodations",
                "admin_note",
                "accept_invite_url",  # Read Only
                "counseling_student_types_list",
                "school_list_finalized",
                "address",
                "address_line_two",
                "city",
                "zip_code",
                "state",
                "high_school",
                "high_schools",
                "gpa",
                "counselor_name",
                "country",
                # Below are the fields that really provide value on counseling platform :)
                "school_count",
                "overdue_task_count",
                "next_counselor_meeting",
                "counselor_note",
                "file_uploads",
                "activities_notes",
                "cw_gpa",
                "is_cas_student",
                "roadmaps",
                "schools_page_note",
                "cpp_notes",
                "has_access_to_cap",
                "tags",
                "program_advisor",
                "pronouns",
                "hide_target_reach_safety",
                "is_prompt_active",
            )
            + admin_fields
        )

    def save(self, **kwargs):
        counselor = kwargs.pop("counselor", None)
        student = super().save(**kwargs)
        student_manager = StudentManager(student)
        student_manager.save_counseling_student_types()
        return student_manager.set_counselor(counselor)

    def get_cpp_notes(self, obj: Student):
        return reverse("students-cpp_notes", kwargs={"pk": obj.pk}) if obj.cpp_notes else None

    def get_roadmaps(self, obj):
        """ Read-only field that is Student.applied_roadmaps.
            Has different name for backwards compatibility with old computed field
        """
        return obj.applied_roadmaps.values_list("pk", flat=True)

    def get_file_uploads(self, obj):
        """ We include file uploads directly associated with this student through counseling_file_uploads,
            AND ALSO FILE UPLOADS THIS STUDENT CREATED that are not associated with a diagnostic
        """
        return FileUploadSerializer(
            FileUpload.objects.filter(active=True).filter(
                Q(counseling_student=obj) | Q(Q(created_by__student=obj) & Q(test_result=None, diagnostic_result=None))
            ),
            many=True,
        ).data

    def get_cw_gpa(self, obj: Student):
        """ Average of non-final CW equivalent grades """
        courses = obj.high_school_courses.filter(include_in_cw_gpa=True, planned_course=False)
        grades = []
        for course in courses:
            # We use the final grade if it is set. Otherwise we average the non-final grades
            if len(course.cw_equivalent_grades) == 0:
                continue
            if course.cw_equivalent_grades[-1] is not None:
                grades.append(course.cw_equivalent_grades[-1])
            else:
                non_null_equiv_grades = [x for x in course.cw_equivalent_grades[:-1] if x is not None]
                if non_null_equiv_grades:
                    grades.append(sum(non_null_equiv_grades) * 1.0 / len(non_null_equiv_grades))
        if not grades:
            return None
        return round(sum(grades) * 100.0 / len(grades)) / 100.0

    def get_is_cas_student(self, obj: Student):
        return obj.tutoring_package_purchases.exists() or obj.tutoring_sessions.exists()

    def get_school_count(self, obj):
        """ Returns number of YES StudentUniversityDecisions """
        return StudentUniversityDecision.objects.filter(student=obj, is_applying=StudentUniversityDecision.YES,).count()

    def get_overdue_task_count(self, obj):
        """ Returns number of overdue tasks for student. We use tasks with `task_type` set as a proxy
            for our counseling platform tasks.
        """
        return (
            obj.user.tasks.filter(
                completed=None, due__lt=timezone.now(), archived=None, visible_to_counseling_student=True
            )
            .exclude(task_type="")
            .count()
        )

    def get_next_counselor_meeting(self, obj: Student):
        """ The next future and un-cancelled counselor meeting date for student
        """
        cm = obj.counselor_meetings.filter(start__gt=timezone.now(), cancelled=None).order_by("start").first()
        return cm.start.isoformat() if cm else None


class AdminListStudentSerializer(CWUserSerializer):
    """ Special serializer for students used on the admin platform to list students. Whenever details for a student
        are needed, the student is retrieved using either StudentSerializer or StudentSerializerCounseling.
        This serializer is used only to get data needed to display students in a table
    """

    purchased_hours = serializers.SerializerMethodField()
    location = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Student
        fields = (
            "pk",
            "slug",
            "first_name",
            "last_name",
            "email",
            "user_id",
            "counselor",
            "purchased_hours",
            "parent",
            "graduation_year",
            "tutors",
            "location",
            "accept_invite_url",
            "is_paygo",
            "is_active",
            "counseling_student_types_list",
            "tags",
        )
        read_only_fields = fields  # All fields read only for optimization

    def get_purchased_hours(self, obj):
        total_hours = StudentTutoringPackagePurchaseManager(obj).get_total_hours()
        return sum(total_hours.values())


class StudentLastPaidMeetingSerializer(serializers.ModelSerializer):
    """ This serializer is used to list students' last paid meetings - that is none tentative meetings. Note
        that a student's last paid meeting can be in the past or the future (it's not their most recent paid
        meeting, because then we would call this StudentMostRecentPaidMeetingSerializer obviously)
    """

    last_paid_meeting = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = ("pk", "last_paid_meeting")

    def get_last_paid_meeting(self, obj: Student):
        next_session = (
            StudentTutoringSession.objects.filter(student=obj, set_cancelled=False, is_tentative=False)
            .order_by("start")
            .last()
        )
        return next_session.start if next_session else None


class StudentSerializer(CWUserSerializer):
    """ Serializer for Student
        Note there are some special fields that get included if there is 'tutor' in context:
            - next_meeting
            - most_recent_meeting
    """

    counselor = serializers.PrimaryKeyRelatedField(queryset=Counselor.objects.all(), required=False, allow_null=True)
    counselor_name = serializers.CharField(read_only=True, source="counselor.name")
    tutors = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.all(), required=False, many=True)
    location = serializers.SerializerMethodField()
    location_id = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), write_only=True, source="location", required=False, allow_null=True,
    )
    visible_resources = serializers.PrimaryKeyRelatedField(queryset=Resource.objects.all(), many=True, required=False)
    visible_resource_groups = serializers.PrimaryKeyRelatedField(
        queryset=ResourceGroup.objects.all(), many=True, required=False
    )

    courses = serializers.PrimaryKeyRelatedField(read_only=True, many=True)

    # These fields are only included if tutor {Tutor} is included in context
    next_meeting = serializers.SerializerMethodField()
    most_recent_meeting = serializers.SerializerMethodField()

    # Hours and payment settings
    hours = serializers.SerializerMethodField()
    wellness_history = serializers.CharField(read_only=True)

    # Read only fields from basecamp export
    basecamp_attachments = serializers.SerializerMethodField()
    basecamp_documents = serializers.SerializerMethodField()

    pending_enrollment_course = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.all(), write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Student
        # Invite URL not admin field for students
        admin_fields = tuple([x for x in BASE_ADMIN_FIELDS if x != "accept_invite_url"]) + ("counselor_pay_rate",)
        # Fields that are popped _unless_ user is admin or tutor
        admin_tutor_fields = ("basecamp_attachments", "basecamp_documents", "admin_note")
        fields = (
            BASE_FIELDS
            + admin_fields
            + admin_tutor_fields
            + (
                "counselor",
                "program_advisor",
                "parent",
                "graduation_year",
                "tutors",
                "location",
                "location_id",
                "visible_resources",
                "visible_resource_groups",
                "accommodations",
                "courses",
                "hours",
                "accept_invite_url",  # Read Only
                "is_paygo",
                "is_active",
                "is_prompt_active",
                "last_paygo_purchase_id",
                "counseling_student_types_list",
                "school_list_finalized",
                "wellness_history",  # Read Only
                "next_meeting",
                "most_recent_meeting",
                "address",
                "address_line_two",
                "city",
                "zip_code",
                "state",
                "high_school",
                "high_schools",
                "gpa",
                "counselor_name",
                "country",
                "pending_enrollment_course",
                "pronouns",
                "tags",
                "has_access_to_cap",
            )
        )

    def __init__(self, *args, **kwargs):
        # will strip out fields below if not an admin or tutor
        super().__init__(*args, **kwargs)
        context_request = self.context.get("request")
        user = context_request.user if context_request else self.context.get("user")
        if not (hasattr(user, "administrator") or hasattr(user, "tutor") or hasattr(user, "parent")):
            [self.fields.pop(x) for x in self.Meta.admin_tutor_fields]
            self.fields.pop("accept_invite_url")

    def save(self, **kwargs):
        counselor = kwargs.pop("counselor", None)
        student = super().save(**kwargs)
        student_manager = StudentManager(student)
        return student_manager.set_counselor(counselor)

    def get_basecamp_attachments(self, obj):
        return obj.basecamp_attachments.url if obj.basecamp_attachments else None

    def get_basecamp_documents(self, obj):
        return obj.basecamp_documents.url if obj.basecamp_documents else None

    def get_location(self, obj):
        if not obj.location:
            return None
        if self.context.get("condensed"):
            return obj.location_id
        return LocationSerializer(obj.location).data

    def get_hours(self, obj):
        return StudentTutoringPackagePurchaseManager(obj).get_available_hours()

    def get_next_meeting(self, obj):
        """ The next StudentTutoringSession start between student (obj) and tutor (context['tutor])
        """
        if not self.context.get("tutor"):
            return
        next_session = (
            StudentTutoringSession.objects.filter(
                student=obj,
                individual_session_tutor=self.context["tutor"],
                start__gt=timezone.now(),
                set_cancelled=False,
                is_tentative=False,
            )
            .order_by("start")
            .first()
        )
        return next_session.start if next_session else None

    def get_most_recent_meeting(self, obj):
        """ The most recent meeting (time) StudentTutoringSession between student (obj) and tutor (context['tutor])
        """
        if not self.context.get("tutor"):
            return
        previous_session = (
            StudentTutoringSession.objects.filter(
                student=obj,
                individual_session_tutor=self.context["tutor"],
                end__lt=timezone.now(),
                missed=False,
                set_cancelled=False,
            )
            .order_by("-start")
            .first()
        )
        return previous_session.start if previous_session else None


class CounselorSerializer(CWUserSerializer):
    """Serializer for counselor
    """

    students = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=Student.objects.all())
    location = LocationSerializer(read_only=True)
    location_id = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), write_only=True, source="location", required=False,
    )
    # Whether or not counselor has linked admin acct
    is_admin = serializers.SerializerMethodField()

    class Meta:
        """ deets """

        model = Counselor
        admin_fields = BASE_ADMIN_FIELDS + ("hourly_rate", "part_time")
        fields = (
            BASE_FIELDS
            + admin_fields
            + (
                "students",
                "location",
                "location_id",
                "has_connected_outlook",
                "is_admin",
                "is_active",
                "prompt",
                "email_header",
                "email_signature",
                "max_meetings_per_day",
                "minutes_between_meetings",
                "cc_on_meeting_notes",
                "student_schedule_meeting_buffer_hours",
                "include_all_availability_for_remote_sessions",
                "student_reschedule_hours_required",
            )
        )

    def get_is_admin(self, obj: Counselor):
        return hasattr(obj.user, "linked_administrator") and obj.user.linked_administrator.user.is_active


class ParentSerializer(CWUserSerializer):
    """Serializer for parent
    """

    phone_number = serializers.CharField(source="user.notification_recipient.phone_number", read_only=True)
    students = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        """ deets """

        model = Parent
        # Invite URL not admin field for Parent
        admin_fields = tuple([x for x in BASE_ADMIN_FIELDS if x != "accept_invite_url"])
        fields = (
            BASE_FIELDS
            + admin_fields
            + (
                "students",
                "phone_number",
                "address",
                "address_line_two",
                "secondary_parent_first_name",
                "secondary_parent_last_name",
                "secondary_parent_phone_number",
                "cc_email",  # AKA secondary parent's email
                "city",
                "zip_code",
                "state",
                "country",
                "accept_invite_url",
                "is_active",
            )
        )


class AdministratorSerializer(CWUserSerializer):
    """Serializer for administrator
    """

    # Whether or not admin has linked tutor/counselor acct
    is_tutor = serializers.SerializerMethodField()
    is_counselor = serializers.SerializerMethodField()

    class Meta:
        """ deets """

        model = Administrator
        admin_fields = BASE_ADMIN_FIELDS
        fields = (
            BASE_FIELDS
            + BASE_ADMIN_FIELDS
            + ("is_tutor", "is_counselor", "is_cap_administrator", "is_cas_administrator")
        )

    def get_is_tutor(self, obj: Administrator):
        return obj.linked_user and obj.linked_user.is_active and hasattr(obj.linked_user, "tutor")

    def get_is_counselor(self, obj: Administrator):
        return obj.linked_user and obj.linked_user.is_active and hasattr(obj.linked_user, "counselor")


class TutorSerializer(CWUserSerializer):
    students = serializers.PrimaryKeyRelatedField(required=False, many=True, queryset=Student.objects.all())
    university = serializers.PrimaryKeyRelatedField(required=False, queryset=University.objects.all())
    location = LocationSerializer(read_only=True)
    location_id = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), write_only=True, source="location", required=False,
    )
    has_recurring_availability = serializers.BooleanField(read_only=True, source="recurring_availability.active")
    tutoring_services = serializers.PrimaryKeyRelatedField(
        queryset=TutoringService.objects.all(), many=True, required=False
    )
    # Whether or not tutor has linked admin acct
    is_admin = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)  # will strip out admin fields if not admin
        context_request = self.context.get("request")
        user = context_request.user if context_request else self.context.get("user")
        if not (hasattr(user, "administrator") or hasattr(user, "tutor")):
            [self.fields.pop(field_name) for field_name in self.Meta.tutor_fields]

    class Meta:
        """ deets """

        model = Tutor
        tutor_fields = ("hourly_rate",)
        admin_fields = BASE_ADMIN_FIELDS + ZOOM_FIELDS
        fields = (
            BASE_FIELDS
            + BASE_ADMIN_FIELDS
            + ZOOM_FIELDS
            + tutor_fields
            + (
                "students",
                "university",
                "degree",
                "bio",
                "remote_tutoring_link",
                "can_tutor_remote",
                "location",
                "location_id",
                "has_recurring_availability",
                "is_curriculum_tutor",
                "is_test_prep_tutor",
                "is_diagnostic_evaluator",
                "tutoring_services",
                "students_can_book",
                "has_connected_outlook",
                "is_admin",
                "is_active",
                "include_all_availability_for_remote_sessions",
            )
        )

    def get_is_admin(self, obj: Tutor):
        return hasattr(obj.user, "linked_administrator") and obj.user.linked_administrator.user.is_active


# Helper dict that translates model classes to their associated serializer
MODEL_TO_SERIALIZER = {
    Student: StudentSerializer,
    Tutor: TutorSerializer,
    Counselor: CounselorSerializer,
    Parent: ParentSerializer,
}
