"""
    All of the different types of notifications. Each notification entry is a diction with
        key
        default_email: Boolean indicating whether or not users get emails for this notification
            by default (i.e. they must explicitly unsubscribe)
        can_unsubscribe_email: Boolean indicating whether or not users can unsubscribe from
            this notification type
        default_text: Boolean indicating whether or not users get texts for this notification
            by default (i.e. they must explicitly unsubscribe)
        can_unsubscribe_text: Boolean indicating whether or not users can unsubscribe from
            this notification type (text)
        cc_parent: Boolean indicating whether or not parent should be cc'd on notifications
            to student for given notification type

        Any key (with boolean val) that is omitted will be assumed to be False
"""

# Notifications that don't need a recipient
from cwnotifications.constants import notification_types


SYSTEM_NOTIFICATIONS = [
    "ops_paygo_payment_success",
    "ops_paygo_payment_failure",
    "ops_magento_webhook",
    "ops_magento_webhook_failure",
]

# Notifications
UNSUBSCRIBABLE_NOTIFICATIONS = {
    "tutor": [
        "task_complete",
        "individual_tutoring_session_tutor",
        "tutor_tutoring_session_cancelled",
        "tutor_tutoring_session_rescheduled",
        "tutor_tutoring_session_reminder",
        "group_tutoring_session_cancelled",
        "tutor_daily_digest",
    ],
    "cas_student": [
        "tutoring_session_notes",
        "student_task_reminder",
        "task_digest",
        "student_diagnostic_result",
        "student_tutoring_session_reminder",
        "student_tutoring_session_cancelled",
        "student_tutoring_session_rescheduled",
        "group_tutoring_session_cancelled",
    ],
    "cap_student": [
        "student_task_reminder",
        "task_digest",
        "student_counselor_meeting_confirmed",
        "student_counselor_meeting_rescheduled",
        "student_counselor_meeting_cancelled",
        "student_counselor_session_reminder",
        "student_diagnostic_result",
    ],
    "administrator": [
        "diagnostic_result",
        "diagnostic_score_required",
        "diagnostic_recommendation_required",
        "tutor_altered_availability",
        "first_individual_tutoring_session_daily_digest",
        "student_self_assigned_diagnostic",
        "ops_student_diagnostic_registration",
        "ops_failed_charge",
        "ops_magento_webhook",
        "ops_magento_webhook_failure",
        "ops_paygo_payment_success",
        "ops_paygo_payment_failure",
        "last_meeting",
        "ops_upcoming_course",
        "cas_magento_student_created",
        "cap_magento_student_created",
    ],
    "counselor": [
        "counselor_diagnostic_result",
        "task_complete",
        "counselor_file_upload",
        "counselor_weekly_digest",
        "counselor_task_digest",
        # notification_types.COUNSELOR_FORWARD_STUDENT_MESSAGE,
        "counselor_completed_tasks",
    ],
}

NOTIFICATION_TYPES = {
    "invite": {"default_email": True, "can_unsubscribe_email": False, "default_text": False, "cc_parent": False,},
    "task_diagnostic": {
        "default_email": True,
        "can_unsubscribe_email": False,
        "default_text": False,
        "cc_parent": True,
    },
    "task": {"default_email": False, "default_text": False, "can_unsubscribe_email": False, "cc_parent": False},
    notification_types.STUDENT_TASK_REMINDER: {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": False,
        "can_unsubscribe_email": True,
        "cc_parent": True,
    },
    "student_diagnostic_result": {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": True,
        "can_unsubscribe_email": True,
        "cc_parent": True,
    },
    "student_tutoring_session_confirmed": {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": True,
        "can_unsubscribe_email": True,
        "cc_parent": True,
    },
    "student_tutoring_session_reminder": {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": True,
        "can_unsubscribe_email": True,
        "cc_parent": True,
    },
    "student_tutoring_session_cancelled": {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": True,
        "can_unsubscribe_email": True,
        "cc_parent": True,
    },
    "student_tutoring_session_rescheduled": {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": True,
        "can_unsubscribe_email": True,
        "cc_parent": True,
    },
    "tutoring_session_notes": {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": True,
        "can_unsubscribe_email": True,
        "cc_parent": False,
    },
    "unread_messages": {
        "default_email": True,
        "can_unsubscribe_email": True,
        "default_text": False,
        "can_unsubscribe_text": True,
        "cc_parent": False,
    },
    "student_counselor_meeting_confirmed": {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": True,
        "can_unsubscribe_email": True,
        "cc_parent": True,
    },
    "student_counselor_session_reminder": {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": True,
        "can_unsubscribe_email": True,
        "cc_parent": True,
    },
    "student_counselor_meeting_cancelled": {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": True,
        "can_unsubscribe_email": True,
        "cc_parent": True,
    },
    "student_counselor_meeting_rescheduled": {
        "default_email": True,
        "default_text": True,
        "can_unsubscribe_text": True,
        "can_unsubscribe_email": True,
        "cc_parent": True,
    },
    "counselor_meeting_message": {
        "default_email": True,
        "can_unsubscribe_email": False,
        "default_text": False,
        "can_unsubscribe_text": True,
        "cc_parent": False,
    },
    notification_types.COUNSELOR_FORWARD_STUDENT_MESSAGE: {
        "default_email": False,
        "can_unsubscribe_email": False,
        "default_text": True,
        "can_unsubscribe_text": True,
    },
    notification_types.INDIVIDUAL_TASK_REMINDER: {
        "default_email": True,
        "can_unsubscribe_email": False,
        "default_text": True,
        "can_unsubscribe_text": False,
        "cc_parent": False,
    },
    "last_meeting": {"default_email": True, "can_unsubscribe_email": True},
}

# Only the following notifications get sent to users that have not accepted their invite yet
NOTIFICATIONS_FOR_PENDING_USERS = [
    "invite",
    "invite_reminder",
    "student_tutoring_session_confirmation",
    "student_tutoring_session_cancelled",
    "student_tutoring_session_rescheduled",
    "tutoring_session_notes",
    "student_tutoring_session_reminder",
    "student_diagnostic_registration",
    "student_diagnostic_result",
    "diagnostic_invite",
    "task_diagnostic",
    "counselor_meeting_message",
]

# For notifications that don't have overriding settings in NOTIFICATION_TYPES
DEFAULT = {
    "default_email": True,
    "can_unsubscribe_email": True,
    "default_text": False,
    "can_unsubscribe_text": True,
    "cc_parent": True,
}

# Function to return configuration for a notification type. Will return matching config from NOTIFICATION_TYPES
# if exists, otherwise returns DEFAULT


def get_notification_config(notification_type):
    return NOTIFICATION_TYPES.get(notification_type, DEFAULT)


# Reminder frequency for various notifications (minutes)
NOTIFICATION_TUTORING_SESSION_REMINDER = [48 * 60]
NOTIFICATION_COUNSELOR_MEETING_REMINDER = [48 * 60]
NOTIFICATION_TASK_DUE_IN_LESS_THAN_HOURS = 48
NOTIFICATION_TASK_OVERDUE_RECURRING = 48 * 60
NOTIFICATION_TUTOR_AVAILABILITY_REQUIRED_RECURRING = 24 * 60
NOTIFICATION_TUTOR_TIMECARD_CONFIRMATION_RECURRING = 24 * 60

# Minutes until first invite reminder for users who have not accepted their invite
INVITE_FIRST_REMINDER = 60 * 48
# Send invite reminder every this many minutes
INVITE_PERIODIC_REMINDER = 7 * 24 * 60
