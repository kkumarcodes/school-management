""" python manage.py test cwcounseling.tests.test_counseling_prompt_api_manager
"""
import json
from django.test import TestCase
from django.urls import reverse
from cwcounseling.tasks import sync_all_prompt_assignment_tasks
from cwcounseling.utilities.counseling_prompt_api_manager import CounselingPromptAPIManager
from cwuniversities.managers.student_university_decision_manager import StudentUniversityDecisionManager
from snusers.models import Counselor, Student
from cwuniversities.models import StudentUniversityDecision, University
from cwtasks.models import TaskTemplate

HARVARD_IPED = "166027"


class TestCounselingPromptAPIManager(TestCase):
    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.mgr = CounselingPromptAPIManager()
        self.harvard = University.objects.create(name="Harvard", iped=HARVARD_IPED)

    def test_post_get_assignments(self):
        """ Test retrieving assignments from Prompt, including by posting school list first
        """
        self.assertFalse(self.student.user.tasks.exists())
        # Just try getting assignments. There should be none
        self.student.school_list_finalized = True
        self.student.save()
        tasks = self.mgr.update_assignment_tasks(self.student)
        self.assertEqual(tasks.count(), 0)

        # Add a school, we get some tasks!
        sud, created = StudentUniversityDecisionManager.create(
            university=self.harvard, is_applying=StudentUniversityDecision.YES, student=self.student
        )
        tasks = self.mgr.update_assignment_tasks(self.student)
        self.assertEqual(tasks.count(), 3)
        self.assertTrue(all([x.due is None for x in tasks]))
        self.assertTrue(all([x.task_type == TaskTemplate.ESSAY for x in tasks]))

        # Remove the school and tasks go away
        sud.is_applying = StudentUniversityDecision.MAYBE
        sud.save()
        tasks = self.mgr.update_assignment_tasks(self.student)
        self.assertEqual(tasks.count(), 0)
        self.assertFalse(self.student.user.tasks.exists())

    def test_sync_view(self):
        """ Test view to sync school list doesn't lead to any exceptions
        """
        # Login required
        url = reverse("sync_prompt_assignments", kwargs={"student": self.student.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 401)
        self.client.force_login(self.student.user)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        # No tasks
        self.assertEqual(len(json.loads(response.content)), 0)

    def test_sync_all_prompt_assignments_tasks(self):
        """ Test celery task that syncs all prompt assignments for students
            DOES NOT test the actual sync process (happens in test case above), just
            tests that we would attempt syncing assignments for the proper student
        """
        counselor = Counselor.objects.first()
        counselor.prompt = True
        counselor.save()
        Student.objects.all().update(is_prompt_active=False, counselor=counselor)
        result = sync_all_prompt_assignment_tasks()
        self.assertEqual(result["updated_students"], [])
        self.assertEqual(result["failed_students"], [])

        Student.objects.all().update(is_prompt_active=True)
        result = sync_all_prompt_assignment_tasks()
        self.assertEqual(len(result["updated_students"]), Student.objects.count())
        self.assertEqual(result["failed_students"], [])
