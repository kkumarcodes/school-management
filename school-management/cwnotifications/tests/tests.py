""" Test cwresources.utilities
    python manage.py test cwnotifications.tests.tests
"""
import json

from django.test import TestCase
from django.core.files.base import ContentFile
from django.shortcuts import reverse
from django.urls.exceptions import NoReverseMatch
from django.core import mail
from cwnotifications.mailer import send_email_for_notification

from snusers.models import Student, Administrator, Parent
from cwnotifications.models import NotificationRecipient, Notification


class TestNotificationRecipientView(TestCase):
    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.parent = Parent.objects.first()  # Not related to student
        self.student_recipient = NotificationRecipient.objects.create(user=self.student.user)
        self.parent_recipient = NotificationRecipient.objects.create(user=self.parent.user)
        self.admin = Administrator.objects.first()

    def test_update_recipient(self):
        """ TODO: Test updating other fields """
        url = reverse("notification_recipients-detail", kwargs={"pk": self.student_recipient.pk})
        data = {"phone_number": "12485656987"}
        # Can't update if not logged in
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Can't update as bad user
        self.client.force_login(self.parent.user)
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

        # Can update as student
        self.assertEqual(self.student_recipient.phone_number_verification_code, "")
        self.client.force_login(self.student.user)
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        # Verification code should have been set (and sent, but we don't send texts in test mode)
        self.assertEqual(result["phone_number"], data["phone_number"])
        self.student_recipient.refresh_from_db()
        self.assertEqual(len(self.student_recipient.phone_number_verification_code), 5)

        # Update as parent with option NOT to send verification. Confirm verification code NOT set
        self.client.force_login(self.parent.user)
        url = reverse("notification_recipients-detail", kwargs={"pk": self.parent_recipient.pk})
        response = self.client.patch(
            f"{url}?dont_send_verification=true", json.dumps(data), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.parent_recipient.refresh_from_db()
        self.assertEqual(self.parent_recipient.phone_number, data["phone_number"])
        self.assertEqual(len(self.parent_recipient.phone_number_verification_code), 0)

    def test_send_verification_code(self):
        self.assertEqual(self.student_recipient.phone_number_verification_code, "")
        self.assertIsNone(self.student_recipient.confirmation_last_sent)
        url = reverse("notification_recipients-send_verification", kwargs={"pk": self.student_recipient.pk},)
        self.assertEqual(self.client.post(url).status_code, 401)
        self.student_recipient.refresh_from_db()
        self.assertEqual(self.student_recipient.phone_number_verification_code, "")
        self.client.force_login(self.parent.user)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.student_recipient.refresh_from_db()
        self.assertEqual(self.student_recipient.phone_number_verification_code, "")

        # Success!
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.student_recipient.refresh_from_db()
        self.assertEqual(len(self.student_recipient.phone_number_verification_code), 5)
        old_code = self.student_recipient.phone_number_verification_code
        self.assertIsNotNone(self.student_recipient.confirmation_last_sent)
        old_last_sent = self.student_recipient.confirmation_last_sent

        # Admin, too!
        self.client.force_login(self.admin.user)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.student_recipient.refresh_from_db()
        self.assertEqual(len(self.student_recipient.phone_number_verification_code), 5)
        self.assertNotEqual(old_code, self.student_recipient.phone_number_verification_code)
        self.assertNotEqual(old_last_sent, self.student_recipient.confirmation_last_sent)

    def test_verify(self):
        # Set a verification code
        self.student_recipient.set_new_verification_code()
        self.student_recipient.refresh_from_db()
        self.assertEqual(len(self.student_recipient.phone_number_verification_code), 5)
        self.assertIsNone(self.student_recipient.phone_number_confirmed)

        # Bad user
        url = reverse("notification_recipients-attempt_verify", kwargs={"pk": self.student_recipient.pk},)
        self.assertEqual(
            self.client.post(url, json.dumps({"code": "12345"}), content_type="application/json").status_code, 401,
        )
        self.client.force_login(self.parent.user)
        self.assertEqual(
            self.client.post(url, json.dumps({"code": "12345"}), content_type="application/json").status_code, 403,
        )
        self.assertIsNone(self.student_recipient.phone_number_confirmed)

        # Bad code
        self.client.force_login(self.student.user)
        response = self.client.post(url, json.dumps({"code": "1234a"}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content).get("detail"), "Invalid verification code")
        self.assertIsNone(self.student_recipient.phone_number_confirmed)

        # Success! Confirm recipient updated properly and included in response
        response = self.client.post(
            url,
            json.dumps({"code": self.student_recipient.phone_number_verification_code}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertTrue(result["phone_number_is_confirmed"])
        self.student_recipient.refresh_from_db()
        self.assertIsNotNone(self.student_recipient.phone_number_confirmed)

    def test_no_retrieve(self):
        # No user can retrieve or list NotificationRecipient
        self.assertRaises(NoReverseMatch, lambda: reverse("notification_recipients-list"))

    def test_cc_from_parent_object(self):
        self.parent.cc_email = "test_cc@mail.com"
        self.parent.save()
        notification = Notification.objects.hidden_create(recipient=self.parent_recipient)
        notification.notification_type = "invite_reminder"
        notification.save()
        noti = send_email_for_notification(notification)

        # confirm email send to parent
        self.assertEqual(
            self.parent.user.notification_recipient.notifications.last().notification_type, "invite_reminder",
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].cc), 1)
        # test with different notification type
        notification.notification_type = "package_purchase_confirmation"
        notification.save()
        noti = send_email_for_notification(notification)
        self.assertEqual(
            self.parent.user.notification_recipient.notifications.last().notification_type,
            "package_purchase_confirmation",
        )
        self.assertEqual(len(mail.outbox[1].cc), 1)

