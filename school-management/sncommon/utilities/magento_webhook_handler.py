""" This module contains a utility for handling incoming Magento webhooks
"""
import re


from rest_framework.exceptions import ValidationError
from django.db.models import Q
from snusers.models import Counselor, Student, Parent
from snusers.serializers.users import ParentSerializer, StudentSerializer
from snusers.utilities.managers import StudentManager
from sncounseling.constants import counseling_student_types

SELF_ENROLLMENT_REQUIRED_FIELDS = ["mailing_student_email", "student_name", "graduation_year"]

# Settings for new students created via self enrollment
SELF_ENROLLMENT_STUDENT_TYPE = counseling_student_types.PAYGO
SELF_ENROLLMENT_STUDENT_IS_PAYGO = True


def handle_self_enrollment_payload(data) -> Student:
    """ Handler for dealing with self-enrollments. Validates data, then
        creates student and parent

        Arguments:
            data: request.data for self enrollment request.
            See ../tests/magento_self_enrollment_payload.json for an example
    """

    if any([not data.get(x) for x in SELF_ENROLLMENT_REQUIRED_FIELDS]):
        raise ValidationError("Missing required field(s) for enrollment payload")

    # First check to see if student exists
    magento_student_email = data.get("mailing_student_email") or data.get("studentEmail")
    parent_data = data.get("shipping_address", {})
    student = Student.objects.filter(
        Q(user__username__iexact=magento_student_email)
        # Student matches on name and parent matches on email. Alot of times parents leave off student
        # email or use a different email from what's already on file in UMS
        | Q(
            Q(invitation_name__iexact=data["student_name"]) & Q(parent__user__username__iexact=parent_data.get("email"))
        )
    ).first()

    # Construct our student serializer, then validate
    split_student_name = data.get("student_name").split(" ")
    data_counselor_name = data.get("counselor_name") or data.get("counselorName")
    counselor: Counselor = Counselor.objects.filter(
        invitation_name=data_counselor_name
    ).first() if data_counselor_name else None
    student_data = {
        "first_name": split_student_name[0],
        "last_name": split_student_name[1] if len(split_student_name) > 1 else "",
        "email": magento_student_email,
        "graduation_year": data.get("graduation_year"),
        "invite": False,
        "counseling_student_types_list": [SELF_ENROLLMENT_STUDENT_TYPE],
        "is_paygo": SELF_ENROLLMENT_STUDENT_IS_PAYGO,
    }
    if counselor:
        student_data["counselor"] = counselor.pk

    # Validate student
    student_serializer = StudentSerializer(instance=student, data=student_data)
    student_serializer.is_valid(raise_exception=True)
    student = student_serializer.save()
    if data.get("mailing_student_cell_phone"):
        student.user.notification_recipient.phone_number = re.sub("[^0-9]", "", data["mailing_student_cell_phone"])
        student.user.notification_recipient.save()

    student_manager = StudentManager(student)
    student_manager.send_new_cap_student_notification()

    # Validate and save parent
    # Note that it's intentional (though ill advised) to create student even if parent validation fails
    if parent_data.get("email") and parent_data.get("email") != student.invitation_email:
        existing_parent = Parent.objects.filter(user__username__iexact=parent_data.get("email")).first()
        parent_serializer = ParentSerializer(
            instance=existing_parent,
            data={
                "first_name": parent_data.get("firstname"),
                "last_name": parent_data.get("lastname"),
                "email": parent_data.get("email"),
            },
        )
        parent_serializer.is_valid(raise_exception=True)
        parent = parent_serializer.save()
        student = student_manager.set_parent(parent)
