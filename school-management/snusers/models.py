from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.urls import reverse
from django.utils import timezone

from sncommon.model_base import CWModel

""" Utility to get cwuser for Django user. If user has multiple cwuser accounts, we obviously only return one """


def get_cw_user(user):
    for user_model in [Administrator, Counselor, Tutor, Parent, Student]:
        cwuser = user_model.objects.filter(user=user).first()
        if cwuser:
            return cwuser
    return None


def get_default_location():
    """ Default location for users that have a single location is the remote location """
    # pylint: ignore=import-outside-toplevel
    from sntutoring.models import Location

    default = Location.objects.filter(is_default_location=True).first()
    if default:
        return default
    remote = Location.objects.filter(is_remote=True).first()
    if remote:
        return remote
    return Location.objects.first()


class AddressFields(CWModel):
    """ Abstract class with fields necessary to represent an address"""

    address = models.CharField(max_length=255, blank=True)
    address_line_two = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255, blank=True)
    zip_code = models.CharField(max_length=11, blank=True)
    state = models.CharField(max_length=2, blank=True)
    country = models.CharField(max_length=255, default="United States", blank=True)

    # A string identifying a timezone that can be read by pytz
    set_timezone = models.CharField(max_length=255, blank=True)

    class Meta:
        abstract = True

    @property
    def full_address(self):
        if self.address:
            return f"{self.address} {self.address_line_two} {self.city}, {self.state}  {self.zip_code}"
        return ""


class ZoomFields(models.Model):
    """ Abstract class that adds zoom related fields to a model """

    class ZoomTypes:
        ZOOM_TYPE_BASIC = 1
        ZOOM_TYPE_LICENSED = 2
        CHOICES = ((ZOOM_TYPE_BASIC, "Basic"), (ZOOM_TYPE_LICENSED, "Licensed"))

    zoom_pmi = models.CharField(max_length=255, blank=True)
    zoom_url = models.CharField(max_length=255, blank=True)
    zoom_phone = models.CharField(max_length=255, blank=True)
    zoom_user_id = models.CharField(max_length=255, blank=True)
    zoom_type = models.IntegerField(choices=ZoomTypes.CHOICES, default=ZoomTypes.ZOOM_TYPE_BASIC)

    class Meta:
        abstract = True


class CommonUser(AddressFields):
    """ Abstract class with fields common to all user types """

    user = models.OneToOneField("auth.user", related_name="%(class)s", on_delete=models.CASCADE, blank=True, null=True,)

    invitation_name = models.CharField(max_length=255, blank=True)
    invitation_email = models.CharField(max_length=255, blank=True)
    last_invited = models.DateTimeField(null=True, blank=True)
    accepted_invite = models.DateTimeField(null=True, blank=True)

    profile_picture = models.OneToOneField(
        "sncommon.FileUpload",
        # Since this is an abstract model, figure no related name is better than a super weird related name for
        # each inherited model
        related_name="+",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="FileUpload object that holds the profile picture for this user",
    )

    registration_timezone = models.CharField(max_length=255, blank=True)

    class Meta:
        abstract = True

    @property
    def is_active(self):
        return self.user.is_active

    @property
    def name(self):
        if self.user:
            return ("%s %s" % (self.user.first_name, self.user.last_name)).strip()
        return self.invitation_name

    @property
    def email(self):
        return self.user.email

    @property
    def timezone(self):
        """ Attempt to get timezone from set_timezone or self.location.
            Returns None if neither timezone is set
        """
        if self.set_timezone:
            return self.set_timezone
        if hasattr(self, "location") and self.location and not self.location.is_remote and self.location.timezone:
            return self.location.timezone
        if self.registration_timezone:
            return self.registration_timezone
        return settings.DEFAULT_TIMEZONE

    @property
    def admin_url(self):
        """ URL to open details for this user on the admin platform """
        return f"{settings.SITE_URL}{reverse('platform', kwargs={'platform_type': 'administrator'})}?{self.user_type}={str(self.slug)}"

    def __str__(self):
        return self.name


