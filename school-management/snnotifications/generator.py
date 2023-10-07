"""
    This module creates notifications. This is the only place that Notification
    objects are created.
    Creating a notification here will:
        - Figure out if the notification needs to be emailed or texted to a user,
            and email or text it to the user.
        - Figure out who needs to be cc'd on the notification, and cc them (i.e. create
            derivative Notification objects)
        - Set the title (subject) and description
"""
import pytz
from django.conf import settings
from snnotifications.constants import notification_types
from snnotifications.models import Notification, NotificationModelManager, NotificationRecipient
from snnotifications.activity_log_descriptions import ACTIVITY_LOG_DESCRIPTION_FUNCTIONS, ACTIVITY_LOG_TITLE_FUNCTIONS
from snnotifications.constants.constants import get_notification_config, SYSTEM_NOTIFICATIONS
from snnotifications.mailer import send_email_for_notification
from sncommon.utilities.twilio import TwilioManager
from snusers.models import get_cw_user

# Functions that return (title) email subject, given notification key
# Oh hey - while you're here: If users need to be able to turn off a notification, make sure you add it to
# UNSUBSCRIBABLE_NOTIFICATIONS in constants


def title_generator_unread_messages(notification):
    """ Helper function for title/subject for unread messages. Depends on both recipient and participant """
    display_name = notification.related_object.conversation_with_name

    if not display_name:
        raise ValueError(f"Unable to determine title for notification {notification.pk}")
    return f"[UMS] New messages in your conversation with {display_name}"


