import datetime
from django.db import models
from django.urls import reverse_lazy
from django.utils import timezone
from django.db.models import JSONField
from django.contrib.postgres.fields import ArrayField
from django.core.serializers.json import DjangoJSONEncoder
from sncommon.model_base import SNModel
from sntutoring.constants import RECURRING_AVAILABILITY_FALL_START_MONTH, RECURRING_AVAILABILITY_SUMMER_START_MONTH


class FileUpload(SNModel):
    """ A file uploaded by user that is stored permanently and will be used elsewhere later.
        Note that we retain OG file name
    """

    title = models.CharField(max_length=255, blank=True)

    # Some "files" are actually google drive links to a file
    link = models.URLField(max_length=255, blank=True, null=True)
    # slug and created fields (via SNModel)
    file_resource = models.FileField(upload_to="temp_file_upload", null=True, blank=True)
    created_by = models.ForeignKey(
        "auth.user", related_name="file_uploads", null=True, blank=True, on_delete=models.SET_NULL
    )

    active = models.BooleanField(default=True)

    # Relations to objects that allow file uploads
    task = models.ForeignKey(
        "sntasks.Task", related_name="file_uploads", null=True, blank=True, on_delete=models.SET_NULL
    )

    diagnostic_result = models.ForeignKey(
        "sntutoring.DiagnosticResult", related_name="file_uploads", null=True, blank=True, on_delete=models.SET_NULL
    )

    bulletin = models.ForeignKey(
        "snnotifications.Bulletin", related_name="file_uploads", null=True, blank=True, on_delete=models.SET_NULL
    )

    # If file is for notes provided by a tutor on their session notes, or a counselor for their meeting notes
    tutoring_session_notes = models.ForeignKey(
        "sntutoring.TutoringSessionNotes",
        related_name="file_uploads",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    counselor_meeting = models.ForeignKey(
        "sncounseling.CounselorMeeting", related_name="file_uploads", null=True, blank=True, on_delete=models.SET_NULL
    )

    test_result = models.ForeignKey(
        "sntutoring.TestResult", related_name="file_uploads", null=True, blank=True, on_delete=models.SET_NULL
    )

    # Counselors can upload files for their students. Usually retrieved via reverse: Student.counseling_file_uploads
    counseling_student = models.ForeignKey(
        "snusers.Student", related_name="counseling_file_uploads", null=True, blank=True, on_delete=models.CASCADE,
    )

    # The models that use file uploads use this field in different ways to categorize files
    tags = ArrayField(models.CharField(max_length=255), blank=True, default=list)

    @property
    def url(self):
        return reverse_lazy("get_file_upload", kwargs={"slug": str(self.slug)})

    @property
    def name(self):
        if self.link:
            return self.title
        return self.file_resource.name.split("/")[-1] if self.file_resource else "File Upload <no file>"

    def __str__(self):
        return self.name


class TimeCardBase(SNModel):
    """ Common fields for our CAP and CAS time card models
    """

    start = models.DateTimeField()
    end = models.DateTimeField()
    # We often want to display end dates irrespective of timezone. This is the date to display
    display_end = models.DateField(null=True, blank=True)

    # We cache hourly rate and total on time cards so that if it changes we can audit old values
    hourly_rate = models.DecimalField(max_digits=5, decimal_places=2)
    total = models.DecimalField(max_digits=8, decimal_places=2, default=0.0)

    admin_approval_time = models.DateTimeField(null=True, blank=True)
    admin_approver = models.ForeignKey(
        "snusers.Administrator", related_name="+", null=True, blank=True, on_delete=models.SET_NULL,
    )
    # Note only for admins; not visible to tutor
    admin_note = models.TextField(blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        username = self.tutor.invitation_name if hasattr(self, "tutor") else self.counselor.invitation_name
        return f"Time card from {self.start} to {self.end} for {username}. {self.total_hours} hours."


def get_default_availability():
    """ Helper method to produce default value for recurring availability schedule's availability
    """
    return {
        BaseRecurringAvailability.TRIMESTER_SPRING: {x: [] for x in BaseRecurringAvailability.ORDERED_WEEKDAYS},
        BaseRecurringAvailability.TRIMESTER_SUMMER: {x: [] for x in BaseRecurringAvailability.ORDERED_WEEKDAYS},
        BaseRecurringAvailability.TRIMESTER_FALL: {x: [] for x in BaseRecurringAvailability.ORDERED_WEEKDAYS},
    }


def get_default_locations():
    """ Helper method to produce default value for recurring availability locations (which location
        user is at each day)
    """
    # We default to all None (null) locations to indicate that user is remote by default
    return {
        BaseRecurringAvailability.TRIMESTER_SPRING: {x: None for x in BaseRecurringAvailability.ORDERED_WEEKDAYS},
        BaseRecurringAvailability.TRIMESTER_SUMMER: {x: None for x in BaseRecurringAvailability.ORDERED_WEEKDAYS},
        BaseRecurringAvailability.TRIMESTER_FALL: {x: None for x in BaseRecurringAvailability.ORDERED_WEEKDAYS},
    }


class BaseRecurringAvailability(SNModel):
    """ Base for our tutor and counselor recurring availability models.
        Why not use the same model for both? Well initially only tutors maintained avialability. To avoid the headache
        of transitioning tutors' availability into a new model, we kept it and pulled the common fields into
        this abstract model
        Weekly recurring availability for a tutor or counselor . We use this recurring availability for days
        when tutor/counselor has not explicitly set their availability or set no availability (indicated
        by an availability with duration 0 saved for the day)
        ALL TIMES ARE ASSUMED TO BE UTC!!!!
    """

    TRIMESTER_SPRING = "spring"
    TRIMESTER_SUMMER = "summer"
    TRIMESTER_FALL = "fall"
    # Helps when parsing and saving data for this model
    ORDERED_WEEKDAYS = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]

    # Deprecated
    active = models.BooleanField(default=True)

    # Note that availability has three keys: 'spring', 'fall', and 'summer'.
    availability = JSONField(encoder=DjangoJSONEncoder, default=get_default_availability)
    # Where user is working each day. None indicates remote. Same keys as availability
    locations = JSONField(encoder=DjangoJSONEncoder, default=get_default_locations)

    @property
    def current_availability(self):
        """ Availability for current semester/summer """
        return self.get_availability_for_date(timezone.now())

    @staticmethod
    def get_trimester_for_date(date):
        current_month = date.month
        if current_month >= RECURRING_AVAILABILITY_FALL_START_MONTH:
            return BaseRecurringAvailability.TRIMESTER_FALL
        elif current_month >= RECURRING_AVAILABILITY_SUMMER_START_MONTH:
            return BaseRecurringAvailability.TRIMESTER_SUMMER
        return BaseRecurringAvailability.TRIMESTER_SPRING

    def get_availability_for_date(self, date):
        """ Gets the recurring availability for the correct trimester given a date """
        return self.availability.get(self.get_trimester_for_date(date))

    def get_location_for_date(self, date: datetime):
        weekday = self.ORDERED_WEEKDAYS[date.weekday()]
        return self.locations.get(self.get_trimester_for_date(date)).get(weekday)

    class Meta:
        abstract = True


class BaseAvailability(SNModel):
    """ A block of time that a tutor or counselor is available
        Why not use the same model for both? Well initially only tutors maintained availability. To avoid the headache
        of transitioning tutors' availability into a new model, we kept it and pulled the common fields into
        this abstract model
    """

    start = models.DateTimeField()
    end = models.DateTimeField()
    location = models.ForeignKey(
        "sntutoring.Location",
        related_name="+",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="If availability is in person, the location where user is available in person. If null, then this availability is remote.",
    )

    class Meta:
        abstract = True
        ordering = ["start"]
