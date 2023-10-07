""" Test celery tasks in cwtasks
    python manage.py test cwtasks.tests.test_task_tasks
"""
from datetime import timedelta
from django.core import mail

from django.test import TestCase
from django.utils import timezone

from cwnotifications.constants.constants import (
    NOTIFICATION_TASK_DUE_IN_LESS_THAN_HOURS,
    NOTIFICATION_TASK_OVERDUE_RECURRING,
)
from cwtasks.tasks import send_student_task_reminders
from cwtasks.models import TaskTemplate, Task
from cwtasks.tasks import MAX_REMINDER_HOURS
from snusers.models import Administrator, Parent, Student, Counselor, Tutor


class TestTaskTasks(TestCase):
    fixtures = ("fixture.json",)

    def setUp(self):
        self.now = timezone.now()
        self.admin = Administrator.objects.first()
        self.tutor = Tutor.objects.first()
        self.counselor = Counselor.objects.first()
        self.student = Student.objects.first()
        self.task = Task.objects.create(for_user=self.student.user, title="Test Task", due=timezone.now())
        self.student.counselor = self.counselor
        self.parent = Parent.objects.first()
        self.student.parent = self.parent
        self.student.save()

    def test_upcoming_task_notification(self):
        """ python manage.py test cwtasks.tests.test_task_tasks:TestTaskTasks.test_upcoming_task_notification """

        # Test more than most minutes away. No noti
        self.task.due = timezone.now() + timedelta(hours=NOTIFICATION_TASK_DUE_IN_LESS_THAN_HOURS + 1)
        self.task.save()
        result = send_student_task_reminders()
        self.assertEqual(len(result), 0)

        # Test between first and second noti. One noti sent
        self.task.due = timezone.now() + timedelta(hours=NOTIFICATION_TASK_DUE_IN_LESS_THAN_HOURS - 1)
        self.task.save()
        result = send_student_task_reminders()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.task.pk)
        self.task.refresh_from_db()
        self.assertTrue(self.task.last_reminder_sent)
        last_reminder = self.task.last_reminder_sent
        result = send_student_task_reminders()
        self.assertEqual(len(result), 0)

        # Final Noti
        self.task.due = timezone.now() + timedelta(minutes=30)
        self.task.last_reminder_sent = timezone.now() - timedelta(hours=MAX_REMINDER_HOURS + 1)
        self.task.save()
        result = send_student_task_reminders()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.task.pk)
        # Confirm that parent was copied
        message = mail.outbox[-1]
        self.assertEqual(message.cc, [self.parent.invitation_email])

        self.task.refresh_from_db()
        self.assertGreater(self.task.last_reminder_sent, last_reminder)
        result = send_student_task_reminders()
        self.assertEqual(len(result), 0)

        # Noti not sent if task due in the past
        self.task.last_reminder_sent = None
        self.task.due = timezone.now() - timedelta(minutes=2)
        result = send_student_task_reminders()
        self.assertEqual(len(result), 0)

    def test_invisible_counseling_task(self):
        # python manage.py test cwnotifications.tests.test_automated_notifications:TestTaskNotifications.test_invisible_counseling_task
        # Test to ensure that upcoming and overdue task noti are not sent for counseling student tasks where
        # visible_to_counseling_student is False or counseling_parent_task is True
        tt = TaskTemplate.objects.create(title="tt")
        self.task.task_template = tt
        self.task.visible_to_counseling_student = False
        self.task.due = timezone.now() + timedelta(hours=NOTIFICATION_TASK_DUE_IN_LESS_THAN_HOURS - 1)
        self.task.save()

        # Notification should NOT be sent because task is not visible
        result = send_student_task_reminders()
        self.assertEqual(len(result), 0)

        # Notification NOT sent when it's a parent task
        tt.counseling_parent_task = True
        tt.save()
        self.task.visible_to_counseling_student = True
        self.task.save()
        result = send_student_task_reminders()
        self.assertEqual(len(result), 0)

        # But notification is sent if task is visible to student
        tt.counseling_parent_task = False
        tt.save()
        result = send_student_task_reminders()
        self.assertEqual(len(result), 1)

    def test_overdue_task_notification(self):
        self.task.due = timezone.now() + timedelta(hours=60)
        self.task.save()
        result = send_student_task_reminders()
        self.assertEqual(len(result), 0)

        self.task.due = timezone.now() - timedelta(minutes=1)
        self.task.save()
        result = send_student_task_reminders()
        self.assertEqual(len(result), 1)
        self.task.refresh_from_db()
        self.assertTrue(self.task.last_reminder_sent)
        self.assertEqual(result[0], self.task.pk)
        # Only one noti is sent
        result = send_student_task_reminders()
        self.assertEqual(len(result), 0)
        self.task.due = timezone.now() - timedelta(minutes=NOTIFICATION_TASK_OVERDUE_RECURRING - 2)
        self.task.save()
        result = send_student_task_reminders()
        self.assertEqual(len(result), 0)

        # Another noti is sent
        self.task.last_reminder_sent = timezone.now() - timedelta(minutes=NOTIFICATION_TASK_OVERDUE_RECURRING + 2)
        self.task.due = timezone.now() - timedelta(minutes=NOTIFICATION_TASK_OVERDUE_RECURRING + 2)
        self.task.save()
        result = send_student_task_reminders()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.task.pk)
