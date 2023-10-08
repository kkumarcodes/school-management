import random
from django.contrib.postgres.fields.array import ArrayField

from django.db import models
from django.db.models import JSONField
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ObjectDoesNotExist

from sncommon.model_base import SNModel


class NotificationModelManager(models.Manager):
    """
        We override ObjectManager for Notification model so we can hide create(). Use
        notification_manager.NotificationManager.create instead
    """

    def create(self, *args, **kwargs):
        """ We override create so that it can't be called. Replaced with _hidden_create """
        raise NotImplementedError("Cannot directly call Notification.objects.create. Use Notification Generator.")

    def hidden_create(self, *args, **kwargs):
        """ Hide ORM create() """
        return super(NotificationModelManager, self).create(*args, **kwargs)


class Notification(SNModel):
    """  A notification about some action or message in the platform """

    notification_type = models.CharField(max_length=255)
    # Person who created the notification
    actor = models.ForeignKey("auth.user", related_name="+", null=True, blank=True, on_delete=models.SET_NULL)

    # A blank recipient is a system notification. Used to create activity log for system unrelated to specific
    # user(s)
    recipient = models.ForeignKey(
        "snnotifications.NotificationRecipient",
        related_name="notifications",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    # If this notification is just a cc on another
    # Since FK can get set null upon delete
    is_cc = models.BooleanField(default=False)
    cc_on = models.ForeignKey(
        "snnotifications.Notification",
        related_name="cc_notifications",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    # Optional field enable a notification to be cc'd
    cc_email = models.CharField(max_length=255, null=True, blank=True)

    # Copy that appears in notification within platform
    # Subject for email messages or title in platform
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Title and description for how this item will appear in ActivityLog
    activity_log_title = models.CharField(max_length=255, blank=True)
    activity_log_description = models.TextField(blank=True)

    # Used to determine if/when notification is sent
    emailed = models.DateTimeField(null=True, blank=True)
    texted = models.DateTimeField(null=True, blank=True)

    # Can be marked read/unread. Last read is last time was marked read (not unread)
    read = models.BooleanField(default=False)
    last_read = models.DateTimeField(null=True, blank=True)

    # Generic related objects for this notification. Different types of notifications will use these relations
    # in different ways
    related_object_content_type = models.ForeignKey(
        ContentType, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    related_object_pk = models.IntegerField(null=True, blank=True)
    secondary_related_object_content_type = models.ForeignKey(
        ContentType, related_name="+", null=True, blank=True, on_delete=models.SET_NULL
    )
    secondary_related_object_pk = models.IntegerField(null=True, blank=True)

    # In addition, non-database objects may be supplied
    additional_args = JSONField(encoder=DjangoJSONEncoder, default=dict)

    # Custom model manager (hide create)
    objects = NotificationModelManager()

    def __str__(self):
        return f"{self.title} emailed: {self.emailed}  texted: {self.texted}"

    # Properties to assist in getting related objects
    @property
    def related_object(self):
        if self.related_object_content_type and self.related_object_pk:
            try:
                related_object = self.related_object_content_type.get_object_for_this_type(pk=self.related_object_pk)
                return related_object
            except ObjectDoesNotExist:
                # Oh that's okay
                pass
        return None

    @property
    def secondary_related_object(self):
        if self.secondary_related_object_content_type and self.secondary_related_object_pk:
            try:
                related_object = self.secondary_related_object_content_type.get_object_for_this_type(
                    pk=self.secondary_related_object_pk
                )
                return related_object
            except ObjectDoesNotExist:
                # Oh that's okay
                pass
        return None


class NotificationRecipient(SNModel):
    """ Collection of settings pertaining to notifications for a single user """

    user = models.OneToOneField("auth.user", related_name="notification_recipient", on_delete=models.CASCADE)

    # Notification settings
    phone_number = models.CharField(max_length=18, blank=True)
    phone_number_confirmed = models.DateTimeField(null=True, blank=True)
    confirmation_last_sent = models.DateTimeField(null=True, blank=True)
    phone_number_verification_code = models.CharField(max_length=5, blank=True)

    # Killswitch for notification types
    receive_texts = models.BooleanField(default=True)
    receive_emails = models.BooleanField(default=True)

    # Arrays of notification types that user is UNSUBSCRIBED from
    unsubscribed_email_notifications = JSONField(encoder=DjangoJSONEncoder, default=list)
    unsubscribed_text_notifications = JSONField(encoder=DjangoJSONEncoder, default=list)

    """ Incoming FK """
    # participants > many ConversationParticipant

    def __str__(self):
        return f"Notification Recipient for {self.user.get_full_name()}"

    def set_new_verification_code(self):
        """ Sets a new verification code (self.verification_code) """
        self.phone_number_verification_code = "".join([str(random.randint(1, 9)) for x in range(5)])
        self.phone_number_confirmed = None
        self.save()
        return self


class Bulletin(SNModel):
    """ A bulletin is an announcement created by an admin or counselors for some users on UMS.
        Bulletins can be made visible to students, parents, tutors, and/or counselors.
        Within the platform, these are also called "Announcements"
    """

    created_by = models.ForeignKey("auth.user", related_name="created_bulletins", on_delete=models.CASCADE)
    title = models.CharField(max_length=255, blank=True)
    content = models.TextField(blank=True)  # HTML via Quill
    # Making this False makes the bulletin invisible to everyone except admins/its creator
    visible = models.BooleanField(default=True)
    pinned = models.BooleanField(default=False)
    # Pinned notes can be sorted
    priority = models.IntegerField(default=0)
    visible_to_notification_recipients = models.ManyToManyField(
        "snnotifications.NotificationRecipient", related_name="bulletins", blank=True
    )
    # Notification Recipients that have read announcement by opening it within schoolnet
    read_notification_recipients = models.ManyToManyField(
        "snnotifications.NotificationRecipient", related_name="read_bulletins", blank=True
    )

    # Whether or not notification was sent when Bulletin was created
    send_notification = models.BooleanField(default=True)

    # These were the settings used to filter which people were sent the bulletin when it was created.
    # visible_to_notification_recipients can be changed after creation, so these fields are for auditability
    # and are NOT meant to represent which user(s) can see the bulletin
    class_years = ArrayField(models.IntegerField(blank=True, null=True), default=list, blank=True)
    counseling_student_types = ArrayField(models.CharField(max_length=255, default=""), default=list, blank=True)

    all_class_years = models.BooleanField(default=False)
    all_counseling_student_types = models.BooleanField(default=False)

    # Whether or not students and parents on tutoring platform get bulletin
    cas = models.BooleanField(default=False)
    # Whether or not students and parents on counseling platform get bulletin
    cap = models.BooleanField(default=False)
    students = models.BooleanField(default=True)
    parents = models.BooleanField(default=True)
    counselors = models.BooleanField(default=False)
    tutors = models.BooleanField(default=False)

    # Evergreen announcements become visible to new students and parents who meeting the criteria of the announcement
    # as long as they are created before the announcement's expiration
    evergreen = models.BooleanField(default=False)
    evergreen_expiration = models.DateTimeField(null=True, blank=True)

    tags = ArrayField(models.TextField(default=""), blank=True, default=list)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return self.title
