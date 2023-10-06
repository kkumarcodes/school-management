from django.contrib.postgres.fields.array import ArrayField
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import JSONField
from django.core.serializers.json import DjangoJSONEncoder
from cwcommon.model_base import CWModel, CWAbbreviation
from cwusers.models import AddressFields
from .constants import application_tracker_status, applications, acceptance_status, application_requirements


class University(AddressFields):
    """ A university that a `Student` can apply to """

    # Display name
    name = models.CharField(max_length=255)
    # Long name (if we shortened name)
    long_name = models.CharField(max_length=255)
    city = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=255, blank=True)
    # Space separated list of abbreviations that can be searched on
    abbreviations = models.CharField(max_length=255, blank=True)
    rank = models.IntegerField(null=True)
    active = models.BooleanField(default=True)

    us_news_url = models.URLField(max_length=255, blank=True, null=True)
    niche_url = models.URLField(max_length=255, blank=True, null=True)
    campus_reel_url = models.URLField(max_length=255, blank=True, null=True)
    tpr_url = models.URLField(max_length=255, blank=True, null=True)
    college_board_url = models.URLField(max_length=255, blank=True, null=True)
    unigo_url = models.URLField(max_length=255, blank=True, null=True)
    twitter_url = models.URLField(max_length=255, blank=True, null=True)
    facebook_url = models.URLField(max_length=255, blank=True, null=True)
    instagram_url = models.URLField(max_length=255, blank=True, null=True)
    youtube_url = models.URLField(max_length=255, blank=True, null=True)
    pinterest_url = models.URLField(max_length=255, blank=True, null=True)
    linkedin_url = models.URLField(max_length=255, blank=True, null=True)

    accepted_applications = ArrayField(
        models.CharField(choices=applications.APPLICATION_CHOICES, blank=True, max_length=255),
        default=list,
        help_text="The applications that this university accepts(common_app, uc, coalition, apply_texas, questbridge, ucas, school_specific)",
    )

    # Admissions site URL
    url = models.CharField(max_length=255, blank=True)
    logo = models.ImageField(upload_to="universities/logos/", blank=True)

    # WGOH ID
    scid = models.CharField(max_length=255, blank=True)
    # U.S. Dept of Ed ID
    iped = models.CharField(max_length=255, blank=True)

    # We store data from various data sources to display on school profile pages
    # See import_scorecard_data.py for the keys
    scorecard_data = JSONField(encoder=DjangoJSONEncoder, default=dict)

    # App Requirements
    common_app_personal_statement_required = models.BooleanField(default=False)
    transcript_requirements = models.TextField(blank=True)
    courses_and_grades = models.TextField(blank=True)
    common_app_portfolio = models.TextField(blank=True)
    testing_requirements = models.TextField(blank=True)
    common_app_test_policy = models.TextField(blank=True)
    counselor_recommendation_required = models.BooleanField(default=False)
    mid_year_report = models.BooleanField(default=False)
    international_tests = models.TextField(blank=True)
    required_teacher_recommendations = models.IntegerField(default=0)
    optional_teacher_recommendations = models.IntegerField(default=0)
    optional_other_recommendations = models.IntegerField(default=0)
    required_other_recommendations = models.IntegerField(default=0)
    interview_requirements = models.TextField(
        blank=True, choices=application_requirements.INTERVIEW_REQUIREMENT_OPTIONS
    )
    need_status = models.TextField(blank=True)
    demonstrated_interest = models.TextField(blank=True)
    international_sat_act_subject_test_required = models.BooleanField(default=False)
    resume_required = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class UniversityList(CWModel):
    """
    A curated collection of `University` objects.

    UniversityLists may be curated by `Student`, `Parent`, or `Counselor` users.
    """

    # Title of this list
    name = models.CharField(max_length=255)
    # Description of this list
    description = models.TextField(blank=True)
    # Universities in this list
    universities = models.ManyToManyField("cwuniversities.University", related_name="university_lists", blank=True)
    # User who created this list. Lists may be created by `Student`, `Parent`,
    # or `Counselor` users
    created_by = models.ForeignKey(
        "auth.user", related_name="university_lists_created", on_delete=models.SET_NULL, null=True,
    )
    # User who owns, and therefore can modify, this lists. Lists may be owned by
    # `Student` or `Counselor` users
    owned_by = models.ForeignKey("auth.user", related_name="university_lists_owned", on_delete=models.CASCADE)
    # Users to whom this list is assigned. Student-owned lists are
    # automatically assigned to the `Student` for whom they are created
    assigned_to = models.ManyToManyField("auth.user", related_name="university_lists_assigned", blank=True)

    def __str__(self):
        return self.name


class DeadlineCategory(CWAbbreviation):
    """
    A deadline category.

    A deadline may be related to admissions, financial aid, etc.
    """


class DeadlineType(CWAbbreviation):
    """
    A deadline type.

    Entities (like `Universities`) may have more than one type of deadline,
    e.g., Early Decision, Early Action, etc.
    """


class Deadline(CWModel):
    """
    A deadline for an entity.
    """

    # The category of deadline this belongs to
    category = models.ForeignKey("DeadlineCategory", related_name="deadlines", on_delete=models.PROTECT)
    # The type of deadline this is
    type_of = models.ForeignKey("DeadlineType", related_name="deadlines", on_delete=models.PROTECT)
    # The start date of the deadline "window"
    startdate = models.DateTimeField(blank=True, null=True)
    # The end date of the deadline "window". Typically the actual "due date" of
    # the deadline
    enddate = models.DateTimeField(blank=True, null=True)
    # The University to which this deadline belongs
    university = models.ForeignKey("University", related_name="deadlines", on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.university.name} - {self.type_of.name}"

    class Meta:
        # A Deadline must be a unique combination of University + DeadlineType
        # + DeadlineCategory
        constraints = [models.UniqueConstraint(fields=["university", "category", "type_of"], name="unique_deadline")]


