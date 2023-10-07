from decimal import Decimal

from django.conf import settings
from django.db.models import JSONField
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.shortcuts import reverse
from nose.tools import nottest

from cwcommon.model_base import CWModel

# Though it's not used, we need to keep get_default_availability because it is referenced in migrations
# as being in this module (it used to be)
from cwcommon.models import BaseAvailability, BaseRecurringAvailability, TimeCardBase, get_default_availability
from snusers.models import AddressFields


class Diagnostic(CWModel):
    """ A test given to students as they start tutoring program. Can be in-person or remote.
        Instances of remote Diagnostic are assigned to students as Task.
        Instances of in-person Diagnostic are assigned to students as Tutoring Session.
    """

    DIAGNOSTIC_TYPE_ACT = "act"
    DIAGNOSTIC_TYPE_SAT = "sat"
    DIAGNOSTIC_TYPE_MATH = "math"
    DIAGNOSTIC_TYPE_SCIENCE = "science"
    DIAGNOSTIC_TYPE_WRITING = "writing"
    DIAGNOSTIC_TYPE_OTHER = "other"

    DIAGNOSTIC_TYPES = (
        (DIAGNOSTIC_TYPE_ACT, "ACT"),
        (DIAGNOSTIC_TYPE_ACT, "Other"),
        (DIAGNOSTIC_TYPE_SAT, "SAT"),
        (DIAGNOSTIC_TYPE_MATH, "Math"),
        (DIAGNOSTIC_TYPE_SCIENCE, "Science"),
        (DIAGNOSTIC_TYPE_WRITING, "Writing"),
    )
    diagnostic_type = models.CharField(max_length=100, choices=DIAGNOSTIC_TYPES)
    created_by = models.ForeignKey(
        "auth.user", related_name="created_diagnostics", null=True, blank=True, on_delete=models.SET_NULL,
    )
    updated_by = models.ForeignKey("auth.user", related_name="+", null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)  # Can be Rich Text

    resources = models.ManyToManyField("cwresources.Resource", related_name="diagnostics", blank=True)

    # Will potentially be used later
    form_specification = JSONField(encoder=DjangoJSONEncoder, default=dict, blank=True)

    # Whether or not students can assign this diagnostic to themselves
    can_self_assign = models.BooleanField(default=False)

    # We archive old diagnostics instead of deleting
    archived = models.BooleanField(default=False)

    """ Incoming FK """
    # tasks > many Task

    def __str__(self):
        return self.title


