""" Test cwtasks.tasks
"""

from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from cwusers.models import Student
from cwnotifications.models import Notification
from cwtasks.models import Task, TaskTemplate
from cwtasks.tasks import send_daily_task_digest
from cwtasks.utilities.task_manager import TaskManager


class TestTaskDigest(TestCase):
    """ python manage.py test cwtasks.tests.test_tasks:TestTaskDigest
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()

    def test_send_task_digest(self):
        # Doesn't send when there are no tasks
        sent_digests = send_daily_task_digest()
        self.assertEqual(len(sent_digests), 0)
        self.assertFalse(Notification.objects.exists())

        # Sends for CAP task
        task: Task = TaskManager.create_task(self.student.user, title="Test Task")
        self.assertFalse(task.is_cap)
        self.assertIsNotNone(task.assigned_time)
        sent_digests = send_daily_task_digest()
        self.assertEqual(len(sent_digests), 1)
        self.assertEqual(Notification.objects.count(), 1)
        # Idempotentent
        self.assertEqual(len(send_daily_task_digest()), 0)
        Notification.objects.all().delete()

        # Doesn't send for completed task
        task.completed = timezone.now()
        task.save()
        self.assertEqual(len(send_daily_task_digest()), 0)
        task.delete()

        # Doesn't seend for CAP tasks that aren't visible to student
        task_template = TaskTemplate.objects.create(title="TT")
        task: Task = TaskManager.create_task(self.student.user, task_template=task_template, title="Test Task")
        task.assigned_time = timezone.now() - timedelta(hours=1)
        task.save()
        self.assertEqual(len(send_daily_task_digest()), 0)
        task.visible_to_counseling_student = True
        task.save()
        self.assertEqual(len(send_daily_task_digest()), 1)

        # Resends after 24
        self.assertEqual(len(send_daily_task_digest()), 0)
        noti = Notification.objects.last()
        noti.created = timezone.now() - timedelta(hours=25)
        noti.save()
        self.assertEqual(len(send_daily_task_digest()), 1)
        self.assertEqual(len(send_daily_task_digest()), 0)
