""" Serializers for CounselorMeeting-related models
"""
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from cwcommon.serializers.base import AdminModelSerializer
from cwcommon.serializers.file_upload import UpdateFileUploadsSerializer
from cwcommon.utilities.availability_manager import AvailabilityManager
from cwcounseling.constants.counselor_time_entry_category import ADMIN_CATEGORIES, ADMIN_TIME_PAY_RATE

from cwcounseling.models import (
    CounselingHoursGrant,
    CounselorAvailability,
    CounselorMeeting,
    CounselorMeetingTemplate,
    CounselorNote,
    AgendaItemTemplate,
    AgendaItem,
    CounselorTimeCard,
    CounselorTimeEntry,
    CounselorEventType,
    RecurringCounselorAvailability,
)

from cwcounseling.utilities.counselor_meeting_manager import CounselorMeetingManager
from cwcounseling.utilities.counselor_time_card_manager import CounselorTimeCardManager
from cwtasks.models import Task, TaskTemplate
from cwtutoring.models import Location
from cwusers.models import Counselor, Student
from cwresources.serializers import ResourceSerializer


class AgendaItemSerializer(serializers.ModelSerializer):
    counselor_meeting = serializers.PrimaryKeyRelatedField(queryset=CounselorMeeting.objects.all())
    counselor_instructions = serializers.SerializerMethodField()

    class Meta:
        model = AgendaItem
        fields = (
            "pk",
            "slug",
            "counselor_title",
            "student_title",
            "counselor_meeting",
            "agenda_item_template",
            "counselor_instructions",
        )
        read_only_fields = ("counselor_title", "student_title", "counselor_instructions")

    def get_counselor_instructions(self, obj: AgendaItem):
        """Must be a request with counselor or admin in context"""
        if not (
            self.context.get("request")
            and (
                hasattr(self.context["request"].user, "counselor")
                or hasattr(self.context["request"].user, "administrator")
            )
        ):
            return None
        return obj.agenda_item_template.counselor_instructions if obj.agenda_item_template else ""


class AgendaItemTemplateSerializer(serializers.ModelSerializer):
    """Serializer for counselor meeting agenda item templates
    Note that this serializer includes full nested pre and post meeting task templates
    """

    pre_meeting_task_templates = serializers.PrimaryKeyRelatedField(
        many=True, queryset=TaskTemplate.objects.all(), required=False
    )
    post_meeting_task_templates = serializers.PrimaryKeyRelatedField(
        many=True, queryset=TaskTemplate.objects.all(), required=False
    )
    counselor_meeting_template = serializers.PrimaryKeyRelatedField(
        queryset=CounselorMeetingTemplate.objects.all(), required=False
    )

    class Meta:
        model = AgendaItemTemplate
        fields = (
            "pk",
            "slug",
            "counselor_title",
            "student_title",
            "pre_meeting_task_templates",
            "post_meeting_task_templates",
            "counselor_meeting_template",
            "order",
            "repeatable",
            "counselor_instructions",
        )


class CounselorMeetingTemplateSerializer(serializers.ModelSerializer):
    counselor_resources = ResourceSerializer(many=True, required=False)
    # Array of task types of all related task templates
    agenda_item_templates = AgendaItemTemplateSerializer(many=True, read_only=True)

    class Meta:
        model = CounselorMeetingTemplate
        fields = (
            "pk",
            "slug",
            "title",
            "counselor_instructions",
            "student_instructions",
            "counselor_resources",
            "roadmap",
            "agenda_item_templates",
            "order",
            "create_when_applying_roadmap",
            "grade",
            "semester",
            "use_agenda",
        )


