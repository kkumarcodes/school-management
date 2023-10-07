from datetime import timedelta, datetime

from celery import shared_task
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from snusers.models import Tutor, Administrator
from cwtutoring.models import StudentTutoringSession, TutorTimeCard
from cwtutoring.utilities.time_card_manager import TutorTimeCardManager
from cwtutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager
from cwnotifications.generator import create_notification

CREATE_RECURRING_AVAILABILITY = "create_recurring_availability"
WEEKS_OF_AVAILABILITY = 2
TIME_CARD_BUFFER_DAYS = 8


@shared_task
def notify_admins_of_last_meetings():
    """ Sent notification to admins listing all students who have their last scheduled session within 1 week
    """
    day = timezone.now()
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=7)
    sessions = StudentTutoringSession.objects.filter(
        set_cancelled=False,
        start__gte=start,
        start__lte=end,
        individual_session_tutor__isnull=False,
        student__isnull=False,
        is_tentative=False,
    )

    def is_last_session(session: StudentTutoringSession) -> bool:
        """ Utility function that returns whether or not session is a student's last PAID session
        """
        if StudentTutoringSession.objects.filter(
            set_cancelled=False,
            start__gt=session.start,
            individual_session_tutor__isnull=False,
            student=session.student,
        ).exists():
            return False
        mgr = StudentTutoringPackagePurchaseManager(session.student)
        # Make sure student is out of hours that this session requires
        hours = mgr.get_available_hours()
        return (
            hours["individual_curriculum"] < 1
            if session.session_type == session.SESSION_TYPE_CURRICULUM
            else hours["individual_test_prep"] < 1
        )

    last_sessions = filter(is_last_session, sessions)
    student_pks = list(set([x.student.pk for x in last_sessions]))
    # Last session for each student (since one of our students may have multiple sessions in the next week
    # but we only care about the last one)
    session_pks = [sessions.filter(student=x).order_by("start").last().pk for x in student_pks]
    if student_pks:
        for admin in Administrator.objects.all():
            create_notification(
                admin.user,
                notification_type="last_meeting",
                additional_args={"students": student_pks, "date": day.strftime("%m/%d/%Y"), "sessions": session_pks},
            )
    return student_pks


@shared_task
def create_time_cards():
    """ Create time card from the end of the most recent Friday through the prior two weeks
        We only create time cards for tutors that have not had time card created in past 8 days (since
        we can't create Celery task that runs every other week)
    """

    today = timezone.now()
    offset = today.weekday() - 4 if today.weekday() >= 5 else today.weekday() + 3
    most_recent_friday = today - timedelta(days=offset)

    most_recent_friday_end = datetime(
        most_recent_friday.year,
        most_recent_friday.month,
        most_recent_friday.day,
        23,
        59,
        tzinfo=most_recent_friday.tzinfo,
    )
    # When creating time cards, we actually end at 6a on Saturday to catch late night events on West Coast Friday
    end = most_recent_friday_end + timedelta(hours=6)

    start = end - timedelta(days=14)

    (time_cards, skipped_tutors) = TutorTimeCardManager.create_many_time_cards(
        Tutor.objects.exclude(
            time_cards__created__gt=(timezone.now() - timedelta(days=TIME_CARD_BUFFER_DAYS))
        ).distinct(),
        start=start,
        end=end,
    )

    # And then we update timecards to make it _look_ like they ended on Friday
    time_card_pks = [x.pk for x in time_cards]
    TutorTimeCard.objects.filter(pk__in=time_card_pks).update(end=most_recent_friday_end)

    # And last but not least -- send the time cards
    for tc in time_cards:
        create_notification(
            tc.tutor.user,
            notification_type="tutor_time_card",
            related_object_content_type=ContentType.objects.get_for_model(TutorTimeCard),
            related_object_pk=tc.pk,
        )

    return (time_card_pks, skipped_tutors)
