from django.db import models
from django.db.models import Q, JSONField
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.core.serializers.json import DjangoJSONEncoder

from sncommon.model_base import CWModel
from sncounseling.models import Roadmap
from snnotifications.models import Notification
from snuniversities.constants import applications


class Task(CWModel):
    """ A task is an item that a user can complete or submit. Tasks are primary used to give
        students "To-Dos". Tasks can be completed or - if they allow file or content submission -
        then they can be submitted. If a task is submitted, then the task can be scored and feedback
        can be provided (for example, if there is a diagnostic associated with the task).
        Tasks can have resources associated with them.
    """

    created_by = models.ForeignKey(
        "auth.user", related_name="created_tasks", null=True, blank=True, on_delete=models.SET_NULL,
    )
    updated_by = models.ForeignKey("auth.user", related_name="+", null=True, blank=True, on_delete=models.SET_NULL)
    title = models.TextField(blank=True)
    description = models.TextField(blank=True)  # Can be HTML!
    # Don't allow changing user task is for via serializer
    for_user = models.ForeignKey("auth.user", related_name="tasks", on_delete=models.CASCADE)
    due = models.DateTimeField(null=True, blank=True)
    # When user who this task is assigned to should be reminded of this task
    reminder = models.DateTimeField(null=True, blank=True)
    last_reminder_sent = models.DateTimeField(null=True, blank=True)
    completed = models.DateTimeField(null=True, blank=True)
    # "Deleted" tasks just have archived set to True (so we keep record of Task)
    archived = models.DateTimeField(null=True, blank=True)
    # Note that task can also have resource(s) via diagnostic
    resources = models.ManyToManyField("snresources.Resource", related_name="tasks")

    # If this task is to submit a rich text submission
    content_submission = models.TextField(blank=True)
    # If this task is to complete a diagnostic
    diagnostic = models.ForeignKey(
        "sntutoring.Diagnostic", related_name="tasks", null=True, blank=True, on_delete=models.CASCADE
    )
    # If this task is to complete a form
    form = models.ForeignKey("sntasks.Form", related_name="tasks", null=True, blank=True, on_delete=models.CASCADE)

    application = models.CharField(max_length=255, choices=applications.APPLICATION_CHOICES, blank=True, default="")
    student_university_decisions = models.ManyToManyField(
        "snuniversities.StudentUniversityDecision", related_name="tasks", blank=True
    )

    # Submission settings
    allow_content_submission = models.BooleanField(default=True)  # Rich text
    require_content_submission = models.BooleanField(default=False)
    allow_file_submission = models.BooleanField(default=True)
    require_file_submission = models.BooleanField(default=False)
    allow_form_submission = models.BooleanField(default=False)
    require_form_submission = models.BooleanField(default=False)

    # Metadata for tasks
    task_type = models.CharField(blank=True, max_length=255)
    related_object_pk = models.IntegerField(null=True, blank=True)
    related_object_content_type = models.ForeignKey(
        ContentType, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )

    # ID (slug) of task (really an assignment) in Prompt.
    # used by CounselingPromptAPIManager to keep tasks/assignmentsin sync
    prompt_id = models.CharField(max_length=255, blank=True)

    # On Counseling platform, tasks can be associated with MULTIPLE meetings
    counselor_meetings = models.ManyToManyField("sncounseling.CounselorMeeting", related_name="tasks", blank=True)
    # This is just a reference field - this is the meeting on the roadmap from when this task was
    # created. Used as a reference for counselors in case they don't create the corresponding meeting when
    # applying the roadmap, but we still want to display which meeting would have been associated with the task
    counselor_meeting_template = models.ForeignKey(
        "sncounseling.CounselorMeetingTemplate", related_name="+", blank=True, null=True, on_delete=models.SET_NULL
    )

    task_template = models.ForeignKey(
        "sntasks.TaskTemplate", related_name="tasks", blank=True, null=True, on_delete=models.SET_NULL
    )

    # Whether or not task is visible to students/parents on counseling platform (independent of whether or
    # not task has due date)
    visible_to_counseling_student = models.BooleanField(default=False)

    # When the task is made visible to student (if CAP task) otherwise when the task is created
    assigned_time = models.DateTimeField(null=True, blank=True)

    """ Incoming FK """
    # file_uploads > Many FileUpload

    def __str__(self):
        return "%s: %s" % (self.for_user.get_full_name(), self.title)

    @property
    def notifications(self):
        """ Returns all notifications with this task as their primary related obj.
            Useful for getting history of reminders for this task.
            EXCLUDES CC
        """
        return (
            Notification.objects.filter(is_cc=False,)
            .filter(
                Q(related_object_content_type=ContentType.objects.get_for_model(Task), related_object_pk=self.pk,)
                | Q(
                    secondary_related_object_content_type=ContentType.objects.get_for_model(Task),
                    secondary_related_object_pk=self.pk,
                )
            )
            .order_by("created")
        )

    @property
    def is_cap(self):
        """ Proxy for whether or not task is a counseling task """
        return bool(self.task_template or (self.created_by and hasattr(self.created, "counselor")))