class CounselorMeetingSerializer(UpdateFileUploadsSerializer, serializers.ModelSerializer):
    related_name_field = "counselor_meeting"

    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())
    student_name = serializers.CharField(source="student.name", read_only=True)
    zoom_url = serializers.SerializerMethodField()
    use_agenda = serializers.BooleanField(source="counselor_meeting_template.use_agenda", read_only=True)
    counselor_instructions = serializers.CharField(
        source="counselor_meeting_template.counselor_instructions", read_only=True
    )
    student_instructions = serializers.CharField(
        source="counselor_meeting_template.student_instructions", read_only=True
    )
    description = serializers.CharField(read_only=True, source="counselor_meeting_template.description")
    # When meeting occurs on roadmap
    grade = serializers.IntegerField(read_only=True, source="counselor_meeting_template.grade")
    semester = serializers.IntegerField(read_only=True, source="counselor_meeting_template.semester")

    student_resources = ResourceSerializer(many=True, required=False, read_only=True)
    tasks = serializers.PrimaryKeyRelatedField(many=True, queryset=Task.objects.all(), required=False)
    # Number of related tasks that have due dates
    assigned_task_count = serializers.SerializerMethodField()
    agenda_items = serializers.PrimaryKeyRelatedField(many=True, queryset=AgendaItem.objects.all(), required=False)
    order = serializers.SerializerMethodField()
    counselor_meeting_template_name = serializers.SerializerMethodField()

    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all(), allow_null=True, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not (
            self.context.get("counselor")
            or self.context.get("request")
            and hasattr(self.context["request"].user, "counselor")
        ):
            [self.fields.pop(x) for x in self.Meta.counselor_fields]

    class Meta:
        model = CounselorMeeting
        counselor_fields = (
            "private_notes",
            "counselor_instructions",
            "counselor_meeting_template_name",
            "notes_message_last_sent",
            "update_file_uploads",
            "use_agenda",
        )
        read_only_fields = ("notes_message_last_sent", "use_agenda")
        fields = (
            "student",
            "student_name",
            "pk",
            "slug",
            "title",
            "counselor_meeting_template",
            "start",
            "end",
            "duration_minutes",
            "cancelled",
            "student_notes",
            "student_resources",
            "student_instructions",
            "agenda_items",
            "tasks",
            "assigned_task_count",
            "order",
            "outlook_event_id",
            "notes_message_note",
            "notes_message_subject",
            "notes_message_upcoming_tasks",
            "notes_message_completed_tasks",
            "link_schedule_meeting_pk",
            "file_uploads",
            "event_type",
            "notes_finalized",
            "grade",
            "semester",
            "description",
            "zoom_url",
            "student_schedulable",
            "location",
        ) + counselor_fields

    def get_zoom_url(self, obj: CounselorMeeting):
        return obj.student.counselor.zoom_url if obj.student.counselor and not obj.location else ""

    def get_counselor_meeting_template_name(self, obj: CounselorMeeting):
        return obj.counselor_meeting_template.title if obj.counselor_meeting_template else ""

    def get_assigned_task_count(self, obj: CounselorMeeting):
        return obj.tasks.filter(due__isnull=False).count()

    def get_order(self, obj: CounselorMeeting):
        return obj.counselor_meeting_template.order if obj.counselor_meeting_template else None

    def save(self, **kwargs):
        start_end_included = "start" in self.initial_data or "end" in self.initial_data
        old_start = self.instance.start if self.instance else None
        old_location = self.instance.location
        new_start = self.validated_data.pop("start", None)
        new_end = self.validated_data.pop("end", None)
        cancelled = self.validated_data.pop("cancelled", None)

        counselor_meeting: CounselorMeeting = super(CounselorMeetingSerializer, self).save(**kwargs)
        new_start_date = new_start.strftime("%y-%m-%d %H:%M") if new_start else None
        old_start_date = counselor_meeting.start.strftime("%y-%m-%d %H:%M") if counselor_meeting.start else None
        mgr = CounselorMeetingManager(counselor_meeting)

        rescheduled = (new_start_date and new_start_date != old_start_date) or cancelled
        location_change = old_location != self.validated_data.get("location")

        if rescheduled or location_change:
            # We scheduled - need to send notification

            # Check if session is being cancelled
            if cancelled:
                counselor_meeting = mgr.cancel()
            # Not cancelling, must be scheduling/rescheduling
            else:
                send_noti = self.context.get("send_notification", True)
                actor = self.context["request"].user if self.context.get("request") else None
                counselor_meeting = (
                    mgr.schedule(new_start, new_end, send_notification=send_noti, actor=actor)
                    if not old_start
                    else mgr.reschedule(new_start, new_end, send_notification=send_noti, actor=actor)
                )
        elif start_end_included and old_start_date and not new_start_date:
            # Meeting is getting unscheduled. Cancel it (but don't set cancelled prop!)
            counselor_meeting = mgr.cancel(set_cancelled=False, send_notification=False)
        elif new_end:
            # Make sure we save the new end, even if the start did not change
            counselor_meeting.end = new_end
            counselor_meeting.save()
        self.instance = counselor_meeting
        return counselor_meeting


