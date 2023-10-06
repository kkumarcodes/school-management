""" Views for interacting with magento, which is used across both CAS and counseling platforms to execute
    purchases and create accounts
"""
from datetime import datetime
from decimal import Decimal
import logging
import re
from uuid import uuid4
from sentry_sdk import configure_scope, capture_exception

from django.db.models import Q, F, Sum
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from cwcounseling.models import CounselingPackage
from cwcounseling.utilities.counseling_hours_manager import CounselingHoursManager

from cwusers.constants.counseling_student_types import COUNSELING_PRODUCT_IDS
from cwusers.utilities.managers import StudentManager
from cwusers.models import Student, Parent, Counselor
from cwusers.serializers.users import StudentSerializer, ParentSerializer
from cwusers.mixins import AccessStudentPermission
from cwusers.utilities.hubspot_manager import HubspotDealManager
from cwtutoring.models import (
    TutoringPackagePurchase,
    TutoringPackage,
    Location,
    StudentTutoringSession,
)
from cwtutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager
from cwtutoring.serializers.tutoring_sessions import StudentTutoringSessionSerializer
from cwtutoring.utilities.tutoring_session_manager import TutoringSessionManager
from cwnotifications.generator import create_notification
from cwcommon.utilities.magento import MagentoAPIManager, MagentoAPIManagerException
from cwcommon.utilities.magento_webhook_handler import handle_self_enrollment_payload

REQUIRED_FIELDS = {
    # Fields that must be on every item
    "item": ["price", "order_id", "sku", "product_id"],
    # Required nested objects (MUST ALSO APPEAR AS KEYS BELOW)
    "nested": ["billing_address", "payment", "extension_attributes"],
    # Fields on nested (single) objects
    "billing_address": ["email", "firstname", "lastname", "parent_id", "telephone"],
    "payment": [],
    "extension_attributes": [
        "studentEmail",
        "student_name",
        "graduation_year",
        "mailing_student_email",
        "mailing_student_cell_phone",
        "associated_vids",
    ],
}


class MagentoPurchaseWebhookException(Exception):
    pass


