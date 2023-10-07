"""
  python manage.py test cwmessages.tests.test_tasks
  Test cwmessages.tasks
"""
from datetime import timedelta

from nose.plugins.attrib import attr
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from snusers.models import Student, Counselor, Tutor, Parent
from cwmessages.models import Conversation, ConversationParticipant
from cwmessages.tasks import send_unread_messages, UNREAD_MESSAGE_DELAY
from cwmessages.utilities.conversation_manager import ConversationManager


@override_settings(TEST_TWILIO=True)
@attr("slow")
@attr("api")
class TestUnreadMessagesNotification(TestCase):
    fixtures = (
        "fixture.json",
        "phone_numbers.json",
    )

    def setUp(self):
        self.student = Student.objects.first()
        self.tutor = Tutor.objects.first()
        self.counselor = Counselor.objects.first()
        self.parent = Parent.objects.first()
        self.student.parent = self.parent
        self.student.save()
        self.tutor.students.add(self.student)
        self.counselor.students.add(self.student)
        self.url = reverse("conversations_list")
        self.mgr = ConversationManager()

    @classmethod
    def tearDownClass(cls):
        """ Delete remaining twilio participants """
        # Delete all participants for any conversation that exists in DB
        for conversation in Conversation.objects.all():
            mgr = ConversationManager()
            try:
                mgr.client.conversations.conversations(conversation.sid).delete()
            except Exception as e:
                print("Could not delete", e)
        super().tearDownClass()

    def test_create_conversations(self):
        # We create conversation as tutor, make sure student gets added as participant
        tutor_created_conversation = self.mgr.get_or_create_conversation(
            Conversation.CONVERSATION_TYPE_TUTOR, student=self.student
        )
        self.assertEqual(tutor_created_conversation.participants.count(), 2)
        self.assertTrue(
            tutor_created_conversation.participants.filter(notification_recipient__user__student=self.student).exists()
        )

        # We create conversation as parent, make sure tutor gets added as participant
        parent_created_conversation = self.mgr.get_or_create_conversation(
            Conversation.CONVERSATION_TYPE_TUTOR, parent=self.parent
        )
        self.assertEqual(parent_created_conversation.participants.count(), 2)
        self.assertTrue(
            parent_created_conversation.participants.filter(notification_recipient__user__parent=self.parent).exists()
        )

    def test_successful_notifications(self):
        """ python manage.py test cwmessages.tests.test_tasks:TestUnreadMessagesNotification.test_successful_notifications
        """
        # Create conversation as student with their tutor
        conversation: Conversation = self.mgr.get_or_create_conversation(
            Conversation.CONVERSATION_TYPE_TUTOR, student=self.student
        )
        self.assertEqual(conversation.participants.count(), 2)
        student_participant: ConversationParticipant = conversation.participants.get(
            notification_recipient__user__student=self.student
        )
        tutor_participant: ConversationParticipant = conversation.participants.get(
            notification_recipient__user__tutor=self.tutor
        )
        # Ensure no unread messages notifications sent because there are no unread messages
        result = send_unread_messages()
        self.assertEqual(len(result), 0)

        test_message_body = "Test Message"

        # Tutor sends a message
        message = self.mgr.client.conversations.conversations(
            tutor_participant.conversation.conversation_id
        ).messages.create(author=tutor_participant.chat_identifier, body=test_message_body)

        conversation.last_message = timezone.now()
        conversation.save()
        self.assertIsNone(student_participant.last_unread_message_notification)
        tutor_participant.last_unread_message_notification = timezone.now()
        tutor_participant.save()
        # self.assertGreater(conversation.last_message, student_participant.last_unread_message_notification)
        # self.assertGreater(conversation.last_message, tutor_participant.last_unread_message_notification)

        # Last message needs to be more than UNREAD_MESSAGE_DELAY ago
        result = send_unread_messages()
        self.assertEqual(len(result), 0)
        conversation.last_message = timezone.now() - timedelta(minutes=UNREAD_MESSAGE_DELAY + 2)
        conversation.save()
        student_participant.last_unread_message_notification = timezone.now() - timedelta(
            minutes=UNREAD_MESSAGE_DELAY + 20
        )
        student_participant.save()

        # Success. Ensure we send the notification to student (and only student)
        result = send_unread_messages()
        self.assertEqual(len(result), 1)
        self.assertEqual(result, [student_participant.pk])
        # Confirm stuent student last unread noti is set
        student_participant.refresh_from_db()
        self.assertGreater(student_participant.last_unread_message_notification, conversation.last_message)

        notification = student_participant.notification_recipient.notifications.last()
        self.assertEqual(notification.notification_type, "unread_messages")
        # The actual message should be in additional_args
        self.assertEqual(len(notification.additional_args), 1)
        self.assertEqual(notification.additional_args[0], f"{message.author}: {message.body}")

        # Idempotent - doesn't send again
        result = send_unread_messages()
        self.assertEqual(len(result), 0)

        # Test again with a new message
        conversation.last_message = timezone.now()
        conversation.save()

        # And doesn't send again even after MIN_DURATION_BETWEEN_MESSAGES if there aren't messages
        # after last notification
        conversation.last_message = notification.created - timedelta(seconds=1)
        conversation.save()
        student_participant.last_unread_message_notification = conversation.last_message
        student_participant.save()
        result = send_unread_messages()
        self.assertEqual(len(result), 0)

    def test_successful_notifications_counselor(self):
        """ Lightweight test to ensure counselors get notified of new student messages
            python manage.py test cwmessages.tests.test_tasks:TestUnreadMessagesNotification.test_successful_notifications_counselor

            Here's how we test:
            1. Initialize conversation, make sure we get student and counselor participants
            2. No notis sent
            3. Create message as student. Hit Twilio endpoint. Confirm counselor notified afterwards. Idempotent.
            3. Update student last noti so they would get notified, except there are no messages from counselor
            4. Send message from counselor. Hit Twilio endpoint. Confirm student notified. Idempotent
        """
        # 1. Initialize conversation, make sure we get student and counselor participants
        conversation: Conversation = self.mgr.get_or_create_conversation(
            Conversation.CONVERSATION_TYPE_COUNSELOR, student=self.student, counselor=self.counselor
        )
        self.assertEqual(conversation.participants.count(), 2)
        student_participant: ConversationParticipant = conversation.participants.get(
            notification_recipient__user__student=self.student
        )
        counselor_participant: ConversationParticipant = conversation.participants.get(
            notification_recipient__user__counselor=self.counselor
        )
        self.assertIsNone(conversation.last_message)
        self.assertIsNone(student_participant.last_unread_message_notification)
        self.assertIsNone(counselor_participant.last_unread_message_notification)

        test_message_body = "Test Message"

        message = self.mgr.client.conversations.conversations(
            student_participant.conversation.conversation_id
        ).messages.create(author=student_participant.chat_identifier, body=test_message_body)
        # We hit our TwilioWebhook to alert the system that there is a new message
        url = reverse("twilio_webhook")
        response = self.client.post(
            url, {"ConversationSid": message.conversation_sid, "ParticipantSid": message.participant_sid}
        )
        self.assertEqual(response.status_code, 200)

        conversation.refresh_from_db()
        student_participant.refresh_from_db()
        self.assertIsNotNone(conversation.last_message)
        self.assertIsNotNone(student_participant.last_unread_message_notification)
        self.assertIsNotNone(student_participant.last_read)
        self.assertIsNone(counselor_participant.last_unread_message_notification)

        # No notification yet because last message was not long enough ago
        self.assertEqual(len(send_unread_messages()), 0)
        conversation.last_message = timezone.now() - timedelta(minutes=UNREAD_MESSAGE_DELAY + 1)
        conversation.save()

        # Counselor should get a notification
        result = send_unread_messages()
        self.assertEqual(len(result), 1)
        self.assertIn(counselor_participant.pk, result)
        counselor_participant.refresh_from_db()
        self.assertGreater(counselor_participant.last_unread_message_notification, conversation.last_message)
        notification = counselor_participant.notification_recipient.notifications.last()
        self.assertEqual(notification.notification_type, "unread_messages")
        # Idempotent
        self.assertEqual(len(send_unread_messages()), 0)

        # Counselor lsat unread now before conversation last message
        counselor_participant.last_unread_message_notification = conversation.last_message - timedelta(minutes=1)
        self.assertEqual(len(result), 1)
        self.assertIn(counselor_participant.pk, result)

        # Counselor sends a message, confirm student gets notified
        student_participant.last_unread_message_notification = timezone.now() - timedelta(
            minutes=UNREAD_MESSAGE_DELAY + 1
        )
        student_participant.save()
        result = send_unread_messages()
        self.assertEqual(len(result), 0)

        message = self.mgr.client.conversations.conversations(
            counselor_participant.conversation.conversation_id
        ).messages.create(author=counselor_participant.chat_identifier, body=test_message_body)
        url = reverse("twilio_webhook")
        response = self.client.post(
            url, {"ConversationSid": message.conversation_sid, "ParticipantSid": message.participant_sid}
        )
        conversation.last_message = timezone.now() - timedelta(minutes=UNREAD_MESSAGE_DELAY)
        conversation.save()
        self.assertEqual(response.status_code, 200)
        result = send_unread_messages()
        self.assertEqual(len(result), 1)
        self.assertIn(student_participant.pk, result)
        notification = student_participant.notification_recipient.notifications.last()
        self.assertEqual(notification.notification_type, "unread_messages")
