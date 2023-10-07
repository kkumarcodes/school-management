from twilio.rest import Client
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import ChatGrant
from django.conf import settings
from cwcommon.utilities.twilio import TwilioException
from cwnotifications.models import NotificationRecipient
from cwmessages.models import (
    CWPhoneNumber,
    ConversationParticipant,
    Conversation,
)
from snusers.models import Counselor, Tutor

# Some constants we use for testing
TEST_CONVERSATION_ID = "testconversation"
TEST_PARTICIPANT_ID = "testparticipant"
TEST_CHAT_SERVICE_ID = "testchatserviceid"
TEST_CHAT_TOKEN = "testtoken"


class ConversationManagerException(Exception):
    pass


class ConversationManager:
    """ Manager for creating Twilio Conversations and conversation Participants, and managing
        which participants particpate in each Conversation.
        Was that confusing?
        This may help: https://www.twilio.com/docs/conversations/api
    """

    # instance of twilio.rest.Client
    client = None

    def __init__(self):
        if settings.TESTING and not settings.TEST_TWILIO:
            return
        if settings.TWILIO_SID and settings.TWILIO_SECRET:
            self.client = Client(settings.TWILIO_SID, settings.TWILIO_SECRET)
        elif not settings.TESTING:
            raise TwilioException("Missing Twilio config settings")

    def provision_phone_number(self):
        """ Provision a new phone number from Twilio.
            Returns: CWPhoneNumber
            TODO
        """
        raise NotImplementedError("Cannot provision phone number")

    @staticmethod
    def user_can_view_conversation(user, conversation: Conversation):
        """ Permissions check. Returns boolean indicating whether or not user should be allowed to view
            conversation
            Arguments:
                user {User}
                conversation {Conversation}
        """
        if hasattr(user, "administrator"):
            return True

        # Counselors can view all of their students' conversations
        if hasattr(user, "counselor") and (
            conversation.counselor == user.counselor
            or (conversation.student and conversation.student.counselor and conversation.student.counselor.user == user)
            or (conversation.parent and user.counselor.students.filter(parent=conversation.parent).exists())
        ):
            return True

        # Users can view all of their own conversations
        for user_type in ("student", "counselor", "parent"):
            if hasattr(user, user_type) and getattr(user, user_type) == getattr(conversation, user_type):
                return True

        # Tutors can view conversations of type tutor with their students and their parents
        if hasattr(user, "tutor"):
            if conversation.tutor == user.tutor:
                return True
            return conversation.conversation_type == Conversation.CONVERSATION_TYPE_TUTOR and (
                (conversation.student and conversation.student.tutors.filter(user=user).exists())
                or (conversation.parent and conversation.parent.students.filter(tutors__user=user).exists())
            )

        return False

    def _create_twilio_conversation(self, friendly_name):
        """ Use Twilio SDK to create Twilio Conversation object.
            This method is private because we should create Twilio Conversations via self.get_or_creat_conversation
                to ensure we have accompanying Conversation objects for our twilio conversations
            Arguments:
                friendly_name {string} Name for the Conversation
            Returns:
                Twilio Conversation (https://www.twilio.com/docs/conversations/api/conversation-resource)
        """
        if settings.TEST_TWILIO or not settings.TESTING:
            return self.client.conversations.conversations.create(friendly_name=friendly_name)

    def delete_conversation_participant(self, conversation_participant):
        """ Remove a participant from a conversation.
            Deletes the associated Twilio ConversationParticipant, and sets our ConversationParticipant
            to be inactive
            Arguments:
                conversation_participant {ConversationParticipant}
            Returns: None
        """
        if not (conversation_participant.active and conversation_participant.conversation.active):
            return

        if settings.TEST_TWILIO or not settings.TESTING:
            self.client.conversations.conversations(conversation_participant.conversation.conversation_id).participants(
                conversation_participant.participant_id
            ).delete()

        conversation_participant.delete()

    def deactivate_conversation(self, conversation):
        """ Delete a Twilio conversation and deactivate the associated Conversation object on our end.
            Note that this will first deactivate all conversation participants.
            Conversation object (and all related ConversationParticipant objects) will get active set to False
            Arguments:
                conversation {Conversation}
            Returns: updated Conversation object
        """
        if not conversation.active:
            return conversation
        for participant in conversation.participants.filter(active=True):
            self.delete_conversation_participant(participant)

        if settings.TEST_TWILIO or not settings.TESTING:
            self.client.conversations.conversations(conversation.conversation_id).delete()

        conversation.active = False
        conversation.save(update_fields=("active",))
        return conversation

    def _confirm_recipient_can_recieve_texts(self, notification_recipient):
        """ Raise TwilioException with helpful message if notification_recipient can't receive texts
            Arguments:
                notification_recipient {NotificationRecipient}
            Returns:
                None; Raises Exception
        """
        if not (
            notification_recipient.phone_number
            and notification_recipient.phone_number_confirmed
            and notification_recipient.receive_texts
        ):
            raise TwilioException(
                "Cannot create Conversation for recipient {notification_recipient.pk} because they cannot receive texts"
            )

    def add_sms_participant_to_conversation(self, conversation, notification_recipient):
        """ Add a notification recipient as an SMS participant on a Conversation.
            Conversation must be active, and notification recipient must be able to receive texts
            Arguments:
                conversation {Conversation} must be active
                notification_recipient {NotificationRecipient} must have verified phone number, and have texts
                    turned on
            Returns:
                ConversationParticipant with valid twilio participant sid
        """
        self._confirm_recipient_can_recieve_texts(notification_recipient)
        """
            TODO This will fail if notification recipient is already using
            the proxy address for another conversation.
            When we get to implementing counselor conversation types, we'll need to get or
            create a new number for counselors here instead of using conversation.phone_number.phone_number
        """
        twilio_participant = None
        if settings.TEST_TWILIO or not settings.TESTING:
            twilio_participant = self.client.conversations.conversations(
                conversation.conversation_id
            ).participants.create(
                messaging_binding_address=f"+{notification_recipient.phone_number}",
                # TODO: Obtain a new number for counselors
                messaging_binding_proxy_address=conversation.phone_number.phone_number,
            )
        return ConversationParticipant.objects.create(
            conversation=conversation,
            notification_recipient=notification_recipient,
            participant_id=twilio_participant.sid if twilio_participant else TEST_PARTICIPANT_ID,
            phone_number=f"+{notification_recipient.phone_number}",
            proxy_phone_number=conversation.phone_number.phone_number,
        )

    def get_or_create_chat_participant(self, conversation, identifier, notification_recipient=None):
        """ Add a chat participant to a conversation, using identifier.
            If participant with identifier does not yet exist, they will be created. If notification recipient
            is supplied, then it will be associated with ConversationParticipant iff ConversationParticipant is
            being created.
            Arguments:
                conversation {Conversation}
                identifier {string}
                notification_recipient {optional; NotificationRecipient}
            Returns:
                ConversationParticipant
        """
        existing_participant = ConversationParticipant.objects.filter(
            conversation=conversation, chat_identifier=identifier
        ).first()
        if existing_participant:
            if not existing_participant.active:
                existing_participant.active = True
                existing_participant.save()
            return existing_participant
        # Create new conversation recipient
        twilio_participant = None
        if settings.TEST_TWILIO or not settings.TESTING:
            twilio_participant = self.client.conversations.conversations(
                conversation.conversation_id
            ).participants.create(identity=identifier)

        return ConversationParticipant.objects.create(
            conversation=conversation,
            chat_identifier=identifier,
            participant_id=twilio_participant.sid if twilio_participant else TEST_PARTICIPANT_ID,
            notification_recipient=notification_recipient,
        )

    def get_chat_access_token(self, conversation_participant):
        """ Obtain an access token that can be used for web chat, for a conversation participant
            Note that access tokens are valid for 24 hours.
            Docs: https://www.twilio.com/docs/chat/create-tokens
            Arguments:
                conversation_participant {ConversationParticipant}
            Returns:
                Twilio chat access token {string}
        """
        if settings.TESTING and not settings.TEST_TWILIO:
            return TEST_CHAT_TOKEN

        if not (settings.TWILIO_API_SID and settings.TWILIO_API_SECRET):
            raise TwilioException("Missing Twilio API credentails")

        if not conversation_participant.chat_identifier:
            raise TwilioException(
                f"Cannot create chat access token for conversation participant {conversation_participant.pk}"
            )
        token = AccessToken(
            settings.TWILIO_SID,
            settings.TWILIO_API_SID,
            settings.TWILIO_API_SECRET,
            identity=conversation_participant.chat_identifier,
            ttl=86400,
        )
        chat_grant = ChatGrant(service_sid=conversation_participant.conversation.conversation_chat_id)
        token.add_grant(chat_grant)
        return token.to_jwt().decode("ascii")

    def get_or_create_conversation(
        self, conversation_type, student=None, parent=None, counselor=None, cw_phone_number=None, tutor=None
    ):
        """ Get or create a conversation for a student or parent.
            Arguments:
                conversation_type {Conversation.CONVERSATION_TYPES}
                    If conversation of this type for student/parent already exists, we will return it instead
                    of creating a new one.
                    If conversation type TUTOR or COUNSELOR is created, then we will add the student/parent's
                        tutor(s) and counselor, respectively.
                student {Student} either student or parent must be specified. They will be added via SMS
                    to the conversation if they have SMS verified and enabled.
                parent {Parent} ^^
                cw_phone_number {optional; CWPhoneNumber} CWPhoneNumber to use for the conversation (as proxy number)
                    If not provided, then we'll attempt to find the default phone number for the conversation type,
                        provided no participants are already in a conversation with number. If conversation type is counselor
                        and default phone number is already in use in another of the prospective counselor's conversations, then
                        we will find a CWPhoneNumber that isn't already in use by counselor. If
                        no such number exists then one is provisioned
            Returns:
                Conversation

            TODO: Counselor conversation types
        """
        # Validate arguments
        if conversation_type not in [x[0] for x in Conversation.CONVERSATION_TYPES]:
            raise ValueError(f"Invalid conversation type: {conversation_type}")
        if not (
            student
            or parent
            or (conversation_type == Conversation.CONVERSATION_TYPE_COUNSELOR_TUTOR and counselor and tutor)
        ):
            raise ValueError(f"Student or parent, or counselor and tutor must be specified to create Conversation")

        if conversation_type in [
            Conversation.CONVERSATION_TYPE_OTHER,
        ]:
            raise NotImplementedError(f"Unsupported conversation type: {conversation_type}")
        conversation_data = {
            "student": student,
            "parent": parent,
            "counselor": counselor,
            "conversation_type": conversation_type,
            "tutor": tutor,
        }
        existing_conversation = Conversation.objects.filter(**conversation_data).first()
        if existing_conversation:
            return existing_conversation
        # Get or create notification_recipient - just need to ensure they exist
        for user_type in (student, counselor, tutor, parent):
            if user_type:
                NotificationRecipient.objects.get_or_create(user=user_type.user)

        # Ensure we have a CWPhoneNumber to use as proxy for conversation
        if not cw_phone_number:
            if conversation_type == Conversation.CONVERSATION_TYPE_TUTOR:
                cw_phone_number = CWPhoneNumber.objects.get(default_tutor_number=True)
            elif conversation_type == Conversation.CONVERSATION_TYPE_OPERATIONS:
                cw_phone_number = CWPhoneNumber.objects.get(default_operations_number=True)
            elif conversation_type == Conversation.CONVERSATION_TYPE_COUNSELOR:
                cw_phone_number = CWPhoneNumber.objects.get(default_counselor_number=True)

        # Create twilio conversation
        twilio_conversation = None
        if settings.TEST_TWILIO or not settings.TESTING:
            twilio_conversation = self._create_twilio_conversation("CW Conversation")

        # Create our Conversation
        conversation = Conversation.objects.create(
            **conversation_data,
            phone_number=cw_phone_number,
            conversation_id=twilio_conversation.sid if twilio_conversation else TEST_CONVERSATION_ID,
            conversation_chat_id=twilio_conversation.chat_service_sid if twilio_conversation else TEST_CHAT_SERVICE_ID,
        )

        # Create chat participant for the users we know
        if conversation.student:
            notip, _ = NotificationRecipient.objects.get_or_create(user=conversation.student.user)
            self.get_or_create_chat_participant(
                conversation, conversation.student.name, notification_recipient=notip,
            )
        elif conversation.parent:
            notip, _ = NotificationRecipient.objects.get_or_create(user=conversation.parent.user)
            self.get_or_create_chat_participant(
                conversation, conversation.parent.name, notification_recipient=notip,
            )
        elif conversation_type == Conversation.CONVERSATION_TYPE_COUNSELOR_TUTOR:
            notip, _ = NotificationRecipient.objects.get_or_create(user=conversation.counselor.user)
            self.get_or_create_chat_participant(
                conversation, conversation.counselor.name, notification_recipient=notip,
            )
            notip, _ = NotificationRecipient.objects.get_or_create(user=conversation.tutor.user)
            self.get_or_create_chat_participant(
                conversation, conversation.tutor.name, notification_recipient=notip,
            )

        # Chat participants for tutors or counselor
        if conversation.conversation_type == Conversation.CONVERSATION_TYPE_TUTOR and (
            conversation.parent or conversation.student
        ):
            # Add all of student or parent's tutors
            tutors = (
                Tutor.objects.filter(students__parent=conversation.parent)
                if conversation.parent
                else conversation.student.tutors.all()
            )

            for tutor in tutors:
                notip, _ = NotificationRecipient.objects.get_or_create(user=tutor.user)
                self.get_or_create_chat_participant(conversation, tutor.name, notification_recipient=notip)

        if conversation.conversation_type == Conversation.CONVERSATION_TYPE_COUNSELOR:
            if conversation.student and conversation.student.counselor:
                notip, _ = NotificationRecipient.objects.get_or_create(user=conversation.student.counselor.user)
                self.get_or_create_chat_participant(
                    conversation, conversation.student.counselor.name, notification_recipient=notip
                )
            elif conversation.parent:
                counselor = Counselor.objects.filter(students__parent=conversation.parent).first()
                if not counselor:
                    raise ConversationManagerException(f"Error adding counselor to conversation {conversation.pk}")
                notip, _ = NotificationRecipient.objects.get_or_create(user=counselor.user)
                self.get_or_create_chat_participant(conversation, counselor.name, notification_recipient=notip)

        return conversation
