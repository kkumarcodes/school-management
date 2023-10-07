""" Utility for managing available TutoringPackages, and for managing students'
    TutoringPackagePurchases
"""
from typing import List
from decimal import Decimal
from django.db.models import Sum
from django.conf import settings
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from cwtutoring.models import (
    StudentTutoringSession,
    TutoringPackagePurchase,
    TutoringPackage,
)
from cwcommon.utilities.magento import MagentoAPIManager
from cwnotifications.generator import create_notification
from cwresources.models import ResourceGroup
from snusers.models import Student


class TutoringPackageManagerException(Exception):
    pass


class StudentTutoringPackagePurchaseManager:
    student: Student = None

    def __init__(self, student: Student):
        self.student = student

    def purchase_package(
        self,
        package: TutoringPackage,
        paid=None,
        purchaser=None,
        send_noti=True,
        execute_charge=False,
        hours=None,
        admin_note="",
    ) -> List[TutoringPackagePurchase]:
        """ Woot self.student is going to get a new package! Lucky kid
            This method creates a TutoringPackagePurchase, grants student access to materials
            associated with TutoringPackage, and enrolls student in GroupTutoringSessions
            associated with TutoringPackage.
            Arguments:
                package {TutoringPackage} package being purchased
                paid {Decimal} optional amount that was paid for package. If execute_charge is True but paid
                    is not provided, then we'll use package price (or package price * hours for a paygo purchase)
                purchaser {User} optional user who made the purchase (or is giving package to student,
                  in case of ops/admin)
                send_noti {Boolean} Whether or not to send confirmation to student/parent of package purchase
                execute_charge {Boolean} Whether or not a charge should be executed for purchase using student's
                    last_paygo_transaction_id
                hours {number} If purchasing a paygo package with exactly 1 hour, can specify the real number of hours
                    being purchased (we'll create duplicate package purchases to match hours)
            Returns: List[TutoringPackagePurchase]
        """
        is_paygo_charge = False
        paid = paid or package.price
        magento_response = {}
        if execute_charge:
            if not self.student.last_paygo_purchase_id:
                raise TutoringPackageManagerException("Can't execute charge for student w/o last purchase ID")

            # If package is paygo with exactly 1 hour, we allow specifying hours
            if package.is_paygo_package and (
                package.individual_curriculum_hours + package.individual_test_prep_hours == 1
            ):
                is_paygo_charge = True
                hours = hours or 1
                if not float.is_integer(float(hours)):
                    raise ValueError(f"Invalid hours: {hours}")
                paid = package.price * Decimal(hours)

            # Attempt the charge. Note that we raise TutoringPackageManagerException if failure
            try:
                # We need to generate a unique ID for this purchase
                student_packages = self.student.tutoring_package_purchases.count()
                schoolnet_id = f"{self.student.slug}-{student_packages}"
                magento_response = MagentoAPIManager.execute_charge(
                    self.student.last_paygo_purchase_id,
                    f"Package: {package.title} ({hours} hours)",
                    float(paid),
                    product_id=package.product_id,
                    tutor_id=package.restricted_tutor.invitation_email if package.restricted_tutor else "",
                    paygo_hours=hours if is_paygo_charge else None,
                    schoolnet_id=schoolnet_id,
                )
            except Exception as err:
                if settings.TESTING:
                    magento_response["transaction_id"] = "TEST"
                else:
                    raise TutoringPackageManagerException("Charge failed")

        package_count = hours if is_paygo_charge else 1
        purchases = [
            TutoringPackagePurchase.objects.create(
                student=self.student,
                tutoring_package=package,
                price_paid=(paid or 0) / package_count,
                purchased_by=purchaser,
                admin_note=admin_note,
                paygo_transaction_id=magento_response.get("transaction_id", ""),
            )
            for x in range(package_count)
        ]

        # Grant student access to package's resource groups
        self.student.visible_resource_groups.add(*package.resource_groups.all())

        # Enroll student in package's group sessions. Don't send notifications
        for group_session in package.group_tutoring_sessions.exclude(student_tutoring_sessions__student=self.student):
            StudentTutoringSession.objects.create(
                student=self.student,
                start=group_session.start,
                end=group_session.end,
                duration_minutes=group_session.charge_student_duration,
                created_by=purchaser,
                group_tutoring_session=group_session,
            )

        if send_noti:
            noti_data = {
                "notification_type": "package_purchase_confirmation",
                "related_object_content_type": ContentType.objects.get_for_model(TutoringPackagePurchase),
                "related_object_pk": purchases[0].pk,
            }
            create_notification(self.student.user, **noti_data)

        return purchases

    def unpurchase_package(self, package_purchase, reversed_by):
        """ womp womp self.student is losing a package! Unlucky kid
            This method reverses a TutoringPackagePurchase, removing student's access materials associated
            with TutoringPackage that aren't also associated with an un-reversed TutoringPackagePurchase,
            cancels StudentTutoringSessions associated with TutoringPackage's GroupTutoringSessions, and sets
            reversed fields on TutoringPackagePurchase
            Arguments:
                package_purchase {TutoringPackagePurchase} package purchase to reverse
                reversed_by {auth.User} user who is reversing this purchase
            Returns:
                updated TutoringPackagePurchase (with reversed fields set)
        """
        if package_purchase.student != self.student:
            raise TutoringPackageManagerException("Package purchase student does not match manager student")
        # First we reverse the package
        package_purchase.purchase_reversed = timezone.now()
        package_purchase.purchase_reversed_by = reversed_by
        package_purchase.save()

        # If student has another, not reversed version of this purchae, we can
        if package_purchase.student.tutoring_package_purchases.filter(
            tutoring_package=package_purchase.tutoring_package, purchase_reversed=None
        ).exists():
            return package_purchase

        # Next we revoke access to resources
        other_purchases = TutoringPackagePurchase.objects.filter(student=self.student, purchase_reversed=None)
        resources_for_other_purchases = ResourceGroup.objects.filter(
            tutoring_packages__tutoring_package_purchases__in=other_purchases
        ).distinct()

        bad_resource_groups = (
            ResourceGroup.objects.filter(tutoring_packages=package_purchase.tutoring_package)
            .exclude(pk__in=resources_for_other_purchases.values_list("pk", flat=True))
            .distinct()
        )
        self.student.visible_resource_groups.remove(*bad_resource_groups.all())

        # And finally we cancel any future scheduled sessions from tutoring package's
        # group tutoring sessions. We can assume that another unreversed purchase
        # of this same package doesn't exist (see above)
        StudentTutoringSession.objects.filter(
            group_tutoring_session__tutoring_packages=package_purchase.tutoring_package,
            student=self.student,
            missed=False,
            start__gt=timezone.now(),
        ).update(set_cancelled=True)

        return package_purchase

    def get_available_hours(self):
        """ Returns the available individual and group hours that student has remaining
            Returns:
              { 'individual_test_prep' <decimal>, 'group_test_prep': <decimal>, 'individual_curriculum': <decimal> }
        """
        total_hours = self.get_total_hours()
        # Missed hours ARE deducted (thus included in sessions below)
        # Cancelled sessions - whether late cancel or not - are NOT deducted (this excluded)
        student_sessions = (
            self.student.tutoring_sessions.exclude(set_cancelled=True)
            .filter(is_tentative=False)
            .exclude(late_cancel=True)
            .exclude(group_tutoring_session__cancelled=True)
            .select_related("group_tutoring_session")
        )
        ind_test_prep = 0
        ind_curr = 0
        group_test_prep = 0
        # Faster to do this loop than three queries
        for session in student_sessions:
            if session.group_tutoring_session:
                group_test_prep += session.duration_minutes
            elif session.session_type == StudentTutoringSession.SESSION_TYPE_TEST_PREP:
                ind_test_prep += session.duration_minutes
            else:
                ind_curr += session.duration_minutes

        hours = {
            "individual_test_prep": float(total_hours["individual_test_prep"]) - float(ind_test_prep) / 60.0,
            "individual_curriculum": float(total_hours["individual_curriculum"]) - float(ind_curr) / 60.0,
            "group_test_prep": float(total_hours["group_test_prep"]) - float(group_test_prep) / 60.0,
            "total_individual_test_prep": float(total_hours["individual_test_prep"]),
            "total_individual_curriculum": float(total_hours["individual_curriculum"]),
            "total_group_test_prep": float(total_hours["group_test_prep"]),
        }
        return hours

    def get_total_hours(self):
        """ Returns total hours a student has purchased (via TutoringPackagePurchase)
            Returns:
              { 'individual' <decimal individual hours>, 'group': <decimal group hours> }
        """
        purchases = self.student.tutoring_package_purchases.filter(purchase_reversed=None).aggregate(
            ind_test_prep=Sum("tutoring_package__individual_test_prep_hours"),
            group_test_prep=Sum("tutoring_package__group_test_prep_hours"),
            ind_curriculum=Sum("tutoring_package__individual_curriculum_hours"),
        )

        return {
            "individual_test_prep": purchases["ind_test_prep"] or 0,
            "group_test_prep": purchases["group_test_prep"] or 0,
            "individual_curriculum": purchases["ind_curriculum"] or 0,
        }

    def get_paygo_tutoring_package(
        self, student_tutoring_session: StudentTutoringSession,
    ):
        """ Returns the TutoringPackage that a family can use to make a paygo (single session)
            purchase. Paygo families (families that can pay for a session after it takes place)
            can purchase this package to pay for a future or past session. We'll also automatically
            charge families by purchasing this package to pay for specified session (if they have not already
            paid for it)
            Arguments:
                student_tutoring_session {StudentTutoringSession}
                    Package needs to pay for specified session, so we'll start by looking for packages for
                    session's tutor.
            Returns:
                TutoringPackage or None
        """
        # In order of specificity, find a link for specified tutor, then student's tutor, student's location, all locs
        filter_data = {
            "individual_test_prep_hours": 0,
            "group_test_prep_hours": 0,
            "individual_curriculum_hours": 0,
        }
        if student_tutoring_session.session_type == StudentTutoringSession.SESSION_TYPE_CURRICULUM:
            filter_data["individual_curriculum_hours"] = 1
        else:
            filter_data["individual_test_prep_hours"] = 1

        # Look for package for session's tutor
        tutor_package = TutoringPackage.objects.filter(
            is_paygo_package=True, restricted_tutor=student_tutoring_session.individual_session_tutor, **filter_data
        ).first()
        if tutor_package:
            return tutor_package

        # Look for package specific to student's location, otherwise we go with all locations
        location_package = TutoringPackage.objects.filter(
            is_paygo_package=True, locations=self.student.location, **filter_data, restricted_tutor=None
        ).first()
        if location_package:
            return location_package

        return TutoringPackage.objects.filter(
            is_paygo_package=True, all_locations=True, restricted_tutor=None, **filter_data
        ).first()