class MagentoPurchaseWebhookView(APIView):
    permission_classes = (IsAdminUser,)
    authentication_classes = (TokenAuthentication,)

    def _validate_data(self, data):
        """ Ensure all the fields we need are present
            Returns array of errors (or empty array if no errors)
        """
        errors = []
        if len(data.get("items", [])) == 0:
            errors.append("Invalid items array")
        for idx, item in enumerate(data["items"]):
            for key in REQUIRED_FIELDS["item"]:
                if key not in item:
                    errors.append(f"item {idx} missing field {key}")
        for key in REQUIRED_FIELDS["nested"]:
            if not (key in data and isinstance(data.get(key), dict)):
                errors.append(f"Missing field {key}")
            else:
                # Ensure nested fields are correct
                for nested_key in REQUIRED_FIELDS[key]:
                    if nested_key not in data[key]:
                        errors.append(f"{key} missing field {nested_key}")
        return errors

    def _create_package_purchase(
        self, student: Student, package: TutoringPackage, itemData, paygo_duplicate=False,
    ):
        """ Utlity method to create a package purchase for a student
            Arguments:
                student {Student} Student that purchase is for
                package {TutoringPackage} Package that is being purchased
                itemData {Object representing Item data from Magento payload}
                paygo_duplicate {Boolean} For paygo orders, we duplicate buying the same 1 hour package
                    over and over. Set this to True to suppress extra notifications
        """

        purchase_mgr = StudentTutoringPackagePurchaseManager(student)
        purchase: TutoringPackagePurchase = purchase_mgr.purchase_package(
            package,
            paid=itemData.get("price", package.price),
            purchaser=student.parent.user if student.parent else student.user,
            send_noti=not paygo_duplicate,
        )[0]
        purchase.magento_payload = itemData
        purchase.magento_status_code = 200
        purchase.sku = itemData["sku"]
        purchase.payment_confirmation = itemData["order_id"]
        purchase.save()

        return purchase

    def post(self, request, *args, **kwargs):
        """ We get a magento webhook post
            Details: https://drive.google.com/file/d/1WpOi4agL1PYYc7V8cV4EAB1L_-Kra-zG/view?usp=sharing
        """
        if not settings.TESTING:
            logger = logging.getLogger("watchtower")
            logger.info(f"Magento Webhook: \n\n {str(request.data)}")

        package = student = None

        items = request.data.get("items", [])
        data = {}
        if not (isinstance(items, list) and len(items) == 1):
            # We moved business logic for handling self-enrollemnts into a utility.
            # Up next (TODO:) The monstrosity below
            handle_self_enrollment_payload(request.data)
            return Response({})
        else:
            data = items[0]
            errors = self._validate_data(data)

        # We create a system notification so this post appears in webhook
        create_notification(None, notification_type="ops_magento_webhook", additional_args=data)

        # Get or create student via email
        student_created = False
        magento_student_email = data["extension_attributes"].get("studentEmail")
        if magento_student_email == "None":
            magento_student_email = None
        if not errors:
            student = Student.objects.filter(
                Q(user__username__iexact=magento_student_email)
                | Q(user__username__iexact=data["extension_attributes"]["mailing_student_email"])
                # Student matches on name and parent matches on email. Alot of times parents leave off student
                # email or use a different email from what's already on file in UMS
                | Q(
                    Q(invitation_name__iexact=data["extension_attributes"]["student_name"])
                    & Q(parent__user__email__iexact=data["billing_address"]["email"])
                )
            ).first()
            student_created = not student
            student_name = data["extension_attributes"]["student_name"]
            split_name = student_name.split(" ")
            payload_counselor = None
            if data["extension_attributes"].get("counselorName"):
                payload_counselor = Counselor.objects.filter(
                    invitation_name__iexact=data["extension_attributes"]["counselorName"]
                ).first()
            if not payload_counselor and data["extension_attributes"].get("dealId"):
                payload_counselor_name = HubspotDealManager.get_counselor_name(data["extension_attributes"]["dealId"])
                payload_counselor = Counselor.objects.filter(invitation_name__iexact=payload_counselor_name).first()

            student_email = magento_student_email or data["extension_attributes"].get("mailing_student_email")
            if not student_email:
                # We create a fake student email so that we can still create account
                student_email = f"{uuid4()}@wisernet.collegewise.com"
            graduation_year = data["extension_attributes"]["graduation_year"]
            if graduation_year == "None":
                graduation_year = datetime.now().year + 1
            student_data = {
                "first_name": split_name[0],
                "invite": True,
                "last_name": split_name[-1] if len(split_name) > 1 else "",
                "email": student_email,
                "graduation_year": graduation_year,
            }
            if payload_counselor:
                student_data["counselor"] = payload_counselor.pk
                student_data["invite"] = False
            payload_location = Location.objects.filter(magento_id=data["store_id"]).first()
            if payload_location:
                student_data["location_id"] = payload_location.pk
            student_serializer = StudentSerializer(instance=student, data=student_data)
            if not student_serializer.is_valid():
                errors.append(f"Invalid student data. Errors: {str(student_serializer.errors)}")
            else:
                student = student_serializer.save()
                # Set student's phone number
                if "mailing_student_cell_phone" in data["extension_attributes"]:

                    student_notification_recipient = student.user.notification_recipient
                    phone = re.sub("[^0-9]", "", data["extension_attributes"]["mailing_student_cell_phone"])
                    old_phone = student_notification_recipient.phone_number
                    student_notification_recipient.phone_number = f"1{phone}" if len(phone) == 10 else phone
                    # Reset phone verification
                    if old_phone != student_notification_recipient.phone_number:
                        student_notification_recipient.phone_number_confirmed = None

                    student_notification_recipient.save()
        # Get or create parent
        if not errors:
            # We only create parent if they are different from the student
            parent = Parent.objects.filter(user__username__iexact=data["billing_address"]["email"]).first()
            parent_data = {
                "invite": student_data["invite"],
                "first_name": data["billing_address"]["firstname"],
                "last_name": data["billing_address"]["lastname"],
                "email": data["billing_address"]["email"],
                # "address": data["billing_address"]["street"][0],
                # "address_line_two": data["billing_address"]["street"][1]
                # if len(data["billing_address"]["street"]) > 1
                # else "",
                # "city": data["billing_address"]["city"],
                # "zip_code": data["billing_address"]["postcode"],
                # "state": data["billing_address"]["region_code"],
            }
            serializer = ParentSerializer(instance=parent, data=parent_data)
            if not serializer.is_valid():
                # If parent and student have the same email, then we just create the student account
                if parent_data["email"].lower() != student_data["email"].lower():
                    errors.append(f"Invalid parent data Errors: {str(serializer.errors)}")
            else:
                parent = serializer.save()

                # Set parent's phone number
                if data["billing_address"].get("telephone"):
                    parent_notification_recipient = parent.user.notification_recipient
                    phone = data["billing_address"]["telephone"]
                    old_phone = parent_notification_recipient.phone_number
                    parent_notification_recipient.phone_number = f"1{phone}" if len(phone) == 10 else phone
                    if old_phone != parent_notification_recipient.phone_number:
                        parent_notification_recipient.phone_number_confirmed = None
                    parent_notification_recipient.save()

                # Set student's parent
                student_manager = StudentManager(student)
                student = student_manager.set_parent(parent)

        # Create package purchase
        student_had_tutoring_package = student and not student_created and student.tutoring_package_purchases.exists()
        if not errors:
            for item in data["items"]:
                package = None
                paygo_hours_field = item.get("paygo_total", data["extension_attributes"].get("paygo_total", "00:00"))

                counseling_package = CounselingPackage.objects.filter(package_name__iexact=item.get("name")).first()

                # We determine whether or not this is a counseling package, in which case we just add product name to
                # student's product types list
                if item.get("name") and item.get("product_id") in COUNSELING_PRODUCT_IDS:
                    if item["name"].strip() not in student.counseling_student_types_list:
                        student.counseling_student_types_list.append(item["name"].strip())
                        student.save()
                    paygo_total = item.get("paygo_total")
                    if paygo_total and ":" in paygo_total:
                        try:
                            hours = int(paygo_total.split(":")[0])
                            minutes = int(paygo_total.split(":")[1])
                            # Add paygo hours as time entry
                            paid = item.get("price", None)
                            if paid:
                                paid = Decimal(paid)
                            hours_manager = CounselingHoursManager(student)
                            description = f"Created via Magento order ID {item.get('order_id')}"
                            # For some reason, Magento sometimes sends us duplicate orders. This prevents
                            # us creating duplicate time entries
                            if not student.counseling_hours_grants.filter(note=description).exists():
                                hours_manager.add_hours(
                                    (hours + minutes / 60.0),
                                    note=description,
                                    amount_paid=paid,
                                    magento_id=item.get("order_id", ""),
                                )
                            student.is_paygo = True
                            student.save()
                        except ValueError:
                            with configure_scope() as scope:
                                scope.set_context("Magento Payload Item", {"item": item, "paygo_total": paygo_total})
                                capture_exception(MagentoPurchaseWebhookException("Paygo total error for CAP package"))
                if counseling_package and student.counselor.part_time:
                    # Add hours to full-package student for part-time counselor
                    hours_manager = CounselingHoursManager(student)
                    try:
                        hours_manager.add_hours(
                            counseling_package.number_of_hours,
                            amount_paid=Decimal(item["price"]) if item.get("price") else None,
                            magento_id=item.get("order_id"),
                            package=counseling_package,
                        )
                    except ValueError:
                        with configure_scope() as scope:
                            scope.set_context("Magento Payload Item", {"item": item, "paygo_total": paygo_total})
                            capture_exception(
                                MagentoPurchaseWebhookException("Counseling Hours Grant error for CAP Package")
                            )

                if isinstance(paygo_hours_field, str):
                    paygo_hours_split = paygo_hours_field.split(":")[0] or 1
                else:
                    paygo_hours_split = int(paygo_hours_field)
                paygo_hours = int(paygo_hours_split)
                # We attempt to find package with associated SKU or product_id. Note that multiple products
                # can have same product ID, in which case we use product name to break ties
                packages = TutoringPackage.objects.filter(Q(Q(sku=item["sku"]) | Q(product_id=item["product_id"])))
                if packages.count() == 1:
                    package = packages.first()
                elif packages.count() > 1:
                    # First try and match on pending enrollment course
                    restricted_tutor_filter = Q(Q(restricted_tutor__students=student) | Q(restricted_tutor=None))
                    filtered_packages = TutoringPackage.objects.none()
                    if packages.filter(courses__pending_enrollment_students=student).exists():
                        package = packages.filter(courses__pending_enrollment_students=student).first()
                    elif packages.filter(restricted_tutor_filter, locations__id=item.get("store_id")).exists():
                        # Try location match
                        filtered_packages = packages.filter(restricted_tutor_filter, locations__id=item.get("store_id"))
                    if (
                        not package
                        and not filtered_packages.exists()
                        and packages.filter(restricted_tutor_filter, all_locations=True).exists()
                    ):
                        # Try to find package available at all locations
                        filtered_packages = packages.filter(restricted_tutor_filter, all_locations=True)
                    if (
                        not package
                        and not filtered_packages.exists()
                        and packages.filter(restricted_tutor_filter, title__iexact=item.get("name")).exists()
                    ):
                        # Try name match
                        filtered_packages = packages.filter(restricted_tutor_filter, title__iexact=item.get("name"))

                    # Alright so we have filtered packages. We should try and find one that matches our hours.
                    # Otherwise we just take the one with the fewest hours
                    if filtered_packages.exists():
                        package = (
                            filtered_packages.filter(is_paygo_package=True,)
                            .filter(
                                Q(
                                    Q(individual_test_prep_hours=paygo_hours)
                                    | Q(individual_curriculum_hours=paygo_hours)
                                )
                            )
                            .first()
                        )
                        if not package:
                            # Get the package with the fewest hours. This will be one hour.
                            # We then duplicate this package with multiple package purchases below to get correct
                            # number of paygo hours on student
                            package = (
                                filtered_packages.annotate(
                                    ind_hours=Sum(F("individual_test_prep_hours") + F("individual_curriculum_hours"))
                                )
                                .filter(ind_hours__gt=0)
                                .order_by("ind_hours")
                                .first()
                            )

                    if not package and packages.exists():
                        # Fine, we'll just take an arbitrary package
                        package = packages.first()

                if not package:
                    if not (settings.TESTING or settings.DEBUG):
                        with configure_scope() as scope:
                            scope.set_context(
                                "magento_webhook_errors",
                                {
                                    "errors": errors,
                                    "sku": item["sku"],
                                    "product_id": item["product_id"],
                                    "product_name": item["name"],
                                },
                            )
                            capture_exception(MagentoPurchaseWebhookException("Missing product SKU or Product ID"))
                else:
                    # Try not to duplicate purchases
                    purchase = TutoringPackagePurchase.objects.filter(
                        student=student, payment_confirmation=item["order_id"], purchase_reversed=None,
                    ).first()
                    if not purchase:
                        purchase = self._create_package_purchase(student, package, item)
                        student.last_paygo_purchase_id = purchase.payment_confirmation
                        student.save()

                        # If this is a paygo product and total
                        if package.is_paygo_package and paygo_hours > 1:
                            # Duplicate the package to get the correct number of hours
                            try:
                                if (
                                    paygo_hours != package.individual_curriculum_hours
                                    and paygo_hours != package.individual_test_prep_hours
                                ):
                                    for _ in range(1, max(paygo_hours, 1)):
                                        # Add another package purchase
                                        self._create_package_purchase(student, package, item, paygo_duplicate=True)
                            except ValueError:
                                with configure_scope() as scope:
                                    scope.set_context(
                                        "magento_webhook_errors",
                                        {
                                            "errors": errors,
                                            "sku": item["sku"],
                                            "product_id": item["product_id"],
                                            "product_name": item["name"],
                                            "paygo_total": data["extension_attributes"]["paygo_total"],
                                        },
                                    )
                                    capture_exception(MagentoPurchaseWebhookException("Invalid Paygo Total"))

                    # Check and see if we need to complete student's enrollment in a course
                    if (
                        student.pending_enrollment_course
                        and purchase.tutoring_package.courses.filter(pk=student.pending_enrollment_course.pk).exists()
                    ):
                        TutoringSessionManager.enroll_student_in_course(student, student.pending_enrollment_course)

        if errors:
            if not (settings.TESTING or settings.DEBUG):
                with configure_scope() as scope:
                    scope.set_context("magento_webhook_errors", {"errors": errors})
                    capture_exception(MagentoPurchaseWebhookException("Validation error"))
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        # Send admin/counselor notification when student created
        if student:
            student_manager = StudentManager(student)
            # New CAP student
            if student_created and student.counselor:
                student_manager.send_new_cap_student_notification()

            # New CAS Student OR CAP student getting their first CAS purchase
            is_cas_student = student.tutoring_package_purchases.exists() or not student.counselor
            if (student_created or not student_had_tutoring_package) and is_cas_student:
                student_manager.send_new_cas_student_notification()

        if package and student and package.is_paygo_package and student.is_paygo:
            paygo_hours = int(data["extension_attributes"].get("paygo_total", "1:00").split(":")[0])
            TutoringSessionManager.mark_paygo_sessions_paid(
                StudentTutoringSession.SESSION_TYPE_TEST_PREP
                if package.individual_test_prep_hours > 0
                else StudentTutoringSession.SESSION_TYPE_CURRICULUM,
                student,
                paygo_hours,
            )

        return Response({})


