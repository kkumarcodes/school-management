""" Celery tasks related to counseling features
"""

from django.contrib.contenttypes.models import ContentType
import pytz
from datetime import datetime, timedelta
from celery import shared_task
from django.conf import settings
from django.utils import timezone
import sentry_sdk

from cwcommon.constants import envs
from cwcounseling.models import CounselorMeeting
from cwusers.models import Counselor, Student
from cwuniversities.models import StudentUniversityDecision
from cwcounseling.utilities.counseling_prompt_api_manager import (
    CounselingPromptAPIManagerException,
    CounselingPromptAPIManager,
)
from cwnotifications.constants.notification_types import COUNSELOR_TASK_DIGEST, COUNSELOR_COMPLETED_TASKS
from cwnotifications.models import Notification, NotificationRecipient
from cwnotifications.generator import create_notification
from cwtasks.models import Task

# We send at this hour in COUNSELOR'S LOCAL TIME
COUNSELOR_TASK_DIGEST_SEND_HOUR = 14  # 2pm
COUNSELOR_COMPLETED_TASKS_SEND_HOUR = 19  # 7pm
FRIDAY_WEEKDAY = 4


@shared_task
def sync_all_prompt_assignment_tasks() -> dict:
    """ Celery task used to sync all assignments from Prompt into tasks in UMS
        (via CounselorPromptAPIManager.update_assignment_tasks)
        This task is (obviously) load intensive, and should be run in the middle of the night
        # TODO: If performance becomes a problem with UMS, we could parallelize
    """
    updated_students = []
    failed_students = []
    students = Student.objects.filter(is_prompt_active=True, counselor__prompt=True)
    for student in students:
        try:
            mgr = CounselingPromptAPIManager()
            if not settings.TESTING:
                mgr.update_assignment_tasks(student)
            updated_students.append(student.pk)
        except Exception as err:
            print(err)
            if not (settings.DEBUG or settings.TESTING):
                with sentry_sdk.configure_scope() as scope:
                    scope.set_context(
                        "Celery - Sync Prompt Tasks", {"student_name": student.name, "student_slug": str(student.slug)},
                    )
                    sentry_sdk.capture_exception(err)
            failed_students.append((student.pk, str(err)))
    return {"updated_students": updated_students, "failed_students": failed_students}


@shared_task
def send_counselor_completed_task_digest(send_hour=COUNSELOR_COMPLETED_TASKS_SEND_HOUR):
    """ This celery task sends counselors a digest every day with tasks that were completed since the last digest
        Arguments:
            send_hour: The hour IN COUNSELOR LOCAL TIME when they will receive their digest
    """
    # Celery should be setup NOT to run on the weekend, but this is an extra check
    if timezone.now().weekday() > FRIDAY_WEEKDAY and settings.ENV == envs.PRODUCTION:
        return
    end = timezone.now()
    start = (end - timedelta(hours=72)) if end.weekday() == FRIDAY_WEEKDAY else (end - timedelta(hours=24))
    tasks = Task.objects.filter(
        for_user__student__counselor__isnull=False, completed__gte=start, completed__lte=end, archived=None
    )

    # We find counselors for whom it is after send_hour in local time that have not received this digest
    # in past 24 hours
    recent_sent_notifications = Notification.objects.filter(
        created__gt=start, notification_type=COUNSELOR_COMPLETED_TASKS
    )
    recent_sent_noti_recipients = list(
        NotificationRecipient.objects.filter(notifications__in=recent_sent_notifications)
    )
    counselors = (
        Counselor.objects.filter(students__user__tasks__in=tasks)
        .exclude(user__notification_recipient__in=recent_sent_noti_recipients)
        .distinct()
    )

    def test_counselor_send_hour(counselor):
        counselor_hour = datetime.now().astimezone(pytz.timezone(counselor.timezone)).hour
        return counselor_hour >= send_hour and (counselor_hour - send_hour) < 3

    counselors = filter(test_counselor_send_hour, counselors)
    counselors_sent_notification = []

    for counselor in counselors:
        counselors_sent_notification.append(counselor.pk)
        task_pks = list(tasks.filter(for_user__student__counselor=counselor).values_list("pk", flat=True))
        create_notification(
            counselor.user,
            notification_type=COUNSELOR_COMPLETED_TASKS,
            related_object_content_type=ContentType.objects.get_for_model(Counselor),
            related_object_pk=counselor.pk,
            additional_args=task_pks,
        )
    return counselors_sent_notification


@shared_task
def send_counselor_task_digest(send_hour=COUNSELOR_TASK_DIGEST_SEND_HOUR):
    """ This Celery task sends counselors a task digest with all of the overdue/coming due tasks for students with
        meetings in the next 24 hours
        Arguments:
            send_hour: The hour IN COUNSELOR LOCAL TIME when they will receive their digest
    """
    # Celery should be setup NOT to run on the weekend, but this is an extra check
    if timezone.now().weekday() > FRIDAY_WEEKDAY and settings.ENV == envs.PRODUCTION:
        return
    # Time period over which we will look for upcoming meetings
    # Our time period is 24 hours, except on Fridays when it also includes the weekend
    # We can assume we're sending at 2pm, so we need to capture meetings in the next 10 - 34 hours
    start = timezone.now() + timedelta(hours=10)
    end = start + timedelta(hours=72) if start.weekday() == FRIDAY_WEEKDAY else start + timedelta(hours=24)
    # We do 00:00 the next day to catch events that end at midnight, which is possible because counselors
    # can be in weird timezones
    # end = datetime(end.year, end.month, end.day, 0, 0, tzinfo=end.tzinfo) + timedelta(days=1)

    # We find counselors for whom it is after send_hour in local time that have not received this digest
    # in past 24 hours
    sent_digests = Notification.objects.filter(
        notification_type=COUNSELOR_TASK_DIGEST, created__gt=start - timedelta(hours=24)
    )
    counselors = Counselor.objects.exclude(user__notification_recipient__notifications__in=sent_digests).distinct()

    def test_counselor_send_hour(counselor):
        counselor_hour = datetime.now().astimezone(pytz.timezone(counselor.timezone)).hour
        return counselor_hour >= send_hour and (counselor_hour - send_hour) < 3

    counselors = filter(test_counselor_send_hour, counselors)

    # First we find the students with a meeting
    meetings = CounselorMeeting.objects.filter(
        student__counselor__in=counselors, start__gte=start, end__lte=end, cancelled=None
    )
    send_to_counselors = Counselor.objects.filter(students__counselor_meetings__in=meetings).distinct()

    counselors_sent_digest = []
    for counselor in send_to_counselors:
        # Find all of the tasks that are either overdue or for an upcoming meeting and are for a student
        # with upcoming meeting
        meetings_with_counselor = meetings.filter(student__counselor=counselor)
        meeting_tasks = Task.objects.filter(
            counselor_meetings__in=meetings_with_counselor, completed=None, archived=None
        ).values_list("pk", flat=True)
        overdue_tasks = Task.objects.filter(
            for_user__student__counselor_meetings__in=meetings_with_counselor,
            completed=None,
            archived=None,
            due__lt=end,
        ).values_list("pk", flat=True)
        task_pks = list(set(list(meeting_tasks) + list(overdue_tasks)))

        # We create a notification; We include the task PKs in the notification additional context
        if task_pks:
            counselors_sent_digest.append(counselor.pk)
            create_notification(
                counselor.user,
                notification_type=COUNSELOR_TASK_DIGEST,
                related_object_content_type=ContentType.objects.get_for_model(Counselor),
                related_object_pk=counselor.pk,
                additional_args=task_pks,
            )
    return counselors_sent_digest
