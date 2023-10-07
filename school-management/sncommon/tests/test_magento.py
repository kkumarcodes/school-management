""" Test our views and utilities for interfacing with Magento
    python manage.py test sncommon.tests.test_magento
    python manage.py test sncommon.tests.test_magento:TestMagentoPurchaseWebhook.test_ambiguous_package
"""
import json

from datetime import timedelta
from django.test import TestCase
from django.shortcuts import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from sncounseling.constants import counseling_student_types
from sncounseling.models import CounselingHoursGrant, CounselingPackage, CounselorTimeEntry
from snnotifications.constants.notification_types import CAP_MAGENTO_STUDENT_CREATED, INVITE

from sntutoring.models import (
    TutoringPackage,
    GroupTutoringSession,
    TutoringPackagePurchase,
    Location,
)
from sntutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager
from snusers.serializers.users import CounselorSerializer
from snusers.models import Administrator, Student, Counselor, Parent
from snusers.utilities.managers import StudentManager
from snnotifications.models import Notification, NotificationRecipient

TEST_PAYLOAD = "sncommon/tests/magento_test_payload.json"
TEST_CAP_PAYLOAD = "sncommon/tests/cap_magento_payload.json"
TEST_SELF_ENROLL_PAYLOAD = "sncommon/tests/magento_self_enrollment_payload.json"
TEST_CAP_ORDER_ID = 6149
TEST_CAP_STUDENT_EMAIL = "greatstudent@student.edu"
TEST_CAP_HOURS = 1
TEST_MAGENTO_ORDER_ID = "1593"


