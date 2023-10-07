from django.contrib.auth.models import User
from rest_framework import serializers
from django.db.models import Func, F

from sncommon.serializers.base import AdminCounselorModelSerializer, AdminModelSerializer
from sncommon.serializers.file_upload import UpdateFileUploadsSerializer
from snnotifications.models import Bulletin, NotificationRecipient, Notification
from snnotifications.constants.constants import UNSUBSCRIBABLE_NOTIFICATIONS
from snmessages.models import ConversationParticipant


from snusers.models import Parent, Student, get_cw_user

CAP_STUDENT = "cap_student"
CAS_STUDENT = "cas_student"


class NotificationRecipientSerializer(AdminModelSerializer):
    """ Serializer for - you guessed it - NotificationRecipient objects """

    # We just return whether or not phone number is confirmed, but not when. READ ONLY
    phone_number_is_confirmed = serializers.SerializerMethodField()
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    # Number of conversations with unread messages
    unread_conversations = serializers.SerializerMethodField()

    # A list of notifications that user can unsubscribe from
    unsubscribable_notifications = serializers.SerializerMethodField()

    class Meta:
        model = NotificationRecipient
        admin_fields = ("phone_number_confirmed", "confirmation_last_sent")
        fields = (
            "pk",
            "slug",
            "phone_number",
            "phone_number_is_confirmed",
            "receive_texts",
            "receive_emails",
            "unsubscribed_email_notifications",
            "unsubscribed_text_notifications",
            "unsubscribable_notifications",
            "user",
            "unread_conversations",
        ) + admin_fields

    def get_phone_number_is_confirmed(self, obj):
        return bool(obj.phone_number_confirmed)

    def get_unread_conversations(self, obj):
        participants = ConversationParticipant.objects.filter(
            notification_recipient=obj, conversation__last_message__isnull=False
        ).annotate(duration=Func(F("last_read"), F("conversation__last_message"), function="age"))
        return len(
            [x for x in participants if hasattr(x, "duration") and x.duration and x.duration.total_seconds() < 0]
        )

    def get_unsubscribable_notifications(self, obj):
        cw_user = get_cw_user(obj.user)
        if not cw_user:
            return []
        if isinstance(cw_user, Student):
            # We separate CAS and CAP notifications
            notis = []
            if cw_user.is_cap:
                notis += UNSUBSCRIBABLE_NOTIFICATIONS[CAP_STUDENT]
            if cw_user.is_cas:
                notis += UNSUBSCRIBABLE_NOTIFICATIONS[CAS_STUDENT]
            return list(set(notis))

        return (
            UNSUBSCRIBABLE_NOTIFICATIONS[cw_user.user_type] if cw_user.user_type in UNSUBSCRIBABLE_NOTIFICATIONS else []
        )


class NotificationSerializer(serializers.ModelSerializer):
    """ Serializes a notification (surprise). Primarily used to display activity log
    """

    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = read_only_fields = (
            "created",
            "slug",
            "notification_type",
            "actor",
            "actor_name",
            "recipient",
            "title",
            "description",
            "activity_log_title",
            "activity_log_description",
            "emailed",
            "texted",
            "related_object_pk",
        )

    def get_actor_name(self, obj: Notification):
        return obj.actor.get_full_name() if obj.actor else ""


class BulletinSerializer(UpdateFileUploadsSerializer, AdminCounselorModelSerializer):
    # Used by UpdateFileUploadsSerializer
    related_name_field = "bulletin"

    visible_to_notification_recipients = serializers.PrimaryKeyRelatedField(
        many=True, queryset=NotificationRecipient.objects.all(), required=False
    )
    created_by = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    admin_announcement = serializers.BooleanField(read_only=True, source="created_by.administrator")

    # The names of students and parents who have read announcement
    read_student_names = serializers.SerializerMethodField()
    read_parent_names = serializers.SerializerMethodField()

    class Meta:
        model = Bulletin
        read_only_fields = ("pk", "slug", "created")
        admin_counselor_fields = (
            "send_notification",
            "class_years",
            "counseling_student_types",
            "students",
            "parents",
            "all_class_years",
            "all_counseling_student_types",
            "evergreen",
            "evergreen_expiration",
            "cap",
            "cas",
            "read_student_names",
            "read_parent_names",
        )
        fields = (
            "pk",
            "created",
            "slug",
            "title",
            "content",
            "pinned",
            "priority",
            "visible_to_notification_recipients",
            "send_notification",
            "class_years",
            "counseling_student_types",
            "students",
            "parents",
            "counselors",
            "tutors",
            "created_by",
            "cap",
            "cas",
            "admin_announcement",
            "all_class_years",
            "all_counseling_student_types",
            "evergreen",
            "evergreen_expiration",
            "read_student_names",
            "read_parent_names",
            "visible_to_notification_recipients",
            "file_uploads",
            "update_file_uploads",
            "tags",
        )

    def get_read_student_names(self, obj: Bulletin):
        return (
            Student.objects.filter(user__notification_recipient__read_bulletins=obj)
            .order_by("invitation_name")
            .distinct()
            .values_list("invitation_name", flat=True)
        )

    def get_read_parent_names(self, obj: Bulletin):
        return (
            Parent.objects.filter(user__notification_recipient__read_bulletins=obj)
            .order_by("invitation_name")
            .distinct()
            .values_list("invitation_name", flat=True)
        )
