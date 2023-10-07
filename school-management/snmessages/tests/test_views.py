"""
  python manage.py test snmessages.tests.test_views
  Note that in this module we don't actually test interacting with twilio
  That is done in test_conversation_manager
"""
import json
from uuid import uuid4
from urllib.parse import urlencode
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.shortcuts import reverse
from snnotifications.constants.notification_types import COUNSELOR_FORWARD_STUDENT_MESSAGE
from snusers.models import Student, Counselor, Tutor, Parent
from snmessages.models import Conversation, ConversationParticipant
from snnotifications.models import Notification, NotificationRecipient
from snmessages.utilities.conversation_manager import (
    ConversationManager,
    TEST_CHAT_TOKEN,
)


class TestConversationView(TestCase):
    fixtures = (
        "fixture.json",
        "phone_numbers.json",
    )

    def setUp(self):
        self.student = Student.objects.first()
        self.tutor = Tutor.objects.first()
        self.counselor = Counselor.objects.first()
        self.parent = Parent.objects.first()
        self.tutor.students.add(self.student)
        self.counselor.students.add(self.student)
        self.url = reverse("conversations_list")
        self.mgr = ConversationManager()

    def test_get_conversation(self):
        # Required login
        data = {
            "student": self.student.pk,
            "conversation_type": Conversation.CONVERSATION_TYPE_TUTOR,
        }

        response = self.client.get(f"{self.url}?{urlencode(data)}")
        self.assertEqual(response.status_code, 401)
        # Student gets their tutor conversation. At first it doesn't exist
        self.client.force_login(self.student.user)
        response = self.client.get(f"{self.url}?{urlencode(data)}")
        self.assertEqual(response.status_code, 404)
        conversation = self.mgr.get_or_create_conversation(Conversation.CONVERSATION_TYPE_TUTOR, student=self.student)
        response = self.client.get(f"{self.url}?{urlencode(data)}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["pk"], conversation.pk)
        # Conversation starts with participants
        self.assertEqual(len(json.loads(response.content)["participants"]), 2)

        # Can't get conversation as unrelated parent
        self.client.force_login(self.parent.user)
        response = self.client.get(f"{self.url}?{urlencode(data)}")
        self.assertEqual(response.status_code, 403)

    def test_get_create_conversation(self):
        # Login required
        data = {
            "student": self.student.pk,
            "conversation_type": Conversation.CONVERSATION_TYPE_TUTOR,
        }
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Student creates tutor conversation
        self.client.force_login(self.student.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        conversation = Conversation.objects.get(pk=result["pk"])
        self.assertEqual(conversation.student, self.student)
        self.assertEqual(conversation.conversation_type, Conversation.CONVERSATION_TYPE_TUTOR)
        self.assertEqual(result["student"], self.student.pk)

        # Idempotent
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Conversation.objects.count(), 1)

        # Counselor creates student conversation
        data["conversation_type"] = Conversation.CONVERSATION_TYPE_COUNSELOR
        data["counselor"] = self.counselor.pk
        self.client.force_login(self.counselor.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        conversation = Conversation.objects.get(pk=result["pk"])
        self.assertEqual(conversation.student, self.student)
        self.assertEqual(conversation.counselor, self.counselor)
        self.assertEqual(conversation.conversation_type, Conversation.CONVERSATION_TYPE_COUNSELOR)
        self.assertEqual(result["student"], self.student.pk)

        # Student creating same conversation just retrieves it
        self.client.force_login(self.student.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Conversation.objects.count(), 2)

        # Unrelated parent can't create student conversation
        self.client.force_login(self.parent.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

        # Tutor creates tutor-counselorconversation
        data = {
            "conversation_type": Conversation.CONVERSATION_TYPE_COUNSELOR_TUTOR,
            "counselor": self.counselor.pk,
            "tutor": self.tutor.pk,
        }
        # Not allowed for parent
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        # Counselor can
        self.client.force_login(self.counselor.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        conversation = Conversation.objects.get(pk=result["pk"])
        self.assertEqual(conversation.tutor, self.tutor)
        self.assertEqual(conversation.counselor, self.counselor)
        self.assertEqual(conversation.conversation_type, Conversation.CONVERSATION_TYPE_COUNSELOR_TUTOR)
        self.assertIsNone(conversation.phone_number)


class TestChatConversationTokenView(TestCase):
    """ python manage.py test snmessages.tests.test_views:TestChatConversationTokenView """

    fixtures = (
        "fixture.json",
        "phone_numbers.json",
    )

    def setUp(self):
        self.student = Student.objects.first()
        self.tutor = Tutor.objects.first()
        self.parent = Parent.objects.first()
        self.tutor.students.add(self.student)
        self.url = reverse("chat_token")
        self.mgr = ConversationManager()
        self.conversation = self.mgr.get_or_create_conversation(
            Conversation.CONVERSATION_TYPE_TUTOR, student=self.student
        )

    def test_post(self):
        data = {"conversation": self.conversation.pk, "identity": self.student.name}
        # auth required
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Check how many conversation participants we have.
        self.assertEqual(ConversationParticipant.objects.count(), 2)

        # Student gets chat token
        self.client.force_login(self.student.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ConversationParticipant.objects.count(), 2)
        participant: ConversationParticipant = ConversationParticipant.objects.get(
            conversation=self.conversation, notification_recipient=self.student.user.notification_recipient
        )
        self.assertEqual(participant.notification_recipient.user, self.student.user)
        self.assertEqual(participant.participant_id, json.loads(response.content)["participant_id"])
        self.assertEqual(json.loads(response.content)["token"], TEST_CHAT_TOKEN)
        self.assertTrue(participant.last_read > timezone.now() - timedelta(seconds=3))

        # Student getting chat token doesn't create new participant
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ConversationParticipant.objects.count(), 2)
        # No SMS participants
        self.assertFalse(
            ConversationParticipant.objects.filter(conversation=participant.conversation,)
            .exclude(phone_number="")
            .exists()
        )

        # Tutor gets chat token for same conversation
        self.client.force_login(self.tutor.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ConversationParticipant.objects.count(), 2)
        participant = ConversationParticipant.objects.last()
        self.assertEqual(participant.notification_recipient.user, self.tutor.user)
        self.assertEqual(participant.participant_id, json.loads(response.content)["participant_id"])
        self.assertEqual(json.loads(response.content)["token"], TEST_CHAT_TOKEN)

        # Unrelated parent can't join chat
        self.client.force_login(self.parent.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ConversationParticipant.objects.count(), 2)


class TestConversationParticipantViewset(TestCase):
    fixtures = (
        "fixture.json",
        "phone_numbers.json",
    )

    def setUp(self):
        self.student = Student.objects.first()
        self.tutor = Tutor.objects.first()
        self.counselor = Counselor.objects.first()
        self.parent = Parent.objects.first()
        self.tutor.students.add(self.student)
        self.counselor.students.add(self.student)
        self.mgr = ConversationManager()
        self.conversation = self.mgr.get_or_create_conversation(
            Conversation.CONVERSATION_TYPE_COUNSELOR, student=self.student
        )
        NotificationRecipient.objects.all().delete()
        self.student_nr = NotificationRecipient.objects.create(
            user=self.student.user, phone_number_confirmed=timezone.now(), phone_number="1231231123",
        )

    def test_create(self):
        data = {"conversation": self.conversation.pk}
        url = reverse("conversation_participants-list")
        # Requires auth
        self.assertEqual(
            self.client.post(url, json.dumps(data), content_type="application/json",).status_code, 401,
        )

        # Student create SMS participant for themselves. Confirm participant has correct phone
        self.client.force_login(self.student.user)
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        participant = ConversationParticipant.objects.get(pk=json.loads(response.content)["pk"])
        self.assertEqual(ConversationParticipant.objects.count(), 1)
        self.assertEqual(participant.notification_recipient, self.student_nr)
        self.assertEqual(participant.conversation, self.conversation)
        self.assertEqual(participant.phone_number, f"+{self.student_nr.phone_number}")
        self.assertEqual(participant.proxy_phone_number, self.conversation.phone_number.phone_number)
        self.assertTrue(participant.active)

        # Idempotent
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ConversationParticipant.objects.count(), 1)
        self.assertEqual(json.loads(response.content)["pk"], participant.pk)

        # Tutor fails - only available to students and counselors
        self.client.force_login(self.tutor.user)
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

        # Attempt for student, but fails without confirmed phone on NotificationRecipient
        participant.delete()
        self.client.force_login(self.student.user)
        self.student_nr.phone_number_confirmed = None
        self.student_nr.save()
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ConversationParticipant.objects.count(), 0)

        # Counselor can't view conversation - fails
        self.counselor.students.clear()
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

        # TODO: Test counselor successfully subscribing to conversation

    def test_get_vcard(self):
        participant = self.mgr.add_sms_participant_to_conversation(self.conversation, self.student_nr)
        # Requires auth
        url = reverse("conversation_participants-vcard", kwargs={"pk": participant.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

        # Requires access to user
        self.client.force_login(self.parent.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Counselor gets student card
        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/x-vCard")

    def test_update_last_read(self):
        # We create a CP that's not connected to Twilio to avoid the extra requests
        participant = ConversationParticipant.objects.create(
            conversation=self.conversation, notification_recipient=self.student_nr
        )
        old_last_read = participant.last_read
        url = reverse("conversation_participants-update_last_read", kwargs={"pk": participant.pk})

        # Login required
        result = self.client.post(url)
        self.assertEqual(result.status_code, 401)

        # Success
        self.client.force_login(self.student.user)
        result = self.client.post(url)
        self.assertEqual(result.status_code, 200)

        participant.refresh_from_db()
        self.assertIsNotNone(participant.last_read)
        self.assertGreater(participant.last_read, old_last_read)


class TestTwilioWebhook(TestCase):
    """ python manage.py test snmessages.tests.test_views:TestTwilioWebhook """

    fixtures = (
        "fixture.json",
        "phone_numbers.json",
    )

    def setUp(self):
        self.student = Student.objects.first()
        self.tutor = Tutor.objects.first()
        self.counselor = Counselor.objects.first()
        self.parent = Parent.objects.first()
        self.tutor.students.add(self.student)
        self.counselor.students.add(self.student)
        self.mgr = ConversationManager()
        self.conversation = Conversation.objects.create(
            conversation_id="test_conversdation",
            student=self.student,
            conversation_type=Conversation.CONVERSATION_TYPE_COUNSELOR,
        )
        NotificationRecipient.objects.create(user=self.counselor.user)

    def test_post(self):
        self.assertIsNone(self.conversation.last_message)
        response = self.client.post(reverse("twilio_webhook"), {"ConversationSid": self.conversation.conversation_id},)
        self.assertEqual(response.status_code, 200)
        self.conversation.refresh_from_db()
        self.assertTrue(self.conversation.last_message > timezone.now() - timedelta(seconds=3))

    def test_counselor_forward_student_message_notification(self):
        """ Test to ensure that new messages from students are forwarded to counselor via SMS, if counselor
            has SMS enabled
            python manage.py test snmessages.tests.test_views:TestTwilioWebhook.test_counselor_forward_student_message_notification
        """
        MESSAGE = "Hey!"
        data = {
            "ConversationSid": self.conversation.conversation_id,
            "MessageSid": str(uuid4()),
            "Body": MESSAGE,
            "ParticipantSid": str(uuid4()),
            "Author": self.student.user.get_full_name(),
        }
        counselor_nr: NotificationRecipient = self.counselor.user.notification_recipient
        counselor_nr.phone_number_confirmed = timezone.now()
        counselor_nr.phone_number = "+11111111111"
        counselor_nr.save()
        response = self.client.post(reverse("twilio_webhook"), data)
        self.assertEqual(response.status_code, 200)

        # Confirm that notification was created for counselor
        notification: Notification = self.counselor.user.notification_recipient.notifications.order_by("pk").last()
        self.assertTrue(notification)
        self.assertEqual(notification.notification_type, COUNSELOR_FORWARD_STUDENT_MESSAGE)
        self.assertEqual(notification.additional_args["participant_sid"], data["ParticipantSid"])
        self.assertEqual(notification.additional_args["message"], MESSAGE)
        self.assertEqual(notification.additional_args["message_sid"], data["MessageSid"])
        self.assertTrue(data["Author"] in notification.title)
        self.assertTrue(notification.texted)

        # Idempotent
        response = self.client.post(reverse("twilio_webhook"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Notification.objects.filter(notification_type=COUNSELOR_FORWARD_STUDENT_MESSAGE).count(), 1)