class CounselorNoteSerializer(serializers.ModelSerializer):
    counselor_meeting = serializers.PrimaryKeyRelatedField(
        queryset=CounselorMeeting.objects.all(), allow_null=True, required=False
    )
    student = serializers.PrimaryKeyRelatedField(read_only=True, source="counselor_meeting.student", allow_null=True)
    meeting_date = serializers.DateTimeField(read_only=True, source="counselor_meeting.start", allow_null=True)
    note_date = serializers.DateField(allow_null=True, required=False)
    note_student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all(), allow_null=True, required=False)

    class Meta:
        model = CounselorNote
        fields = (
            "pk",
            "slug",
            "title",
            "counselor_meeting",
            "category",
            "note",
            "student",
            "meeting_date",
            "note_date",
            "note_student",
            "note_title",
        )


class CounselingHoursGrantSerializer(serializers.ModelSerializer):
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all(), required=False)
    date = serializers.DateTimeField(source="created", required=False)
    student_name = serializers.CharField(read_only=True, source="student.name")

    class Meta:
        model = CounselingHoursGrant
        fields = (
            "date",
            "pk",
            "slug",
            "marked_paid",
            "created",
            "number_of_hours",
            "student",
            "note",
            "amount_paid",
            "magento_id",
            "student_name",
            "include_in_hours_bank",
        )
        read_only_fields = ("pk", "slug", "created", "magento_id")

    def validate_student(self, value):
        if self.instance and value != self.instance.student:
            raise ValidationError("Cannot change the student on a CounselingHoursGrant")
        return value