def default_grad_year():
    """ Returns current year """
    return timezone.now().year


class Student(CommonUser):
    """ A student on either academic or admissions platform """

    COUNSELING_STUDENT_BASIC = "basic"

    user_type = "student"
    # A student's current high school
    high_school = models.CharField(max_length=255, blank=True)
    # A list of previous attended high schools
    high_schools = ArrayField(models.CharField(max_length=255), blank=True, default=list)

    graduation_year = models.IntegerField(default=default_grad_year)

    accommodations = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)
    counselor_note = models.TextField(blank=True)
    activities_notes = models.TextField(blank=True)  # Rich text field

    # Student Profile FIelds that AREN't test scores (those are cwTutoring.TestResult)
    gpa = models.DecimalField(decimal_places=2, max_digits=4, null=True, blank=True)

    # Student has one counselor (but many tutors)
    counselor = models.ForeignKey(
        "snusers.Counselor", related_name="students", null=True, blank=True, on_delete=models.SET_NULL,
    )
    program_advisor = models.CharField(max_length=255, blank=True)
    parent = models.ForeignKey(
        "snusers.Parent", related_name="students", null=True, blank=True, on_delete=models.SET_NULL,
    )

    # Resources that have been made available to student
    visible_resources = models.ManyToManyField("snresources.Resource", related_name="visible_students", blank=True)
    visible_resource_groups = models.ManyToManyField(
        "snresources.ResourceGroup", related_name="visible_students", blank=True
    )

    location = models.ForeignKey(
        "sntutoring.Location", related_name="students", on_delete=models.PROTECT, default=get_default_location,
    )

    # Student has opted to enroll in this course but has not purchased required package yet
    pending_enrollment_course = models.ForeignKey(
        "sntutoring.Course",
        related_name="pending_enrollment_students",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    pronouns = models.TextField(blank=True)

    hubspot_id = models.CharField(max_length=255, blank=True)
    hubspot_company_id = models.CharField(max_length=255, blank=True)

    # Paygo students are students who can pay for sessions after they occur. They can book at most 1 session
    # (beyond their hours)
    is_paygo = models.BooleanField(default=False)
    # Used by our payment API to charge future purchases. Payment API can only be used if this is set
    last_paygo_purchase_id = models.CharField(max_length=255, blank=True)

    # Read-only field with summary of student's appointment history from Wellness - the old UMS
    # Populated by wellness_appointments_transform.py
    wellness_history = models.TextField(blank=True)

    # Empty string if student is not counseling student
    counseling_student_types_list = ArrayField(models.CharField(max_length=255, default=""), default=list, blank=True,)
    school_list_finalized = models.BooleanField(default=False)

    # Fields used to store files from Basecamp for tutors and ops
    basecamp_attachments = models.FileField(upload_to="basecamp_export/attachments/", blank=True)
    basecamp_documents = models.FileField(upload_to="basecamp_export/documents/", blank=True)

    # Note added by counselor on the student's schools page
    schools_page_note = models.TextField(blank=True)

    # PDF of notes from CPP
    cpp_notes = models.FileField(upload_to="cpp_export/notes/", blank=True)

    # Whether or not the student has access to the CAP platform
    has_access_to_cap = models.BooleanField(default=True)
    # Whether or not Prompt integration is active for this student
    is_prompt_active = models.BooleanField(default=False)

    applied_roadmaps = models.ManyToManyField("sncounseling.Roadmap", related_name="students", blank=True)

    # Counselor or Admin created tags on a student. Tags are use to filter which students see Announcements/Bulletins
    tags = ArrayField(models.TextField(default=""), blank=True, default=list)
    # A Counselor can toggle T/R/Likely visibility (previously target_reach_safety) for their student/parent
    hide_target_reach_safety = models.BooleanField(default=False)

    counselor_pay_rate = models.DecimalField(
        null=True,
        max_digits=5,
        decimal_places=2,
        help_text="Pay rate for counselor for time captured by CounselorTimeEntry objects for this student",
    )

    """ Incoming FK """
    # high_school_courses > many StudentHighSchoolCourse
    # courses > many Course

    @property
    def is_cas(self):
        return self.tutoring_sessions.exists() or self.tutoring_package_purchases.exists()

    @property
    def is_cap(self):
        return self.counselor or self.counseling_student_types_list


class StudentHighSchoolCourse(CWModel):
    """ A high school course that a student is taking (or took)
        A set of these comprises a student's high school coursework
        These are setup to match the Common App
    """

    student = models.ForeignKey("snusers.Student", related_name="high_school_courses", on_delete=models.CASCADE)
    course_level = models.CharField(max_length=255, blank=True)
    # The year representing the fall year. A value of 2020 indicates 2020-2021 school year
    school_year = models.IntegerField(blank=True, null=True)
    grading_scale = models.CharField(max_length=255, blank=True)
    schedule = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=255, blank=True)
    high_school = models.CharField(max_length=255, blank=True)

    # Array of grades for each grading period (determined by schedule). Last grade is "Final"
    grades = ArrayField(models.CharField(max_length=10, blank=True), default=list)
    credits = ArrayField(models.CharField(max_length=10, blank=True), default=list)
    credits_na = models.BooleanField(default=False)

    name = models.CharField(max_length=255)
    course_notes = models.TextField(blank=True)

    # Array for CW Equivalents. Last one is "Final" (and the only one used to calculate student's CW GPA)
    cw_equivalent_grades = ArrayField(models.FloatField(null=True, blank=True), default=list)
    include_in_cw_gpa = models.BooleanField(default=True)

    # Whether course appears in course planning section or with all other courses
    planned_course = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name


