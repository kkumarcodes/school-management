from django.db import models
from django.urls import reverse_lazy

from cwcommon.model_base import CWModel


class ResourceGroup(CWModel):
    """ A collection of Resource objects that can be exposed to a user all at once
        ResourceGroups are ONLY to be used for stock resources, and can only be managed
        by admins (i.e. a Tutor cannot create a ResourceGroup for Resources they create
        for one of their students)
    """

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    cap = models.BooleanField(default=True)
    cas = models.BooleanField(default=False)
    is_stock = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        "auth.user", on_delete=models.SET_NULL, related_name="resource_groups", null=True, blank=True
    )

    """ Incoming FK """
    # - visible_students > many Student
    # - tutoring_packages > many TutoringPackage

    def __str__(self):
        return self.title


class Resource(CWModel):
    """ A file or link that can be made available to a student to help with their academic tutoring
        or college application process
    """

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    resource_file = models.FileField(null=True, blank=True, upload_to="resources")
    link = models.CharField(max_length=255, blank=True)  # URL to Resource
    # If resource is a vimeo video, then we embed it in the platform instead of linking.
    # This Vimeo ID allows us to do this
    vimeo_id = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "auth.user", related_name="created_resources", null=True, blank=True, on_delete=models.SET_NULL,
    )
    resource_group = models.ForeignKey(
        "cwresources.ResourceGroup", related_name="resources", null=True, blank=True, on_delete=models.SET_NULL,
    )
    view_count = models.IntegerField(default=0)

    archived = models.BooleanField(default=False)
    # Whether or not Resource is provided by CW (i.e. not created by a counselor or tutor for individual use)
    is_stock = models.BooleanField(default=False)

    """ Incoming FK """
    # - visible_students > many Student
    # - tasks > many Task (note that task can, in turn, have a Diagnostic associated with it)
    # - diagnostics > many Diagnostic
    # - student_tutoring_sessions > many StudentTutoringSession
    # - courses > many Course
    # - counselor_meeting_student_resources > many CounselorMeeting
    # - counselor_meeting_template_resources > many CounselorMeetingTemplate

    def __str__(self):
        return self.title

    def url(self):
        """ URL (via get_resource view) """
        return reverse_lazy("get_resource", kwargs={"resource_slug": str(self.slug)})
