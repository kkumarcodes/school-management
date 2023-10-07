from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from cwcommon.serializers.base import AdminModelSerializer
from cwcommon.utilities.availability_manager import AvailabilityManager
from cwresources.models import Resource
from cwresources.serializers import ResourceSerializer
from cwtutoring.models import (
    Diagnostic,
    Location,
    TutorAvailability,
    StudentTutoringSession,
    GroupTutoringSession,
    RecurringTutorAvailability,
    TutoringSessionNotes,
    Course,
    TutoringPackage,
    TutoringService,
)
from cwtutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager
from snusers.models import Student, Tutor


class TutorAvailabilitySerializer(serializers.ModelSerializer):
    tutor = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.all())
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all(), required=False, allow_null=True)

    class Meta:
        model = TutorAvailability
        fields = ("pk", "slug", "start", "end", "tutor", "location")


class RecurringTutorAvailabilitySerializer(serializers.ModelSerializer):
    availability = serializers.JSONField()
    locations = serializers.JSONField(required=False)
    pk = serializers.IntegerField(read_only=True)
    tutor = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.all())

    class Meta:
        model = RecurringTutorAvailability
        fields = ("pk", "tutor", "availability", "locations")

    def validate(self, val):
        """ Make sure there are no overlapping availabilities, every day is included """
        mgr = AvailabilityManager(val["tutor"])
        mgr.validate_recurring_availability(val["availability"])
        if "locations" in val:
            mgr.validate_locations(val["locations"])
        return val


class TutoringServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TutoringService
        fields = (
            "pk",
            "slug",
            "name",
            "tutors",
            "locations",
            "session_type",
            "level",
            "applies_to_group_sessions",
            "applies_to_individual_sessions",
        )


class LocationSerializer(serializers.ModelSerializer):
    timezone = serializers.CharField(source="set_timezone", required=False)
    tutoring_services = serializers.PrimaryKeyRelatedField(
        queryset=TutoringService.objects.all(), many=True, required=False
    )

    class Meta:
        model = Location
        fields = (
            "pk",
            "slug",
            "name",
            "description",
            "offers_tutoring",
            "address",
            "address_line_two",
            "city",
            "zip_code",
            "state",
            "timezone",
            "is_remote",
            "default_zoom_url",
            "tutoring_services",
        )


class GroupTutoringSessionSerializer(serializers.ModelSerializer):
    primary_tutor = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.all())
    support_tutors = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.all(), many=True, required=False)
    location = LocationSerializer(read_only=True)
    # Use this field to update/create
    location_id = serializers.PrimaryKeyRelatedField(
        write_only=True, required=False, allow_null=True, source="location", queryset=Location.objects.all(),
    )

    resources = ResourceSerializer(many=True, required=False)

    # Use this field to set resources when creating/updating. The set of resources
    # on GroupTutoringSession will be OVERWRITTEN (replaced) by set of resources identified
    # by SLUGS supplied in this field.
    update_resources = serializers.ListField(child=serializers.CharField(), write_only=True, required=False)

    tutoring_session_notes = serializers.PrimaryKeyRelatedField(
        queryset=TutoringSessionNotes.objects.all(), required=False, allow_null=True
    )
    is_course_session = serializers.SerializerMethodField()

    verbose_title = serializers.SerializerMethodField()

    enrolled_students = serializers.SerializerMethodField()
    requires_hours = serializers.SerializerMethodField()
    diagnostic = serializers.PrimaryKeyRelatedField(queryset=Diagnostic.objects.all(), required=False, allow_null=True)

    class Meta:
        model = GroupTutoringSession
        admin_tutor_fields = ("set_pay_tutor_duration",)
        tutor_students_field = ("enrolled_students",)
        exclude_landing_fields = (
            "tutoring_session_notes",
            "resources",
            "primary_tutor",
            "support_tutors",
            "location",
            "zoom_url",
        )
        fields = (
            (
                "pk",
                "slug",
                "start",
                "end",
                "update_resources",
                "location_id",
                "title",
                "capacity",
                "verbose_title",
                "description",
                "cancelled",
                "notes_skipped",
                "is_remote",
                "is_course_session",
                "requires_hours",
                "set_charge_student_duration",
                "outlook_event_id",
                "diagnostic",
            )
            + tutor_students_field
            + exclude_landing_fields
            + admin_tutor_fields
        )

    # extract user making request
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        include_student_names = self.context.get("include_student_names")
        if not include_student_names:
            [self.fields.pop(field_name) for field_name in self.Meta.tutor_students_field]
        if self.context.get("landing"):
            for field_name in self.Meta.exclude_landing_fields:
                self.fields.pop(field_name)
        if not (
            self.context.get("request")
            and (
                hasattr(self.context["request"].user, "administrator")
                or hasattr(self.context["request"].user, "administrator"),
            )
        ):
            [self.fields.pop(field_name) for field_name in self.Meta.admin_tutor_fields]

    def get_requires_hours(self, obj: GroupTutoringSession):
        return obj.charge_student_duration > 0

    def get_enrolled_students(self, obj):
        session_roster = StudentTutoringSession.objects.filter(
            group_tutoring_session=obj.pk, set_cancelled=False, student__isnull=False
        ).values_list("student__invitation_name", flat=True)
        return session_roster

    def get_verbose_title(self, obj):
        if obj.primary_tutor:
            return f"Group Session {obj.title} led by {obj.primary_tutor.name}"
        return obj.title

    def get_is_course_session(self, obj):
        """ True if this session is part of a course """
        return obj.courses.exists()

    def get_notes_url(self, obj):
        if not obj.cancelled and obj.tutoring_session_notes:
            return True
        return False

    def create(self, validated_data):
        """ Override create to set resources """
        update_resource_slugs = validated_data.pop("update_resources", [])
        instance = super(GroupTutoringSessionSerializer, self).create(validated_data)
        instance.resources.set(list(Resource.objects.filter(slug__in=update_resource_slugs)))
        return instance

    def update(self, instance, validated_data):
        """ Override update to overwrite related resources IFF resources are included in update data """
        update_resource_slugs = validated_data.pop("update_resources", None)
        instance = super(GroupTutoringSessionSerializer, self).update(instance, validated_data)
        if update_resource_slugs is not None:
            instance.resources.set(list(Resource.objects.filter(slug__in=update_resource_slugs)))
        return instance