class PaygoPurchaseView(AccessStudentPermission, APIView):
    """ This view is used to execute a payment against the magento paygo API
        via MagentoAPIManager
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        """ Arguments:
                student_tutoring_session: ID of StudentTutoringSession purchase is being made for
                tutoring_package: Optional ID of TutoringPackage to use to purchase hours for session
            Returns:
                Updated StudentProfile upon success
        """
        session = get_object_or_404(StudentTutoringSession, pk=request.data.get("student_tutoring_session"))
        if not self.has_access_to_student(session.student):
            self.permission_denied(request)

        if request.data.get("tutoring_package"):
            tutoring_package = get_object_or_404(TutoringPackage, pk=request.data["tutoring_package"])
        else:
            mgr = StudentTutoringPackagePurchaseManager(session.student)
            tutoring_package = mgr.get_paygo_tutoring_package(session)
        try:
            MagentoAPIManager.create_paygo_purchase(session, tutoring_package)
        except MagentoAPIManagerException as err:
            # Ex will have already been logged
            return Response({"message": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        # We return an updated student
        student = Student.objects.get(pk=session.student.pk)
        return Response(StudentSerializer(student).data)


class LateChargeView(APIView):
    permission_classes = (IsAdminUser,)

    """ View for admin/ops to execute a late charge for a student tutoring session
        Marks session as late cancel if not already late cancel
        Arguments:
            student_tutoring_session {pk} ID of STS to execute late charge for
            amount {Decimal} Optional amount to charge (defaults to LATE_CANCEL_CHARGE constant)
        Returns:
            updated StudentTutoringSession
    """

    def post(self, request, *args, **kwargs):
        session: StudentTutoringSession = get_object_or_404(
            StudentTutoringSession, pk=request.data.get("student_tutoring_session")
        )
        if not session.late_cancel:
            session.set_cancelled = True
            session.late_cancel = True
            session.save()
        try:
            session = MagentoAPIManager.create_late_cancel_charge(session, request.data.get("amount", None))
        except MagentoAPIManagerException as err:
            # Ex will have already been logged
            return Response({"message": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(StudentTutoringSessionSerializer(session).data)