class Tutor(CommonUser, ZoomFields):
    """ A tutor on the academic platform; leads class tutoring sessions and individual sessions with studs """

    user_type = "tutor"

    can_tutor_remote = models.BooleanField(default=True)
    # Zoom or similar link that this tutor ALWAYS uses for remote tutoring
    remote_tutoring_link = models.CharField(max_length=255, blank=True)
    bio = models.TextField(blank=True)

    university = models.ForeignKey(
        "snuniversities.University", related_name="tutors", null=True, blank=True, on_delete=models.SET_NULL,
    )
    degree = models.CharField(max_length=255, blank=True)

    students = models.ManyToManyField("snusers.Student", "tutors")

    location = models.ForeignKey(
        "sntutoring.Location", related_name="tutors", on_delete=models.PROTECT, default=get_default_location,
    )

    is_curriculum_tutor = models.BooleanField(default=True)
    is_test_prep_tutor = models.BooleanField(default=True)

    # Whether or not students (and parents) can book sessions directly with this tutor
    students_can_book = models.BooleanField(default=True)

    # Used to determine pay on time cards
    hourly_rate = models.DecimalField(max_digits=5, decimal_places=2, default=50.0)

    # Whether or not this tutor can be assinged as an evaluator of daignostics
    is_diagnostic_evaluator = models.BooleanField(default=False)

    # for Outlook authorization
    microsoft_token = models.TextField(blank=True, null=True)
    microsoft_refresh = models.TextField(blank=True, null=True)

    # Whether or not we include in-person availablity when students are booking remote sessions with user
    include_all_availability_for_remote_sessions = models.BooleanField(default=False)

    """ Incoming FK """
    # time_cards > many TutorTimeCard
    # primary_group_tutoring_sessions > many GroupTutoringSession
    # support_group_tutoring_sessions > many GroupTutoringSession
    # coureses > many Course (tutor is separately related to group tutoring sessions that comprise course)
    # tutoring_services > many TutoringService that tutor offers (for individual tutoring sessions)
    # restricted_tutoring_packages > many TutoringPackage packages that are only available to this tutor


