import json
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.db.models import Q, F
from django.contrib.contenttypes.models import ContentType
from sentry_sdk import configure_scope, capture_exception

from snnotifications.constants.constants import (
    NOTIFICATION_TUTORING_SESSION_REMINDER,
    NOTIFICATION_COUNSELOR_MEETING_REMINDER,
    INVITE_FIRST_REMINDER,
    INVITE_PERIODIC_REMINDER,
)
from snnotifications.models import Notification
from snnotifications.generator import create_notification
from sntasks.models import Task
from sntutoring.models import StudentTutoringSession, GroupTutoringSession, Course
from sncounseling.models import CounselorMeeting
from snusers.models import Counselor, Tutor, Student, Parent, Administrator

OVERDUE_TASK_NOTI = "overdue_task_reminder"
COMING_DUE_TASK_NOTI = "coming_due_task_reminder"
STUDENT_TUTORING_SESSION_NOTIFICATION = "student_tutoring_session_reminder"
TUTOR_TUTORING_SESSION_NOTIFICATION = "tutor_tutoring_session_reminder"
STUDENT_COUNSELOR_MEETING_NOTIFICATION = "student_counselor_session_reminder"
COUNSELOR_COUNSELOR_MEETING_NOTIFICATION = "counselor_counselor_session_reminder"
COUNSELOR_WEEKLY_DIGEST_NOTIFICATION = "counselor_weekly_digest"
TUTOR_GTS_NOTIFICATION = "tutor_gts_reminder"
TUTOR_DAILY_DIGEST_NOTIFICATION = "tutor_daily_digest"
FIRST_INDIVIDUAL_TUTORING_SESSION_DAILY_DIGEST = "first_individual_tutoring_session_daily_digest"


@shared_task
def send_upcoming_tutoring_notification():
    """ Send notifications to students and tutors about upcoming tutoring sessions
        Returns lists of all StudentTutoringSessions and GroupTutoringSessions that noti was
            sent for
    """
    sorted_reminders = NOTIFICATION_TUTORING_SESSION_REMINDER
    sorted_reminders.sort(reverse=True)
    # Keep track of PKs of StudentTutoringSession and GroupTutoringSessions we send noti for
    all_sts = []
    all_gts = []
    for idx, x in enumerate(sorted_reminders):
        sessions = (
            StudentTutoringSession.objects.filter(
                missed=False,
                set_cancelled=False,
                start__lte=timezone.now() + timedelta(minutes=x),
                start__gt=timezone.now(),
                is_tentative=False,
            )
            .exclude(group_tutoring_session__cancelled=True)
            .filter(Q(last_reminder_sent=None) | Q(last_reminder_sent__lt=F("start") - timedelta(minutes=x)))
        )
        group_sessions = (
            GroupTutoringSession.objects.filter(
                cancelled=False, start__lte=timezone.now() + timedelta(minutes=x), start__gt=timezone.now(),
            )
            .filter(Q(last_reminder_sent=None) | Q(last_reminder_sent__lt=F("start") - timedelta(minutes=x)))
            .distinct()
        )
        if len(NOTIFICATION_TUTORING_SESSION_REMINDER) > idx + 1:
            sessions = sessions.filter(start__gte=(timezone.now() + timedelta(minutes=sorted_reminders[idx + 1])))
            group_sessions = sessions.filter(start__gte=timezone.now() + timedelta(minutes=sorted_reminders[idx + 1]))
        else:
            sessions = sessions.filter(start__gte=timezone.now())
            group_sessions = group_sessions.filter(start__gte=timezone.now())

        for session in sessions:
            # Notify student and notify tutor
            session.last_reminder_sent = timezone.now()
            session.save()
            create_notification(
                session.student.user,
                **{
                    "notification_type": STUDENT_TUTORING_SESSION_NOTIFICATION,
                    "related_object_content_type": ContentType.objects.get_for_model(StudentTutoringSession),
                    "related_object_pk": session.pk,
                },
            )
            if session.individual_session_tutor:
                create_notification(
                    session.individual_session_tutor.user,
                    **{
                        "notification_type": TUTOR_TUTORING_SESSION_NOTIFICATION,
                        "related_object_content_type": ContentType.objects.get_for_model(StudentTutoringSession),
                        "related_object_pk": session.pk,
                    },
                )

        for group_session in group_sessions:
            # Notify primary and support tutors
            group_session.last_reminder_sent = timezone.now()
            group_session.save()
            tutors = Tutor.objects.filter(
                Q(primary_group_tutoring_sessions=group_session) | Q(support_group_tutoring_sessions=group_session)
            ).distinct()
            for tutor in tutors:
                create_notification(
                    tutor.user,
                    notification_type=TUTOR_GTS_NOTIFICATION,
                    related_object_content_type=ContentType.objects.get_for_model(GroupTutoringSession),
                    related_object_pk=group_session.pk,
                )

        all_sts += [x.pk for x in sessions]
        all_gts += [x.pk for x in group_sessions]

    return {"sts": all_sts, "gts": all_gts}


