from django.db import models
from cwcommon.model_base import CWModel
from cwusers.models import Counselor, Tutor, get_cw_user


class CWPhoneNumber(CWModel):
    """ A phone number we own in Twilio and can use as a proxy number for conversations """

    active = models.BooleanField(default=True)  # Whether or not we currently hold this number
    phone_number = models.CharField(max_length=18)  # The number, prepended with '+' and country code
    default_tutor_number = models.BooleanField(default=False)  # Default number for student-tutor Conversations
    default_counselor_number = models.BooleanField(default=False)  # Default number for student-counselor Conversations
    default_operations_number = models.BooleanField(default=False)  # Default number for student-tutor Conversations

    def __str__(self):
        return self.phone_number


class Conversation(CWModel):
    """ Our representation of a Twilio Conversation object
        Note that the combination of conversation type, student, parent, and counselor
        uniquely identify a conversation (or potential conversation)
        This is often the set of data we'll get from the frontend (see ConversationSpecification)
        to specify a conversation
    """

    CONVERSATION_TYPE_COUNSELOR = "co"
    CONVERSATION_TYPE_TUTOR = "tu"
    CONVERSATION_TYPE_OPERATIONS = "op"
    CONVERSATION_TYPE_OTHER = "ot"
    CONVERSATION_TYPE_COUNSELOR_TUTOR = "ct"
    CONVERSATION_TYPES = (
        (CONVERSATION_TYPE_COUNSELOR, "Counselor"),
        (CONVERSATION_TYPE_TUTOR, "Tutor"),
        (CONVERSATION_TYPE_OPERATIONS, "Operations"),
        (CONVERSATION_TYPE_COUNSELOR_TUTOR, "Counselor-Tutor"),
        (CONVERSATION_TYPE_OTHER, "Other"),
    )
    active = models.BooleanField(default=True)
    # The CW phone number associated with conversation. If null, then conversation solely exists
    # on web chat
    phone_number = models.ForeignKey(
        "cwmessages.CWPhoneNumber", related_name="conversations", null=True, blank=True, on_delete=models.SET_NULL,
    )
    student = models.ForeignKey(
        "cwusers.Student", related_name="conversations", on_delete=models.SET_NULL, null=True, blank=True,
    )
    parent = models.ForeignKey(
        "cwusers.Parent", related_name="conversations", on_delete=models.SET_NULL, null=True, blank=True,
    )
    counselor = models.ForeignKey(
        "cwusers.Counselor", related_name="conversations", on_delete=models.SET_NULL, null=True, blank=True,
    )
    tutor = models.ForeignKey(
        "cwusers.Tutor", related_name="conversations", on_delete=models.SET_NULL, null=True, blank=True
    )
    conversation_type = models.CharField(max_length=2, default=CONVERSATION_TYPE_OTHER, choices=CONVERSATION_TYPES)
    conversation_id = models.CharField(max_length=255)  # SID of Twilio Conversation obj
    conversation_chat_id = models.CharField(max_length=255)  # Chat service ID of Twilio Conversation obj

    # Last time messages were sent to this conversation
    last_message = models.DateTimeField(null=True, blank=True)

    """ Incoming FK """
    # participants > many ConversationParticipant

    @property
    def conversation_type_description(self):
        return list(filter(lambda x: x[0] == self.conversation_type, Conversation.CONVERSATION_TYPES,))[0][1]

    def __str__(self):
        return f"{self.conversation_type_description} conversation"


class ConversationParticipant(CWModel):
    """ Our representation of a Twilio Participant object """

    conversation = models.ForeignKey("cwmessages.Conversation", related_name="participants", on_delete=models.CASCADE,)
    # Can be null if ConversationParticipant is shared amongst multiple users,
    # for example the ops team. CANNOT BE NULL FOR SMS PARTICIPANTS
    notification_recipient = models.ForeignKey(
        "cwnotifications.NotificationRecipient",
        related_name="participants",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    active = models.BooleanField(default=True)  # If False, then participant has been removed from conversation
    deactivated = models.DateTimeField(null=True, blank=True)  # When participant was removed from conversation
    participant_id = models.CharField(max_length=255)  # SID of Twilio Participant obj
    # If participant is SMS participant, this is phone number they're sending FROM.
    # Prepended by '+' and country code
    phone_number = models.CharField(max_length=18, blank=True)
    chat_identifier = models.CharField(
        max_length=255, blank=True
    )  # If participant is chat participant, this is the chat identifier they're using
    # SMS participants can use a different proxy phone number than the number associated with the conversation
    proxy_phone_number = models.CharField(max_length=18, blank=True)

    last_read = models.DateTimeField(auto_now_add=True, blank=True)
    last_unread_message_notification = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.notification_recipient.user.get_full_name()} in conversation {self.conversation}"

    @property
    def conversation_with_name(self):
        """ Human readable name for the person that this participant sees as the other end of this conversation
            (i.e. for a student in a counselor conversation, this returns the counselor's name)
        """
        cwuser = get_cw_user(self.notification_recipient.user)
        conversation: Conversation = self.conversation
        display_name = ""

        # Tutor or counselor viewing conversation with student or parent
        if (isinstance(cwuser, Tutor) and conversation.conversation_type == conversation.CONVERSATION_TYPE_TUTOR) or (
            isinstance(cwuser, Counselor) and conversation.conversation_type == conversation.CONVERSATION_TYPE_COUNSELOR
        ):
            display_name = (
                f"student {conversation.student.name}" if conversation.student else f"parent {conversation.parent.name}"
            )
        elif conversation.conversation_type == Conversation.CONVERSATION_TYPE_COUNSELOR:
            display_name = (
                conversation.student.counselor.name
                if (conversation.student and conversation.student.counselor)
                else "Collegewise Counselor"
            )
        elif conversation.conversation_type == Conversation.CONVERSATION_TYPE_TUTOR:
            display_name = (
                conversation.student.tutors.first().name
                if (conversation.student and conversation.student.tutors.count() == 1)
                else "Collegewise Tutors"
            )
        elif conversation.conversation_type == Conversation.CONVERSATION_TYPE_COUNSELOR_TUTOR:
            if isinstance(cwuser, Tutor):
                return conversation.counselor.name if conversation.counselor else "Collegewise Counselor"
            return conversation.tutor.name if conversation.tutor else "Collegewise Tutor"
        return display_name
