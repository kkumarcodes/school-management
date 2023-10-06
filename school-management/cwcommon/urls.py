"""
    All urls prefaced by /cw/
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views.views import health_check_version, throw_exception
from .views.file_upload import FileUploadView, FileUploadListUpdateViewset, FileUploadFromGoogleDriveView
from .views.magento import MagentoPurchaseWebhookView, PaygoPurchaseView, LateChargeView
from .views.availability import RecurringAvailabilityView, AvailabilityView

router = DefaultRouter()
router.register(r"upload-list-update", FileUploadListUpdateViewset, basename="file_upload_list_update")

# pylint: disable=invalid-name
urlpatterns = router.urls + [
    path("magento-purchase/", MagentoPurchaseWebhookView.as_view(), name="magento_purchase_webhook",),
    path("magento-paygo-purchase/", PaygoPurchaseView.as_view(), name="magento_paygo_purchase",),
    path("magento-late-cancel/", LateChargeView.as_view(), name="magento_late_charge"),
    path("upload/", FileUploadView.as_view(), name="file_upload"),
    path("upload/google-drive/", FileUploadFromGoogleDriveView.as_view(), name="file_upload_google_drive"),
    path("upload/<str:slug>/", FileUploadView.as_view(), name="get_file_upload"),
    path("health-check/", health_check_version, name="health_check"),
    path("throw-exception/", throw_exception, name="throw_exception"),
    # Availability URLs
    path(
        r"tutoring/tutor-availability/recurring/<int:pk>/",
        RecurringAvailabilityView.as_view(),
        name="tutor_recurring_availability-detail",
        kwargs={"user_type": "tutor"},
    ),
    path(
        r"tutoring/tutor-availability/<int:pk>/",
        AvailabilityView.as_view(),
        name="tutor_availability-detail",
        kwargs={"user_type": "tutor"},
    ),
    path(
        r"counseling/counselor-availability/recurring/<int:pk>/",
        RecurringAvailabilityView.as_view(),
        name="counselor_recurring_availability-detail",
        kwargs={"user_type": "counselor"},
    ),
    path(
        r"counseling/counselor-availability/<int:pk>/",
        AvailabilityView.as_view(),
        name="counselor_availability-detail",
        kwargs={"user_type": "counselor"},
    ),
]
