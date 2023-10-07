""" This module contains a model manager for managing StudentUniversityDecision objects
"""

from typing import Tuple
from sncommon.managers.model_manager_base import ModelManagerBase
from snuniversities.models import StudentUniversityDecision, University
from snuniversities.constants import application_requirements

RECOMMENDATION_FIELDS = (
    "recommendation_one_status",
    "recommendation_two_status",
    "recommendation_three_status",
    "recommendation_four_status",
)


class StudentUniversityDecisionManager(ModelManagerBase):
    student_university_decision: StudentUniversityDecision = StudentUniversityDecision

    class Meta:
        model = StudentUniversityDecision

    @classmethod
    def create(cls, **kwargs) -> Tuple[StudentUniversityDecision, bool]:
        """ Create a new StudentUniversityDecision; Sets fields based on fields from University """
        sud, created = cls._get_or_create(**kwargs)
        if created:
            manager = StudentUniversityDecisionManager(sud)
            sud = manager.copy_app_requirements_from_university()
        return sud, created

    def copy_app_requirements_from_university(self) -> StudentUniversityDecision:
        """ Each university has application requirements (stored on University). Each StudentUniversityDecision
            has fields that represents a student's progress towards completing those requirements.
            This method is used to initialize the app req fields on self.student_university_decision, based
            on the requirements in the related University.

            Arguments:
                overwrite: Whether or not existing values on SUD should be overwritten
        """
        uni: University = self.student_university_decision.university

        # First we copy fields as denoted in our app requirements mapping
        for uni_field_name, mapping in application_requirements.APP_REQUIREMENTS_MAPPING.items():
            sud_field = mapping["sud_field_name"]
            for key, val in mapping["values"].items():
                if getattr(uni, uni_field_name) == key:
                    setattr(self.student_university_decision, sud_field, val)

        # All of the fields that lead to "Additional Requirements"
        self.student_university_decision.additional_requirement_deadline = False
        if uni.resume_required:
            self.student_university_decision.additional_requirement_deadline = True
            self.student_university_decision.additional_requirement_deadline_note += "\nResume"
        if uni.interview_requirements == application_requirements.INTERVIEW_REQUIRED:
            self.student_university_decision.additional_requirement_deadline = True
            self.student_university_decision.additional_requirement_deadline_note += "\nAdmissions Interview"

        # We figure out how many recommendations are needed
        required_recommendations = uni.required_teacher_recommendations + uni.required_other_recommendations
        optional_recommendations = uni.optional_teacher_recommendations + uni.optional_other_recommendations
        if uni.counselor_recommendation_required:
            required_recommendations += 1

        # Reset all rec requirements, then alter to indicate correct number of required and optional recs
        # Required recommendations always come first
        [setattr(self.student_university_decision, x, application_requirements.NONE) for x in RECOMMENDATION_FIELDS]
        for x in range(min(required_recommendations, len(RECOMMENDATION_FIELDS))):
            setattr(self.student_university_decision, RECOMMENDATION_FIELDS[x], application_requirements.REQUIRED)
        for x in range(
            required_recommendations,
            min(required_recommendations + optional_recommendations, len(RECOMMENDATION_FIELDS)),
        ):
            setattr(self.student_university_decision, RECOMMENDATION_FIELDS[x], application_requirements.OPTIONAL)

        self.student_university_decision.save()
        return self.student_university_decision