class TestMagentoCounselingSelfEnrollment(TestCase):
    """ This tests counseling self-enrollments
        (i.e. using magento_webhook_handler.handle_self_enrollment_payload).
        Note that validation and authentication tests are handled in TestMagentoPurchaseWebhook

        python manage.py test sncommon.tests.test_magento:TestMagentoCounselingSelfEnrollment
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        with open(TEST_SELF_ENROLL_PAYLOAD) as file_handle:
            self.payload = json.loads(file_handle.read())

        # Need to create counselor with name matching test counselor
        counselor_split_name = self.payload["counselorName"].split(" ")
        counselor_serializer = CounselorSerializer(
            data={"first_name": counselor_split_name[0], "last_name": counselor_split_name[1], "email": "c@m.com",}
        )
        counselor_serializer.is_valid()
        self.counselor = counselor_serializer.save()
        self.admin = Administrator.objects.first()
        self.admin_token = Token.objects.create(user=self.admin.user)
        self.url = reverse("magento_purchase_webhook")

    def test_self_enrollment(self):
        response = self.client.post(
            self.url,
            json.dumps(self.payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)

        # Test to ensure student and parent are created
        student: Student = Student.objects.get(invitation_email=self.payload.get("mailing_student_email"))
        parent: Parent = student.parent
        self.assertEqual(parent.invitation_email, self.payload["shipping_address"]["email"])
        self.assertEqual(parent.user.username, parent.invitation_email)
        self.assertEqual(student.user.username, student.invitation_email)
        self.assertTrue(student.is_paygo)
        self.assertEqual(student.graduation_year, int(self.payload["graduation_year"]))
        self.assertEqual(student.counselor, self.counselor)
        self.assertTrue(counseling_student_types.PAYGO in student.counseling_student_types_list)

        # Test that notifications were sent to admin and counselor about new student
        self.admin.user.refresh_from_db()
        self.assertEqual(
            self.counselor.user.notification_recipient.notifications.last().notification_type,
            CAP_MAGENTO_STUDENT_CREATED,
        )

        # Confirm student was NOT invited
        self.assertFalse(Notification.objects.filter(notification_type=INVITE).exists())


class TestMagentoPurchaseWebhook(TestCase):
    """ This tests all scenarios for non self-enrollment payloads
        python manage.py test sncommon.tests.test_magento:TestMagentoPurchaseWebhook
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        with open(TEST_PAYLOAD) as file_handle:
            self.payload = json.loads(file_handle.read())

        data = self.payload["items"][0]
        self.group_session = GroupTutoringSession.objects.create(
            start=timezone.now(), end=timezone.now() + timedelta(hours=1), title="Test Group Session",
        )
        self.package = TutoringPackage.objects.create(
            sku=data["items"][0]["sku"], title="Test Package", individual_test_prep_hours=2, group_test_prep_hours=2,
        )
        self.package_two = TutoringPackage.objects.create(
            sku=data["items"][0]["sku"], title="Test Package 2", individual_test_prep_hours=2, group_test_prep_hours=2,
        )
        self.package.group_tutoring_sessions.add(self.group_session)
        self.url = reverse("magento_purchase_webhook")

        # Need to create counselor with name matching test counselor
        counselor_split_name = data["extension_attributes"]["counselorName"].split(" ")
        counselor_serializer = CounselorSerializer(
            data={"first_name": counselor_split_name[0], "last_name": counselor_split_name[1], "email": "c@m.com",}
        )
        counselor_serializer.is_valid()
        self.counselor = counselor_serializer.save()

        self.location = Location.objects.create(magento_id=data["store_id"], name="test")

        self.admin = Administrator.objects.first()
        self.admin_token = Token.objects.create(user=self.admin.user)

    def test_authentication(self):
        # Must be staff. Only allows for token authentication
        response = self.client.post(self.url, json.dumps(self.payload), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        counselor_token = Token.objects.create(user=self.counselor.user)
        response = self.client.post(
            self.url,
            json.dumps(self.payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(counselor_token)}",
        )
        self.assertEqual(response.status_code, 403)

        # Success!
        response = self.client.post(
            self.url,
            json.dumps(self.payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)

    def test_counseling_product(self):
        """ python manage.py test sncommon.tests.test_magento:TestMagentoPurchaseWebhook.test_counseling_product
        """

        data = self.payload["items"][0]
        # Confirm we update student counseling type
        student = Student.objects.first()
        student.invitation_email = data["extension_attributes"]["mailing_student_email"]
        student.counselor = Counselor.objects.first()
        student.save()
        student.user.email = student.user.username = student.invitation_email
        student.user.save()
        NotificationRecipient.objects.create(user=student.user)
        NotificationRecipient.objects.create(user=student.counselor.user)

        response = self.client.post(
            self.url,
            json.dumps(self.payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)
        student.refresh_from_db()
        self.assertTrue(student)
        self.assertListEqual(student.counseling_student_types_list, ["Test Package"])
        self.assertTrue(TutoringPackagePurchase.objects.filter(student=student, tutoring_package=self.package).exists())

        # Confirm counselor got notification that student was created
        student.counselor.refresh_from_db()
        self.assertTrue(
            student.counselor.user.notification_recipient.notifications.filter(
                notification_type="cas_magento_student_created"
            ).exists()
        )

        # Confirm we don't update for product ID that's not counseling product
        student.counseling_student_types_list = []
        student.save()
        data["items"][0]["product_id"] = 765
        data = self.payload["items"][0]
        response = self.client.post(
            self.url,
            json.dumps(self.payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        student.refresh_from_db()
        self.assertListEqual(student.counseling_student_types_list, [])

    def test_counseling_paygo(self):
        """ Test that paygo hours get added to a student using cap_magento_payload
            python manage.py test sncommon.tests.test_magento:TestMagentoPurchaseWebhook.test_counseling_paygo
        """
        with open(TEST_CAP_PAYLOAD) as file_handle:
            payload = json.loads(file_handle.read())
        response = self.client.post(
            self.url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)
        data = payload["items"][0]
        student: Student = Student.objects.filter(
            user__username=data["extension_attributes"]["mailing_student_email"]
        ).first()
        self.assertTrue(student)
        # Confirm that student is paygo
        self.assertTrue(student.is_paygo)
        self.assertEqual(student.counseling_hours_grants.count(), 1)
        self.assertEqual(student.counseling_hours_grants.first().number_of_hours, TEST_CAP_HOURS)

        # Confirm that price is on time entry
        hours_grant: CounselingHoursGrant = student.counseling_hours_grants.first()
        self.assertEqual(hours_grant.amount_paid, 350)

        # Idempotence. Magento sends us duplicate payloads. Confirm we don't make duplicate time entries in this case
        response = self.client.post(
            self.url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(student.counseling_hours_grants.count(), 1)

    def test_counseling_package(self):
        """ Test that when we see a counseling package for a part-time counselor
            (and only for a part-time counselor) we add the associated hours to the student
            python manage.py test sncommon.tests.test_magento:TestMagentoPurchaseWebhook.test_counseling_package
        """
        ESSAY_PACKAGE_NAME = "Essay Package"
        with open(TEST_CAP_PAYLOAD) as file_handle:
            payload = json.loads(file_handle.read())
            # We pop off the Paygo package, because this would create an hours grant
            payload["items"][0]["items"].pop(0)

        counseling_package: CounselingPackage = CounselingPackage.objects.create(
            package_name=ESSAY_PACKAGE_NAME, number_of_hours=13
        )
        response = self.client.post(
            self.url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        data = payload["items"][0]
        self.assertEqual(response.status_code, 200)
        student: Student = Student.objects.filter(
            user__username=data["extension_attributes"]["mailing_student_email"]
        ).first()
        self.assertTrue(student)
        # No package should have been created yet, because counselor is not part time
        self.assertFalse(student.counseling_hours_grants.exists())

        student.user.delete()

        # Should succeed this time because counselor is part time
        self.counselor.part_time = True
        self.counselor.save()
        response = self.client.post(
            self.url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        data = payload["items"][0]
        self.assertEqual(response.status_code, 200)
        student: Student = Student.objects.filter(
            user__username=data["extension_attributes"]["mailing_student_email"]
        ).first()
        self.assertEqual(student.counselor, self.counselor)
        self.assertTrue(student.counseling_hours_grants.exists())
        grant: CounselingHoursGrant = student.counseling_hours_grants.first()
        self.assertEqual(grant.counseling_package, counseling_package)
        self.assertEqual(grant.number_of_hours, counseling_package.number_of_hours)
        self.assertTrue(grant.include_in_hours_bank)

    def test_validation_fail(self):
        """ Test to ensure we properly validate data from magento before updating accounts/purchases
            in our system
        """
        pass

    def test_ambiguous_package(self):
        """ Test a case where we differentiate package by name, or have multiple packages at
            the same location
        """
        # Package One
        data = self.payload["items"][0]
        response = self.client.post(
            self.url,
            json.dumps(self.payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)
        student = Student.objects.filter(user__username=data["extension_attributes"]["mailing_student_email"]).first()
        self.assertTrue(student)
        self.assertTrue(TutoringPackagePurchase.objects.filter(student=student, tutoring_package=self.package).exists())

        # Confirm there is a system notification for webhook
        self.assertEqual(
            Notification.objects.filter(notification_type="ops_magento_webhook", recipient=None).count(), 1
        )

        TutoringPackagePurchase.objects.all().delete()
        payload = self.payload
        payload["items"][0]["items"][0]["name"] = self.package_two.title
        response = self.client.post(
            self.url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)
        student = Student.objects.filter(user__username=data["extension_attributes"]["mailing_student_email"]).first()
        self.assertTrue(student)
        self.assertTrue(
            TutoringPackagePurchase.objects.filter(student=student, tutoring_package=self.package_two).exists()
        )
        # Confirm there is a system notification for webhook
        self.assertEqual(
            Notification.objects.filter(notification_type="ops_magento_webhook", recipient=None).count(), 2
        )

    def test_paygo_hours(self):
        # Test creating student with multiple paygo hours (will result in multiple package purchases)
        data = self.payload
        data["items"][0]["items"][0]["paygo_total"] = "07:00"

        self.package.is_paygo_package = True
        self.package.individual_test_prep_hours = 1
        self.package.group_test_prep_hours = 0
        self.package.group_tutoring_sessions.clear()
        self.package.save()
        self.package_two.delete()

        response = self.client.post(
            self.url,
            json.dumps(self.payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)
        student: Student = Student.objects.filter(
            user__username=data["items"][0]["extension_attributes"]["mailing_student_email"]
        ).first()
        self.assertEqual(student.tutoring_package_purchases.count(), 7)
        mgr = StudentTutoringPackagePurchaseManager(student)
        hours = mgr.get_available_hours()
        self.assertEqual(hours["individual_test_prep"], 7)
        self.assertEqual(hours["individual_curriculum"], 0)
        self.assertEqual(hours["group_test_prep"], 0)

        # Confirm only one STS was created and only one notification was sent
        self.assertEqual(student.tutoring_sessions.count(), 0)
        self.assertEqual(
            Notification.objects.filter(
                recipient__user=student.user, notification_type="package_purchase_confirmation",
            ).count(),
            1,
        )

    def test_paygo_package(self):
        # Test to ensure that if there are two Paygo packages with our product ID, we use the one with the correct
        # number of hours, or the one with the fewest hours
        TutoringPackage.objects.all().delete()
        package_one: TutoringPackage = TutoringPackage.objects.create(
            individual_test_prep_hours=1, product_id=11, all_locations=True, is_paygo_package=True
        )
        package_two: TutoringPackage = TutoringPackage.objects.create(
            individual_test_prep_hours=5, product_id=11, all_locations=True, is_paygo_package=True
        )
        payload = self.payload

        for x in (1, 2, 3, 4, 6):
            payload["items"][0]["items"][0]["product_id"] = package_one.product_id
            payload["items"][0]["extension_attributes"]["paygo_total"] = f"0{x}:00"
            response = self.client.post(
                self.url,
                json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
            )
            self.assertEqual(response.status_code, 200)
            student: Student = Student.objects.last()
            # Create x package purchases, all for package one
            self.assertEqual(student.tutoring_package_purchases.count(), x)
            self.assertTrue(all([y.tutoring_package == package_one for y in student.tutoring_package_purchases.all()]))
            TutoringPackagePurchase.objects.all().delete()

        # For 5, we create a purchase of package two.
        payload["items"][0]["extension_attributes"]["paygo_total"] = f"05:00"
        response = self.client.post(
            self.url,
            json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)
        student: Student = Student.objects.last()
        self.assertEqual(student.tutoring_package_purchases.count(), 1)
        self.assertEqual(student.tutoring_package_purchases.first().tutoring_package, package_two)

    def test_create_student_parent(self):
        data = self.payload["items"][0]
        response = self.client.post(
            self.url,
            json.dumps(self.payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)

        # Confirm student details
        student = Student.objects.filter(user__username=data["extension_attributes"]["mailing_student_email"]).first()
        self.assertTrue(student)
        self.assertEqual(student.invitation_name, data["extension_attributes"]["student_name"])
        self.assertEqual(
            student.user.notification_recipient.phone_number,
            f"1{data['extension_attributes']['mailing_student_cell_phone']}",
        )
        self.assertEqual(student.counselor, self.counselor)
        self.assertEqual(
            str(student.graduation_year), str(data["extension_attributes"]["graduation_year"]),
        )
        self.assertEqual(student.location, self.location)

        # Confirm that admins were notified of student creation
        self.assertTrue(
            self.admin.user.notification_recipient.notifications.filter(
                notification_type="cas_magento_student_created", related_object_pk=student.pk,
            ).exists()
        )
        # Confirm that counselor was also notified
        self.assertTrue(
            self.counselor.user.notification_recipient.notifications.filter(
                notification_type="cap_magento_student_created", related_object_pk=student.pk,
            ).exists()
        )
        # Confirm that counselor won't get notified twice
        student_mgr = StudentManager(student)
        student_mgr.send_new_cas_student_notification()
        self.assertEqual(
            self.counselor.user.notification_recipient.notifications.filter(
                notification_type="cap_magento_student_created", related_object_pk=student.pk,
            ).count(),
            1,
        )

        # Confirm parent details
        parent = Parent.objects.filter(user__username=data["billing_address"]["email"]).first()
        self.assertTrue(parent)
        self.assertEqual(parent.user.email, data["billing_address"]["email"])
        # self.assertEqual(parent.address, data["billing_address"]["street"][0])
        # self.assertEqual(parent.city, data["billing_address"]["city"])
        # self.assertEqual(parent.country, data["billing_address"]["region_code"])
        self.assertEqual(
            parent.user.notification_recipient.phone_number, f"1{data['billing_address']['telephone']}",
        )
        self.assertEqual(student.parent, parent)

        # Confirm purchase
        purchase = TutoringPackagePurchase.objects.filter(
            student=student, tutoring_package__sku=data["items"][0]["sku"]
        ).first()
        self.assertTrue(purchase)
        self.assertEqual(purchase.magento_status_code, 200)
        # Pretty much just ensures we save magento payload properly
        self.assertEqual(purchase.magento_payload["price"], purchase.price_paid)
        self.assertEqual(purchase.price_paid, data["grand_total"])

        # Confirm student last_paygo_purchase_id
        self.assertEqual(purchase.student.last_paygo_purchase_id, str(data["items"][0]["order_id"]))

        # And student should have been signed up for group session
        self.assertTrue(student.tutoring_sessions.filter(group_tutoring_session=self.group_session).exists())

        # Confirm that both parent and student were sent invitations
        self.assertFalse(student.user.notification_recipient.notifications.filter(notification_type="invite").exists())
        self.assertFalse(parent.user.notification_recipient.notifications.filter(notification_type="invite").exists())

        # Test idempotency. Create a second package purchase. Resetting phone numbers changes their confirmation
        student_nr = student.user.notification_recipient
        student_nr.phone_number_confirmed = timezone.now()
        student_nr.save()
        self.payload["items"][0]["extension_attributes"]["mailing_student_cell_phone"] = ""
        response = self.client.post(
            self.url,
            json.dumps(self.payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)
        # Package wasn't created because same order id
        self.assertEqual(student.tutoring_package_purchases.count(), 1)
        self.payload["items"][0]["items"][0]["order_id"] = "new_order"
        response = self.client.post(
            self.url,
            json.dumps(self.payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {str(self.admin_token)}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(student.tutoring_package_purchases.count(), 2)
        student_nr.refresh_from_db()
        self.assertIsNone(student_nr.phone_number_confirmed)


""" Tests tests test UMS's interfacing with Magento API for executing charges
    These tests (temporarily?) disabled because the staging Magento API we were using
    is no longer available.
"""
# class TestPaygoChargeTask(TestCase):
#     """ python manage.py test sncommon.tests.test_magento:TestPaygoChargeTask
#         Test sncommon.tasks.charge_paygo_sessions
#     """

#     fixtures = ("fixture.json",)

#     def setUp(self):
#         self.student: Student = Student.objects.first()
#         self.tutor: Tutor = Tutor.objects.first()
#         self.student.tutors.add(self.tutor)
#         self.student.is_paygo = True
#         self.student.last_paygo_purchase_id = TEST_MAGENTO_ORDER_ID
#         self.student.save()
#         self.session = StudentTutoringSession.objects.create(
#             student=self.student,
#             individual_session_tutor=self.student.tutors.first(),
#             duration_minutes=60,
#             session_type=StudentTutoringSession.SESSION_TYPE_CURRICULUM,
#             start=timezone.now(),
#             end=timezone.now() + timedelta(hours=1),
#         )
#         self.tutoring_package = TutoringPackage.objects.create(
#             individual_curriculum_hours=1,
#             is_paygo_package=True,
#             price=50,
#             restricted_tutor=self.session.individual_session_tutor,
#         )

#     def test_create_charge_success(self):
#         mgr = StudentTutoringPackagePurchaseManager(self.student)
#         self.assertEqual(mgr.get_available_hours()["individual_curriculum"], -1)

#         # No charge because session isn't old enough
#         result = charge_paygo_sessions()
#         self.assertEqual(len(result["charged"]), 0)
#         self.assertEqual(len(result["errors"]), 0)

#         # Make session super long ago. Now it should get charged!
#         self.session.start = timezone.now() - timedelta(hours=20)
#         self.session.end = self.session.start + timedelta(hours=1)
#         self.session.save()

#         # Ensure student has negative hours
#         mgr = StudentTutoringPackagePurchaseManager(self.student)
#         self.assertEqual(mgr.get_available_hours()["individual_curriculum"], -1)
#         self.session.refresh_from_db()
#         self.assertEqual(self.session.paygo_transaction_id, "")

#         # Tentative sessions not picked up
#         self.session.is_tentative = True
#         self.session.save()
#         result = charge_paygo_sessions()
#         self.assertEqual(len(result["errors"]), 0)
#         self.assertEqual(len(result["charged"]), 0)

#         # Non tentative session is charged
#         self.session.is_tentative = False
#         self.session.save()
#         result = charge_paygo_sessions()
#         self.assertEqual(len(result["errors"]), 0)
#         self.assertEqual(len(result["charged"]), 1)

#         # Confirm system notification
#         self.assertTrue(
#             Notification.objects.filter(
#                 recipient=None,
#                 notification_type="ops_paygo_payment_success",
#                 related_object_content_type=ContentType.objects.get_for_model(StudentTutoringSession),
#                 related_object_pk=self.session.pk,
#                 emailed=None,
#             ).exists()
#         )

#         self.session.refresh_from_db()
#         self.assertNotEqual(self.session.paygo_transaction_id, "")
#         purchase = TutoringPackagePurchase.objects.last()
#         self.assertEqual(purchase.student, self.student)
#         self.assertEqual(purchase.paygo_transaction_id, self.session.paygo_transaction_id)
#         # Student back to 0 hours
#         mgr = StudentTutoringPackagePurchaseManager(self.student)
#         self.assertEqual(mgr.get_available_hours()["individual_curriculum"], 0)

#         # Don't charge twice
#         result = charge_paygo_sessions()
#         self.assertEqual(len(result["charged"]), 0)
#         self.assertEqual(len(result["errors"]), 0)

#     def test_create_charge_fail(self):
#         self.student.last_paygo_purchase_id = ""
#         self.student.save()

#         # Make session super long ago. Now it should get charged!
#         self.session.start = timezone.now() - timedelta(hours=40)
#         self.session.end = self.session.start + timedelta(hours=1)
#         self.session.save()

#         result = charge_paygo_sessions()
#         self.assertEqual(len(result["charged"]), 0)
#         self.assertEqual(len(result["errors"]), 0)
#         self.assertEqual(self.session.paygo_transaction_id, "")


# class TestMagentoPaygoAPI(TestCase):
#     """ Test making a purchase through the Magento Paygo API
#         python manage.py test sncommon.tests.test_magento:TestMagentoPaygoAPI.test_view
#     """

#     fixtures = ("fixture.json",)

#     def setUp(self):
#         self.student: Student = Student.objects.first()
#         self.tutor: Tutor = Tutor.objects.first()
#         self.student.tutors.add(self.tutor)
#         self.session = StudentTutoringSession.objects.create(
#             student=self.student,
#             individual_session_tutor=self.student.tutors.first(),
#             duration_minutes=60,
#             session_type=StudentTutoringSession.SESSION_TYPE_CURRICULUM,
#             start=timezone.now(),
#             end=timezone.now() + timedelta(hours=1),
#         )
#         self.tutoring_package = TutoringPackage.objects.create(
#             individual_curriculum_hours=1,
#             is_paygo_package=True,
#             price=50,
#             restricted_tutor=self.session.individual_session_tutor,
#         )

#     def test_view(self):
#         self.student.is_paygo = True
#         self.student.last_paygo_purchase_id = TEST_MAGENTO_ORDER_ID
#         self.student.save()
#         # Student pays for session via API
#         url = reverse("magento_paygo_purchase")
#         payload = {"student_tutoring_session": self.session.pk}
#         # Confirm student has negative hours before purchase, and then 0 after
#         mgr = StudentTutoringPackagePurchaseManager(self.student)
#         self.assertEqual(mgr.get_available_hours()["individual_curriculum"], -1)

#         self.client.force_login(self.student.user)
#         response = self.client.post(url, json.dumps(payload), content_type="application/json")
#         self.assertEqual(response.status_code, 200)
#         purchase = TutoringPackagePurchase.objects.last()
#         self.assertEqual(purchase.student, self.student)
#         self.assertEqual(purchase.tutoring_package, self.tutoring_package)
#         self.assertEqual(
#             json.loads(response.content).get("hours", {}).get("individual_curriculum"), 0,
#         )
#         self.assertEqual(mgr.get_available_hours()["individual_curriculum"], 0)
#         self.session.refresh_from_db()
#         self.assertNotEqual(self.session.paygo_transaction_id, "")
#         self.assertEqual(purchase.paygo_transaction_id, self.session.paygo_transaction_id)

#         # Must have access to student
#         purchase.delete()
#         self.client.force_login(Parent.objects.first().user)
#         response = self.client.post(url, json.dumps(payload), content_type="application/json")
#         self.assertEqual(response.status_code, 403)

#         # Student must be paygo and have last purchase ID
#         self.student.last_paygo_purchase_id = ""
#         self.student.save()
#         self.client.force_login(self.student.user)
#         response = self.client.post(url, json.dumps(payload), content_type="application/json")
#         self.assertEqual(response.status_code, 400)

#     def test_purchase_failure(self):
#         # Fails if student is not paygo or does not have last order ID
#         def create_purchase(session):
#             mgr = StudentTutoringPackagePurchaseManager(session.student)
#             tutoring_package = mgr.get_paygo_tutoring_package(session)
#             return MagentoAPIManager.create_paygo_purchase(session, tutoring_package)

#         self.assertRaises(MagentoAPIManagerException, create_purchase, self.session)
#         self.student.is_paygo = True
#         self.student.save()
#         self.assertRaises(MagentoAPIManagerException, create_purchase, self.session)

#         # Can't double charge
#         self.student.is_paygo = True
#         self.student.last_paygo_purchase_id = "1593"
#         self.student.save()
#         self.session.refresh_from_db()
#         purchase = create_purchase(self.session)
#         self.session.refresh_from_db()
#         self.assertNotEqual(self.session.paygo_transaction_id, "")
#         self.assertRaises(MagentoAPIManagerException, create_purchase, self.session)

#         # Confirm system notification
#         self.assertTrue(
#             Notification.objects.filter(
#                 recipient=None,
#                 notification_type="ops_paygo_payment_failure",
#                 related_object_content_type=ContentType.objects.get_for_model(StudentTutoringSession),
#                 related_object_pk=self.session.pk,
#                 emailed=None,
#             ).exists()
#         )

#     def test_purchase_success(self):
#         self.student.is_paygo = True
#         self.student.last_paygo_purchase_id = TEST_MAGENTO_ORDER_ID
#         self.student.save()
#         mgr = StudentTutoringPackagePurchaseManager(self.student)
#         tutoring_package = mgr.get_paygo_tutoring_package(self.session)
#         tutoring_package_purchase = MagentoAPIManager.create_paygo_purchase(self.session, tutoring_package)
#         self.assertTrue(tutoring_package_purchase)
#         self.assertEqual(tutoring_package_purchase.tutoring_package, self.tutoring_package)
#         self.assertEqual(tutoring_package_purchase.student, self.student)
#         self.assertEqual(tutoring_package_purchase.price_paid, self.tutoring_package.price)

#         # New package is created for 1.5 hours
#         tutoring_package_purchase.delete()
#         self.session.duration_minutes = 75
#         self.session.paygo_transaction_id = ""
#         self.session.save()
#         tutoring_package_purchase = MagentoAPIManager.create_paygo_purchase(self.session, tutoring_package)
#         self.assertTrue(tutoring_package_purchase)
#         self.assertNotEqual(tutoring_package_purchase.tutoring_package, self.tutoring_package)
#         self.assertEqual(tutoring_package_purchase.tutoring_package.individual_curriculum_hours, 1.25)
#         self.assertEqual(tutoring_package_purchase.student, self.student)
#         self.assertEqual(tutoring_package_purchase.price_paid, self.tutoring_package.price * 1.25)