class Counselor(CommonUser, ZoomFields):
    """ A counselor who works on the admissions platform """

    user_type = "counselor"

    location = models.ForeignKey(
        "sntutoring.Location", related_name="counselors", on_delete=models.PROTECT, default=get_default_location,
    )
    gets_beta_features = models.BooleanField(default=False)

    # Used to detertime if counselor uses Prompt
    prompt = models.BooleanField(default=True)

    # Used to determine pay on time cards
    part_time = models.BooleanField(default=False)
    hourly_rate = models.DecimalField(max_digits=5, decimal_places=2, default=50.0)

    # for Outlook authorization
    microsoft_token = models.TextField(blank=True, null=True)
    microsoft_refresh = models.TextField(blank=True, null=True)

    # For meeting notes email. HTML
    email_header = models.TextField(blank=True, default="Hello,")
    email_signature = models.TextField(blank=True)

    # Calendar settings
    max_meetings_per_day = models.PositiveSmallIntegerField(null=True, blank=True)
    # Buffer between meetings; used for students/parents scheduling meetings
    minutes_between_meetings = models.PositiveSmallIntegerField(default=0)
    # Students can't schedule/reschedule meetings < this many hours in the future
    student_schedule_meeting_buffer_hours = models.PositiveSmallIntegerField(default=24)
    # Whether or not we include in-person availablity when students are booking remote sessions with user
    include_all_availability_for_remote_sessions = models.BooleanField(default=False)

    # If True, counselor is cc'd on notes emails to PARENTS (but not students)
    cc_on_meeting_notes = models.BooleanField(default=False)
    # Minimum number of hours before a meeting required to reschedule.
    student_reschedule_hours_required = models.PositiveSmallIntegerField(null=True)


class Parent(CommonUser):
    """ A parent account. Parents can have many students """

    user_type = "parent"

    hubspot_id = models.CharField(max_length=255, blank=True)
    hubspot_company_id = models.CharField(max_length=255, blank=True)
    cc_email = models.CharField(max_length=255, blank=True)

    # Counselors can enter a secondary parent name/email/phone number. Email will be cc_email
    # Note that secondary parent does NOT get their own UMS account/login
    secondary_parent_first_name = models.CharField(max_length=255, blank=True)
    secondary_parent_last_name = models.CharField(max_length=255, blank=True)
    secondary_parent_phone_number = models.CharField(max_length=18, blank=True)

    @property
    def timezone(self):
        if self.set_timezone:
            return self.set_timezone
        if self.students.exists() and self.students.first().timezone:
            return self.students.first().timezone
        return self.registration_timezone


class Administrator(CommonUser):
    """
        A CW staff member who has admin access to both academic and admissions platforms.
        Can also be a counselor or tutor
    """

    user_type = "administrator"

    can_approve_timesheets = models.BooleanField(default=True)  # Applies to both CAP and CAS timesheets

    is_cas_administrator = models.BooleanField(default=True)
    is_cap_administrator = models.BooleanField(default=True)
    # Managing counselors only have access to a subset of counselors and their students
    managed_counselors = models.ManyToManyField("snusers.Counselor", related_name="managing_administrators", blank=True)

    # Controls who gets notifications for diagnostics workflow
    is_diagnostic_scorer = models.BooleanField(default=False)
    is_diagnostic_recommendation_writer = models.BooleanField(default=False)

    # for Outlook authorization
    microsoft_token = models.TextField(blank=True, null=True)
    microsoft_refresh = models.TextField(blank=True, null=True)

    # Linked users allow users to switch between admin accounts and a counselor or tutor account
    # If this field is set, then the User actually associated with this Administrator is a "shadow user"
    # only used to log in as the Administrator
    linked_user = models.OneToOneField(
        "auth.user", related_name="linked_administrator", null=True, on_delete=models.SET_NULL
    )

    """ Incoming FK """
    # approved_time_cards > many TutorTimeCard
