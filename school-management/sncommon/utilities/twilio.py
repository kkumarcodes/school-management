"""
  This module contains utilities for interacting with Twilio
"""
from typing import List

from twilio.rest import Client
from twilio.rest.conversations.v1.conversation.message import MessageInstance
from django.conf import settings
from django.utils import timezone

from snnotifications.text_templates import TEXT_TEMPLATES
from snmessages.models import SNPhoneNumber, ConversationParticipant


class TwilioException(Exception):
    pass


class TwilioManager:
    """ Manager class that can be used to interact with Twilio.
        Must be instaniated.
    """

    # instance of twilio.rest.Client
    client = None
    phone_number = None

    def __init__(self):
        if settings.TESTING and not settings.TEST_TWILIO:
            return
        if (
            settings.TWILIO_SID
            and settings.TWILIO_SECRET
            and SNPhoneNumber.objects.filter(default_operations_number=True).exists()
        ):
            self.client = Client(settings.TWILIO_SID, settings.TWILIO_SECRET)
            self.phone_number = SNPhoneNumber.objects.get(default_operations_number=True).phone_number
        elif not settings.TESTING:
            raise TwilioException("Missing Twilio config settings")

    def get_unread_messages_for_conversation_participant(
        self, participant: ConversationParticipant
    ) -> List[MessageInstance]:
        """ Retrieve actual message objects for a Twilio conversation. Since the frontend Twilio client
            also retrieves the messages, this is primarily used to send email notifications of unread messages
            Returns at most 10 most recent unread messages.
        """
        all_messages = self.client.conversations.conversations(participant.conversation.conversation_id).messages.list()
        # We only display messages sent after our last read
        messages = list(
            filter(
                lambda x: (not participant.last_unread_message_notification)
                or x.date_created > participant.last_unread_message_notification,
                all_messages,
            )
        )
        return messages[:10]

    def send_verification(self, notification_recipient):
        """ Send a NEW verification code to a notification recipient
            Arguments:
                notification_recipient {NotificationRecipient} who should receive new verification code
            Returns:
                True
        """
        # Sets a new verificatino code on recipient! We always generate a new code before sending
        notification_recipient = notification_recipient.set_new_verification_code()

        if not (settings.TESTING and not settings.TEST_TWILIO):
            self.client.messages.create(
                from_=self.phone_number,
                to=f"+{notification_recipient.phone_number}",
                body=f"Hi! It's Schoolnet :) Your verification code is: {notification_recipient.phone_number_verification_code}",
            )

        notification_recipient.confirmation_last_sent = timezone.now()
        notification_recipient.save()
        return True

    def send_message(
        self, notification_recipient, message, fail_silently=True,
    ):
        """ Send a text message to a NotificationRecipient. Recipient must have text messaging enabled
            and must have a confirmed cell phone number.
            Arguments:
                notification_recipient {NotificationRecipient}
                message {string} Message to send, up to 1600 chars
                fail_silently {bool} If False, then we will throw an error for undeliverable messages.
                    Otherwise, we just return False
            Returns:
                Boolean indicating whether or not message was sent
        """
        if (
            len(message) > 1600
            or not (notification_recipient.receive_texts and notification_recipient.phone_number_confirmed)
            or not (self.client or settings.TESTING)
        ):
            if fail_silently:
                return False
            raise TwilioException

        if not settings.TESTING and not settings.TEST_TWILIO:
            self.client.messages.create(
                from_=self.phone_number, to=f"+{notification_recipient.phone_number}", body=message,
            )
        return True

    def send_message_for_notification(self, notification, fail_silently=True):
        """ Attempt to send a text message for a Notification.
            Updates notification's texted field upon success
            Arguments:
                notification {Notification}
                fail_silently {bool} If False, then we will throw an error for undeliverable messages.
                    Otherwise, we just return False
            Returns:
                Boolean indicating whether or not message was sent
        """
        msg = (
            TEXT_TEMPLATES[notification.notification_type](notification)
            if notification.notification_type in TEXT_TEMPLATES
            else notification.title
        )
        result = self.send_message(notification.recipient, msg, fail_silently=fail_silently,)
        if result:
            notification.texted = timezone.now()
            notification.save()
        return result
