from datetime import timedelta
from typing import List

from django.db.models.query_utils import Q
from celery import shared_task
from django.utils import timezone
from django.db.models import F
from django.contrib.contenttypes.models import ContentType
from sentry_sdk import configure_scope, capture_exception, set_tag

from cwmessages.models import ConversationParticipant
from cwcommon.utilities.twilio import TwilioException, TwilioManager
from cwnotifications.generator import create_notification
from cwmessages.models import Conversation

# Time between last unread message being sent and when we send email about it, in minutes
UNREAD_MESSAGE_DELAY = 3
# MIN_DURATION_BETWEEN_MESSAGES = 8


@shared_task
def send_unread_messages() -> List[int]:
    """ Sends notifications for unread messages in conversations.
        We wait 3 minutes after last message to send.

        Note that we are only comparing last message in a conversation (from another participant)
        with the last sent notification to other participants.
    """
    unread_conversation_participants = (
        ConversationParticipant.objects.filter(
            conversation__last_message__lt=timezone.now() - timedelta(minutes=UNREAD_MESSAGE_DELAY), active=True,
        )
        .filter(
            Q(conversation__last_message__gt=F("last_unread_message_notification"))
            | Q(Q(conversation__last_message__isnull=False) & Q(last_unread_message_notification=None))
        )
        .filter(phone_number="")
        .exclude(
            Q(notification_recipient__user__administrator__isnull=False)
            & ~Q(conversation__conversation_type=Conversation.CONVERSATION_TYPE_OPERATIONS)
        )
    )  # Filter for no phone because we only want chat participants
    twilio_manager: TwilioManager = TwilioManager()
    sent_notification_recipients = []
    for participant in unread_conversation_participants:
        try:
            # Retrieve unread message objects. We store as strings in Notification.additional_args
            # because I felt weird doing the Twilio API request in notification context getter
            unread_messages = twilio_manager.get_unread_messages_for_conversation_participant(participant)
            # Users can create messages by texting, which wouldn't update their last read. As such, unread_messages
            # can contain messages sent by our ConversationParticipant. We filter those out to make sure there are some
            # actual new messages sent by other people that our participant should read
            if [x for x in unread_messages if x.participant_sid != participant.participant_id]:
                string_messages = [f"{x.author}: {x.body}" for x in unread_messages]
                sent_notification_recipients.append(participant.pk)
                create_notification(
                    participant.notification_recipient.user,
                    notification_type="unread_messages",
                    related_object_content_type=ContentType.objects.get_for_model(ConversationParticipant),
                    related_object_pk=participant.pk,
                    additional_args=string_messages,
                )
                participant.last_unread_message_notification = timezone.now()
                participant.save()
        except (TwilioException, ValueError) as err:
            with configure_scope() as scope:
                set_tag("Task Error", "Unread Messages")
                scope.set_context(
                    "twilio_context", {"operation": "Get unread messages", "particpant": participant.pk},
                )
                capture_exception(err)

    return sent_notification_recipients


# To test:
# from cwmessages.tasks import send_unread_messages
# from datetime import timedelta

# conversation = Conversation.objects.last()
# conversation.last_message = timezone.now() - timedelta(minutes=20)
# conversation.save()
# conversation.participants.update(last_read=timezone.now() - timedelta(days=100))
# tutor_cp = conversation.participants.get(notification_recipient__user__tutor__isnull=False)
# send_unread_messages()
