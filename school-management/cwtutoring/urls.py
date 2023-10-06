from rest_framework.routers import DefaultRouter
from django.urls import path
from .views.diagnostic import (
    DiagnosticResultViewset,
    DiagnosticViewset,
    LocationViewset,
    TestResultViewset,
    DiagnosticGroupTutoringSessionRegistrationViewset,
    DiagnosticRegistrationCounselorViewset,
)
from .views.tutoring_session import (
    StudentTutoringSessionViewset,
    GroupTutoringSessionViewset,
    TutoringServiceViewset,
    TutorTutoringSessionsView,
    DiagnosticGTSView,
    AvailabelZoomURLView,
)
from .views.tutoring_package import (
    TutoringPackageViewset,
    TutoringPackagePurchaseViewset,
    PurchaseableTutoringPackageView,
)
from .views.courses import CourseViewset
from .views.time_cards import TutorTimeCardViewset, TutorTimeCardLineItemViewset, TutorTimeCardLineItemAccountingView
from .views.tutoring_session_notes import TutoringSessionNotesViewset
from .views.reports import ReportTutoringPackagePurchaseView, ReportTutorView

# all paths prefaced by /tutoring/

# pylint: disable=invalid-name
router = DefaultRouter()
router.register(
    r"tutoring-session-notes", TutoringSessionNotesViewset, basename="tutoring_session_notes",
)
router.register(r"diagnostics", DiagnosticViewset, basename="diagnostics")
router.register(r"locations", LocationViewset, basename="locations")
router.register(r"time-cards", TutorTimeCardViewset, basename="time_cards")
router.register(
    r"time-card-line-items", TutorTimeCardLineItemViewset, basename="time_card_line_items",
)
router.register(
    r"student-tutoring-sessions", StudentTutoringSessionViewset, basename="student_tutoring_sessions",
)
router.register(r"tutoring-services", TutoringServiceViewset, basename="tutoring_services")
router.register(r"diagnostic-results", DiagnosticResultViewset, basename="diagnostic_results")
router.register(r"test-results", TestResultViewset, basename="test_results")
router.register(
    r"group-tutoring-sessions", GroupTutoringSessionViewset, basename="group_tutoring_sessions",
)
router.register(r"tutoring-packages", TutoringPackageViewset, basename="tutoring_packages")
router.register(
    r"tutoring-package-purchases", TutoringPackagePurchaseViewset, basename="tutoring_package_purchases",
)
router.register(r"courses", CourseViewset, basename="courses")
router.register(r"active-counselors", DiagnosticRegistrationCounselorViewset, basename="active_counselors")


urlpatterns = router.urls + [
    path(
        r"time-card-line-item-accounting/",
        TutorTimeCardLineItemAccountingView.as_view(),
        name="time_card_line_item_accounting",
    ),
    path(r"tutor-tutoring-sessions/<int:pk>/", TutorTutoringSessionsView.as_view(), name="tutor_tutoring_sessions",),
    path(
        r"purchaseable-tutoring-packages/",
        PurchaseableTutoringPackageView.as_view(),
        name="purchaseable_tutoring_packages",
    ),
    path(
        r"diagnostic/registration/",
        DiagnosticGroupTutoringSessionRegistrationViewset.as_view(),
        name="diagnostic_registration",
    ),
    path(
        r"diagnostic/registration/<int:pk>/",
        DiagnosticGroupTutoringSessionRegistrationViewset.as_view(),
        name="diagnostic_registration-detail",
    ),
    path(r"diagnostic-group-tutoring-sessions/", DiagnosticGTSView.as_view(), name="diagnostic_gts",),
    path(
        r"report/tutoring-package-purchase/",
        ReportTutoringPackagePurchaseView.as_view(),
        name="report_tutoring_package_purchase",
    ),
    path(r"report/tutor/", ReportTutorView.as_view(), name="report_tutor",),
    path(r"available-zoom-urls/", AvailabelZoomURLView.as_view(), name="available_zoom_urls"),
]
