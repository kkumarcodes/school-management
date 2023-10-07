""" Test model managers in cwuniversities
    python manage.py test cwuniversities.tests.test_managers
"""

from django.test import TestCase
from cwuniversities.constants.application_requirements import INTERVIEW_REQUIRED, NOT_OFFERED
from cwuniversities.constants.application_tracker_status import NONE, OPTIONAL, REQUIRED
from cwuniversities.managers.student_university_decision_manager import StudentUniversityDecisionManager
from cwuniversities.models import University
from snusers.models import Student


class TestStudentUniversityDecisionManager(TestCase):
    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()

    def test_copy_application_requirements(self):
        """ Test to ensure app requirements get copied from university to SUD (including
        upon SUD creation)
        """
        uni: University = University.objects.create(name="Big Time University Town")
        uni.transcript_requirements = "Unofficial Allowed"  # To become OPTIONAL
        uni.testing_requirements = "Test Flexible"  # To become REQUIRED
        uni.optional_other_recommendations = 1
        uni.required_other_recommendations = 1
        uni.required_teacher_recommendations = 0
        uni.optional_teacher_recommendations = 1
        uni.counselor_recommendation_required = True
        uni.resume_required = True
        uni.interview_requirements = INTERVIEW_REQUIRED
        uni.save()

        sud, created = StudentUniversityDecisionManager.create(student=self.student, university=uni)
        self.assertTrue(created)
        self.assertEqual(sud.transcript_status, OPTIONAL)
        self.assertEqual(sud.test_scores_status, REQUIRED)
        self.assertTrue(sud.additional_requirement_deadline)
        self.assertIn("Resume", sud.additional_requirement_deadline_note)
        self.assertIn("Interview", sud.additional_requirement_deadline_note)

        # Four recommendations; two required two optional
        self.assertEqual(sud.recommendation_one_status, REQUIRED)
        self.assertEqual(sud.recommendation_two_status, REQUIRED)
        self.assertEqual(sud.recommendation_three_status, OPTIONAL)
        self.assertEqual(sud.recommendation_four_status, OPTIONAL)

        # And we try again, with just two recommendations and no additional requirements
        uni.required_other_recommendations = 0
        uni.optional_teacher_recommendations = 0
        uni.resume_required = False
        uni.interview_requirements = NOT_OFFERED
        uni.save()
        sud.delete()

        sud, created = StudentUniversityDecisionManager.create(student=self.student, university=uni)
        self.assertFalse(sud.additional_requirement_deadline)

        # One required and one optional rec
        self.assertEqual(sud.recommendation_one_status, REQUIRED)
        self.assertEqual(sud.recommendation_two_status, OPTIONAL)
        self.assertEqual(sud.recommendation_three_status, NONE)
        self.assertEqual(sud.recommendation_four_status, NONE)
