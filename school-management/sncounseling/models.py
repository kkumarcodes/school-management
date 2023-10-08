from decimal import Decimal
from typing import List, cast
from O365.utils.utils import OneDriveWellKnowFolderNames
from django.core.validators import MinValueValidator

from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.db.models.aggregates import Sum
from django.db.models.deletion import SET, SET_NULL
from django.db.models.fields.related import ForeignKey
from django.db.models.query_utils import Q

from sncommon.model_base import SNModel
from sncommon.models import BaseAvailability, BaseRecurringAvailability, TimeCardBase

from sncounseling.constants import (
    counselor_note_category,
    roadmap_semesters,
    student_activity_category,
    student_activity_recognition_level,
    counselor_time_entry_category,
)


class AgendaItemTemplate(SNModel):
    """An agenda item that a counselor could include on a meeting should they want to
    SN defines stock agenda items that have related pre and post meeting task templates
    Counselors can also define their own agenda items (with no related task templates)
    """

    key = models.TextField(blank=True)

    # The meeting template that this agenda item template is associated with
    counselor_meeting_template = models.ForeignKey(
        "sncounseling.CounselorMeetingTemplate",
        related_name="agenda_item_templates",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    # Agenda items are ordered on meetings
    order = models.IntegerField(default=1)

    # Inactive items are not shown to counselors, but are retained for auditability
    active = models.BooleanField(default=True)

    # Title as it appears to counselor and student/parent
    counselor_title = models.CharField(max_length=255, blank=True)
    student_title = models.CharField(max_length=255, blank=True)
    counselor_instructions = models.TextField(blank=True)

    # The templates used to define tasks created as pre-meeting tasks
    pre_meeting_task_templates = models.ManyToManyField(
        "sntasks.TaskTemplate", related_name="pre_agenda_item_templates", blank=True
    )
    post_meeting_task_templates = models.ManyToManyField(
        "sntasks.TaskTemplate", related_name="post_agenda_item_templates", blank=True
    )

    repeatable = models.BooleanField(default=True)

    def __str__(self):
        return f"Agenda item {self.counselor_title} for {self.counselor_meeting_template}"

    class Meta:
        ordering = ["order"]


class AgendaItem(SNModel):
    """Agenda items are created for CounselorMeetings from agenda item templates
    They can also be created by counselors
    """

    agenda_item_template = models.ForeignKey(
        "sncounseling.AgendaItemTemplate",
        related_name="agenda_items",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    counselor_meeting = models.ForeignKey(
        "sncounseling.CounselorMeeting", related_name="agenda_items", on_delete=models.CASCADE
    )
    order = models.IntegerField(default=1)

    # Title as it appears to counselor and student/parent
    counselor_title = models.CharField(max_length=255, blank=True)
    student_title = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Agenda item {self.counselor_title} for {self.counselor_meeting}"


class CounselorMeetingTemplate(SNModel):
    """A template for a meeting. That is a type of meeting. Can include resources or instructions for counselor
    and student
    Initial implementation based off of meeting cadence described here:
    https://www.notion.so/Counseling-Application-Plan-Resources-52139d2c9a5445039e70015a483b3ebd#08c967be923849f2a532d44d7404ab67
    """

    # To be used to uniquely identify meeting templates (so that the title can change)
    key = models.TextField(blank=True)
    order = models.SmallIntegerField(default=1)

    title = models.TextField(blank=True)
    # Rich text - HTML
    counselor_instructions = models.TextField(blank=True)
    student_instructions = models.TextField(blank=True)
    counselor_resources = models.ManyToManyField(
        "snresources.Resource", related_name="counselor_meeting_template_resources", blank=True
    )

    roadmap = models.ForeignKey(
        "sncounseling.Roadmap",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="counselor_meeting_templates",
    )

    # Description for families
    description = models.TextField(blank=True)

    # Half grades indicate summer-first semester transtion between two grades
    grade = models.DecimalField(blank=True, null=True, decimal_places=1, max_digits=3)

    # These are labeled differently in different places. See roadmap_semesters constant for enumeration of values
    semester = models.FloatField(null=True, blank=True, choices=roadmap_semesters.CHOICES)

    create_when_applying_roadmap = models.BooleanField(default=False)

    use_agenda = models.BooleanField(
        default=True, help_text="Whether or not counselors can set an agenda for meetings that use this meeting type"
    )

    # Incoming FK
    # counselor_meetings > many CounselorMeeting
    # agenda_item_templates > many AgendaItemTemplate

    def __str__(self):
        return f"CounselorMeetingTemplate: {self.title}"

    class Meta:
        ordering = ["order"]

    @property
    def task_templates(self):
        """This property is primarily used for debugging so we don't have to write these darned
        Q statements all the time like a lunatic
        Returns all task templates associated with CMT
        """
        from sntasks.models import TaskTemplate

        return TaskTemplate.objects.filter(
            Q(pre_agenda_item_templates__counselor_meeting_template=self)
            | Q(post_meeting_task_templates__counselor_meeting_template=self)
        ).distinct()


class CounselorMeeting(SNModel):
    """A meeting with a counselor. Counselor is meeting with a student or parent or both"""

    # If meeting was created from a template
    counselor_meeting_template = models.ForeignKey(
        "sncounseling.CounselorMeetingTemplate",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="counselor_meetings",
    )

    event_type = models.ForeignKey(
        "sncounseling.CounselorEventType",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="counselor_meetings",
    )

    student = models.ForeignKey("snusers.Student", related_name="counselor_meetings", on_delete=models.CASCADE)

    created_by = models.ForeignKey(
        "auth.user", related_name="created_counselor_meetings", null=True, blank=True, on_delete=models.SET_NULL
    )

    title = models.TextField(blank=True)
    # Note that meetings can be UNSCHEDULED in which case they have no start/end date (yet)
    start = models.DateTimeField(null=True, blank=True)
    end = models.DateTimeField(null=True, blank=True)
    # A counselor can optionally fix the meeting duration for a student without actually scheduling the meeting
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    # Private note _before_ meeting that counselor can edit
    private_notes = models.TextField(blank=True)
    # Notes visible to and editable by student and parent
    student_notes = models.TextField(blank=True)
    student_resources = models.ManyToManyField(
        "snresources.Resource", related_name="counselor_meeting_student_resources", blank=True
    )
    last_reminder_sent = models.DateTimeField(null=True, blank=True)
    # If set, then session is cancelled. This field indicates when session was cancelled
    cancelled = models.DateTimeField(null=True, blank=True)
    # Whether or not this meeting is schedulable by a student
    student_schedulable = models.BooleanField(default=False)
    # Counselor can send notes to student/parent after meeting in a message. The fields below record
    # the HTML message, and selected upcoming/completed tasks for the message the counselor wants to send
    notes_message_note = models.TextField(blank=True)
    notes_message_subject = models.TextField(blank=True)
    notes_message_upcoming_tasks = models.ManyToManyField("sntasks.Task", related_name="+", blank=True)
    notes_message_completed_tasks = models.ManyToManyField("sntasks.Task", related_name="+", blank=True)
    notes_message_last_sent = models.DateTimeField(blank=True, null=True)
    # If set, we include in email a link to schedule next counselor meeting with PK indicated by this field
    # We don't use FK here because meeting may get deleted, but we need to maintain record of whether or not
    # link was included (and what meeting it was for)
    # Also no strict need to enforce FK constraints here. If this PK is wrong, then the link will just open UMS
    # and won't show modal to schedule meeting
    link_schedule_meeting_pk = models.IntegerField(null=True, blank=True)
    # Finalized notes are visible to parent/student even if they aren't sent
    notes_finalized = models.BooleanField(default=False)
    # for Outlook authorization
    outlook_event_id = models.TextField(blank=True, null=True)

    location = models.ForeignKey("sntutoring.Location", null=True, blank=True, on_delete=models.SET_NULL)

    # Incoming FK
    # tasks > many Task
    # counselor_notes > many CounselorNote
    def __str__(self):
        return f"Counselor {self.student.counselor} meeting with student {self.student} on {self.start}"


class Roadmap(SNModel):
    """A Roadmap is a pre-defined collection of TaskTemplates, MeetingTemplates and Resources"""

    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    category = models.CharField(blank=True, max_length=255)
    # Whether or not roadmap can be applied even if this or another roadmap has already been applied
    repeatable = models.BooleanField(default=False)

    def __str__(self):
        return f"Roadmap: {self.title}"

    @property
    def all_task_templates(self):
        """ Shortcut that gets all task templates associated with meetings on this roadmap
        """
        from sntasks.models import TaskTemplate

        return TaskTemplate.objects.filter(
            Q(pre_agenda_item_templates__counselor_meeting_template__roadmap=self)
            | Q(post_agenda_item_templates__counselor_meeting_template__roadmap=self)
        )


class CounselorNote(SNModel):
    """There are two types of counselor notes:
    1. A note - in a specific category - that a counselor leaves on one of their meetings. (meeting note)
                            The category is important because a counselor can add multiple notes for the same meeting if those notes
                            are of different category (i.e. activities, academics, etc)
    2. A note - not associated with a meeting - that a counselor can associate with a date. (date note)
            Just like meeting notes, a date note can have multiple notes if those notes are of different category.

    Only meeting notes can be made visible to student and/or parent (i.e. finalized)
    """

    CATEGORIES = (
        (counselor_note_category.NOTE_CATEGORY_ACADEMICS, "Academics"),
        (counselor_note_category.NOTE_CATEGORY_ACTIVITIES, "Activities"),
        (counselor_note_category.NOTE_CATEGORY_COLLEGES, "Colleges"),
        (counselor_note_category.NOTE_CATEGORY_MAJORS, "Majors"),
        (counselor_note_category.NOTE_CATEGORY_OTHER, "Other"),
        (counselor_note_category.NOTE_CATEGORY_APPLICATION_WORK, "Application Work"),
        (counselor_note_category.NOTE_CATEGORY_PRIVATE, "Private (Counselor)"),
        (counselor_note_category.NOTE_CATEGORY_TESTING, "Testing"),
    )

    counselor_meeting = models.ForeignKey(
        "sncounseling.CounselorMeeting", related_name="counselor_notes", null=True, blank=True, on_delete=models.CASCADE
    )
    category = models.CharField(max_length=255, default=counselor_note_category.NOTE_CATEGORY_OTHER, choices=CATEGORIES)
    note = models.TextField(blank=True)
    # Associated date for non-meeting notes
    note_date = models.DateField(null=True, blank=True)
    # Associated student for non-meeting notes
    note_student = models.ForeignKey(
        "snusers.Student", related_name="counselor_notes", null=True, blank=True, on_delete=models.CASCADE
    )
    # note_title is a custom title on non-meeting notes based on counselor input (only non-blank for non-meeting notes)
    note_title = models.TextField(blank=True)

    @property
    def title(self):
        if self.counselor_meeting:
            return f"{self.category.capitalize()} notes for {self.counselor_meeting}"
        if self.note_date and self.note_student:
            return f"{self.category.capitalize()} notes for {self.note_student} on {self.note_date}"

    def __str__(self):
        return self.title


class StudentActivity(SNModel):
    """An activity for a specific student (note that awards ARE activities)"""

    CATEGORIES = [
        (student_activity_category.SUMMER, "Summer Activity"),
        (student_activity_category.WORK, "Work Experience"),
        (student_activity_category.AWARD, "Award"),
        (student_activity_category.OTHER, "Other"),
    ]
    RECOGNITION = [
        (student_activity_recognition_level.SCHOOL, student_activity_recognition_level.SCHOOL),
        (student_activity_recognition_level.STATE_REGIONAL, student_activity_recognition_level.STATE_REGIONAL),
        (student_activity_recognition_level.NATIONAL, student_activity_recognition_level.NATIONAL),
        (student_activity_recognition_level.INTERNATIONAL, student_activity_recognition_level.INTERNATIONAL),
    ]
    category = models.CharField(max_length=255, choices=CATEGORIES, default=student_activity_category.OTHER)
    common_app_category = models.CharField(max_length=255, blank=True)
    position = models.CharField(max_length=255, blank=True)
    intend_to_participate_college = models.BooleanField(default=False)
    during_school_year = models.BooleanField(default=False)
    during_school_break = models.BooleanField(default=False)
    all_year = models.BooleanField(default=False)

    student = models.ForeignKey("snusers.Student", related_name="activity", on_delete=models.CASCADE)
    years_active = ArrayField(models.IntegerField(), blank=True, default=list)
    hours_per_week = models.DecimalField(max_digits=5, decimal_places=1, default=0.0)
    weeks_per_year = models.DecimalField(max_digits=5, decimal_places=1, default=0.0)
    awards = models.TextField(null=True, blank=True)
    name = models.CharField(max_length=255, null=False, blank=False)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField()
    # Award specific fields
    post_graduate = models.BooleanField(default=False)
    recognition = models.CharField(choices=RECOGNITION, blank=True, max_length=255)


class CounselingPackage(SNModel):
    """ A package of counseling hours that a student can purchase.
    """

    SEMESTER_SPRING = "spring"
    SEMESTER_FALL = "fall"

    counseling_student_type = models.CharField(
        max_length=255, blank=True, help_text="All students of this type will automatically get this package applied"
    )
    number_of_hours = models.DecimalField(
        decimal_places=2, max_digits=6, help_text="Number of hours included in package"
    )
    package_name = models.CharField(max_length=255, blank=True, help_text="Customer readable name of package")

    # For some packages, the package that we apply depends on the student's start semester and year.
    # If these fields are set, then the CounselingPackage should only be applied to students starting
    # in this grade and semester
    grade = models.IntegerField(
        null=True, help_text="Grade in which student starts working with SN to get this package"
    )
    semester = models.IntegerField(
        null=True,
        help_text="Semester in which student starts working with SN to get this package. 1 = Fall. 2 = Spring/Summer",
    )

    def __str__(self) -> str:
        return self.package_name


class CounselingHoursGrant(SNModel):
    """ Counseling hours granted to a CAP student
    """

    student = models.ForeignKey(
        "snusers.Student",
        related_name="counseling_hours_grants",
        on_delete=models.PROTECT,
        help_text="Student hours grant is for",
    )
    counseling_package = models.ForeignKey(
        "sncounseling.CounselingPackage",
        related_name="counseling_hours_grants",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="(Optional) Counseling Package that was purchased/added resulting in this hours grant",
    )
    number_of_hours = models.DecimalField(
        decimal_places=2,
        max_digits=6,
        help_text="Number of hours granted to student. Must be positive.",
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    created_by = models.ForeignKey(
        "auth.user",
        related_name="created_counseling_hours_grants",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="The user who created the grant (or purchased package)",
    )

    # Admin can mark hours as paid
    marked_paid = models.BooleanField(
        default=False, help_text="If hours were paid for via Magento OR marked paid for by admin"
    )
    # If this time entry represents hours purchased by student/parent, then this is how much was
    # paid. Used for reporting
    amount_paid = models.DecimalField(
        default=0.0,
        decimal_places=2,
        max_digits=8,
        null=True,
        blank=True,
        help_text="The amount that was paid for the hours",
    )

    note = models.TextField(
        blank=True,
        help_text="Optional note on what these hours are for. Can be set by admin if they are granting hours",
    )

    magento_id = models.TextField(
        blank=True, help_text="ID of Magento Order from which these hours were created (if applicable)"
    )

    include_in_hours_bank = models.BooleanField(
        help_text="Whether or not we should include this hours grant when summing up how many hours the student has total/remaining",
        default=True,
    )

    def __str__(self) -> str:
        return f"{self.number_of_hours} hours for {self.student}"


class CounselorTimeEntry(SNModel):
    """A single line item of counselor meeting time tracking. Counselors and
    Admins can create new time entries.  Entry can optionally be associated with
    a student.
    Negative time entries represent adding time to a student.
    """

    CATEGORIES = (
        (counselor_time_entry_category.TIME_CATEGORY_MEETING, "Meeting"),
        (counselor_time_entry_category.TIME_CATEGORY_ACT, "ACT"),
        (counselor_time_entry_category.TIME_CATEGORY_SAT, "SAT"),
        (counselor_time_entry_category.TIME_CATEGORY_COLLEGE, "College"),
        (counselor_time_entry_category.TIME_CATEGORY_OTHER, "Other"),
        (counselor_time_entry_category.TIME_CATEGORY_MEETING_GENERAL, "Meeting - General"),
        (counselor_time_entry_category.TIME_CATEGORY_MEETING_COLLEGE_RESEARCH, "Meeting - College Research"),
        (counselor_time_entry_category.TIME_CATEGORY_MEETING_ACTIVITY_REVIEW, "Meeting - Action Review"),
        (counselor_time_entry_category.TIME_CATEGORY_MEETING_COURSE_SELECTION, "Meeting - Course Selection"),
        (counselor_time_entry_category.TIME_CATEGORY_MEETING_ESSAY_BRAINSTORMING, "Meeting - Essay Brainstorming"),
        (counselor_time_entry_category.TIME_CATEGORY_OTHER_GENERAL, "Other - General"),
        (
            counselor_time_entry_category.TIME_CATEGORY_OTHER_ESSAY_REVIEW_AND_EDITING,
            "Other - Essay Review and Editing",
        ),
        (counselor_time_entry_category.TIME_CATEGORY_OTHER_PHONE_CALL, "Other - Phone Call"),
        (counselor_time_entry_category.TIME_CATEGORY_OTHER_FOLLOW_UP_EMAIL_NOTES, "Other - Follow Up Email or Notes"),
        (counselor_time_entry_category.TIME_CATEGORY_OTHER_COLLEGE_RESEARCH_PREP, "Other - College Research Prep"),
        (counselor_time_entry_category.TIME_CATEGORY_OTHER_ACTIVITY_REVIEW_PREP, "Other - Activity Review Prep"),
        (counselor_time_entry_category.TIME_CATEGORY_OTHER_GENERAL_MEETING_PREP, "Other - General Meeting Prep"),
        (counselor_time_entry_category.TIME_CATEGORY_OTHER_COURSE_SELECTION_PREP, "Other - Course Selection Prep"),
        (counselor_time_entry_category.ADMIN_CATEGORIES[0], "Admin - Training"),
        (counselor_time_entry_category.ADMIN_CATEGORIES[1], "Admin - Freshmen Forum"),
        (counselor_time_entry_category.ADMIN_CATEGORIES[2], "Admin - The Gut Check"),
        (counselor_time_entry_category.ADMIN_CATEGORIES[3], "Admin - Office Hours"),
        (counselor_time_entry_category.ADMIN_CATEGORIES[4], "Admin - Counseling Calls"),
        (counselor_time_entry_category.ADMIN_CATEGORIES[5], "Admin - Meeting with Manager"),
        (counselor_time_entry_category.ADMIN_CATEGORIES[6], "Admin - Miscellaneous Admin Tasks",),
    )
    date = models.DateTimeField(null=True)

    # Note that negative hours are used to indicate hours ADDED to student's account (this is mostly used)
    # for Paygo students
    hours = models.DecimalField(default=0.0, decimal_places=2, max_digits=5)
    # Admin can mark hours as paid
    marked_paid = models.BooleanField(default=False)
    # If this time entry represents hours purchased by student/parent, then this is how much was
    # paid. Used for reporting
    amount_paid = models.DecimalField(default=0.0, decimal_places=2, max_digits=8, null=True, blank=True)

    student = ForeignKey(
        "snusers.Student", null=True, blank=True, on_delete=models.SET_NULL, related_name="counseling_time_entries"
    )
    category = models.CharField(
        max_length=255, default=counselor_time_entry_category.TIME_CATEGORY_MEETING_GENERAL, choices=CATEGORIES
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "auth.user", related_name="counselor_time_entry", null=True, on_delete=models.SET_NULL
    )
    counselor = models.ForeignKey(
        "snusers.counselor", null=True, on_delete=models.SET_NULL, related_name="time_entries"
    )

    # If this time entry is for a specific meeting
    counselor_meeting = models.OneToOneField(
        "sncounseling.CounselorMeeting",
        null=True,
        blank=True,
        related_name="counselor_time_entry",
        on_delete=models.CASCADE,
    )

    pay_rate = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    counselor_time_card = models.ForeignKey(
        "sncounseling.CounselorTimeCard",
        related_name="counselor_time_entries",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    include_in_hours_bank = models.BooleanField(
        help_text="Whether or not we should include this time when summing up how many hours the student has total/remaining",
        default=True,
    )

    def __str__(self) -> str:
        return f"{self.hours} hours for {self.student}"


class CounselorTimeCard(TimeCardBase):
    """Time card with CounselorTimeEntries"""

    counselor = models.ForeignKey("snusers.Counselor", on_delete=models.CASCADE)
    counselor_approval_time = models.DateTimeField(null=True, blank=True)
    counselor_note = models.TextField(blank=True)

    # Incoming FK:
    counselor_time_entries: "django.db.models.manager.RelatedManager['CounselorTimeEntry']" = cast(
        'django.db.models.manager.RelatedManager["CounselorTimeEntry"]', None
    )

    @property
    def total_hours(self):
        return self.counselor_time_entries.all().aggregate(s=Sum("hours"))["s"] or 0

    def __str__(self):
        return f"Time card for {self.counselor} created {self.created.strftime('%m/%d/%Y')}"


class CounselorEventType(SNModel):
    """An EventType is specified by a Counselor"""

    created_by = models.ForeignKey(
        "snusers.counselor", related_name="event_types", null=True, blank=True, on_delete=models.SET_NULL,
    )
    # Duration in minutes
    duration = models.IntegerField(null=True)
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self) -> str:
        return f"{self.created_by}'s {self.title}"


class CounselorAvailability(BaseAvailability):
    """A block of time that a counselor is available for meetings (including via EventType)
    See BaseAvailability doscstring for more
    """

    counselor = models.ForeignKey("snusers.Counselor", related_name="availabilities", on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.counselor.name} from {self.start} to {self.end}"


class RecurringCounselorAvailability(BaseRecurringAvailability):
    """Weekly recurring availability for a counselor. See BaseRecurringAvailability docstring for more"""

    counselor = models.OneToOneField(
        "snusers.Counselor", related_name="recurring_availability", on_delete=models.CASCADE
    )