class StudentTutoringSessionSerializer(serializers.ModelSerializer):
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())
    individual_session_tutor = serializers.PrimaryKeyRelatedField(
        queryset=Tutor.objects.all(), required=False, allow_null=True
    )
    # Note that resources is READ ONLY field that returns all resources on this particular session
    # as well as resources on session's related GroupTutoringSession
    resources = ResourceSerializer(many=True, read_only=True)

    # Note tha set_resources is WRITE ONLY field used to update the resources on this StudentTutoringSession object
    set_resources = serializers.PrimaryKeyRelatedField(
        queryset=Resource.objects.all(), write_only=True, many=True, required=False
    )
    title = serializers.SerializerMethodField()
    set_cancelled = serializers.BooleanField(write_only=True, required=False)

    # URL that can be used to obtain PDF of session notes, if notes have been provided
    # and session is not missed
    notes_url = serializers.SerializerMethodField()

    tutoring_session_notes = serializers.PrimaryKeyRelatedField(
        queryset=TutoringSessionNotes.objects.all(), required=False, allow_null=True
    )

    zoom_url = serializers.CharField(read_only=True)
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all(), required=False, allow_null=True)

    tutoring_service = serializers.PrimaryKeyRelatedField(queryset=TutoringService.objects.all(), required=False)
    # Convenience so we don't have to seaparately retrieve TutoringService just to get its name
    tutoring_service_name = serializers.CharField(source="tutoring_service.name", read_only=True)
    verbose_title = serializers.SerializerMethodField()

    primary_tutor = serializers.PrimaryKeyRelatedField(source="group_tutoring_session.primary_tutor", read_only=True)

    # ID of TutoringPackage that can be used to pay for this session
    paygo_tutoring_package = serializers.SerializerMethodField()

    late_cancel_charge_transaction_id = serializers.CharField(read_only=True)

    class Meta:
        model = StudentTutoringSession
        fields = (
            "pk",
            "slug",
            "start",
            "end",
            "student",
            "title",
            "note",
            "group_tutoring_session",
            "individual_session_tutor",
            "cancelled",
            "missed",
            "tutoring_session_notes",
            "notes_skipped",
            "resources",
            "set_resources",
            "duration_minutes",
            "set_cancelled",
            "notes_url",
            "zoom_url",
            "verbose_title",
            "location",
            "is_remote",
            "session_type",
            "tutoring_service",
            "tutoring_service_name",
            "primary_tutor",
            "paygo_tutoring_package",
            "paygo_transaction_id",
            "late_cancel",
            "late_cancel_charge_transaction_id",
            "is_tentative",
            "outlook_event_id",
        )

    def update(self, instance, validated_data):
        """ Pop student and group tutoring session, which can't be updated """
        validated_data.pop("student", None)
        validated_data.pop("group_tutoring_session", None)
        return super(StudentTutoringSessionSerializer, self).update(instance, validated_data)

    def validate(self, attrs):
        if not (
            attrs.get("group_tutoring_session")
            or attrs.get("individual_session_tutor")
            or attrs.get("individual_session_tutor")
            or attrs.get("individual_session_tutor")
            or self.instance
        ):
            raise ValidationError("Group or individual tutoring session must be specified")
        return super(StudentTutoringSessionSerializer, self).validate(attrs)

    def _get_title(self, obj):
        if obj.individual_session_tutor:
            if obj.tutoring_service:
                return f"{obj.tutoring_service} session with {obj.individual_session_tutor.name}"
            return f"Session with {obj.individual_session_tutor.name}"
        elif obj.group_tutoring_session:
            return obj.group_tutoring_session.title

    def get_paygo_tutoring_package(self, obj):
        if obj.student.is_paygo:
            mgr = StudentTutoringPackagePurchaseManager(obj.student)
            package = mgr.get_paygo_tutoring_package(obj)
            if package:
                return package.pk

    def get_verbose_title(self, obj):
        if not (obj.student and obj.individual_session_tutor):
            return self._get_title(obj)
        if obj.tutoring_service:
            return f"Student {obj.student.name} with {obj.individual_session_tutor.name} ({obj.tutoring_service})"
        return f"Student {obj.student.name} with {obj.individual_session_tutor.name}"

    def get_title(self, obj):
        """ User-readable title for session """
        return self._get_title(obj)

    def get_notes_url(self, obj):
        if obj.tutoring_session_notes and not (obj.missed or obj.cancelled):
            if self.context.get("admin") or self.context.get("tutor"):
                return obj.notes_url
            # Ensure student or parent who is allowed to view notes
            user = self.context.get("request").user if self.context.get("request") else None
            if obj.tutoring_session_notes.visible_to_student and (
                self.context.get("student") or user and hasattr(user, "student")
            ):
                return obj.notes_url
            if obj.tutoring_session_notes.visible_to_parent and (
                self.context.get("parent") or user and hasattr(user, "parent")
            ):
                return obj.notes_url


