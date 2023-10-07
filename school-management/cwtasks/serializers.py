from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from django.contrib.auth.models import User
from django.db.models import Q

from cwcommon.serializers.base import AdminModelSerializer
from cwcommon.serializers.file_upload import UpdateFileUploadsSerializer
from cwcounseling.serializers.counselor_meeting import AgendaItemTemplateSerializer
from cwcounseling.serializers.roadmap import RoadmapSerializer
from cwcounseling.models import CounselorMeeting, AgendaItemTemplate
from cwresources.models import Resource
from cwcounseling.models import Roadmap
from cwresources.serializers import ResourceSerializer
from cwtutoring.models import DiagnosticResult, Diagnostic
from cwtutoring.serializers.diagnostics import DiagnosticSerializer
from snusers.models import get_cw_user
from cwuniversities.models import StudentUniversityDecision
from .models import Task, TaskTemplate, FormFieldEntry, FormField, FormSubmission, Form
from cwtasks.utilities.task_manager import TaskManager


class FormFieldEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = FormFieldEntry
        fields = ("pk", "slug", "content", "form_field", "form_submission")


class FormFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormField
        fields = (
            "pk",
            "slug",
            "form",
            "key",
            "title",
            "description",
            "instructions",
            "placeholder",
            "default",
            "input_type",
            "field_type",
            "required",
            "min_length",
            "max_length",
            "min_num",
            "max_num",
            "field_format",
            "field_pattern",
            "choices",
            "order",
            "inline",
            "created_by",
        )


class FormSubmissionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormSubmission
        fields = ("pk", "slug", "form", "task", "submitted_by")


class FormSubmissionSerializer(serializers.ModelSerializer):
    form_field_entries = FormFieldEntrySerializer(many=True, required=False)

    class Meta:
        model = FormSubmission
        fields = ("pk", "slug", "form", "task", "submitted_by", "form_field_entries")

    def create(self, validated_data):
        form_field_entries_data = validated_data.pop("form_field_entries", [])
        instance = super(FormSubmissionSerializer, self).create(validated_data)
        for form_field_entry in form_field_entries_data:
            FormFieldEntry.objects.create(
                form_submission=instance, created_by=instance.submitted_by, **form_field_entry
            )
        return instance

    def update(self, instance, validated_data):
        form_field_entries_data = validated_data.pop("form_field_entries", [])
        for form_field_entry in form_field_entries_data:
            ffe, created = FormFieldEntry.objects.get_or_create(
                form_submission=instance, form_field=form_field_entry["form_field"]
            )
            ffe.content = form_field_entry["content"]
            ffe.save()
        return instance


class FormListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Form
        fields = ("pk", "slug", "title", "description", "university", "active")


class FormSerializer(serializers.ModelSerializer):
    form_fields = serializers.SerializerMethodField()
    form_fields_write = FormFieldSerializer(required=False, many=True,)

    class Meta:
        model = Form
        fields = ("pk", "slug", "title", "description", "university", "form_fields", "form_fields_write", "active")

    def get_form_fields(self, obj):
        queryset = FormField.objects.filter(form=obj).filter(hidden=False).filter(Q(editable=False))
        return FormFieldSerializer(queryset, many=True).data

    def create(self, validated_data):
        form_fields_data = validated_data.pop("form_fields_write", [])
        instance = super(FormSerializer, self).create(validated_data)
        for form_field in form_fields_data:
            FormField.objects.create(form=instance, created_by=instance.created_by, **form_field)
        return instance

    def update(self, instance, validated_data):
        """ Pop nested form fields. Can't update nested relations. Use form_field update endpoint """
        validated_data.pop("form_fields_write", None)
        return super(FormSerializer, self).update(instance, validated_data)


