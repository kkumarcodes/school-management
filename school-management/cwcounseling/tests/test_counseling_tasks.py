""" Tests for our cwcounseling celery tasks (cwcounseling.tasks)
    python manage.py test cwcounseling.tests.test_counseling_tasks
"""
from datetime import timedelta
from django.core import mail
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
import pytz
from cwtasks.models import Task
from cwtasks.utilities.task_manager import TaskManager
from cwusers.models import Student, Counselor
from cwcounseling.models import CounselorMeeting
from cwcounseling.tasks import send_counselor_completed_task_digest, send_counselor_task_digest
from cwnotifications.models import Notification
from cwnotifications.constants import notification_types


class TestCounselorCompletedTaskDigest(TestCase):
    """ python manage.py test cwcounseling.tests.test_counseling_tasks:TestCounselorCompletedTaskDigest
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.counselor.set_timezone = "America/New_York"
        self.counselor.save()
        self.student.counselor = self.counselor
        self.student.save()

        self.tasks = [TaskManager.create_task(self.student.user, title=f"Test Task {i}") for i in range(3)]

    def test_send_digest(self):
        send_hour = timezone.now().astimezone(pytz.timezone(self.counselor.timezone)).hour
        # One completed task - Simple happy path
        self.tasks[0].completed = timezone.now() - timedelta(hours=1)
        self.tasks[1].completed = timezone.now() - timedelta(days=4)
        self.tasks[0].save()
        self.tasks[1].save()
        result = send_counselor_completed_task_digest(send_hour=send_hour)
        self.assertEqual(len(result), 1)
        noti: Notification = self.counselor.user.notification_recipient.notifications.last()
        self.assertEqual(noti.notification_type, notification_types.COUNSELOR_COMPLETED_TASKS)
        self.assertTrue(noti.emailed)
        self.assertEqual(len(noti.additional_args), 1)
        self.assertEqual(noti.additional_args[0], self.tasks[0].pk)

        # Confirm task appears in our email
        message = mail.outbox[-1]
        self.assertIn(self.tasks[0].title, str(message.alternatives[0][0]))
        self.assertIn(self.student.user.get_full_name(), str(message.alternatives[0][0]))

        # Idempotent
        result = send_counselor_completed_task_digest(send_hour=send_hour)
        self.assertEqual(len(result), 0)
        self.assertEqual(self.counselor.user.notification_recipient.notifications.count(), 1)
        noti.delete()

        # Archived tasks excluded
        self.tasks[0].archived = timezone.now()
        self.tasks[0].save()
        result = send_counselor_completed_task_digest(send_hour=send_hour)
        self.assertEqual(len(result), 0)
        self.assertEqual(self.counselor.user.notification_recipient.notifications.count(), 0)

        # Test timing
        self.tasks[0].archived = None
        self.tasks[0].save()
        self.counselor.set_timezone = "America/Los_Angeles"
        self.counselor.save()
        result = send_counselor_completed_task_digest(send_hour=send_hour)
        self.assertEqual(len(result), 0)
        # But just for good measure ensure that we would send if the counselor was in NY
        self.counselor.set_timezone = "America/New_York"
        self.counselor.save()
        result = send_counselor_completed_task_digest(send_hour=send_hour)
        self.assertEqual(len(result), 1)


class TestCounselorTaskDigest(TestCase):
    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.counselor_two = Counselor.objects.create(user=User.objects.create_user("c2"))
        self.student_two = Student.objects.create(user=User.objects.create_user("s2"), counselor=self.counselor_two)
        self.student.counselor = self.counselor
        self.student.save()
        self.counselor_meeting = CounselorMeeting.objects.create(
            student=self.student, start=timezone.now() + timedelta(hours=18), end=timezone.now() + timedelta(hours=19)
        )
        self.counselor_meeting_two = CounselorMeeting.objects.create(student=self.student_two,)
        self.student_tasks = [Task.objects.create(for_user=self.student.user, title=f"Task U {x}") for x in range(10)]
        [t.counselor_meetings.add(self.counselor_meeting) for t in self.student_tasks]
        self.student_two_tasks = [
            Task.objects.create(for_user=self.student_two.user, title=f"Task U {x}") for x in range(10)
        ]
        [t.counselor_meetings.add(self.counselor_meeting_two) for t in self.student_two_tasks]

    def test_send_digest(self):
        # Simple success - we send digest with all of student tasks
        result = send_counselor_task_digest(
            send_hour=timezone.now().astimezone(pytz.timezone(self.counselor.timezone)).hour
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.counselor.pk)
        self.assertEqual(
            Notification.objects.filter(notification_type=notification_types.COUNSELOR_TASK_DIGEST).count(), 1
        )
        n: Notification = Notification.objects.filter(notification_type=notification_types.COUNSELOR_TASK_DIGEST).last()
        self.assertEqual(n.recipient.user, self.counselor.user)
        self.assertEqual(len(n.additional_args), 10)

        # Idempotent - won't immediately send another noti
        self.assertEqual(
            len(
                send_counselor_task_digest(
                    send_hour=timezone.now().astimezone(pytz.timezone(self.counselor.timezone)).hour
                )
            ),
            0,
        )
        n.delete()

        # Confirm only coming due, overdue and meeting tasks are included
        self.student.user.tasks.all().delete()

        correct_tasks = []
        # One task is for meeting
        t = Task.objects.create(for_user=self.student.user)
        t.counselor_meetings.add(self.counselor_meeting)
        correct_tasks.append(t)
        # One task is coming due
        t = Task.objects.create(due=timezone.now() + timedelta(hours=12), for_user=self.student.user)
        correct_tasks.append(t)
        # Another task is coming due but is archived
        Task.objects.create(
            due=timezone.now() + timedelta(hours=12), for_user=self.student.user, archived=timezone.now()
        )
        # Another task is for meeting but completed
        t = Task.objects.create(for_user=self.student.user, completed=timezone.now())
        t.counselor_meetings.add(self.counselor_meeting)
        # Another task is overdue but completed
        Task.objects.create(
            due=timezone.now() + timedelta(hours=12), for_user=self.student.user, completed=timezone.now()
        )
        # Another task is for meeting but archived
        t = Task.objects.create(for_user=self.student.user, archived=timezone.now())
        t.counselor_meetings.add(self.counselor_meeting)

        send_counselor_task_digest(send_hour=timezone.now().astimezone(pytz.timezone(self.counselor.timezone)).hour)
        n: Notification = Notification.objects.filter(notification_type=notification_types.COUNSELOR_TASK_DIGEST).last()
        self.assertEqual(n.recipient.user, self.counselor.user)
        self.assertEqual(len(n.additional_args), len(correct_tasks))
        self.assertTrue(all([x.pk in n.additional_args for x in correct_tasks]))

        # Ensure tasks are in the actual email sent
        message = mail.outbox[-1]
        self.assertIn(self.student.invitation_name, str(message.alternatives[0][0]))
        for task in correct_tasks:
            self.assertIn(task.title, str(message.alternatives[0][0]))

    def test_send_hour(self):
        """ python manage.py test cwcounseling.tests.test_counseling_tasks:TestCounselorTaskDigest.test_send_hour
        """
        # Confirm that we only send after a certain hour in counselor local time
        # Send to first counselor
        self.counselor.set_timezone = "America/New_York"
        self.counselor.save()
        self.counselor_two.set_timezone = "America/Los_Angeles"
        self.counselor_two.save()
        self.counselor_meeting_two.start = self.counselor_meeting.start
        self.counselor_meeting_two.end = self.counselor_meeting.end
        self.counselor_meeting_two.save()

        result = send_counselor_task_digest(
            send_hour=timezone.now().astimezone(pytz.timezone(self.counselor.timezone)).hour
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.counselor.pk)

        result = send_counselor_task_digest(
            send_hour=timezone.now().astimezone(pytz.timezone(self.counselor.timezone)).hour
        )
        self.assertEqual(len(result), 0)

        # Finally we send to first counselor
        result = send_counselor_task_digest(
            send_hour=timezone.now().astimezone(pytz.timezone(self.counselor_two.timezone)).hour
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.counselor_two.pk)
