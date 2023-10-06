""" This module contains utilities for interacting with the Magento (payments) API.
    Note that there are also views we expose for magento webhooks in the cwcommon views module
    This is for posting data TO magento
"""
import requests
import json
import logging
from decimal import Decimal
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from cwtutoring.models import (
    StudentTutoringSession,
    TutoringPackage,
    TutoringPackagePurchase,
)
from cwtutoring.constants import LATE_CANCEL_CHARGE
from cwusers.models import Student, Administrator
from cwnotifications.generator import create_notification
from sentry_sdk import configure_scope, capture_exception

PAYGO_API_ENDPOINT = f"{settings.MAGENTO_API_BASE}/rest/V1/existing-customer-charge"

TIMEOUT = 7  # seconds


class MagentoAPIManagerException(Exception):
    pass


class MagentoAPIManager:
    @staticmethod
    def execute_charge(
        last_order_id: str,
        description: str,
        amount: float,
        product_id="",
        tutor_id="",
        wisernet_id="",
        paygo_hours=None,
    ) -> str:
        """ Helper method to perform a request against the Magento API
            Returns object from body of response, but if returned you can assume it's successful because this method
            also handles reqeuest errors.
        """
        try:
            # We have our package - let's figure out the purchase :)
            payload = {
                "username": settings.MAGENTO_API_USERNAME,
                "password": settings.MAGENTO_API_PASSWORD,
                "last_order_id": last_order_id.replace("M", ""),
                "description": description,
                "amount": amount,
                "product_id": product_id,
                "tutor_id": tutor_id,
                "wisernet_id": wisernet_id,
            }
            if paygo_hours:
                paygo_hours["paygo_hours"] = paygo_hours
            response = requests.post(
                PAYGO_API_ENDPOINT, json=payload, headers={"Content-type": "application/json"}, timeout=TIMEOUT
            )
            if response.status_code == 200:
                return json.loads(response.content)[0]
            err = MagentoAPIManagerException("Non 200 Magento API Response")
            raise err
        # Rare place where we catch generic exception
        except Exception as err:
            if settings.DEBUG or settings.TESTING:
                print(response.status_code, response.content)
            else:
                logger = logging.getLogger("watchtower")
                del payload["password"]
                logger.info(f"Magento API Error: \n\n {str(response.content)} \n {str(payload)}")
                with configure_scope() as scope:
                    scope.set_context(
                        "Magento API Error",
                        {"status": response.status_code, "content": str(response.content), "payload": str(payload),},
                    )
                    capture_exception(err)

            ops_noti_data = {"notification_type": "ops_failed_charge", "additional_args": payload}
            student = Student.objects.filter(last_paygo_purchase_id=last_order_id).first()
            if student:
                ops_noti_data["related_object_pk"] = student.pk
                ops_noti_data["related_object_content_type"] = ContentType.objects.get_for_model(Student)
            for admin in Administrator.objects.all():
                create_notification(admin.user, **ops_noti_data)
            # Re-raise error for our parent to handle
            raise err

    @staticmethod
    def create_paygo_purchase(
        student_tutoring_session: StudentTutoringSession, tutoring_package: TutoringPackage
    ) -> TutoringPackagePurchase:
        """ Create a paygo purchase for a scheduled student tutoring session
            Arguments:
                student_tutoring_session {StudentTutoringSession} - session that purchase is being made for
                tutoring_package {TutoringPackage} - Force a particular package to be purchased.
                    If not set, we'll use TutoringPackageManager.get_paygo_tutoring_package
            Returns: TutoringPackagePurchase or False
        """
        student: Student = student_tutoring_session.student

        def raise_failure(exception):
            # Create a system notification so admins can see there was a failure
            create_notification(
                None,
                notification_type="ops_paygo_payment_failure",
                related_object_content_type=ContentType.objects.get_for_model(StudentTutoringSession),
                related_object_pk=student_tutoring_session.pk,
            )
            raise exception

        if not student.is_paygo or not student.last_paygo_purchase_id:
            raise_failure(
                MagentoAPIManagerException(
                    f"Cannot create paygo purchase for non paygo student {student_tutoring_session.student} {student_tutoring_session.student.pk}"
                )
            )

        if student_tutoring_session.paygo_transaction_id:
            raise_failure(
                MagentoAPIManagerException(f"Cannot charge for paygo ssession twice: {student_tutoring_session.pk}")
            )

        if not tutoring_package:
            raise_failure(
                MagentoAPIManagerException(f"Cannot identify paygo package to purchase {student_tutoring_session.pk}")
            )

        if not settings.MAGENTO_API_PASSWORD:
            raise_failure(MagentoAPIManagerException("No Magento API Password"))

        amount = float(Decimal(student_tutoring_session.duration_minutes) / Decimal(60.0) * tutoring_package.price)
        response = MagentoAPIManager.execute_charge(
            student.last_paygo_purchase_id.replace("M", ""),
            f"Payment for {student_tutoring_session}",
            amount,
            product_id=tutoring_package.product_id,
            wisernet_id=str(student.slug),
        )
        student_tutoring_session.paygo_transaction_id = response.get("transaction_id")
        student_tutoring_session.save()
        # Create tutoring package purchase
        hours = student_tutoring_session.duration_minutes / Decimal(60)
        package = None
        if hours != 1:
            (package, created) = TutoringPackage.objects.get_or_create(
                is_paygo_package=True,
                price=tutoring_package.price,
                individual_test_prep_hours=tutoring_package.individual_test_prep_hours * hours,
                individual_curriculum_hours=tutoring_package.individual_curriculum_hours * hours,
            )
            if created:
                package.active = False
                package.save()

        # System notification
        create_notification(
            None,
            notification_type="ops_paygo_payment_success",
            related_object_content_type=ContentType.objects.get_for_model(StudentTutoringSession),
            related_object_pk=student_tutoring_session.pk,
        )
        return TutoringPackagePurchase.objects.create(
            student=student_tutoring_session.student,
            tutoring_package=package if package else tutoring_package,
            price_paid=amount,
            paygo_transaction_id=response.get("transaction_id"),
        )

    @staticmethod
    def create_late_cancel_charge(
        student_tutoring_session: StudentTutoringSession, amount=LATE_CANCEL_CHARGE
    ) -> StudentTutoringSession:
        """ Execute a late cancel charge for a student tutoring session.
            Can only run a charge once, and can only charge students who have last transaction ID on file
            Returns updated StudentTutoringSession
        """
        if amount is None:
            amount = LATE_CANCEL_CHARGE
        student: Student = student_tutoring_session.student
        if not student.last_paygo_purchase_id:
            raise MagentoAPIManagerException("No student transaction ID on file")
        if student_tutoring_session.late_cancel_charge_transaction_id:
            raise MagentoAPIManagerException("Cannot create same charge for session that already has late charge")

        response = MagentoAPIManager.execute_charge(
            student.last_paygo_purchase_id,
            f"Late charge for {student_tutoring_session}",
            amount,
            wisernet_id=str(student.slug),
        )
        student_tutoring_session.late_cancel_charge_transaction_id = response.get("transaction_id")
        student_tutoring_session.save()
        return student_tutoring_session