TITLE_GENERATORS = {
    "invite": lambda x: f"Create your account on {settings.SITE_NAME}!",
    "invite_reminder": lambda x: f"Reminder: Create your account on {settings.SITE_NAME}!",
    "task": lambda x: f"Task: {x.related_object.title}",
    "cas_magento_student_created": lambda x: f"New student created: {x.related_object.name}",
    "cap_magento_student_created": lambda x: f"New student in UMS: {x.related_object.name}",
    "user_accepted_invite": lambda x: f"{x.related_object.get_full_name()} has accepted their invite to UMS",
    "diagnostic_result": lambda x: f"{x.related_object.student.user.get_full_name()}'s {x.related_object.diagnostic.title} has been submitted",
    "diagnostic_result_pending_return": lambda x: f"{x.related_object.student.user.get_full_name()}'s {x.related_object.diagnostic.title} evaluation is pending return",
    "task_diagnostic": lambda x: f"Task: Complete {x.related_object.title} diagnostic",
    "task_complete": lambda x: f"{x.related_object.for_user.get_full_name()}'s {x.related_object.title} is now Complete",
    "student_self_assigned_diagnostic": lambda x: f"Self Assigned Diagnostic: {x.related_object.for_user.get_full_name()} self-assigned {x.related_object.title} diagnostic",
    "individual_tutoring_session_tutor": lambda x: f"{x.related_object.student.name} has scheduled an individual tutoring session",
    "tutoring_session_notes": lambda x: f"Notes complete on tutoring session: {x.related_object.group_tutoring_session.title if x.related_object.group_tutoring_session else x.related_object.individual_session_tutor.name} on {x.related_object.start.strftime('%b %d')}",
    "student_tutoring_session_confirmation": lambda x: f"Confirmed: Tutoring session",
    "student_tutoring_session_cancelled": lambda x: f"Cancelled tutoring session: {x.related_object.group_tutoring_session.title if x.related_object.group_tutoring_session else x.related_object.individual_session_tutor.name} on {x.related_object.start.strftime('%b %d')}",
    "tutor_tutoring_session_cancelled": lambda x: f"Cancelled tutoring session: {x.related_object.group_tutoring_session.title if x.related_object.group_tutoring_session else x.related_object.student.name} on {x.related_object.start.strftime('%b %d')}",
    "student_tutoring_session_rescheduled": lambda x: f"Rescheduled tutoring session: {x.related_object.group_tutoring_session.title if x.related_object.group_tutoring_session else x.related_object.individual_session_tutor.name}",
    "tutor_daily_digest": lambda x: f"Daily Tutoring Digest",
    "tutor_tutoring_session_rescheduled": lambda x: f"Rescheduled tutoring session: {x.related_object.group_tutoring_session.title if x.related_object.group_tutoring_session else x.related_object.student.name}",
    "tutor_tutoring_session_reminder": lambda x: f"Reminder: Tutoring session with {x.related_object.student.name} - {x.related_object.start.astimezone(pytz.timezone(x.related_object.individual_session_tutor.timezone)).strftime('%b %d %-I:%M%p')}",
    "tutor_gts_reminder": lambda x: f"Reminder: Group tutoring session ({x.related_object.title}) - {x.related_object.start.astimezone(pytz.timezone(x.recipient.user.tutor.timezone)).strftime('%b %d')}",
    "group_tutoring_session_cancelled": lambda x: f"Cancelled tutoring session: {x.related_object.title}",
    "task_digest": lambda x: f"New Task{'s' if len(x.additional_args) > 1 else ''}: {len(x.additional_args)} new task{'s' if len(x.additional_args) > 1 else ''} has been assigned to you in UMS",
    "student_tutoring_session_reminder": lambda x: f"Reminder: Tutoring session - {x.related_object.start.astimezone(pytz.timezone(x.related_object.student.timezone)).strftime('%b %d')}",
    "package_purchase_confirmation": lambda x: f"Confirmed: Collegewise tutoring package {x.related_object.tutoring_package.title}",
    "student_diagnostic_result": lambda x: f"Your {x.related_object.diagnostic.title} diagnostic has been reviewed",
    "counselor_diagnostic_result": lambda x: f"{x.related_object.student.name}'s {x.related_object.diagnostic.title} diagnostic has been reviewed",
    "diagnostic_score_required": lambda x: f"{x.related_object.student.name}'s {x.related_object.diagnostic.title} diagnostic needs to be scored",
    "diagnostic_recommendation_required": lambda x: f"{x.related_object.student.name}'s {x.related_object.diagnostic.title} diagnostic is scored and requires recommendation",
    "student_student_low_on_hours": lambda x: f"[UMS] Running low on hours",
    "tutor_altered_availability": lambda x: f"{x.related_object.name} altered their availability for the week of {x.additional_args['start_date'].strftime('%b %d')}",
    "course_enrollment_confirmation": lambda x: f"{x.related_object.name} course enrollment confirmed",
    "course_unenrollment_confirmation": lambda x: f"Unenrolled from course {x.related_object.name}",
    "tutor_time_card": lambda x: f"New time card created ({x.related_object.start.strftime('%m/%d/%Y')} - {x.related_object.end.strftime('%m/%d/%Y')})",
    "student_counselor_meeting_confirmed": lambda x: f"Meeting scheduled with {x.related_object.student.counselor.name} on {x.related_object.start.astimezone(pytz.timezone(x.related_object.student.timezone)).strftime('%b %d')}",
    "counselor_counselor_meeting_confirmed": lambda x: f"Meeting scheduled with {x.related_object.student.name} on {x.related_object.start.astimezone(pytz.timezone(x.related_object.student.timezone)).strftime('%b %d')}",
    "student_counselor_meeting_rescheduled": lambda x: f"Meeting scheduled with {x.related_object.student.counselor.name} rescheduled to {x.related_object.start.astimezone(pytz.timezone(x.related_object.student.timezone)).strftime('%b %d')}",
    "counselor_counselor_meeting_rescheduled": lambda x: f"Meeting scheduled with {x.related_object.student.name} rescheduled to {x.related_object.start.astimezone(pytz.timezone(x.related_object.student.timezone)).strftime('%b %d')}",
    "student_counselor_meeting_cancelled": lambda x: f"Cancelled: Meeting with {x.related_object.student.counselor.name} on {x.related_object.start.astimezone(pytz.timezone(x.related_object.student.timezone)).strftime('%b %d')}",
    "student_counselor_session_reminder": lambda x: f"Reminder: Meeting scheduled with {x.related_object.student.counselor.name} on {x.related_object.start.astimezone(pytz.timezone(x.related_object.student.timezone)).strftime('%b %d')}",
    "counselor_counselor_session_reminder": lambda x: f"Reminder: Meeting scheduled with {x.related_object.student.name} on {x.related_object.start.astimezone(pytz.timezone(x.related_object.student.timezone)).strftime('%b %d')}",
    "counselor_weekly_digest": lambda x: f"Counselor Weekly Digest",
    "ops_upcoming_course": lambda x: f"Upcoming Course: {x.related_object.verbose_name}",
    "first_individual_tutoring_session_daily_digest": lambda x: f"Individual Tutoring Session Report",
    "unread_messages": title_generator_unread_messages,
    "student_diagnostic_registration": lambda x: "Comfirmed: Diagnostic Registration",
    "ops_student_diagnostic_registration": lambda x: f"Diagnostic Registration: {x.related_object}",
    "recommend_diagnostic": lambda x: f"You have been assigned a diagnostic to evaluate",
    "score_diagnostic": lambda x: f"You have been assigned a diagnostic to score",
    "ops_failed_charge": lambda x: "Failed credit card charge attempt",
    "diagnostic_invite": lambda x: "You have been invited to take a diagnostic with Collegewise",
    "ops_magento_webhook": lambda x: f"Incoming webhook from Magento",
    "ops_magento_webhook_failure": lambda x: f"Incoming webhook from Magento FAILED",
    "registration_success": lambda x: "Confirmed: Successful registration",
    "ops_paygo_payment_success": lambda x: f"Automatic paygo payment successful for {x.related_object.student}'s session: {x.related_object.title_for_student}",
    "ops_paygo_payment_failure": lambda x: f"Automatic paygo payment failed for {x.related_object.student}'s session: {x.related_object.title_for_student}",
    "last_meeting": lambda x: f"{len(x.additional_args['students'])} students have their last session in the next week"
    if len(x.additional_args["students"]) != 1
    else f"1 student has their last session on {x.additional_args['date']}",
    "counselor_file_upload": lambda x: f"New file upload ({x.related_object.title}) for your student {x.related_object.counseling_student}",
    "counselor_meeting_message": lambda x: x.related_object.notes_message_subject
    if x.related_object.notes_message_subject
    else f"{x.related_object.student.counselor.user.first_name} has added notes from your meeting ({x.related_object.title})",
    notification_types.BULLETIN: lambda x: f"[Collegewise] {x.related_object.title}",
    notification_types.COUNSELOR_TASK_DIGEST: lambda x: f"UMS Digest: Upcoming and Overdue Student Tasks ({len(x.additional_args)})",
    notification_types.STUDENT_TASK_REMINDER: lambda x: f"Overdue and Upcoming tasks in UMS",
    notification_types.COUNSELOR_FORWARD_STUDENT_MESSAGE: lambda x: f"New message from {x.additional_args['author']}",
    notification_types.COUNSELOR_COMPLETED_TASKS: lambda x: f"UMS Digest: Recently completed tasks ({len(x.additional_args)})",
    notification_types.INDIVIDUAL_TASK_REMINDER: lambda x: f"Task Reminder: {x.related_object.title}",
}