class CounselorTimeEntrySerializer(serializers.ModelSerializer):
    # Custom fields for CSV representation of data
    hours_used = serializers.SerializerMethodField()
    hours_added = serializers.SerializerMethodField()
    counselor_time_card = serializers.PrimaryKeyRelatedField(
        queryset=CounselorTimeCard.objects.all(), required=False, allow_null=True,
    )
    counselor_name = serializers.SerializerMethodField()
    student_name = serializers.SerializerMethodField()
    student_packages = serializers.SerializerMethodField()

    amount_paid = serializers.FloatField(read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.context.get("format") == "csv":
            self.fields.pop("hours")
        else:
            self.fields.pop("hours_used", "hours_added")

    def validate(self, attrs):
        if attrs.get("counselor") and not attrs.get("student"):
            # If logging time for counselor only, then counselor MUST be part time
            if not attrs["counselor"].part_time:
                raise ValidationError("Can only log time for part time counselors")
        return super().validate(attrs)

    class Meta:
        model = CounselorTimeEntry
        fields = (
            "pk",
            "slug",
            "date",
            "hours",
            "student",
            "category",
            "note",
            "created_by",
            "counselor",
            "hours_used",
            "hours_added",
            "counselor_time_card",
            "counselor_name",
            "student_name",
            "student_packages",
            "amount_paid",
            "marked_paid",
            "pay_rate",
            "include_in_hours_bank",
        )
        read_only_fields = (
            "amount_paid",
            "created_by",
            "pk",
            "slug",
            "counselor_name",
            "student_name",
            "student_packages",
        )

    def get_student_packages(self, obj: CounselorTimeEntry):
        return "; ".join(obj.student.counseling_student_types_list) if obj.student else ""

    def get_counselor_name(self, obj: CounselorTimeEntry):
        return obj.counselor.name if obj.counselor else ""

    def get_student_name(self, obj: CounselorTimeEntry):
        return obj.student.name if obj.student else ""

    def get_hours_used(self, obj: CounselorTimeEntry):
        return obj.hours if obj.hours >= 0 else ""

    def get_hours_added(self, obj: CounselorTimeEntry):
        return abs(obj.hours) if obj.hours < 0 else ""

    def save(self, **kwargs):
        old_time_card = self.instance.counselor_time_card if self.instance else None
        updated_instance: CounselorTimeEntry = super().save(**kwargs)
        if updated_instance.counselor_time_card:
            # Ensure we set admin time pay rate
            if updated_instance.category in ADMIN_CATEGORIES and not updated_instance.pay_rate:
                updated_instance.pay_rate = ADMIN_TIME_PAY_RATE
                updated_instance.save()
            if not updated_instance.counselor_time_card.admin_approval_time:
                mgr = CounselorTimeCardManager(updated_instance.counselor_time_card)
                mgr.set_total()
            if (
                old_time_card
                and not old_time_card.admin_approval_time
                and updated_instance.counselor_time_card != old_time_card
            ):
                mgr = CounselorTimeCardManager(old_time_card)
                mgr.set_total()
        return updated_instance


class CounselorTimeCardSerializer(AdminModelSerializer):
    counselor_time_entries = serializers.PrimaryKeyRelatedField(
        required=False, many=True, queryset=CounselorTimeEntry.objects.all()
    )

    # Approval stuff is updated in dedicated viewset actions, not via serializer
    admin_approval_time = serializers.DateTimeField(read_only=True)
    counselor_approval_time = serializers.DateTimeField(read_only=True)
    admin_approver = serializers.PrimaryKeyRelatedField(read_only=True)

    counselor = serializers.PrimaryKeyRelatedField(queryset=Counselor.objects.all())
    counselor_name = serializers.CharField(source="counselor.name")
    hourly_rate = serializers.DecimalField(decimal_places=2, max_digits=5, required=False)

    admin_has_approved = serializers.SerializerMethodField()

    class Meta:
        model = CounselorTimeCard
        admin_fields = ("admin_approval_time", "admin_approver", "admin_note")
        fields = (
            "pk",
            "slug",
            "counselor_time_entries",
            "counselor",
            "start",
            "end",
            "counselor_approval_time",
            "counselor_note",
            "hourly_rate",
            "total",
            "total_hours",
            "admin_has_approved",
            "counselor_name",
        ) + admin_fields

    def get_admin_has_approved(self, obj: CounselorTimeCard):
        return bool(obj.admin_approval_time)


class CounselorEventTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CounselorEventType
        fields = ("pk", "created_by", "duration", "title", "description")


class CounselorAvailabilitySerializer(serializers.ModelSerializer):
    counselor = serializers.PrimaryKeyRelatedField(queryset=Counselor.objects.all())
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all(), required=False, allow_null=True)

    class Meta:
        model = CounselorAvailability
        fields = ("pk", "slug", "start", "end", "counselor", "location")


class RecurringCounselorAvailabilitySerializer(serializers.ModelSerializer):
    availability = serializers.JSONField()
    pk = serializers.IntegerField(read_only=True)
    counselor = serializers.PrimaryKeyRelatedField(queryset=Counselor.objects.all())
    locations = serializers.JSONField(required=False)

    class Meta:
        model = RecurringCounselorAvailability
        fields = ("pk", "counselor", "availability", "locations")

    def validate(self, val):
        """Make sure there are no overlapping availabilities, every day is included"""
        mgr = AvailabilityManager(val["counselor"])
        mgr.validate_recurring_availability(val["availability"])
        if "locations" in val:
            mgr.validate_locations(val["locations"])
        return val
