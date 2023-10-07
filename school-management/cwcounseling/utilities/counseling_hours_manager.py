""" This utility is used to manage (add/remove/report on) the counseling hours that a student has
    Note that horus are currently accounter for via CounselorTimeEntry objects, but that is subject to
    change in the future.
"""
from django.utils import timezone
from decimal import Decimal
from typing import Optional, Union
from cwcounseling.constants import roadmap_semesters

from snusers.models import Student
from cwcounseling.models import CounselingHoursGrant, CounselingPackage


class CounselingHoursManager:
    student: Student = None

    def __init__(self, student: Student):
        self.student = student

    def get_counseling_package(self, package_name: str) -> Optional[CounselingPackage]:
        """ Given our student, their graduation year, and current semester, we figure out
            which counseling package with key package_name should be applied to the student.
        """
        # Null grade/semester indicates the package is not dependent on students' start grade/semester
        # so we use it
        all_students_package = CounselingPackage.objects.filter(
            package_name=package_name, grade=None, semester=None
        ).first()
        if all_students_package:
            return all_students_package

        current_semester = (
            roadmap_semesters.ONE
            if timezone.now().month > roadmap_semesters.SPRING_END_MONTH
            else roadmap_semesters.TWO
        )
        year_offset = self.student.graduation_year - timezone.now().year
        current_grade = 13 - year_offset if current_semester == roadmap_semesters.ONE else 12 - year_offset

        return CounselingPackage.objects.filter(
            package_name=package_name, grade=current_grade, semester=current_semester
        ).first()

    def add_hours(
        self,
        new_hours: Union[Decimal, float, int],
        amount_paid: Decimal = None,
        note="",
        magento_id="",
        package: CounselingPackage = None,
    ) -> CounselingHoursGrant:
        """ Add new hours to a student by creating a CounselingHoursGrant
        """
        if not isinstance(new_hours, Decimal):
            new_hours = Decimal(new_hours)  # Intentionally throws exception if not possible

        return CounselingHoursGrant.objects.create(
            student=self.student,
            number_of_hours=new_hours,
            note=note,
            amount_paid=amount_paid,
            counseling_package=package,
            magento_id=magento_id,
        )

