from django.urls import path

from rest_framework.routers import DefaultRouter
from snmessages.views.conversations import (
    ConversationView,
    ChatConversationTokenView,
    ConversationParticipantViewset,
)
from snmessages.views.webhooks import TwilioWebhookView

# All routes prefeaced by /message/

# pylint: disable=invalid-name
router = DefaultRouter()
router.register(
    "conversation-participants", ConversationParticipantViewset, basename="conversation_participants",
)
# router.register("conversations", ConversationViewset, basename="conversations")
# pylint: disable=invalid-name
urlpatterns = router.urls + [
    path("conversations/", ConversationView.as_view(), name="conversations_list"),
    path("chat-token/", ChatConversationTokenView.as_view(), name="chat_token"),
    path("twilio/", TwilioWebhookView.as_view(), name="twilio_webhook"),
]