@shared_task
def send_upcoming_counselor_meeting_notification():
    """ Sends email notifications to students and counselors about upcoming counselor meeting
        Send text notification to students
        Returns list of CounselorMeetings that noti was sent for
        NOTIFICATION_COUNSELOR_MEETING_REMINDER
        STUDENT_COUNSELOR_MEETING_NOTIFICATION
        COUNSELOR_COUNSELOR_MEETING_NOTIFICATION
    """
    sorted_reminders = NOTIFICATION_COUNSELOR_MEETING_REMINDER
    sorted_reminders.sort(reverse=True)

    all_meetings = []
    for idx, reminder_time_threshold in enumerate(sorted_reminders):
        meetings = CounselorMeeting.objects.filter(
            cancelled=None,
            start__lte=timezone.now() + timedelta(minutes=reminder_time_threshold),
            start__gt=timezone.now(),
        ).filter(
            Q(last_reminder_sent=None)
            | Q(last_reminder_sent__lt=F("start") - timedelta(minutes=reminder_time_threshold))
        )

        for meeting in meetings:
            try:
                create_notification(
                    meeting.student.user,
                    **{
                        "notification_type": STUDENT_COUNSELOR_MEETING_NOTIFICATION,
                        "related_object_content_type": ContentType.objects.get_for_model(CounselorMeeting),
                        "related_object_pk": meeting.pk,
                    },
                )
                meeting.last_reminder_sent = timezone.now()
                meeting.save()
            except Exception as err:
                # A rare case where we want to catch a general exception so that one notification failing to send
                # doesn't ruin this for everyone. Log the issue
                with configure_scope() as scope:
                    scope.set_context(
                        "Meeting Data",
                        {"meeting ID": meeting.pk, "student ID": meeting.student.pk, "title": meeting.title},
                    )
                    scope.set_tag("Celery Task", "Send upcoming counselor meeting notification")
                    capture_exception(err)
        all_meetings += [x.pk for x in meetings]

    return {"meetings": all_meetings}


@shared_task
def send_tutor_availability_required():
    """ Send tutors who do not have any availability set for the upcoming week a reminder
        to set their availability
    """
    pass


@shared_task
def send_invite_reminder():
    """ Send reminder to users who are ACTIVE and pending invitation """
    # Time Query
    # First reminder is due, or it's time for periodic reminder
    first_reminder_due = Q(
        Q(created__lte=timezone.now() - timedelta(minutes=INVITE_FIRST_REMINDER))
        & ~Q(user__notification_recipient__notifications__notification_type="invite_reminder")
    )
    periodic_reminder_due = Q(last_invited__lt=timezone.now() - timedelta(minutes=INVITE_PERIODIC_REMINDER))

    students = (
        Student.objects.filter(
            accepted_invite=None, user__notification_recipient__notifications__notification_type="invite",
        )
        .filter(first_reminder_due | periodic_reminder_due)
        .distinct()
    )
    tutors = (
        Tutor.objects.filter(
            accepted_invite=None, user__notification_recipient__notifications__notification_type="invite",
        )
        .filter(first_reminder_due | periodic_reminder_due)
        .distinct()
    )
    parents = (
        Parent.objects.filter(
            accepted_invite=None, user__notification_recipient__notifications__notification_type="invite",
        )
        .filter(first_reminder_due | periodic_reminder_due)
        .distinct()
    )
    # Evaluate our querysets so we can return them properly
    students = list(students)
    tutors = list(tutors)
    parents = list(parents)
    all_cw_users = students + tutors + parents
    for cwuser in all_cw_users:
        user = cwuser.user
        if not user.has_usable_password():
            # We send a reminder!
            cwuser.last_invited = timezone.now()
            cwuser.save()
            create_notification(user, notification_type="invite_reminder")
    return {
        "students": [x.pk for x in students],
        "parents": [x.pk for x in parents],
        "tutors": [x.pk for x in tutors],
    }