class CourseSerializer(AdminModelSerializer):
    location = LocationSerializer(read_only=True)
    location_id = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), write_only=True, source="location"
    )
    resources = serializers.PrimaryKeyRelatedField(many=True, queryset=Resource.objects.all(), required=False)
    primary_tutor = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.all(), required=False)
    primary_tutor_name = serializers.CharField(read_only=True, source="primary_tutor.invitation_name")
    package = serializers.PrimaryKeyRelatedField(queryset=TutoringPackage.objects.all(), required=False)
    group_tutoring_sessions = serializers.SerializerMethodField()
    group_tutoring_session_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        write_only=True,
        queryset=GroupTutoringSession.objects.all(),
        source="group_tutoring_sessions",
    )
    magento_purchase_link = serializers.CharField(read_only=True, source="package.magento_purchase_link")
    is_remote = serializers.SerializerMethodField()
    first_session = serializers.SerializerMethodField()

    price = serializers.DecimalField(source="package.price", decimal_places=2, max_digits=6, read_only=True)

    class Meta:
        model = Course
        admin_fields = ("students", "package", "resources")
        exclude_landing_fields = (
            "group_tutoring_session_ids",
            "location",
            "time_description",
        )
        fields = (
            (
                "pk",
                "slug",
                "name",
                "description",
                "location_id",
                "primary_tutor",
                "available",
                "display_on_landing_page",
                "group_tutoring_sessions",
                "magento_purchase_link",
                "is_remote",
                "first_session",
                "category",
                "price",
                "primary_tutor_name",
            )
            + admin_fields
            + exclude_landing_fields
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.context.get("landing"):
            for field_name in self.Meta.exclude_landing_fields:
                self.fields.pop(field_name)

    def get_group_tutoring_sessions(self, obj: Course):
        """ SerializerMethodField so we can pass context """
        return GroupTutoringSessionSerializer(obj.group_tutoring_sessions.all(), many=True, context=self.context).data

    def get_is_remote(self, obj):
        """ Course is remote iff all GTS are remote (all GTS have Zoom URL) """
        return all([x.is_remote for x in obj.group_tutoring_sessions.all()])

    def get_first_session(self, obj):
        """ Date of first session in this course """
        first_session = obj.group_tutoring_sessions.order_by("start").first()
        return first_session.start if first_session else None