class StudentUniversityDecision(CWModel):
    """
        A Student's decision about applying to a University.
        Note that these objects comprise students' official removed/pending/final school lists, as displayed
        in UMS
    """

    # Is the Student applying to this University?
    YES = "YES"
    NO = "NO"
    MAYBE = "MAYBE"
    IS_APPLYING_CHOICES = (
        (YES, "Yes"),
        (NO, "No"),
        (MAYBE, "Maybe"),
    )
    TARGET = "target"
    REACH = "reach"
    SAFETY = "likely"
    TARGET_REACH = "target_reach"
    FAR_REACH = "far_reach"
    TARGET_SAFETY = "target_likely"
    TARGET_REACH_SAFETY = (
        (TARGET, "Target"),
        (REACH, "Reach"),
        (FAR_REACH, "Far Reach"),
        (SAFETY, "Likely"),
        (TARGET_REACH, "Target/Reach"),
        (TARGET_SAFETY, "Target/Likely"),
        ("", "None"),
    )
    is_applying = models.CharField(max_length=5, choices=IS_APPLYING_CHOICES, default=MAYBE)
    target_reach_safety = models.CharField(max_length=255, blank=True, choices=TARGET_REACH_SAFETY, default="")
    # Student making this decision
    student = models.ForeignKey(
        "cwusers.Student", related_name="student_university_decisions", on_delete=models.CASCADE
    )
    # University about which this decision is being made
    university = models.ForeignKey("University", related_name="student_university_decisions", on_delete=models.CASCADE)
    # Deadline related to this decision
    deadline = models.ForeignKey(
        "Deadline", related_name="student_university_decisions", on_delete=models.SET_NULL, null=True
    )
    custom_deadline = models.DateTimeField(null=True, blank=True)
    custom_deadline_description = models.TextField(blank=True)

    # Goal date, set independently of deadline
    # TODO Default to deadline when deadline is changed
    goal_date = models.DateTimeField(null=True, blank=True)
    # A Student's note about a University. Editable by Students (and Parents)
    # and Counselors
    note = models.TextField(blank=True)
    # A Counselor's private note about a University (for one Student).
    # Editable only by the Counselor
    note_counselor_private = models.TextField(blank=True)

    # Fields for counselor application tracker, including notes
    submitted = models.DateTimeField(blank=True, null=True)
    major = models.CharField(max_length=255, blank=True)
    application = models.CharField(
        max_length=255, choices=applications.APPLICATION_CHOICES, blank=True, default=application_tracker_status.NONE
    )
    application_status = models.CharField(
        choices=application_tracker_status.APPLICATION_STATUS_CHOICES,
        blank=True,
        default=application_tracker_status.NONE,
        max_length=255,
    )
    application_status_note = models.TextField(blank=True)

    # Short answer status pulled from essay tasks
    short_answer_note = models.TextField(blank=True)

    transcript_status = models.CharField(
        max_length=255,
        choices=application_tracker_status.STATUS_CHOICES,
        blank=True,
        default=application_tracker_status.NONE,
    )
    transcript_note = models.TextField(blank=True)

    test_scores_status = models.CharField(
        max_length=255,
        choices=application_tracker_status.STATUS_CHOICES,
        blank=True,
        default=application_tracker_status.NONE,
    )
    test_scores_note = models.TextField(blank=True)

    recommendation_one_status = models.CharField(
        max_length=255,
        choices=application_tracker_status.STATUS_CHOICES,
        blank=True,
        default=application_tracker_status.NONE,
    )
    recommendation_one_note = models.TextField(blank=True)

    recommendation_two_status = models.CharField(
        max_length=255,
        choices=application_tracker_status.STATUS_CHOICES,
        blank=True,
        default=application_tracker_status.NONE,
    )
    recommendation_two_note = models.TextField(blank=True)
    recommendation_three_status = models.CharField(
        max_length=255,
        choices=application_tracker_status.STATUS_CHOICES,
        blank=True,
        default=application_tracker_status.NONE,
    )
    recommendation_four_status = models.CharField(
        max_length=255,
        choices=application_tracker_status.STATUS_CHOICES,
        blank=True,
        default=application_tracker_status.NONE,
    )
    standardized_testing = models.TextField(blank=True)

    acceptance_status = models.CharField(
        max_length=255,
        choices=acceptance_status.ACCEPTANCE_STATUS_CHOICES,
        blank=True,
        default=application_tracker_status.NONE,
    )
    scholarship = models.PositiveSmallIntegerField(default=0)
    twin = models.BooleanField(default=False)
    legacy = models.BooleanField(default=False)
    honors_college = models.BooleanField(default=False)
    additional_requirement_deadline = models.BooleanField(default=False)
    additional_requirement_deadline_note = models.TextField(blank=True)

    # Manually set by counselors that disable prompt
    short_answer_completion = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(100)]
    )

    # Checkbox requested by CW for the tracker
    send_test_scores = models.BooleanField(default=False)

    def __str__(self):
        return f"Student {self.student.pk} for {self.university.name}"

    class Meta:
        # Students may not have more than one decision for a University +
        # Deadline combo
        constraints = [
            models.UniqueConstraint(
                fields=["student", "university", "deadline"], name="unique_student_university_decision"
            )
        ]
