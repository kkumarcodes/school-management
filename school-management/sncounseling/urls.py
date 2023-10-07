from django.urls import path
from rest_framework.routers import DefaultRouter
from .views.launch_prompt import LaunchPromptPlatformView
from .views.counselor_prompt_api import SyncPromptAssignmentsView
from .views.counselor_meeting import (
    CounselorMeetingViewset,
    CounselorMeetingTemplateViewset,
    CounselorNoteViewset,
    AgendaItemTemplateViewset,
    AgendaItemListView,
    CounselorEventTypeViewset,
)
from .views.counselor_time_card import (
    CounselingHoursGrantViewset,
    CounselorTimeEntryViewset,
    CounselorTimeCardViewset,
    StudentCounselingHoursViewset,
)
from .views.roadmap import RoadmapViewset
from .views.student_activity import StudentActivityViewset

# All routes prefaced by /counseling/
router = DefaultRouter()
router.register("counselor-meetings", CounselorMeetingViewset, basename="counselor_meetings")
router.register("roadmaps", RoadmapViewset, basename="roadmaps")
router.register("counselor-notes", CounselorNoteViewset, basename="counselor_notes")
router.register("student-activity", StudentActivityViewset, basename="student_activity")
router.register("student-counseling-hours", StudentCounselingHoursViewset, basename="student_counseling_hours")
router.register("counselor-time-entry", CounselorTimeEntryViewset, basename="counselor_time_entry")
router.register("counselor-time-card", CounselorTimeCardViewset, basename="counselor_time_card")
router.register("counselor-event-type", CounselorEventTypeViewset, basename="counselor_event_type")
router.register("counselor-meeting-templates", CounselorMeetingTemplateViewset, basename="counselor_meeting_templates")
router.register("agenda-item-templates", AgendaItemTemplateViewset, basename="agenda_item_templates")
router.register("counseling-hours-grants", CounselingHoursGrantViewset, basename="counseling_hours_grants")
# pylint: disable=invalid-name
urlpatterns = router.urls + [
    path("agenda-items/", AgendaItemListView.as_view(), name="agenda_items"),
    path("launch-essays/", LaunchPromptPlatformView.as_view(), name="launch_prompt"),
    path(
        "sync-prompt-assignments/<int:student>/", SyncPromptAssignmentsView.as_view(), name="sync_prompt_assignments"
    ),
]
