""" View for Twilio webhooks
"""
from django.utils import timezone
from django.shortcuts import get_object_or_404

from django.contrib.contenttypes.models import ContentType
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework.response import Response
from cwmessages.models import Conversation, ConversationParticipant
from cwnotifications.constants.notification_types import COUNSELOR_FORWARD_STUDENT_MESSAGE
from cwnotifications.generator import create_notification
from cwnotifications.models import Notification
from snusers.models import Counselor


class TwilioWebhookView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request, *args, **kwargs):
        """ Here's where we get POSTed Twilio webhooks
            https://www.twilio.com/docs/usage/webhooks
            Payload:
            https://www.twilio.com/docs/conversations/conversations-webhooks#onmessageadd
        """
        conversation = get_object_or_404(Conversation, conversation_id=request.POST.get("ConversationSid"))
        conversation.last_message = timezone.now()
        conversation.save()
        if request.POST.get("ParticipantSid"):
            cp: ConversationParticipant = ConversationParticipant.objects.filter(
                participant_id=request.POST.get("ParticipantSid")
            )
            # We update all conversation participant for the same notification recipient in the same conversation
            ConversationParticipant.objects.filter(
                conversation__participants__in=cp, notification_recipient__participants__in=cp
            ).update(last_unread_message_notification=timezone.now(), last_read=timezone.now())

            # This notification will "forward" the text to counselor if they have text message enabled
            if (
                conversation.conversation_type == Conversation.CONVERSATION_TYPE_COUNSELOR
                and not Counselor.objects.filter(user__notification_recipient__participants__in=cp).exists()
            ):
                message_sid = request.POST.get("MessageSid")
                already_sent = Notification.objects.filter(
                    notification_type=COUNSELOR_FORWARD_STUDENT_MESSAGE,
                    additional_args__contains={"message_sid": message_sid},
                ).exists()
                if conversation.student and conversation.student.counselor and not already_sent:
                    counselor = conversation.student.counselor
                    sender_participant = cp.first()

                    create_notification(
                        counselor.user,
                        notification_type=COUNSELOR_FORWARD_STUDENT_MESSAGE,
                        related_object_content_type=ContentType.objects.get_for_model(Conversation),
                        related_object_pk=conversation.pk,
                        additional_args={
                            "participant_sid": request.POST.get("ParticipantSid"),
                            "message": request.POST.get("Body"),
                            "author": sender_participant.notification_recipient.user.get_full_name()
                            if sender_participant
                            else request.POST.get("Author"),
                            "message_sid": message_sid,
                        },
                    )

        return Response({"last_message": str(conversation.last_message)})