class TaskTemplate(CWModel):
    """
    `Counselors` use `TaskTemplate` to quickly instantiate predefined `Tasks` for their `Students`
    """

    created_by = models.ForeignKey(
        "auth.user", related_name="created_task_templates", null=True, blank=True, on_delete=models.SET_NULL,
    )
    updated_by = models.ForeignKey("auth.user", related_name="+", null=True, blank=True, on_delete=models.SET_NULL)

    ESSAY = "essay"
    REC = "rec"
    SCHOOL_RESEARCH = "school_research"
    SURVEY = "survey"
    TESTING = "testing"
    TRANSCRIPTS = "transcripts"
    OTHER = "other"

    TASK_TYPE_CHOICES = (
        (ESSAY, "Essay"),
        (REC, "Rec"),
        (SCHOOL_RESEARCH, "School Research"),
        (SURVEY, "Survey"),
        (TESTING, "Testing"),
        (OTHER, "Other"),
    )

    # A TaskTemplate can be associated with a single MeetingTemplate. This signals to counselor the types of tasks
    # they need to create for a meeting (or shows related tasks for upcoming meetings)
    # DEPRECATED - we go through agenda items now
    counselor_meeting_template = models.ForeignKey(
        "sncounseling.CounselorMeetingTemplate",
        related_name="task_templates",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    # DEPRECATED - from old roadmap implementation
    roadmap = models.ForeignKey(
        "sncounseling.Roadmap", null=True, blank=True, on_delete=models.SET_NULL, related_name="task_templates",
    )

    # Used to determine which roadmap task this task template represents (or overrides if created by counselor)
    roadmap_key = models.TextField(blank=True)

    # If counselor copied another task template to create this one
    derived_from_task_template = models.ForeignKey(
        "sntasks.TaskTemplate", related_name="derived_task_templates", null=True, blank=True, on_delete=models.PROTECT
    )
    # If counselor has shared task template so it can be copied by other counselors
    shared = models.BooleanField(default=False)

    task_type = models.CharField(max_length=255, blank=True, choices=TASK_TYPE_CHOICES, default=ESSAY)
    title = models.TextField(blank=True)
    description = models.TextField(blank=True)  # Can be HTML!
    # In place of deleting, task templates are archived
    archived = models.DateTimeField(null=True, blank=True)

    resources = models.ManyToManyField("snresources.Resource", related_name="task_templates", blank=True)
    diagnostic = models.ForeignKey(
        "sntutoring.Diagnostic", related_name="tasks_templates", null=True, blank=True, on_delete=models.CASCADE,
    )
    form = models.ForeignKey(
        "sntasks.Form", related_name="task_templates", null=True, blank=True, on_delete=models.CASCADE
    )

    # Submission settings
    allow_content_submission = models.BooleanField(default=False)  # Rich text
    require_content_submission = models.BooleanField(default=False)
    allow_file_submission = models.BooleanField(default=False)
    require_file_submission = models.BooleanField(default=False)
    allow_form_submission = models.BooleanField(default=False)
    require_form_submission = models.BooleanField(default=False)

    # Whether or not this task template can be used to create multiple tasks for a student
    repeatable = models.BooleanField(default=False)

    # Check out the "Tasks and Student University Decisions" section of sncounseling/README
    # for a description on these fields. TL;DR they determine which SUDs a task is to be associated
    # with, and which fields on SUDs get automatically updated when task is complete
    # Note that for derived task templates, we refer to originating task template (associated directly with a roadmap)
    # to determine these values (and also the agenda item template values below)
    include_school_sud_values = JSONField(encoder=DjangoJSONEncoder, default=dict, blank=True)
    on_complete_sud_update = JSONField(encoder=DjangoJSONEncoder, default=dict, blank=True)
    on_assign_sud_update = JSONField(encoder=DjangoJSONEncoder, default=dict, blank=True)
    only_alter_tracker_values = ArrayField(models.TextField(default=""), blank=True, default=list)

    # If true, then these tasks appear on the parent task list
    counseling_parent_task = models.BooleanField(default=False)

    """ Incoming FK """
    # pre_agenda_item_templates > many AgendaItemTemplate
    # post_agenda_item_templates > many AgendaItemTemplate

    def __str__(self):
        return f"TaskTemplate: {self.title} of type {self.task_type}"

    @property
    def roadmaps(self):
        """ Helper property, since we have to access this ALL the time. This is all of the roadmaps
            that include this task template either as a pre or post meeting task for any of the roadmap's
            task templates
        """
        return Roadmap.objects.filter(
            Q(counselor_meeting_templates__agenda_item_templates__pre_meeting_task_templates=self)
            | Q(counselor_meeting_templates__agenda_item_templates__post_meeting_task_templates=self)
        ).distinct()


class Form(CWModel):
    """ A `Form` that a `Counselor` assigns to their `Students` to complete as part of `Task`.
        Only `Admins` may create/update/delete forms
    """

    university = models.ForeignKey(
        "snuniversities.University", related_name="forms", null=True, blank=True, on_delete=models.SET_NULL,
    )
    created_by = models.ForeignKey(
        "auth.user", related_name="created_forms", null=True, blank=True, on_delete=models.SET_NULL,
    )
    updated_by = models.ForeignKey("auth.user", related_name="+", null=True, blank=True, on_delete=models.SET_NULL)

    title = models.TextField(default="", blank=True)  # The title to display
    description = models.TextField(default="", blank=True)  # Displayed as HTML on front end
    active = models.BooleanField(default=True)
    # Special identifier for some forms (i.e. college_research)
    key = models.CharField(max_length=255, blank=True)

    """ Incoming FK """
    # task_templates > Many (TaskTemplate)
    # tasks > Many (Task)
    # form_submissions > Many (FormSubmission)
    # form_fields > Many (FormField)

    def __str__(self):
        return f"Form: {self.title}"


class FormSubmission(CWModel):
    """ Represents a completed `Form` submitted by a `Student` as part of a `Counselor` assigned `Task`. """

    form = models.ForeignKey(
        "sntasks.Form", related_name="form_submissions", null=True, blank=True, on_delete=models.SET_NULL,
    )
    task = models.OneToOneField(
        "sntasks.Task", related_name="form_submission", blank=True, null=True, on_delete=models.SET_NULL,
    )
    # User who completed this form submission(Can be a student, parent or counselor)
    submitted_by = models.ForeignKey("auth.user", related_name="form_submissions", null=True, on_delete=models.SET_NULL)
    # User who updated this form submission (Can be a student, parent or counselor)
    updated_by = models.ForeignKey("auth.user", related_name="+", null=True, blank=True, on_delete=models.SET_NULL)
    # "Deleted" form submissions just have archived set to True (so we keep record of Task)
    archived = models.DateTimeField(null=True, blank=True)
    # When form was updated
    """ Incoming FK """
    # form_field_entries > Many (FormFieldEntry)

    def __str__(self):
        return f"FormSubmission: Submitted by {self.submitted_by.__str__()} Form({self.form.title})"


class FormField(CWModel):
    """ A field on a `Form` created by a `Admin` or `Counselor` and assigned to a `Student` as a `Task`.
        Two category of field are distinguished:
        Standard Fields: fields identified by `editable=False`
        These fields are always included with a form (unless hidden by `Admin`) and are not editable by `Counselors`
        Custom Fields: fields identified by `editable=True`
        These fields are created/updated by `Counselors` in order to customize a form for their `Students`
    """

    TEXTBOX = "textbox"  # One line (string)
    TEXTAREA = "textarea"  # Multiple lines (string)
    SELECT = "select"  # Single-Select
    MULTI = "multi"  # Multi-Select
    CHECKBOX = "checkbox"  # Boolean
    CHECKBOXES = "checkboxes"  # Multi-Checkboxes
    RADIO = "radio"  # RadioGroup
    UPDOWN = "updown"  # Input (number)
    RANGE = "range"  # Range slider (number)
    INPUT_TYPE_CHOICES = (
        (TEXTBOX, "Textbox (one line)"),
        (TEXTAREA, "Text area (multiple lines)"),
        (SELECT, "Select (one selection)"),
        (MULTI, "Multi-Select (allow multiple selections)"),
        (CHECKBOX, "Checkbox (boolean)"),
        (CHECKBOXES, "Checkboxes (allows for multiple checks)"),
        (RADIO, "Radio options list (one-line radio list)"),
        (UPDOWN, "Input[type=number]"),
        (RANGE, "Input[type=range]"),
    )

    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    NULL = "null"

    FIELD_TYPE_CHOICES = (
        (STRING, "String"),
        (NUMBER, "Number"),
        (INTEGER, "Integer"),
        (BOOLEAN, "Boolean"),
        (ARRAY, "Array"),
        (NULL, "Null"),
    )

    EMAIL = "email"
    URI = "uri"
    DATA_URL = "data-url"
    DATE = "date"
    DATE_TIME = "date-time"

    FIELD_FORMAT_CHOICES = (
        (EMAIL, "Email Type"),
        (URI, "URI Type"),
        (DATA_URL, "File Type"),
        (DATE, "Date Type"),
        (DATE_TIME, "DateTime Type"),
    )

    # The form that this field belongs to
    form = models.ForeignKey("sntasks.Form", related_name="form_fields", null=True, on_delete=models.SET_NULL)

    # Whether this field is editable by counselors (admins can edit all fields)
    # (Non-editable fields are the "standard" fields - always displayed for a given form - unless hidden by admin (display=False))
    editable = models.BooleanField(default=False)

    # basic form fields
    key = models.CharField(max_length=255)  # Identifier for the field on the front end
    title = models.TextField(default="", blank=True)  # Field title to display
    description = models.TextField(default="", blank=True)  # Field description to display
    instructions = models.TextField(default="", blank=True)  # Field instructions to display
    placeholder = models.TextField(default="", blank=True)  # Placeholder value to display
    default = models.TextField(blank=True)  # Default value to display

    # Used to determine what type of field to render on front end
    input_type = models.CharField(max_length=15, choices=INPUT_TYPE_CHOICES, default=TEXTBOX)
    field_type = models.CharField(max_length=12, choices=FIELD_TYPE_CHOICES, default=STRING)

    # Fields that enable client-side field validation (built-in form validation)
    required = models.BooleanField(default=False)  # Whether field requires a response when creating/updating
    min_length = models.IntegerField(null=True, blank=True)  # Minimum length in characters, None for no restriction
    max_length = models.IntegerField(null=True, blank=True)  # Maximum length in characters, None for no limit
    min_num = models.IntegerField(null=True, blank=True)  # Min range for a number field
    max_num = models.IntegerField(null=True, blank=True)  # Max range for a number field

    # Allows additional client-side field validation based on `type` attribute
    field_format = models.CharField(max_length=12, choices=FIELD_FORMAT_CHOICES, blank=True)
    field_pattern = models.CharField(max_length=100, blank=True)

    # Only used for Select/Radio/Multi/Checkboxes. Should be a JSON list of options
    choices = JSONField(encoder=DjangoJSONEncoder, default=list, blank=True)

    # Fields related to front end form UISchema
    # The order to display field within the form (Note: order must be unique for a set of form_fields -- but can have gaps)
    # Prompt Codebase to look: in zoom chat ActivitiesListUtilities.heal_ranks
    order = models.IntegerField(default=0)
    # Whether a field should be hidden on the front end (in place of destory we hide fields)
    hidden = models.BooleanField(default=False)
    # Determines if radio group rendered stacked or inline
    inline = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        "auth.user", related_name="form_fields", null=True, blank=True, on_delete=models.SET_NULL
    )
    updated_by = models.ForeignKey("auth.user", related_name="+", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        # Form field keys must be unique per form
        constraints = [models.UniqueConstraint(fields=["form", "key"], name="unique_form_field")]
        ordering = ["order"]

    """ Incoming FK """
    # form_field_entries > Many (FormFieldEntry)

    def __str__(self):
        return f"FormField: {self.key} for {self.form.title}"


class FormFieldEntry(CWModel):
    """ A student's response to a `FormField` on a `FormSubmission` assigned by their `Counselor` as a `Task`. """

    form_submission = models.ForeignKey(
        "sntasks.FormSubmission", related_name="form_field_entries", null=True, on_delete=models.SET_NULL
    )
    form_field = models.ForeignKey("sntasks.FormField", related_name="form_field_entries", on_delete=models.CASCADE)
    created_by = models.ForeignKey("auth.user", related_name="form_field_entries", null=True, on_delete=models.SET_NULL)
    updated_by = models.ForeignKey("auth.user", related_name="+", null=True, blank=True, on_delete=models.SET_NULL)

    content = models.TextField(default="", blank=True)

    class Meta:
        verbose_name = "Form field entry"
        verbose_name_plural = "Form field entries"

    def __str__(self):
        return f"FormFieldEntry: {self.form_field.key} submitted by {self.created_by.__str__()} for {self.form_submission.form.title} as part of task {self.form_submission.task.title}"
