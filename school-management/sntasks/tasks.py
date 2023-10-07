from datetime import timedelta
from celery import shared_task
from django.db.models import Q
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import User
from snnotifications.constants.constants import NOTIFICATION_TASK_DUE_IN_LESS_THAN_HOURS
from snnotifications.constants.notification_types import STUDENT_TASK_REMINDER, TASK_DIGEST
from snnotifications.generator import create_notification
from sntasks.models import Task

MAX_REMINDER_HOURS = 23  # We'll at most notify users of tasks every this many hours


@shared_task
def send_daily_task_digest():
    """ Celery task that sends users assigned new tasks a list of tasks that they were assigned in the last 24 hours
    """
    # Not all tasks are visible to students/parents.
    tasks = (
        Task.objects.filter(archived=None, completed=None)
        .filter(Q(visible_to_counseling_student=True) | Q(task_template=None, created_by__counselor=None))
        .filter(assigned_time__gt=timezone.now() - timedelta(hours=24), assigned_time__lte=timezone.now())
    ).distinct()

    users_assigned_tasks = (
        User.objects.filter(tasks__in=tasks)
        .filter(Q(student__isnull=False) | Q(parent__isnull=False))
        .exclude(
            # Extra check to ensure users don't get more than one notification every 24 hours (we do sligntly less as
            # the task can take a few minutes to run)
            notification_recipient__notifications__notification_type=TASK_DIGEST,
            notification_recipient__notifications__created__gt=timezone.now() - timedelta(hours=23),
        )
        .distinct()
    )
    user_pks = [u.pk for u in users_assigned_tasks]
    for user in users_assigned_tasks:
        create_notification(
            user,
            notification_type=TASK_DIGEST,
            related_object_content_type=ContentType.objects.get_for_model(User),
            related_object_pk=user.pk,
            additional_args=list(tasks.filter(for_user=user).values_list("pk", flat=True)),
        )
    return user_pks


@shared_task
def send_student_task_reminders():
    """ Celery task to send overdue AND upcoming task notifications to students
    """
    return_tasks = []

    # Overdue incomplete tasks visible to student that we haven't sent a reminder for in over 48 hours
    overdue_tasks = (
        Task.objects.filter(due__lt=timezone.now(), archived=None, completed=None,)
        .exclude(task_template__counseling_parent_task=True)
        .exclude(for_user__student__has_access_to_cap=False)
        .filter(
            Q(last_reminder_sent__lt=(timezone.now() - timedelta(hours=MAX_REMINDER_HOURS)))
            | Q(last_reminder_sent=None)
        )
        .filter(
            # Counseling tasks must be visible to student
            Q(visible_to_counseling_student=True)
            | Q(task_template=None, created_by__counselor=None)
        )
        .distinct()
    )

    # Tasks due in the next 48 hours that we haven't sent a reminder for in over 24 hours (
    # guard against too many reminders)
    coming_due_tasks = (
        Task.objects.filter(
            due__gt=timezone.now(),
            archived=None,
            completed=None,
            due__lt=timezone.now() + timedelta(hours=NOTIFICATION_TASK_DUE_IN_LESS_THAN_HOURS),
        )
        .exclude(task_template__counseling_parent_task=True)
        .exclude(for_user__student__has_access_to_cap=False)
        .filter(
            Q(last_reminder_sent__lt=(timezone.now() - timedelta(hours=MAX_REMINDER_HOURS)))
            | Q(last_reminder_sent=None)
        )
        .filter(
            # Counseling tasks must be visible to student
            Q(visible_to_counseling_student=True)
            | Q(task_template=None, created_by__counselor=None)
        )
        .distinct()
    )
    tasks_queryset = (overdue_tasks | coming_due_tasks).distinct()
    tasks = list(tasks_queryset)
    users = User.objects.filter(tasks__in=tasks).distinct()

    for user in users:
        overdue = list(overdue_tasks.filter(for_user=user).values_list("pk", flat=True))
        coming_due = list(coming_due_tasks.filter(for_user=user).values_list("pk", flat=True))
        if overdue or coming_due:
            notification = create_notification(
                user,
                **{
                    "notification_type": STUDENT_TASK_REMINDER,
                    "additional_args": {"overdue": overdue, "coming_due": coming_due},
                },
            )

            if notification.emailed or notification.texted:
                # Note that these tasks will no longer be in tasks_queryset, but they will be in tasks
                return_tasks += overdue + coming_due
                tasks_queryset.filter(for_user=user).update(last_reminder_sent=timezone.now())

    return return_tasks