class TaskSerializer(UpdateFileUploadsSerializer, AdminModelSerializer):
    related_name_field = "task"

    for_user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    # For convenience on the frontend
    for_student = serializers.IntegerField(source="for_user.student.pk", read_only=True)
    diagnostic = DiagnosticSerializer(read_only=True)
    form = FormSerializer(read_only=True)
    form_submission_id = serializers.PrimaryKeyRelatedField(source="form_submission", read_only=True)
    # Used to create task with diagnostic
    diagnostic_id = serializers.PrimaryKeyRelatedField(
        write_only=True, required=False, allow_null=True, source="diagnostic", queryset=Diagnostic.objects.all(),
    )
    # Used to create task with form
    form_id = serializers.PrimaryKeyRelatedField(
        write_only=True, required=False, allow_null=True, source="form", queryset=Form.objects.all(),
    )
    diagnostic_result = serializers.PrimaryKeyRelatedField(
        required=False, queryset=DiagnosticResult.objects.all(), allow_null=True
    )
    resources = serializers.SerializerMethodField()
    set_resources = serializers.PrimaryKeyRelatedField(
        queryset=Resource.objects.all(), write_only=True, many=True, source="resources", required=False
    )
    is_prompt_task = serializers.SerializerMethodField()
    counselor_meetings = serializers.PrimaryKeyRelatedField(
        write_only=True, required=False, queryset=CounselorMeeting.objects.all(), many=True
    )
    student_university_decisions = serializers.PrimaryKeyRelatedField(
        many=True, queryset=StudentUniversityDecision.objects.all(), required=False
    )
    repeatable = serializers.BooleanField(read_only=True, source="task_template.repeatable")

    # Pulled from obj.counselor_meeting_template
    counselor_meeting_template_name = serializers.SerializerMethodField()

    # Whether or not task is for counseling parent (as oppose to students)
    counseling_parent_task = serializers.SerializerMethodField()

    # Whether or not task is for counseling platform (visible to counselors)
    is_cap_task = serializers.SerializerMethodField()

    affects_tracker = serializers.SerializerMethodField()

    def validate(self, attrs):
        """ Validate update_file_uploads """
        if self.instance:
            if (
                (not self.instance.file_uploads.exists())
                and not (self.instance.allow_file_submission or self.instance.require_file_submission)
                and attrs.get("update_file_uploads")
            ):
                raise ValidationError("File submission not allowed")
            if (
                (not self.instance.content_submission)
                and not (self.instance.allow_content_submission or self.instance.require_content_submission)
                and attrs.get("content_submission")
            ):
                raise ValidationError("Content submission not allowed")

        # Can't have task use task template that belongs to a counselor other than this student's
        if self.instance and attrs.get("task_template"):
            if not (self.instance.task_template and self.instance.task_template == attrs.get("task_template")):
                if attrs["task_template"].created_by and not (
                    hasattr(attrs["for_user"], "student")
                    and attrs["for_user"].student.counselor
                    and attrs["for_user"].student.counselor.user == attrs["task_template"].created_by
                ):
                    raise ValidationError("Invalid task template")

        return attrs

    class Meta:
        model = Task
        admin_fields = ("created_by", "updated_by", "created", "archived")
        read_only_fields = ("last_reminder_sent",)
        fields = (
            "pk",
            "slug",
            "task_type",
            "title",
            "description",
            "due",
            "completed",
            "for_user",
            "diagnostic",
            "diagnostic_id",
            "form",
            "repeatable",
            "form_id",
            "allow_content_submission",
            "content_submission",
            "allow_file_submission",
            "file_uploads",
            "update_file_uploads",
            "allow_form_submission",
            "require_form_submission",
            "require_file_submission",
            "require_content_submission",
            "diagnostic_result",
            "resources",
            "for_student",
            "student_university_decisions",
            "task_type",
            "task_template",
            "set_resources",
            "is_prompt_task",
            "is_cap_task",
            "counselor_meetings",
            "form_submission_id",
            "counselor_meeting_template_name",
            "visible_to_counseling_student",
            "counseling_parent_task",
            "affects_tracker",
            "last_reminder_sent",
        ) + admin_fields

    def update(self, instance, validated_data):
        validated_data.pop("for_user", None)
        validated_data.pop("diagnostic", None)
        validated_data.pop("form", None)

        return super(TaskSerializer, self).update(instance, validated_data)

    def get_counselor_meeting_template_name(self, obj: Task):
        return obj.counselor_meeting_template.title if obj.counselor_meeting_template else ""

    def get_counseling_parent_task(self, obj: Task):
        return obj.task_template.counseling_parent_task if obj.task_template else False

    def get_resources(self, obj: Task):
        """ All resources directly tied to task or tied to task through diagnostic """
        task_resources = list(Resource.objects.filter(tasks=obj))
        if obj.diagnostic:
            task_resources += list(Resource.objects.filter(diagnostics=obj.diagnostic))
        return ResourceSerializer(task_resources, many=True).data

    def get_is_prompt_task(self, obj):
        return bool(obj.prompt_id)

    def get_is_cap_task(self, obj: Task):
        # Is a CAP task as long as it's NOT created by a tutor w/o a diag
        is_cap = not bool(hasattr(obj.created_by, "tutor") and not bool(obj.diagnostic_id))
        return is_cap

    def get_affects_tracker(self, obj: Task):
        return obj.task_template and (
            obj.task_template.on_complete_sud_update != {} or obj.task_template.on_assign_sud_update != {}
        )

    def create(self, validated_data):
        """ We override create to create a notification whenever task is created.
            Note that notification type depends on the tasks type
        """
        if self.context.get("creator"):
            validated_data["created_by"] = self.context["creator"]
        return super(TaskSerializer, self).create(validated_data)


