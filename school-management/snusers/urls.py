"""
    All urls prefaced by /user/
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views.register_login import (
    LoginView,
    LogoutView,
    RegisterView,
    RegisterCourseView,
    ObtainJWTLinkView,
    SwitchLinkedUserView,
)
from .views.application import PlatformView
from .views.users_api import (
    StudentViewset,
    ParentViewset,
    CounselorViewset,
    TutorViewset,
    SendInviteView,
    StudentHighSchoolCourseViewset,
    AdministratorViewset,
    ZoomURLView,
)
from .views.zoom_webhook import ZoomWebhookView
from .views.calendar import EventFeed
from .views.hubspot import HubspotUserCardView, HubspotOAuthRedirect
from .views.prompt_api import PromptCounselorAPIView, PromptStudentAPIView, PromptOrganizationAPIView
from .views.ms_graph_api import MSOutlookAPIView

# pylint: disable=invalid-name
router = DefaultRouter()

router.register(r"students", StudentViewset, basename="students")
router.register(r"counselors", CounselorViewset, basename="counselors")
router.register(r"tutors", TutorViewset, basename="tutors")
router.register(r"parents", ParentViewset, basename="parents")
router.register(r"administrators", AdministratorViewset, basename="administrators")
router.register(r"outlook", MSOutlookAPIView, basename="outlook")
router.register(
    r"high-school-courses", StudentHighSchoolCourseViewset, basename="high_school_courses",
)

# pylint: disable=invalid-name
urlpatterns = router.urls + [
    path("login/", LoginView.as_view(), name="cw_login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("register/", RegisterView.as_view(), name="register_post"),
    path("register/course/", RegisterCourseView.as_view(), name="register_course"),
    path("invite/", SendInviteView.as_view(), name="invite"),
    path("zoom-urls/", ZoomURLView.as_view(), name="zoom_urls"),
    path("hubspot-card/", HubspotUserCardView.as_view(), name="hubspot_card"),
    path("hubspot-redirect/", HubspotOAuthRedirect.as_view(), name="hubspot_oauth_redirect",),
    path("register/<str:uuid>/", RegisterView.as_view(), name="register_get"),
    path("platform/<str:platform_type>/<uuid:student_uuid>/", PlatformView.as_view(), name="parent_platform"),
    path("platform/<str:platform_type>/", PlatformView.as_view(), name="platform"),
    path("calendar/<str:slug>/", EventFeed(), name="calendar"),
    path("zoom-webhook/", ZoomWebhookView.as_view(), name="zoom_webhook"),
    # URLs for Prompt API
    path("editate/student/<str:slug>/", PromptStudentAPIView.as_view(), name="prompt_student"),
    path("editate/counselor/<str:slug>/", PromptCounselorAPIView.as_view(), name="prompt_counselor"),
    path("editate/organization/<str:slug>/", PromptOrganizationAPIView.as_view(), name="prompt_organization"),
    # Obtain a login link for someone
    path("obtain-login-link/<str:user_type>/<str:uuid>/", ObtainJWTLinkView.as_view(), name="obtain_jwt_link"),
    path("switch-account/<str:user_type>/", SwitchLinkedUserView.as_view(), name="switch_account"),
]
