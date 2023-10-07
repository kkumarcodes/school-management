""" This module contains the functions needed to generate a description for a notification
    As it should appear in an activity log in the platform
    Because properties on related objects can change, these functions should be used to generate
    descriptions when a notification is created.

    Not all notifications have activity log description functions
"""
from snnotifications.models import Notification

# Only these items appear in activity log
ACTIVITY_LOG_TITLE_FUNCTIONS = {
    "invite": lambda x: "Initial invitation sent",
    "invite_reminder": lambda x: "Invitation reminder sent",
    "task": lambda x: f"Task ({x.related_object.title}) created",
    "diagnostic_result": lambda x: f"Diagnostic ({x.related_object.diagnostic.title}) has been submitted",
    "task_complete": lambda x: f"Task ({x.related_object.title}) is now Complete",
    "tutoring_session_notes": lambda x: f"Notes complete on tutoring session: {x.related_object.group_tutoring_session.title if x.related_object.group_tutoring_session else x.related_object.individual_session_tutor.name} on {x.related_object.start.strftime('%b %d')}",
    "student_tutoring_session_confirmation": lambda x: f"Tutoring session scheduled: {x.related_object.title_for_student}",
    "student_tutoring_session_cancelled": lambda x: f"Cancelled tutoring session: {x.related_object.title_for_student}",
    "student_tutoring_session_rescheduled": lambda x: f"Tutoring session rescheduled. Rescheduled to: {x.related_object.title_for_student}",
    "student_tutoring_session_reminder": lambda x: f"Reminder for tutoring session {x.related_object.title_for_student}",
    "student_diagnostic_result": lambda x: f"Diagnostic ({x.related_object.diagnostic.title}) returned to student",
    "course_enrollment_confirmation": lambda x: f"Enrolled in course {x.related_object.name}",
    "course_unenrollment_confirmation": lambda x: f"Unenrolled from course {x.related_object.name}",
    "student_counselor_meeting_confirmed": lambda x: f"Counselor meeting scheduled. Meeting is on {x.related_object.start.strftime('%b %d')}",
    "student_counselor_meeting_rescheduled": lambda x: f"Counselor meeting rescheduled. Meeting is now on {x.related_object.start.strftime('%b %d')}",
    "student_counselor_meeting_cancelled": lambda x: f"Counselor meeting on {x.related_object.start.strftime('%b %d')} cancelled",
    "ops_magento_webhook": lambda x: f"Incoming webhook from Magento",
    "ops_magento_webhook_failure": lambda x: f"Incoming webhook from Magento FAILED",
    "ops_paygo_payment_success": lambda x: f"Automatic paygo payment successful for {x.related_object.student}'s session: {x.related_object.title_for_student}",
    "ops_paygo_payment_failure": lambda x: f"Automatic paygo payment failed for {x.related_object.student}'s session: {x.related_object.title_for_student}",
    "unread_messages": lambda x: x.title,
    "student_counselor_meeting_confirmed": lambda x: x.title,
    "student_counselor_meeting_rescheduled": lambda x: x.title,
    "student_counselor_meeting_cancelled": lambda x: x.title,
    "student_counselor_session_reminder": lambda x: x.title,
    "counselor_meeting_message": lambda x: x.title,
}


def ops_magento_webhook_description(notification: Notification) -> str:
    data = notification.additional_args
    return_string = f"Order IDs: {', '.join([str(x.get('order_id', '')) for x in data['items']])}\n"
    extension_attributes = data.get("extension_attributes", {})
    for att in extension_attributes.keys():
        return_string += f"{att}: {extension_attributes[att]}\n"
    return return_string


ACTIVITY_LOG_DESCRIPTION_FUNCTIONS = {
    "ops_magento_webhook": ops_magento_webhook_description,
    "ops_magento_webhook_failure": ops_magento_webhook_description,
}
