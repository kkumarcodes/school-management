""" Module for managing vcard objects
"""
import vobject
from cwmessages.models import Conversation
from django.conf import settings


class VcardException(Exception):
    pass


def get_vcard(conversation_participant):
    """ Obtain a vcard object for the conversation that conversation participant is in.
        For example, if participant is student in a tutor conversation, vcard will be for
        "Collegewise Tutors".
        Modeled after: https://www.djangosnippets.org/snippets/58/
        Arguments:
          conversation_participant {ConversationParticipant} Must be an SMS participant
        Returns:
          (serialized vcard, card filename (name))
    """
    if not conversation_participant.phone_number:
        raise VcardException("Cannot create vcard for non-SMS participant")
    card = vobject.vCard()
    card.add("n")
    first_name = None
    last_name = None
    email = "support@collegewise.com"
    if (
        conversation_participant.conversation.conversation_type
        == Conversation.CONVERSATION_TYPE_COUNSELOR
        and hasattr(conversation_participant.notification_recipient.user, "student")
    ):
        # Student get's counselor's name
        student = conversation_participant.notification_recipient.user.student
        if student.counselor:
            first_name = student.counselor.user.first_name
            last_name = f"{student.counselor.user.last_name} (Collegewise)"
            email = student.counselor.user.email
        else:
            first_name = "Collegewise"
            last_name = "Counselor"
    elif (
        conversation_participant.conversation.conversation_type
        == Conversation.CONVERSATION_TYPE_COUNSELOR
        and hasattr(conversation_participant.notification_recipient.user, "counselor")
    ):
        # Counselor gets student's name
        first_name = conversation_participant.conversation.student.user.first_name
        last_name = conversation_participant.conversation.student.user.last_name
        email = conversation_participant.conversation.student.user.email
    elif (
        conversation_participant.conversation.conversation_type
        == Conversation.CONVERSATION_TYPE_TUTOR
        and hasattr(conversation_participant.notification_recipient.user, "student")
    ):
        first_name = "Collegewise"
        last_name = "Tutors"

    card.n.value = vobject.vcard.Name(family=last_name, given=first_name)
    card.add("fn")
    card.fn.value = "%s %s" % (first_name, last_name)
    card.add("email")
    card.email.value = email
    card.add("tel")
    card.tel.value = conversation_participant.proxy_phone_number
    card.tel.type_param = "WORK"
    card.add("url")
    card.url.value = settings.SITE_URL
    card.add("photo")
    card.photo.encoding_param = "binary"
    card.photo.type_param = "PNG"
    output = card.serialize()
    return (output, f"{first_name} {last_name}.vcf")