class TaskTemplateSerializer(serializers.ModelSerializer):
    is_stock = serializers.SerializerMethodField()
    derived_from_task_template = serializers.PrimaryKeyRelatedField(
        queryset=TaskTemplate.objects.all(), required=False, allow_null=True
    )
    resources = serializers.PrimaryKeyRelatedField(queryset=Resource.objects.all(), many=True, required=False)
    roadmap_count = serializers.SerializerMethodField() #error maximum recursion depth exceeded in comparison
    pre_agenda_item_templates = serializers.PrimaryKeyRelatedField(queryset=AgendaItemTemplate.objects.all(), many=True, required=False) #AgendaItemTemplateSerializer(many=True, read_only=True)
    post_agenda_item_templates = serializers.PrimaryKeyRelatedField(queryset=AgendaItemTemplate.objects.all(), many=True, required=False) #AgendaItemTemplateSerializer(many=True, read_only=True)

    class Meta:
        model = TaskTemplate
        fields = (
            "pk",
            "slug",
            "task_type",
            "title",
            "description",
            "resources",
            "diagnostic",
            "form",
            "allow_content_submission",
            "require_content_submission",
            "require_content_submission",
            "allow_file_submission",
            "require_file_submission",
            "allow_form_submission",
            "require_form_submission",
            "roadmap_count",
            "include_school_sud_values",
            "is_stock",
            "created",
            "counseling_parent_task",
            "derived_from_task_template",
            "shared",
            "roadmap_key",
            "created_by",
            "pre_agenda_item_templates",
            "post_agenda_item_templates",

        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.context.get("request") and self.context["request"].method.lower() == "get":
            for field in list(self.fields.keys()):
                self.fields[field].read_only = True
        self.counselor = None
        if self.context.get("request") and hasattr(self.context["request"].user, "counselor"):
            self.counselor = self.context["request"].user.counselor

    def validate(self, attrs):
        """ A counselor can only have one task template with a given roadmap key active at a time
            and cannot write to roadmap_key except when creating a task template
        """
        if self.instance and self.instance.roadmap_key != attrs.get("roadmap_key", ""):
            raise ValidationError("Cannot change TaskTemplate.roadmap_key")
        if attrs.get("roadmap_key") and self.counselor:
            existing_template = TaskManager.get_task_template_for_counselor(self.counselor, attrs["roadmap_key"])
            if (
                existing_template
                and existing_template.created_by
                and not (self.instance and self.instance == existing_template)
            ):
                raise ValidationError("Can only have one active task template for each roadmap task")
        return super().validate(attrs)

    def save(self, **kwargs):
        creating = not bool(self.instance)
        task_template: TaskTemplate = super().save(**kwargs)
        if self.counselor:
            task_template.created_by = self.counselor.user
        if creating and task_template.created_by and task_template.roadmap_key:
            # Copy values from roadmap task template, if it exists
            roadmap_task_template: TaskTemplate = TaskTemplate.objects.filter(
                roadmap_key=task_template.roadmap_key, created_by=None
            ).first()
            if roadmap_task_template:
                task_template.on_assign_sud_update = roadmap_task_template.on_assign_sud_update
                task_template.on_complete_sud_update = roadmap_task_template.on_complete_sud_update
                task_template.include_school_sud_values = roadmap_task_template.include_school_sud_values
        task_template.save()
        return task_template

    def get_is_stock(self, obj: TaskTemplate):
        return not bool(obj.created_by)

    def get_roadmap_count(self, obj: TaskTemplate):

        ids = obj.pre_agenda_item_templates.all().values_list('pk', flat=True)
        pre_ids = list(ids)

        return Roadmap.objects.filter(
            Q(counselor_meeting_templates__agenda_item_templates__in=pre_ids)
        ).distinct().count()