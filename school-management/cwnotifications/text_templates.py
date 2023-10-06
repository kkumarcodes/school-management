""" WHAT?! This isn't a traditional template file!
    That's right. This python module contains lambda functions that return strings that can be
    texted for a given notification type.
"""
from django.utils import timezone
from cwnotifications.constants import notification_types
from cwnotifications.models import Notification
from cwnotifications.utilities.helpers import format_datetime
from cwtasks.models import Task


def student_task_reminder_template(noti: Notification):
    """ Text with upcoming and overdue tasks """
    overdue_tasks = Task.objects.filter(pk__in=noti.additional_args.get("overdue", []))
    coming_due_tasks = Task.objects.filter(pk__in=noti.additional_args.get("coming_due", []))
    text = ""
    if overdue_tasks:
        text += "The following tasks are overdue:\n-"
        text += "\n\n-".join(list(overdue_tasks.values_list("title", flat=True)))

    if coming_due_tasks:
        text += "\n\nThe following tasks are coming due:\n-"
        text += "\n\n-".join(list(coming_due_tasks.values_list("title", flat=True)))

    text += "\nYou can find all of your tasks in UMS"
    return text


def task_reminder(noti: Notification):
    """ Reminder for an individual task """
    task: Task = noti.related_object
    overdue = task.due < timezone.now()
    return f'Reminder: Your task "{task.title}" {"was" if overdue else "is"} due on {task.due.strftime("%A %b %d")}.\nComplete it in UMS.'


TEXT_TEMPLATES = {
    "coming_due_task_reminder": lambda x: x.title,
    "student_diagnostic_result": lambda x: f'Your diagnostic "{x.related_object.diagnostic.title}" has been reviewed!',
    "tutoring_session_notes": lambda x: f"{x.title}. Find the notes in WiserNet",
    "task": lambda x: f"A new task has been assigned in UMS: {x.related_object.title}",
    "counselor_meeting_message": lambda x: x.title,
    "student_counselor_meeting_confirmed": lambda x: f"Meeting ({x.related_object.title}) scheduled with {x.related_object.student.counselor.name} on {format_datetime(x.related_object.start, x.related_object.student.timezone)}",
    "student_counselor_meeting_rescheduled": lambda x: f"Your meeting ({x.related_object.title}) with {x.related_object.student.counselor.name} has been rescheduled to {format_datetime(x.related_object.start, x.related_object.student.timezone)}",
    "student_counselor_meeting_cancelled": lambda x: f"Your meeting ({x.related_object.title}) with {x.related_object.student.counselor.name} on {x.related_object.start.strftime('%b %d')} has been cancelled",
    "student_counselor_session_reminder": lambda x: f"Reminder: You have a meeting ({x.related_object.title}) scheduled with {x.related_object.student.counselor.name} on {format_datetime(x.related_object.start, x.related_object.student.timezone)}",
    notification_types.COUNSELOR_FORWARD_STUDENT_MESSAGE: lambda x: f"New message from {x.additional_args['author']}:\n{x.additional_args['message']}",
    notification_types.STUDENT_TASK_REMINDER: student_task_reminder_template,
    notification_types.INDIVIDUAL_TASK_REMINDER: task_reminder,
}
