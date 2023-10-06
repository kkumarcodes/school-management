from rest_framework import serializers

from cwmessages.models import Conversation, ConversationParticipant
from cwnotifications.models import NotificationRecipient


class ConversationParticipantSerializer(serializers.ModelSerializer):
    """ This serializer is READ ONLY
    """

    notification_recipient = serializers.PrimaryKeyRelatedField(queryset=NotificationRecipient.objects.all())
    conversation = serializers.PrimaryKeyRelatedField(queryset=Conversation.objects.all())
    conversation_title = serializers.SerializerMethodField()
    conversation_type = serializers.CharField(source="conversation.conversation_type", read_only=True)

    conversation_student = serializers.IntegerField(source="conversation.student.pk", read_only=True)
    conversation_parent = serializers.IntegerField(source="conversation.parent.pk", read_only=True)
    conversation_tutor = serializers.IntegerField(source="conversation.tutor.pk", read_only=True)
    conversation_counselor = serializers.IntegerField(source="conversation.counselor.pk", read_only=True)

    display_name = serializers.SerializerMethodField()

    has_unread_messages = serializers.SerializerMethodField()

    class Meta:
        model = ConversationParticipant
        read_only_fields = fields = (
            "pk",
            "slug",
            "conversation",
            "conversation_title",
            "conversation_type",
            "conversation_student",
            "conversation_counselor",
            "conversation_tutor",
            "active",
            "conversation_parent",
            "notification_recipient",
            "participant_id",
            "phone_number",
            "chat_identifier",
            "display_name",
            "proxy_phone_number",
            "has_unread_messages",
        )

    def get_conversation_title(self, obj):
        """ Human-Readable type of chat """
        return f"{obj.conversation.conversation_type_description} chat"

    def get_display_name(self, obj):
        if obj.notification_recipient:
            return obj.notification_recipient.user.get_full_name()
        return obj.chat_identifier

    def get_has_unread_messages(self, obj: ConversationParticipant):
        if not (obj.last_read and obj.conversation.last_message):
            return False
        return obj.last_read < obj.conversation.last_message


class ConversationSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    # This is the phone number (does not exist for all conversations)
    proxy_phone_number = serializers.SerializerMethodField()
    participants = ConversationParticipantSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = (
            "pk",
            "title",
            "conversation_type",
            "student",
            "parent",
            "conversation_chat_id",
            "conversation_id",
            "active",
            "slug",
            "proxy_phone_number",
            "participants",
        )

    def get_title(self, obj):
        """ Human-Readable type of chat """
        return f"{obj.conversation_type_description} chat"

    def get_proxy_phone_number(self, obj: Conversation):
        if obj.phone_number:
            return obj.phone_number.phone_number
        return ""