def create_notification(user, **kwargs):
    """
        Oh man this is exciting. This is the sole function responsible for creating all notifications. Notifications
        are created and then - if recipient is subscribed - they are even sent. This cute little function also handles
        cc'ing other recipients on this notification (by creating more notifications).
        All in this cute little function.

        But sometimes, this function has to follow rules. Regulation messes everything up, man. Even Prompt. Those
        executive types and users sure like to impose lots of complexities that ruin this little function's fun. So
        sometimes, this little function has to exercise self-control, and it is prohibited from creating certain
        notifications for certain users. It doesn't return a Notification when that happens. It returns None.

        Arguments:
            user: User notification is for (NotificationRecipient will be created if doesn't exist)
                USER CAN BE NONE. If it is then it's assumed we're creating a system notification
            kwargs: Should map to fields on Notification (actual keyword args not dict)
    """
    # pylint: disable=unused-variable
    if user:
        (notification_recipient, created_recipient,) = NotificationRecipient.objects.get_or_create(user=user)
        notification: Notification = Notification.objects.hidden_create(recipient=notification_recipient, **kwargs)
    elif kwargs.get("notification_type") not in SYSTEM_NOTIFICATIONS:
        raise ValueError(f"Recipient required for notification of type {kwargs.get('notification_type')}")
    else:
        notification: Notification = Notification.objects.hidden_create(**kwargs)

    if notification.notification_type not in TITLE_GENERATORS:
        raise ValueError(f"Notification {notification.notification_type} has no title generator")

    notification.title = TITLE_GENERATORS[notification.notification_type](notification)
    # Add deets for activity log
    if notification.notification_type in ACTIVITY_LOG_TITLE_FUNCTIONS:
        notification.activity_log_title = ACTIVITY_LOG_TITLE_FUNCTIONS[notification.notification_type](notification)
    if notification.notification_type in ACTIVITY_LOG_DESCRIPTION_FUNCTIONS:
        notification.activity_log_description = ACTIVITY_LOG_DESCRIPTION_FUNCTIONS[notification.notification_type](
            notification
        )
    notification.save()

    if not notification.recipient:
        return notification

    # Determine whether or not notification needs to be emailed
    if (
        notification.notification_type not in notification.recipient.unsubscribed_email_notifications
        and notification.recipient.receive_emails
    ):
        send_email_for_notification(notification)

    elif get_notification_config(notification.notification_type).get("cc_parent"):
        cw_user = get_cw_user(notification.recipient.user)
        if cw_user.user_type == "student" and cw_user.parent:
            # There is a parent who would be cc'd, but student has unsubscribed. So we create separate
            # notification for parent
            create_notification(cw_user.parent.user, **kwargs)

    # Determine whether or not notification needs to be texted
    if (
        get_notification_config(notification.notification_type).get("default_text")
        and notification.notification_type not in notification.recipient.unsubscribed_text_notifications
    ):
        mgr = TwilioManager()
        mgr.send_message_for_notification(notification)

    # Refresh to make sure we have updated emailed/texted field
    notification.refresh_from_db()
    return notification
