""" python manage.py test cwnotifications.tests.test_views """

import json
from datetime import timedelta

from django.test import TestCase
from django.shortcuts import reverse
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from cwusers.models import Student, Parent, Administrator, Tutor, Counselor
from cwnotifications.generator import create_notification
from cwnotifications.models import Notification
from cwcommon.utilities.magento import MagentoAPIManager, MagentoAPIManagerException
from cwtutoring.models import StudentTutoringSession
from cwtutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager
from cwtasks.utilities.task_manager import TaskManager
from cwtasks.models import Task

TEST_PAYLOAD = "cwcommon/tests/magento_test_payload.json"


class TestActivityLogView(TestCase):
    """ Test scenarios for retrieving activity log items (notifications)
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        # DRF Router Base URLs from cwusers.urls
        self.admin = Administrator.objects.first()
        self.parent = Parent.objects.first()
        self.counselor = Counselor.objects.first()
        self.student = Student.objects.first()
        self.tutor = Tutor.objects.first()
        self.student.parent = self.parent
        self.student.counselor = self.counselor
        self.student.counseling_student_types_list = [Student.COUNSELING_STUDENT_BASIC]
        self.student.save()
        self.student_url = reverse("activity_log_user", kwargs={"user_pk": self.student.user.pk})
        self.system_url = reverse("activity_log_system")

    def test_authentication_failure(self):
        # Must be logged in
        self.assertEqual(self.client.get(self.student_url).status_code, 401)
        self.assertEqual(self.client.get(self.system_url).status_code, 401)

        # Must be admin to get system notifications
        for user in (self.student.user, self.parent.user, self.counselor.user):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.system_url).status_code, 403)

        # No access to student
        self.student.parent = self.student.counselor = None
        self.student.save()
        for user in (self.parent.user, self.counselor.user):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.system_url).status_code, 403)

    def test_student_activity_log(self):
        # Create a few notifications
        notifications = [
            create_notification(self.student.user, notification_type="invite"),
            create_notification(self.student.user, notification_type="invite_reminder"),
        ]
        tasks = [TaskManager.create_task(self.student.user, title=f"Task {x}") for x in range(6)]
        for task in tasks:
            mgr = TaskManager(task)
            mgr.send_task_created_notification()
        notifications += list(
            Notification.objects.filter(related_object_content_type=ContentType.objects.get_for_model(Task))
        )

        create_notification(self.counselor.user, notification_type="invite")
        bad_task = TaskManager.create_task(self.counselor.user, title="Bad")
        mgr = TaskManager(bad_task)
        mgr.send_task_created_notification()
        self.assertTrue(
            Notification.objects.filter(
                notification_type="task",
                related_object_content_type=ContentType.objects.get_for_model(Task),
                related_object_pk=bad_task.pk,
            ).exists()
        )

        for user in (self.admin.user, self.student.user, self.counselor.user):
            self.client.force_login(user)
            response = self.client.get(self.student_url)
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            self.assertEqual(len(result), len(notifications))
            noti_pk = [str(x.slug) for x in notifications]
            for el in result:
                self.assertIn(el["slug"], noti_pk)
                self.assertNotEqual(el["activity_log_title"], "")
                self.assertIn("activity_log_description", el)

    def test_system_activity_log(self):
        # First we need to create a couple of system activity log items
        sts = StudentTutoringSession.objects.create(
            student=self.student,
            individual_session_tutor=self.tutor,
            start=timezone.now(),
            end=timezone.now() + timedelta(hours=1),
        )

        # Should raise exception since student is not paygo
        mgr = StudentTutoringPackagePurchaseManager(sts.student)
        tutoring_package = mgr.get_paygo_tutoring_package(sts)
        self.assertRaises(MagentoAPIManagerException, MagentoAPIManager.create_paygo_purchase, sts, tutoring_package)

        paygo_noti = Notification.objects.filter(
            recipient=None,
            notification_type="ops_paygo_payment_failure",
            related_object_content_type=ContentType.objects.get_for_model(StudentTutoringSession),
            related_object_pk=sts.pk,
        ).first()
        self.assertTrue(paygo_noti)

        # Create an ops_magento_webhook with test payload
        with open(TEST_PAYLOAD) as file_handle:
            payload = json.loads(file_handle.read())
        webhook_noti = create_notification(None, notification_type="ops_magento_webhook", additional_args=payload)

        # We create invites just to ensure they AREN'T included
        create_notification(self.student.user, notification_type="invite")
        create_notification(self.student.user, notification_type="invite_reminder")
        create_notification(self.counselor.user, notification_type="invite")

        self.client.force_login(self.admin.user)
        response = self.client.get(self.system_url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)
        for x in result:
            self.assertTrue(x["slug"] == str(webhook_noti.slug) or x["slug"] == str(paygo_noti.slug))
            self.assertNotEqual(x["activity_log_title"], "")
            self.assertIn("activity_log_description", x)
