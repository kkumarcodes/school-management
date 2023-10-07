""" Tests to ensure we generate automated notifications/reminders in the correct circumstances
    python manage.py test snnotifications.tests.test_automated_notifications
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from snnotifications.constants.constants import (
    INVITE_FIRST_REMINDER,
    INVITE_PERIODIC_REMINDER,
)
from snnotifications.mailer import get_first_individual_tutoring_session_digest_details
from snnotifications.models import Notification
from snnotifications.tasks import (
    send_tutor_daily_digest,
    send_invite_reminder,
    send_first_individual_tutoring_session_daily_digest,
    send_upcoming_counselor_meeting_notification,
)
from sntasks.models import Task
from sncounseling.models import CounselorMeeting
from sncounseling.utilities.counselor_meeting_manager import CounselorMeetingManager
from sntutoring.models import StudentTutoringSession, GroupTutoringSession, Location
from sntutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager
from snusers.models import Student, Tutor, Parent, Administrator, Counselor
from snusers.serializers.users import StudentSerializer


class TestTaskNotifications(TestCase):
    fixtures = ("fixture.json",)

    def setUp(self):
        self.now = timezone.now()
        self.admin = Administrator.objects.first()
        self.tutor = Tutor.objects.first()
        self.counselor = Counselor.objects.first()
        self.student = Student.objects.first()
        self.task = Task.objects.create(for_user=self.student.user, title="Test Task", due=timezone.now())
        self.meeting_1 = CounselorMeeting.objects.create(student=self.student, created_by=self.counselor.user)
        self.meeting_2 = CounselorMeeting.objects.create(student=self.student, created_by=self.counselor.user)
        self.group_session = GroupTutoringSession.objects.create(
            primary_tutor=self.tutor,
            title="group_session",
            location=Location.objects.create(name="Example Location"),
            start=self.now,
        )
        self.individual_sts = StudentTutoringSession.objects.create(
            individual_session_tutor=self.tutor, student=self.student, start=self.now
        )
        self.group_sts = StudentTutoringSession.objects.create(
            student=self.student, group_tutoring_session=self.group_session, start=self.group_session.start,
        )
        self.student.counselor = self.counselor
        self.student.save()

    def test_sending_tutors_daily_digest_emails(self):
        """ python manage.py test snnotifications.tests.test_automated_notifications:TestTaskNotifications.test_sending_tutors_daily_digest_emails """
        # Was a digest attempted for one Tutor?
        result = send_tutor_daily_digest()
        self.assertEqual(len(result), 1)

        # Was one notification generated?
        notis = Notification.objects.all()
        self.assertEqual(notis.count(), 1)

        # Is the notification for the expected user?
        noti = notis.first()
        self.assertEqual(noti.recipient.user_id, self.tutor.user.id)

        # Is the notification of the expected notification type?
        self.assertEqual(noti.notification_type, "tutor_daily_digest")

        # Was the notification emailed?
        self.assertIsNotNone(noti.emailed)
        self.assertEqual(type(noti.emailed), type(timezone.now()))

    def test_upcoming_counseling_meeting_notification(self):

        # Test < 48 hours away. One noti sent
        start = timezone.now() + timedelta(hours=47)
        end = start + timedelta(hours=1)
        mgr = CounselorMeetingManager(self.meeting_1)
        updated_meeting = mgr.schedule(start, end)
        result = send_upcoming_counselor_meeting_notification()
        mtg_pks = result["meetings"]
        self.assertEqual(len(mtg_pks), 1)

        # Test meeting time is < 48 hours and a prior noti was sent. No noti sent.
        result = send_upcoming_counselor_meeting_notification()
        mtg_pks = result["meetings"]
        self.assertEqual(len(mtg_pks), 0)

        #  New meeting created. Test that post meeting no noti.
        start = timezone.now() - timedelta(hours=2)
        end = start + timedelta(hours=1)
        mgr = CounselorMeetingManager(self.meeting_2)
        updated_meeting2 = mgr.schedule(start, end)
        result = send_upcoming_counselor_meeting_notification()
        mtg_pks = result["meetings"]
        self.assertEqual(len(mtg_pks), 0)

    def test_first_individual_tutoring_session_daily_digest(self):
        """
        python manage.py test snnotifications.tests.test_automated_notifications:TestTaskNotifications.test_first_individual_tutoring_session_daily_digest -s
        """
        # Individual StudentTutoringSession within past 24 hours and is student's first individual session
        # Expect 1 notification sent, notification has correct type, delievered to expected admin, and was emailed
        noti_pks = json.loads(send_first_individual_tutoring_session_daily_digest())
        self.assertEqual(len(noti_pks), 1)
        noti_pk = noti_pks[0]
        noti = Notification.objects.get(pk=noti_pk)
        self.assertEqual(noti.notification_type, "first_individual_tutoring_session_daily_digest")
        self.assertEqual(noti.recipient.user_id, self.admin.user_id)
        self.assertIsNotNone(noti.emailed)

        # Expect 1 individual tutoring sessions reported in digest details and correct content
        recent_first_individual_sessions = get_first_individual_tutoring_session_digest_details(noti)[
            "recent_first_individual_sessions"
        ]
        self.assertEqual(len(recent_first_individual_sessions), 1)
        session = recent_first_individual_sessions[0]
        student_hours = StudentTutoringPackagePurchaseManager(self.individual_sts.student).get_available_hours()
        self.assertEqual(session["student"], self.student.name)
        self.assertEqual(session["tutor"], self.tutor.name)
        self.assertEqual(session["start"], self.individual_sts.start)
        self.assertEqual(
            session["individual_curriculum"], max(0, student_hours["individual_curriculum"]),
        )
        self.assertEqual(session["individual_test_prep"], max(0, student_hours["individual_test_prep"]))
        self.assertEqual(session["group_test_prep"], max(0, student_hours["group_test_prep"]))

        # Email notification still sent if session is in the future
        # But zero recent_first_individual_sessions are generated
        self.individual_sts.start = self.now + timedelta(minutes=10)
        self.individual_sts.save()
        noti_pks = json.loads(send_first_individual_tutoring_session_daily_digest())
        self.assertEqual(len(noti_pks), 1)
        noti_pk = noti_pks[0]
        noti = Notification.objects.get(pk=noti_pk)
        self.assertIsNotNone(noti.emailed)
        recent_first_individual_sessions = get_first_individual_tutoring_session_digest_details(noti)[
            "recent_first_individual_sessions"
        ]
        self.assertEqual(len(recent_first_individual_sessions), 0)
        # Same result for individual tutoring sessions beyond 24 hours in the past
        self.individual_sts.start = self.now - timedelta(hours=25)
        self.individual_sts.save()
        noti_pks = json.loads(send_first_individual_tutoring_session_daily_digest())
        self.assertEqual(len(noti_pks), 1)
        noti_pk = noti_pks[0]
        noti = Notification.objects.get(pk=noti_pk)
        self.assertIsNotNone(noti.emailed)
        recent_first_individual_sessions = get_first_individual_tutoring_session_digest_details(noti)[
            "recent_first_individual_sessions"
        ]
        self.assertEqual(len(recent_first_individual_sessions), 0)
        # Handle the case where the recent session isn't the *first* individual tutoring session for the student
        # Reset original session (Turning session into second session for student and within 24 hours of now)
        self.individual_sts.start = self.now
        self.individual_sts.save()
        # Creating first session  for student
        other_session = StudentTutoringSession.objects.create(
            individual_session_tutor=self.tutor, student=self.student, start=self.now - timedelta(weeks=1)
        )
        # Expect notification to be sent, but zero recent_first_individual_sessions are generated
        noti_pks = json.loads(send_first_individual_tutoring_session_daily_digest())
        self.assertEqual(len(noti_pks), 1)
        noti_pk = noti_pks[0]
        noti = Notification.objects.get(pk=noti_pk)
        self.assertIsNotNone(noti.emailed)
        recent_first_individual_sessions = get_first_individual_tutoring_session_digest_details(noti)[
            "recent_first_individual_sessions"
        ]
        self.assertEqual(len(recent_first_individual_sessions), 0)
        # If other_session is in the future, expect notification to be sent and
        # to correctly identify original session (self.individual_sts) as first session
        other_session.start = self.now + timedelta(hours=1)
        other_session.save()
        noti_pks = json.loads(send_first_individual_tutoring_session_daily_digest())
        self.assertEqual(len(noti_pks), 1)
        noti_pk = noti_pks[0]
        noti = Notification.objects.get(pk=noti_pk)
        self.assertIsNotNone(noti.emailed)
        recent_first_individual_sessions = get_first_individual_tutoring_session_digest_details(noti)[
            "recent_first_individual_sessions"
        ]
        self.assertEqual(len(recent_first_individual_sessions), 1)
        session = recent_first_individual_sessions[0]
        student_hours = StudentTutoringPackagePurchaseManager(self.individual_sts.student).get_available_hours()
        self.assertEqual(session["student"], self.student.name)
        self.assertEqual(session["tutor"], self.tutor.name)
        self.assertEqual(session["start"], self.individual_sts.start)
        self.assertEqual(
            session["individual_curriculum"], max(0, student_hours["individual_curriculum"]),
        )
        self.assertEqual(session["individual_test_prep"], max(0, student_hours["individual_test_prep"]))
        self.assertEqual(session["group_test_prep"], max(0, student_hours["group_test_prep"]))


class TestUserNotifications(TestCase):
    """ python manage.py test snnotifications.tests.test_automated_notifications:TestUserNotifications """

    fixtures = ("fixture.json",)

    def setUp(self):
        # Delete other students and parents
        Student.objects.all().delete()
        Parent.objects.all().delete()
        student_serializer = StudentSerializer(
            data={"email": "s@mail.com", "first_name": "Student", "last_name": "Name", "invite": True,}
        )
        student_serializer.is_valid()
        self.student = student_serializer.save()
        # Just to be sure
        self.assertIsNotNone(self.student.last_invited)

    def test_first_invite_reminder(self):
        # First reminder not sent until NOTIFICATION_TASK_DUE
        invites_result = send_invite_reminder()
        self.assertEqual(len(invites_result["students"]), 0)
        # Put student creation in the past, now a reminder is sent
        self.student.created = timezone.now() - timedelta(minutes=INVITE_FIRST_REMINDER + 1)
        self.student.last_invited = self.student.created
        self.student.save()
        invites_result = send_invite_reminder()
        self.assertEqual(invites_result["students"], [self.student.pk])
        self.assertEqual(
            self.student.user.notification_recipient.notifications.last().notification_type, "invite_reminder",
        )
        # Reminder not sent again
        invites_result = send_invite_reminder()
        self.assertEqual(len(invites_result["students"]), 0)
        self.assertEqual(self.student.user.notification_recipient.notifications.count(), 2)

        # Finally, invite reminder not sent if invite was never sent
        self.student.save()
        self.student.user.notification_recipient.notifications.all().delete()
        invites_result = send_invite_reminder()
        self.assertEqual(len(invites_result["students"]), 0)
        self.assertFalse(self.student.user.notification_recipient.notifications.exists())

    def test_periodic_invite_reminder(self):
        # Send first reminder
        self.student.last_invited = timezone.now() - timedelta(minutes=INVITE_PERIODIC_REMINDER + 10)
        self.student.save()
        result = send_invite_reminder()
        self.assertEqual(result["students"], [self.student.pk])
        self.assertEqual(
            self.student.user.notification_recipient.notifications.last().notification_type, "invite_reminder",
        )
        # Ensure student last invited is updated
        self.assertGreater(
            Student.objects.get(pk=self.student.pk).last_invited, self.student.last_invited,
        )
        # Not resent
        invites_result = send_invite_reminder()
        self.assertEqual(len(invites_result["students"]), 0)
        self.assertEqual(self.student.user.notification_recipient.notifications.count(), 2)

        # Second reminder sent sent
        self.student.last_invited = timezone.now() - timedelta(minutes=INVITE_PERIODIC_REMINDER * 2 + 10)
        self.student.save()
        result = send_invite_reminder()
        self.assertEqual(result["students"], [self.student.pk])
        self.assertEqual(
            self.student.user.notification_recipient.notifications.last().notification_type, "invite_reminder",
        )
        # Ensure student last invited is updated
        self.assertGreater(
            Student.objects.get(pk=self.student.pk).last_invited, self.student.last_invited,
        )
        # Not resent
        invites_result = send_invite_reminder()
        self.assertEqual(len(invites_result["students"]), 0)
        self.assertEqual(self.student.user.notification_recipient.notifications.count(), 3)

        # Confirm not sent when initial invite wasn't sent
        self.student.last_invited = timezone.now() - timedelta(minutes=INVITE_PERIODIC_REMINDER * 2 + 10)
        self.student.save()
        self.student.user.notification_recipient.notifications.all().delete()
        result = send_invite_reminder()
        self.assertEqual(len(result["students"]), 0)
        self.assertFalse(self.student.user.notification_recipient.notifications.exists())
