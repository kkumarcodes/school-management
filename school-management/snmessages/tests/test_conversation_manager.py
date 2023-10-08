""" python manage.py test snmessages.tests.test_conversation_manager
    This module tests snmessages.utilities.conversation_manager.ConversationManager

    Note that this is the place where we actually test API calls to Twilio.
    Tests that interact with Twilio are tagged so they can be included/excluded
    in test runs
"""

import json
from urllib.parse import urlencode
from twilio.rest import TwilioException
from nose.plugins.attrib import attr

from django.test import TestCase, override_settings, tag
from django.utils import timezone
from django.shortcuts import reverse
from snusers.models import Student, Counselor, Tutor, Administrator, Parent
from snmessages.models import Conversation, ConversationParticipant, SNPhoneNumber
from snnotifications.models import NotificationRecipient
from snmessages.utilities.conversation_manager import (
    ConversationManager,
    TEST_CHAT_TOKEN,
    TEST_CONVERSATION_ID,
    TEST_PARTICIPANT_ID,
)


@override_settings(TEST_TWILIO=True)
@attr("slow")
class TestConversationManagerWithTwilio(TestCase):
    fixtures = (
        "fixture.json",
        "phone_numbers.json",
    )

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

    def setUp(self):
        self.student = Student.objects.first()
        self.tutor = Tutor.objects.first()
        self.counselor = Counselor.objects.first()
        self.parent = Parent.objects.first()
        self.tutor.students.add(self.student)
        self.counselor.students.add(self.student)
        self.url = reverse("conversations_list")
        self.mgr = ConversationManager()
        NotificationRecipient.objects.all().delete()
        # Exclude the + at the beginning, because users' phone numbers don't have that!
        phone = SNPhoneNumber.objects.get(default_tutor_number=True).phone_number[1:]
        self.student_nr = NotificationRecipient.objects.create(
            user=self.student.user, phone_number_confirmed=timezone.now(), phone_number=phone,
        )
        self.counselor_nr = NotificationRecipient.objects.create(
            user=self.counselor.user, phone_number_confirmed=timezone.now(), phone_number=phone,
        )

    def test_create_delete_conversation(self):
        conversation = self.mgr.get_or_create_conversation(Conversation.CONVERSATION_TYPE_TUTOR, student=self.student)
        # Confirm we have a conversation ID and it exists
        self.assertTrue(conversation.conversation_id)
        self.assertTrue(conversation.conversation_chat_id)
        self.assertEqual(conversation.student, self.student)
        self.assertEqual(conversation.conversation_type, Conversation.CONVERSATION_TYPE_TUTOR)
        # This will ensure conversation exists in Twilio. Throws exception if converation does not exist
        twilio_conversation = self.mgr.client.conversations.conversations(conversation.conversation_id).fetch()
        self.assertEqual(twilio_conversation.friendly_name, "SN Conversation")
        self.assertEqual(twilio_conversation.chat_service_sid, conversation.conversation_chat_id)
        # There should be a participant for each the student and the tutor
        self.assertEqual(len(twilio_conversation.participants.list()), conversation.participants.count())

        # Delete the conversation
        self.mgr.deactivate_conversation(conversation)
        conversation.refresh_from_db()
        self.assertFalse(conversation.active)

        self.assertRaises(
            TwilioException, lambda: self.mgr.client.conversations.conversations(conversation.conversation_id).fetch(),
        )

    def test_add_remove_sms_participant(self):
        conversation = self.mgr.get_or_create_conversation(
            Conversation.CONVERSATION_TYPE_COUNSELOR, student=self.student
        )
        student_participant = self.mgr.add_sms_participant_to_conversation(conversation, self.student_nr)

        # Will throw exception if participant doesnt exist in Twilio
        twilio_participant = (
            self.mgr.client.conversations.conversations(conversation.conversation_id)
            .participants(student_participant.participant_id)
            .fetch()
        )
        self.assertEqual(twilio_participant.sid, student_participant.participant_id)
        self.assertEqual(twilio_participant.conversation_sid, conversation.conversation_id)
        self.assertEqual(twilio_participant.messaging_binding["type"], "sms")
        self.assertEqual(
            twilio_participant.messaging_binding["proxy_address"], student_participant.proxy_phone_number,
        )
        self.assertEqual(
            twilio_participant.messaging_binding["address"], student_participant.phone_number,
        )

        # Deactivate that participant. Ensure they're deleted
        self.mgr.delete_conversation_participant(student_participant)
        self.assertFalse(ConversationParticipant.objects.filter(pk=student_participant.pk).exists())
        self.assertRaises(
            TwilioException,
            lambda: self.mgr.client.conversations.conversations(conversation.conversation_id)
            .participants(student_participant.participant_id)
            .fetch(),
        )

        # Reactivate just for fun
        student_participant = self.mgr.add_sms_participant_to_conversation(conversation, self.student_nr)
        twilio_participant = (
            self.mgr.client.conversations.conversations(conversation.conversation_id)
            .participants(student_participant.participant_id)
            .fetch()
        )

        # Deactivate via deactivating conversation
        self.mgr.deactivate_conversation(conversation)
        self.assertRaises(
            TwilioException,
            lambda: self.mgr.client.conversations.conversations(conversation.conversation_id)
            .participants(student_participant.participant_id)
            .fetch(),
        )

    def test_add_remove_chat_participant(self):
        pass

    def test_deactivate_conversation(self):
        pass


class TestConversationManagerWithoutTwilio(TestCase):
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

    def test_user_can_view_conversation(self):
        tutor_conversation = self.mgr.get_or_create_conversation(
            Conversation.CONVERSATION_TYPE_TUTOR, student=self.student
        )

        for user in [self.student.user, self.counselor.user, self.tutor.user]:
            self.assertTrue(ConversationManager.user_can_view_conversation(user, tutor_conversation))

        self.counselor.students.clear()
        self.tutor.students.clear()
        tutor_conversation.refresh_from_db()

        for user in [self.counselor.user, self.tutor.user]:
            self.assertFalse(ConversationManager.user_can_view_conversation(user, tutor_conversation))

        self.counselor.students.add(self.student)
        counselor_conversation = self.mgr.get_or_create_conversation(
            Conversation.CONVERSATION_TYPE_COUNSELOR, student=self.student, counselor=self.counselor,
        )
        for user in [self.counselor.user, self.student.user]:
            self.assertTrue(ConversationManager.user_can_view_conversation(user, counselor_conversation))

        for user in [self.parent.user, self.tutor.user]:
            self.assertFalse(ConversationManager.user_can_view_conversation(user, counselor_conversation))

        # Admin can view all
        admin = Administrator.objects.first()
        self.assertTrue(ConversationManager.user_can_view_conversation(admin.user, tutor_conversation))
        self.assertTrue(ConversationManager.user_can_view_conversation(admin.user, counselor_conversation))

