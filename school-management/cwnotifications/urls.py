from django.urls import path

from rest_framework.routers import DefaultRouter
from cwnotifications.views.notification import NotificationRecipientViewset, CreateNotificationView, ActivityLogView
from cwnotifications.views.bulletin import BulletinViewset

# All patterns prefaced by /notification
# pylint: disable=invalid-name
router = DefaultRouter()
router.register(
    "notification-recipients", NotificationRecipientViewset, basename="notification_recipients",
)
router.register("bulletins", BulletinViewset, basename="bulletins")

# pylint: disable=invalid-name
urlpatterns = router.urls + [
    path("create-notification/<str:notification_type>/", CreateNotificationView.as_view(), name="create_notification"),
    path("activity-log/", ActivityLogView.as_view(), name="activity_log_system"),
    path("activity-log/<int:user_pk>/", ActivityLogView.as_view(), name="activity_log_user"),
]