@shared_task
def send_tutor_daily_digest():
    """
    A daily summary email of session- and conversation-related info for Tutors.
    """
    tutors = Tutor.objects.all()

    tutors_sent_digests = []
    for tutor in tutors:
        create_notification(
            tutor.user,
            **{
                "notification_type": TUTOR_DAILY_DIGEST_NOTIFICATION,
                "related_object_content_type": ContentType.objects.get_for_model(Tutor),
                "related_object_pk": tutor.pk,
            },
        )
        tutors_sent_digests.append(tutor.pk)

    return tutors_sent_digests


@shared_task
def send_upcoming_course():
    """ Notification to ops/admin of upcoming course
    """
    # Courses with session in the next week, but not before, and no notification sent for
    notified_courses = (
        Notification.objects.filter(notification_type="ops_upcoming_course")
        .distinct()
        .values_list("related_object_pk", flat=True)
    )

    courses = (
        Course.objects.filter(
            group_tutoring_sessions__start__gt=timezone.now(),
            group_tutoring_sessions__start__lt=timezone.now() + timedelta(days=7),
            group_tutoring_sessions__cancelled=False,
        )
        .exclude(group_tutoring_sessions__start__lt=timezone.now(), group_tutoring_sessions__cancelled=False,)
        .exclude(pk__in=notified_courses)
        .distinct()
    )

    admins = Administrator.objects.all()
    return_courses = list(courses)
    for course in courses:
        for admin in admins:
            create_notification(
                admin.user,
                notification_type="ops_upcoming_course",
                related_object_content_type=ContentType.objects.get_for_model(Course),
                related_object_pk=course.pk,
            )

    return {
        "courses": [x.pk for x in return_courses],
        "display": [x.verbose_name for x in return_courses],
    }


@shared_task
def send_first_individual_tutoring_session_daily_digest():
    """
    A daily email report sent to admins that list all individual tutoring sessions
    that took place in the last 24 hours and that were the student's first session
    Returns list of notification PKS that were sent
    """
    admins = Administrator.objects.all()

    notis = []
    for admin in admins:
        noti = create_notification(
            admin.user,
            **{
                "notification_type": FIRST_INDIVIDUAL_TUTORING_SESSION_DAILY_DIGEST,
                "related_object_content_type": ContentType.objects.get_for_model(Administrator),
                "related_object_pk": admin.pk,
            },
        )
        notis.append(noti.pk)
    return json.dumps(notis)


@shared_task
def send_counselor_weekly_digest():
    """ This celery task sends counselors an email with:
    (a) Their upcoming `CounselorMeeting`s (over the next week)
    (b) For each meeting, the complete and incomplete tasks for the student.
    If no upcoming meetings, no email(s) sent.
    """
    now = timezone.now()
    upcoming_meetings = CounselorMeeting.objects.filter(start__gte=now, start__lte=now + timedelta(days=7))
    counselor_sent_digest = []

    for counselor in Counselor.objects.all():
        meetings = upcoming_meetings.filter(student__counselor=counselor).filter(cancelled=None)
        if meetings:
            create_notification(
                counselor.user,
                **{
                    "notification_type": COUNSELOR_WEEKLY_DIGEST_NOTIFICATION,
                    "related_object_content_type": ContentType.objects.get_for_model(Counselor),
                    "related_object_pk": counselor.pk,
                    "additional_args": list(meetings.values_list("pk", flat=True)),
                },
            )
            counselor_sent_digest.append(counselor.pk)
    return counselor_sent_digest
