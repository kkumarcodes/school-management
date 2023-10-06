""" Serializers for the user data we pass to Hubspot as part of our Hubspot extension
"""
from rest_framework import serializers
from cwusers.models import Student, Parent
from cwtutoring.utilities.tutoring_package_manager import (
    StudentTutoringPackagePurchaseManager,
)


class HubspotStudentCardSerializer:
    """ Serializer that returns a "Card" in Hubspot extension parlance.
        See props here: https://developers.hubspot.com/docs/methods/crm-extensions/crm-extensions-overview#action-types
        Must be initialized with a student {Student}
        Use data property to get serialized card data for student
    """

    student = None

    def __init__(self, student):
        if (not student) or (not isinstance(student, Student)):
            raise ValueError("Invalid student for HubspotStudentCardSerializer")
        self.student = student

    @property
    def data(self):
        mgr = StudentTutoringPackagePurchaseManager(self.student)
        hours = mgr.get_available_hours()
        return {
            "objectId": str(self.student.pk),
            "title": self.student.name,
            "link": self.student.admin_url,
            "created": self.student.created.strftime("%Y-%m-%d"),
            "individual_test_prep_hours": hours["individual_test_prep"],
            "group_test_prep_hours": hours["group_test_prep"],
            "individual_curriculum_hours": hours["individual_curriculum"],
            "url": self.student.admin_url,
        }


class HubspotExtensionSerializer:
    """ Serilaizer that returns for payload for Hubspot extension, which can include one or more
        cards for students (via HubspotStudentCardSerializer)
        Initialize with a student {Student} or parent {Parent}
    """

    student = None
    parent = None

    def __init__(self, student_or_parent):
        if not (
            student_or_parent
            and (
                isinstance(student_or_parent, Student)
                or isinstance(student_or_parent, Parent)
            )
        ):
            raise ValueError("Invalid student/parent for HubspotExtensionSerializer")
        if isinstance(student_or_parent, Student):
            self.student = student_or_parent
        else:
            self.parent = student_or_parent

    @property
    def data(self):
        if self.student:
            card_data = [HubspotStudentCardSerializer(self.student).data]
        else:
            card_data = [
                HubspotStudentCardSerializer(s).data for s in self.parent.students.all()
            ]
        return {"results": card_data}