class DiagnosticResult(CWModel):
    """ Submission of a Diagnostic - remote or in person - for a student
        Created when Task w/related Diagnostic is submitted
    """

    STATE_PENDING_SCORE = "ps"
    STATE_PENDING_REC = "pr"
    STATE_PENDING_RETURN = "pe"
    STATE_VISIBLE_TO_STUDENT = "v"

    STATES = (
        (STATE_PENDING_SCORE, "Pending Score"),
        (STATE_PENDING_REC, "Pending Recommendation"),
        (STATE_PENDING_RETURN, "Pending Return to Student"),
        (STATE_VISIBLE_TO_STUDENT, "Visible to Student"),
    )

    state = models.CharField(max_length=2, default=STATE_PENDING_SCORE, choices=STATES)

    submission_note = models.TextField(blank=True)
    submitted_by = models.ForeignKey(
        "auth.user", related_name="submitted_tasks", blank=True, null=True, on_delete=models.SET_NULL,
    )

    student = models.ForeignKey("snusers.Student", related_name="diagnostic_results", on_delete=models.CASCADE)
    task = models.OneToOneField(
        "cwtasks.Task", related_name="diagnostic_result", blank=True, null=True, on_delete=models.SET_NULL,
    )

    diagnostic = models.ForeignKey(
        "cwtutoring.Diagnostic", related_name="diagnostic_results", on_delete=models.CASCADE,
    )

    # Diagnostics are scored, have a recommendation written, and are then (optionally) approved by counselor
    score = models.FloatField(blank=True, null=True)
    recommendation = models.OneToOneField(
        "cwcommon.FileUpload",
        related_name="diagnostic_result_recommendation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    feedback = models.TextField(blank=True)  # Rich Text

    # Never visible to student
    admin_note = models.TextField(blank=True)

    # Person who wrote recommendation
    feedback_provided = models.DateTimeField(blank=True, null=True)
    feedback_provided_by = models.ForeignKey(
        "auth.user", related_name="task_feedback", blank=True, null=True, on_delete=models.SET_NULL,
    )

    # Person who is currently assigned (responsible for moving DR from current state to next state)
    assigned_to = models.ForeignKey("auth.user", related_name="+", null=True, blank=True, on_delete=models.SET_NULL)

    """ Incoming FK """
    # file_uploads > Many FileUpload

    def __str__(self):
        return f"{self.diagnostic.title} diagnostic result for {self.student.name}"


class DiagnosticGroupTutoringSessionRegistration(CWModel):
    """ An instance of a family registering for a Diagnostic (GroupTutoringSession). Families
        register via a landing page. Student and parent UMS accounts are created if they
        do not already exist
    """

    REGISTRATION_TYPE_ACT = "act"
    REGISTRATION_TYPE_SAT = "sat"
    REGISTRATION_TYPE_BOTH = "both"
    REGISTRATION_TYPE_CHOICES = (
        (REGISTRATION_TYPE_ACT, "ACT"),
        (REGISTRATION_TYPE_SAT, "SAT"),
        (REGISTRATION_TYPE_BOTH, "Both"),
    )

    registration_type = models.CharField(max_length=4, choices=REGISTRATION_TYPE_CHOICES)
    student = models.ForeignKey(
        "snusers.Student", related_name="diagnostic_gts_registrations", on_delete=models.CASCADE,
    )

    # The diagnostics student registered for
    group_tutoring_sessions = models.ManyToManyField(
        "cwtutoring.GroupTutoringSession", related_name="diagnostic_gts_registrations"
    )
    # The self-assigned diagnostics student registered for
    self_assigned_diagnostics = models.ManyToManyField(
        "cwtutoring.Diagnostic", related_name="diagnostic_gts_registrations"
    )

    # JSON data from the form used to register
    registration_data = JSONField(encoder=DjangoJSONEncoder, default=dict)


@nottest
class TestResult(CWModel):
    """ Instance of student taking (or failing to take) a standardized test """

    title = models.CharField(max_length=255, blank=True)
    test_date = models.DateTimeField(null=True, blank=True)
    test_type = models.CharField(max_length=255)
    student = models.ForeignKey("snusers.Student", related_name="test_results", on_delete=models.CASCADE)
    test_missed = models.BooleanField(default=False)
    # When test was marked complete
    test_complete = models.DateTimeField(null=True, blank=True)
    score = models.FloatField(blank=True, null=True)

    # Subscores differ by test type. The frontend is responsible for displaying the correct subscore options
    # for each test type
    reading = models.FloatField(blank=True, null=True)
    reading_sub = models.FloatField(blank=True, null=True)
    writing = models.FloatField(blank=True, null=True)
    writing_sub = models.FloatField(blank=True, null=True)
    math = models.FloatField(blank=True, null=True)
    math_sub = models.FloatField(blank=True, null=True)
    english = models.FloatField(blank=True, null=True)
    science = models.FloatField(blank=True, null=True)
    speaking = models.FloatField(blank=True, null=True)
    listening = models.FloatField(blank=True, null=True)

    def __str__(self):
        return f"{self.student.name} - {self.test_type} ({self.test_date.strftime('%m/%d/%Y') if self.test_date else 'no date'})"


class Location(AddressFields):
    """ A physical location where tutoring OR COUNSELING is offered
        TODO: This model should probably be moved into cwcommon for logical consistency since change to
            offer counseling in-person
    """

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Remote location
    is_remote = models.BooleanField(default=False)
    is_default_location = models.BooleanField(default=False)
    default_zoom_url = models.TextField(blank=True)

    # Whether or not academic tutoring and admissions services are offered,
    # respectively
    offers_tutoring = models.BooleanField(default=True)
    offers_admissions = models.BooleanField(default=False)

    magento_id = models.CharField(max_length=255, blank=True)

    """ Incoming FK """
    # tutoring_services > many TutoringService services offered at location

    def __str__(self):
        return self.name

    @property
    def timezone(self):
        return self.set_timezone if self.set_timezone else settings.DEFAULT_TIMEZONE

    """ Incoming FK """
    # tutoring_packages > many TutoringPackage


class TutorAvailability(BaseAvailability):
    """ A block of time that a tutor is available to offer one-on-one tutoring sessions.
        See BaseAvailability doscstring for more
    """

    tutor = models.ForeignKey("snusers.Tutor", related_name="availabilities", on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.tutor.name} from {self.start} to {self.end}"


class RecurringTutorAvailability(BaseRecurringAvailability):
    """ Weekly recurring availability for a tutor. See BaseRecurringAvailability docstring for more """

    tutor = models.OneToOneField("snusers.Tutor", related_name="recurring_availability", on_delete=models.CASCADE)


def get_default_location():
    """ Default location for tutoring sessions is the remote location """
    return ''
    # return Location.objects.filter(is_remote=True).first().pk


class GroupTutoringSession(CWModel):
    primary_tutor = models.ForeignKey(
        "snusers.Tutor",
        related_name="primary_group_tutoring_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    # We can change how much tutors are paid how much much tutors are charged (in minutes) for this session
    # Note that duration_minutes property uses set_charge_student_duration if set, otherwise the calculated
    # session duration (start - end)
    set_charge_student_duration = models.IntegerField(null=True, blank=True)

    # Used to determine tutor pay. If not set, then we use calculated duration (start-end)
    set_pay_tutor_duration = models.IntegerField(null=True, blank=True)

    support_tutors = models.ManyToManyField("snusers.Tutor", related_name="support_group_tutoring_sessions", blank=True)
    location = models.ForeignKey(
        "cwtutoring.Location",
        related_name="group_tutoring_sessions",
        on_delete=models.PROTECT,
        default=get_default_location,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # When this session will take place
    start = models.DateTimeField(null=True, blank=True)
    end = models.DateTimeField(null=True, blank=True)

    # If cancelled, session will no longer happen
    cancelled = models.BooleanField(default=False)

    # Note only visible to CW admin, counselors, tutors
    staff_note = models.TextField(blank=True)

    # Number of students who can join session
    capacity = models.SmallIntegerField(default=100)

    resources = models.ManyToManyField("cwresources.Resource", related_name="group_tutoring_sessions", blank=True)
    # If this session is administration of a diagnostic, this is the diag being administered
    diagnostic = models.ForeignKey(
        "cwtutoring.Diagnostic",
        related_name="group_tutoring_sessions",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )

    # Whether or not session is in catalog that student can choose from
    include_in_catalog = models.BooleanField(default=True)

    # Notes do not need to be provided
    notes_skipped = models.BooleanField(default=False)

    # Zoom URL, for remote group sessions
    #
    zoom_url = models.CharField(max_length=255, blank=True)

    # Makes it easier to track notifications
    last_reminder_sent = models.DateTimeField(null=True, blank=True)

    # for Outlook authorization
    outlook_event_id = models.TextField(blank=True, null=True)

    """ Incoming Foreign Keys """
    # student_tutoring_sessions > many cwtutoring.StudentTutoringSession
    # tutoring_packages > many TutoringPackage
    # tutoring_session_notes > ONE TutoringSessionNotes
    # time_card_line_items > many TutorTimeCardLineItem
    # courses > many Course

    def __str__(self):
        if not self.start:
            return self.title
        return f"{self.title} at {self.start.strftime('%m/%d/%Y, %H:%M')}"

    @property
    def is_remote(self):
        # Session is remote if it has Zoom URL, even if NOT at a remote location
        return bool(self.zoom_url)

    @property
    def duration(self):
        # Duration in of session (end - start) in minutes. See properties below for duration that students
        # should be charged for or tutors should be paid for
        if self.start and self.end:
            return round((self.end - self.start).total_seconds() / 60.0)
        return 0

    @property
    def charge_student_duration(self):
        """ How long to charge student for """
        return self.set_charge_student_duration if self.set_charge_student_duration is not None else self.duration

    @property
    def pay_tutor_duration(self):
        return self.set_pay_tutor_duration if self.set_pay_tutor_duration is not None else self.duration


class Course(CWModel):
    """ A course is a group of GroupTutoringSession objects. Courses can be associated with packages,
        so that families can choose to enroll in a course, which can involve purchasing a package
    """

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    # Resources made available to students who register for this course
    resources = models.ManyToManyField("cwresources.Resource", related_name="courses", blank=True)
    time_description = models.TextField(blank=True)
    # Whether or not course is accepting new participants. Note that courses won't display on landing page after their
    # first group session has started, regardless of settings below
    available = models.BooleanField(default=True)
    # Whether or not course is available on landing page for self-enrollment
    display_on_landing_page = models.BooleanField(default=False)

    # Students enrolled in the course
    students = models.ManyToManyField("snusers.Student", related_name="courses", blank=True)

    # If package must be purchased to enroll in course
    package = models.ForeignKey(
        "cwtutoring.TutoringPackage", related_name="courses", null=True, blank=True, on_delete=models.SET_NULL,
    )

    # Note that sessions still have their own primary and support tutors, which technically can be different
    primary_tutor = models.ForeignKey(
        "snusers.Tutor", related_name="courses", blank=True, null=True, on_delete=models.SET_NULL,
    )

    # Non-null location. Obviously can be remote Location
    location = models.ForeignKey(
        "cwtutoring.location", related_name="courses", on_delete=models.PROTECT, default=get_default_location,
    )

    group_tutoring_sessions = models.ManyToManyField(
        "cwtutoring.GroupTutoringSession", related_name="courses", blank=True
    )

    category = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.verbose_name

    @property
    def verbose_name(self):
        """ Name that includes first session date """
        if not self.group_tutoring_sessions.exists():
            return self.name
        return f"{self.name} starting on {self.group_tutoring_sessions.order_by('start').first().start.strftime('%m/%d/%Y')} with {self.group_tutoring_sessions.first().primary_tutor.name}"


class StudentTutoringSession(CWModel):
    """
        A student has signed up for an individual or group tutoring session.
        This object is associated with either a GroupTutoringSession or a TutorAvailability
    """

    SESSION_TYPE_TEST_PREP = "t"
    SESSION_TYPE_CURRICULUM = "c"
    SESSION_TYPES = (
        (SESSION_TYPE_TEST_PREP, "Test Prep"),
        (SESSION_TYPE_CURRICULUM, "Curriculum"),
    )
    session_type = models.CharField(choices=SESSION_TYPES, max_length=1)
    # Service provided in this tutoring session. If set, should have same session_type as self
    # Primarily used for individual tutoring sessions
    tutoring_service = models.ForeignKey(
        "cwtutoring.TutoringService",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="student_tutoring_sessions",
    )

    # When session takes place (copied from group session)
    start = models.DateTimeField(null=True, blank=True)
    end = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.SmallIntegerField(default=60)

    # Tentative meetings are just used by tutors for planning purposes and DO NOT consume student hours (but
    # do block off time on the calendar)
    is_tentative = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        "auth.user", related_name="created_student_tutoring_sessions", blank=True, null=True, on_delete=models.SET_NULL,
    )
    student = models.ForeignKey(
        "snusers.Student", related_name="tutoring_sessions", null=True, blank=True, on_delete=models.SET_NULL,
    )
    # One of the next two fields should be set. We can figure out the tutor(s) via these fields
    group_tutoring_session = models.ForeignKey(
        "cwtutoring.GroupTutoringSession",
        related_name="student_tutoring_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # If is individual session ONLY
    individual_session_tutor = models.ForeignKey(
        "snusers.Tutor", related_name="student_tutoring_sessions", null=True, blank=True, on_delete=models.SET_NULL,
    )

    # Note added by student/family when booking session
    note = models.TextField(blank=True)

    # Notes provided for this session. The same notes object may be associated with multiple StudentTutoringSessions
    # (for example a single set of notes for all students in a group session)
    tutoring_session_notes = models.ForeignKey(
        "cwtutoring.TutoringSessionNotes",
        related_name="student_tutoring_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    # Notes do not need to be provided
    notes_skipped = models.BooleanField(default=False)
    # Resources for this session. Note that resources for GroupTutoringSessions are available on that model
    # So we kinda hide this field (set_resources), and return all resources in resources property on this model
    set_resources = models.ManyToManyField("cwresources.Resource", related_name="student_tutoring_sessions")

    # Location where session is to take place. If None, then session is remote.
    # If self.group_tutoring_session is set, then we use it's location instead of self.location
    location = models.ForeignKey(
        "cwtutoring.Location",
        related_name="student_tutoring_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # Makes it easier to track notifications
    last_reminder_sent = models.DateTimeField(null=True, blank=True)

    # If paygo purchase was made to pay for this session
    paygo_transaction_id = models.CharField(max_length=255, blank=True)

    # Buckle up.
    # There are three states for sessions that did not actually take place
    # 1) Early cancel. Session was cancelled < 24 hours beforehand. Students, parents, tutors and admins can early
    #   cancel. A session is early cancelled, if set_cancelled is true and late_cancel is false
    #   Hours are NOT deducted for student for late cancel or cancel
    set_cancelled = models.BooleanField(default=False)

    # 2) Late cancel. Session is late cancelled if cancelled < 24 hours before session (including after session)
    #   Only admins can mark a session as late cancel, though tutors can cancel < 24 hours beforehand.
    #   Session late cancel if late_cancel is true (independent of set_cancelled)
    #   Tutors are paid for late cancel sessions
    #   Families can be charged for late cancel sessions
    #   Hours are NOT deducted for student for late cancel or cancel
    late_cancel = models.BooleanField(default=False)
    late_cancel_charge_transaction_id = models.CharField(max_length=255, blank=True)

    # Session is missed if student just didn't show up. Hours are deducted. Tutor is paid. Family is not charged
    #   (on top of hours being removed)
    missed = models.BooleanField(default=False)

    # for Outlook authorization
    outlook_event_id = models.TextField(blank=True, null=True)

    """ Incoming Foreign Keys """
    # tutoring_session_notes
    # time_card_line_items > many TutorTimeCardLineItem

    def __str__(self):
        if not self.start:
            return ""
        if self.group_tutoring_session:
            return f"{self.student.name} attending group {self.group_tutoring_session.title} on {self.start.strftime('%b %d')}"
        elif self.individual_session_tutor and self.student:
            return (
                f"{self.student.name} with tutor {self.individual_session_tutor.name} on {self.start.strftime('%b %d')}"
            )
        return ""

    @property
    def title_for_student(self):
        """ Student-readable title for this session. Used for event title on calendar
        """
        if self.group_tutoring_session:
            return f"{self.group_tutoring_session.title} group tutoring session"
        else:
            return f"Individual tutoring session with {self.individual_session_tutor.name}"

    @property
    def title_for_tutor(self):
        """ Student-readable title for this session. Used for event title on calendar
        """
        if self.group_tutoring_session:
            return f"{self.group_tutoring_session.title} group tutoring session"
        else:
            return f"Individual tutoring session with {self.student.name}"

    @property
    def resources(self):
        """ All of our set_resources, pluse resources from self.group_tutoring_session if there is one """
        return (
            (self.set_resources.all() | self.group_tutoring_session.resources.all())
            if self.group_tutoring_session
            else self.set_resources.all().distinct()
        )

    @property
    def cancelled(self):
        """ Whether this session or associated group session has been cancelled """
        return self.set_cancelled or (self.group_tutoring_session and self.group_tutoring_session.cancelled)

    @property
    def cost_duration(self):
        """ Duration (individual) tutor gets paid for for this session. 0 if missed """
        if not (self.cancelled or self.missed or self.is_tentative):
            return self.duration_minutes
        return 0

    @property
    def notes_url(self):
        """ Note that this will return a URL even if notes don't exist!! """
        return reverse("student_tutoring_sessions-pdf", kwargs={"pk": self.pk})

    @property
    def zoom_url(self):
        if self.individual_session_tutor:
            # Session is remote if student doesn't have a location
            if (not self.location) or self.location.is_remote:
                return self.individual_session_tutor.zoom_url
        elif self.group_tutoring_session:
            return self.group_tutoring_session.zoom_url
        return ""

    @property
    def is_remote(self):
        # Session is remote if it has Zoom URL, even if NOT at a remote location
        return bool(self.zoom_url)


class TutoringService(CWModel):
    """ A tutoring service is a subject that a tutor provides assistance in.
        Every StudentTutoringSession has at most 1 service.
        Initially, services will only be annotated on individual tutoring sessions
    """

    LEVEL_AP = "a"
    LEVEL_HONORS = "h"
    LEVELS = ((LEVEL_AP, "AP"), (LEVEL_HONORS, "Honors"))

    name = models.CharField(max_length=255)

    # If set, then these are the ONLY tutors or locations that offer the service
    # If empty, then assume all tutors/locations
    tutors = models.ManyToManyField("snusers.Tutor", related_name="tutoring_services", blank=True)

    # TODO: Not currently used
    locations = models.ManyToManyField("cwtutoring.Location", related_name="tutoring_services", blank=True)

    # Services are EITHER curriculum or test prep
    session_type = models.CharField(choices=StudentTutoringSession.SESSION_TYPES, max_length=1)

    applies_to_group_sessions = models.BooleanField(default=False)
    applies_to_individual_sessions = models.BooleanField(default=False)

    # Each level of a subject is broken out as a separate service here
    # Note that level can be excluded
    level = models.CharField(choices=LEVELS, blank=True, max_length=2)

    """ Incoming FK """
    # student_tutoring_sessions > many StudentTutoringSession where this service is used

    @property
    def display(self):
        """ String to display this service that includes name and level """
        level_display = ""
        if self.level == TutoringService.LEVEL_AP:
            level_display = "AP"
        elif self.level == TutoringService.LEVEL_HONORS:
            level_display = "Honors"
        if self.level:
            return f"{self.name} - {level_display}"
        return self.name

    def __str__(self):
        return self.display


class TutoringSessionNotes(CWModel):
    # Notes provided to one or more students as a result of a tutoring session
    author = models.ForeignKey(
        "snusers.Tutor", related_name="tutoring_session_notes", null=True, blank=True, on_delete=models.SET_NULL,
    )
    notes = models.TextField(blank=True)  # HTML!
    resources = models.ManyToManyField("cwresources.Resource", related_name="tutoring_session_notes")
    group_tutoring_session = models.OneToOneField(
        "cwtutoring.GroupTutoringSession",
        related_name="tutoring_session_notes",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    notes_file = models.FileField(blank=True, upload_to="tutoring_session_notes")
    visible_to_student = models.BooleanField(default=True)
    visible_to_parent = models.BooleanField(default=True)

    """ Incoming Foreign Keys """
    # file_uploads > many cwcommon.FileUpload
    # student_tutoring_sessions > many cwtutoring.StudentTutoringSession

    def __str__(self):
        return f"Notes provided by {self.author.name}"


class TutoringPackage(CWModel):
    """ A package of individual and/or group hours that a student could purchase (or could be given to a student)
    """

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Location(s) where package is offered
    locations = models.ManyToManyField("cwtutoring.Location", related_name="tutoring_packages", blank=True)
    # Override to make package available at all locations (including future locations)
    all_locations = models.BooleanField(default=False)

    price = models.DecimalField(decimal_places=2, max_digits=6, default=0)
    # Can optionally set package to be available starting in the future, and expire on future date
    available = models.DateTimeField(null=True, blank=True)
    expires = models.DateTimeField(null=True, blank=True)

    # Package only available when working with this tutor
    restricted_tutor = models.ForeignKey(
        "snusers.Tutor", related_name="restricted_tutoring_packages", blank=True, null=True, on_delete=models.SET_NULL,
    )

    # Tutoring hours student gets when they purchase this package
    individual_test_prep_hours = models.DecimalField(decimal_places=2, max_digits=6, default=0)
    group_test_prep_hours = models.DecimalField(decimal_places=2, max_digits=6, default=0)
    individual_curriculum_hours = models.DecimalField(decimal_places=2, max_digits=6, default=0)

    # Student will automatically be enrolled in these sessions if they purchase this package
    group_tutoring_sessions = models.ManyToManyField(
        "cwtutoring.GroupTutoringSession", related_name="tutoring_packages", blank=True
    )

    # Resources made available to student upon purchasing this package
    resource_groups = models.ManyToManyField("cwresources.ResourceGroup", related_name="tutoring_packages", blank=True)

    # We don't delete packages (because that would delete purchase history); instead, we set to inactive
    active = models.BooleanField(default=True)

    # Used to align our items with what's in Magento
    sku = models.CharField(max_length=255, blank=True)
    product_id = models.CharField(max_length=255, blank=True)
    magento_purchase_link = models.CharField(max_length=255, blank=True)

    # Whether or not families can choose this package from modal in platform to purchase
    allow_self_enroll = models.BooleanField(default=True)

    # Whether or not this link can be used as paygo payment link for family.
    is_paygo_package = models.BooleanField(default=False)

    # Incoming Related Fields
    # course > single Course

    def __str__(self):
        location_name = "All Locations" if self.all_locations else ""
        if self.locations.count() == 1:
            location_name = self.locations.first().name

        return f"{self.title} at {location_name}"


class TutoringPackagePurchase(CWModel):
    """ This model represents an instance of a TutoringPackage being purchased (or given)
        to a student. Note that the same package can be purchased multiple times.
        Also note that the price PAID according to this model may differ from price
        of TutoringPackage, (i.e. if discounts were applied)
    """

    student = models.ForeignKey("snusers.Student", related_name="tutoring_package_purchases", on_delete=models.CASCADE,)
    tutoring_package = models.ForeignKey(
        "cwtutoring.TutoringPackage", related_name="tutoring_package_purchases", on_delete=models.CASCADE,
    )
    price_paid = models.DecimalField(decimal_places=2, max_digits=6, default=0)
    # May also be admin/ops person who awarded student a package
    purchased_by = models.ForeignKey(
        "auth.User", related_name="tutoring_package_purchases", null=True, blank=True, on_delete=models.SET_NULL,
    )

    # Note only visible to admins
    admin_note = models.TextField(blank=True)

    # If this purchase is later reversed. Reversed packages don't contribute to student's hours
    purchase_reversed = models.DateTimeField(null=True, blank=True)
    purchase_reversed_by = models.ForeignKey(
        "auth.User",
        related_name="reversed_tutoring_package_purchases",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # These fields may be updated - pending integration with Magento
    payment_required = models.BooleanField(default=False)
    payment_link = models.CharField(max_length=255, blank=True)
    payment_completed = models.DateTimeField(null=True, blank=True)
    payment_confirmation = models.CharField(max_length=255, blank=True)  # Holds magento order_id

    # If purchase was created through magento
    magento_payload = JSONField(encoder=DjangoJSONEncoder, default=dict, blank=True)
    sku = models.CharField(max_length=255, blank=True)
    # Status code and response we passed back after magento webhhook
    magento_status_code = models.SmallIntegerField(null=True, blank=True)
    magento_response = models.TextField(blank=True)
    # If we used the Paygo API to purchase the package
    paygo_transaction_id = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.student.name}'s {self.tutoring_package.title} tutoring package"


class TutorTimeCard(TimeCardBase):
    """ A timecard (usually over the course of a week) with line-item entries for a tutor's
        total billable time for the week.
        Note that because they have slightly different functionality but mostly because they were implemented
        a year apart, there is a separate time card model for counselors (in cwcounseling): CounselorTimeCard
    """

    tutor = models.ForeignKey("snusers.Tutor", related_name="time_cards", on_delete=models.CASCADE, editable=False,)

    # When approval took place (for tutor and an admin)
    tutor_approval_time = models.DateTimeField(null=True, blank=True)

    # Note visible/editable to tutor
    tutor_note = models.TextField(blank=True)

    """ Incoming FK """
    # line_items > many TutorTimeCardLineItem

    @property
    def total_hours(self):
        """ Total hours from all line items on this time card """
        return Decimal(self.line_items.aggregate(s=models.Sum("hours"))["s"] or 0)


class TutorTimeCardLineItem(CWModel):
    """ The entries that comprise a timecard. Each entry has a decimal number of hours associated with it
        These line items can be associated with tutoring sessions (or not).
        Note that technically hours can be negative (if adjustments need to be made after a Tutor
        has been paid)
    """

    title = models.CharField(blank=True, max_length=255)
    # Used by the frontend to set hourly rate.
    category = models.CharField(blank=True, max_length=255)
    # FK just in case they want to break up payment across multiple weeks (or need to make a change
    # after payment is paid out)
    group_tutoring_session = models.ForeignKey(
        "cwtutoring.GroupTutoringSession",
        related_name="time_card_line_items",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    individual_tutoring_session = models.ForeignKey(
        "cwtutoring.StudentTutoringSession",
        related_name="time_card_line_items",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    time_card = models.ForeignKey("cwtutoring.TutorTimeCard", related_name="line_items", on_delete=models.CASCADE)
    # We just care about the date; indicates day on which this line item took place
    date = models.DateTimeField(null=True, blank=True)

    hours = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    # Will use tutor's hourly rate if nothing else is provided. Typically this is only set if the line item
    # is NOT for a session (as tutor's hourly rate is used for sessions)
    hourly_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # The person who added line item. Mostly useful if it's an misc line item (not associated with tutoring session)
    created_by = models.ForeignKey(
        "auth.user", related_name="created_time_card_line_items", null=True, blank=True, on_delete=models.SET_NULL,
    )

    def __str__(self):
        if self.group_tutoring_session:
            return f"Group session: {self.group_tutoring_session.title}"
        elif self.individual_tutoring_session:
            return f"Individual session with {self.individual_tutoring_session.student.name}"
        return f"Misc: {self.title}"
