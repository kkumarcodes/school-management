"""
    Test creating/updating tasks, including special cases of creating types of tasks that have
    special behavior (diagnostics, ).
    Includes testing completing tasks (one form of updating them)

    python manage.py test sntasks.tests.test_task_manager
"""
import json
from django.test import TestCase
from django.shortcuts import reverse
from django.utils import timezone
from sntasks.utilities.task_manager import TaskManager
from sntasks.models import Task, TaskTemplate
from snuniversities.managers.student_university_decision_manager import StudentUniversityDecisionManager

from snusers.models import Student, Counselor
from snuniversities.models import University


class TestUpdateSUD(TestCase):
    """ python manage.py test sntasks.tests.test_task_manager:TestUpdateSUD
        Test students' StudentUniversityDecision objects are updated properly upon task completion.
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.student.counseling_student_types_list.append("cap")
        self.student.save()
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()

        self.task_template: TaskTemplate = TaskTemplate.objects.create(
            title="1",
            on_complete_sud_update={"transcript_status": "requested", "test_scores_status": "received",},
            on_assign_sud_update={"transcript_status": "assigned", "test_scores_status": "assigned",},
        )
        self.task_template_with_only_alter_tracker_values: TaskTemplate = TaskTemplate.objects.create(
            title="2",
            on_complete_sud_update={
                "recommendation_one_status": "requested",
                "recommendation_two_status": "requested",
                "recommendation_three_status": "requested",
                "recommendation_four_status": "requested",
            },
            on_assign_sud_update={
                "recommendation_one_status": "assigned",
                "recommendation_two_status": "assigned",
                "recommendation_three_status": "assigned",
                "recommendation_four_status": "assigned",
            },
            only_alter_tracker_values=["required", "optional"],
        )
        self.sud, _ = StudentUniversityDecisionManager.create(
            university=University.objects.create(
                name="1", required_teacher_recommendations=1, optional_other_recommendations=1
            ),
            student=self.student,
        )
        self.task: Task = Task.objects.create(for_user=self.student.user, task_template=self.task_template)
        self.task_with_only_alter_tracker_values: Task = Task.objects.create(
            for_user=self.student.user, task_template=self.task_template_with_only_alter_tracker_values
        )

        self.task.student_university_decisions.add(self.sud)
        self.task_with_only_alter_tracker_values.student_university_decisions.add(self.sud)

    def test_update_sud_on_complete(self):
        mgr = TaskManager(self.task)
        self.assertNotEqual(
            self.sud.transcript_status, self.task.task_template.on_complete_sud_update["transcript_status"]
        )
        self.assertNotEqual(
            self.sud.test_scores_status, self.task.task_template.on_complete_sud_update["test_scores_status"]
        )

        # Complete with manager, make sure statuses update
        mgr.complete_task()
        self.sud.refresh_from_db()
        self.assertEqual(
            self.sud.transcript_status, self.task.task_template.on_complete_sud_update["transcript_status"]
        )
        self.assertEqual(
            self.sud.test_scores_status, self.task.task_template.on_complete_sud_update["test_scores_status"]
        )

    def test_update_sud_on_complete_with_only_alter_tracker_values(self):
        mgr = TaskManager(self.task_with_only_alter_tracker_values)
        self.assertNotEqual(
            self.sud.recommendation_one_status,
            self.task_with_only_alter_tracker_values.task_template.on_complete_sud_update["recommendation_one_status"],
        )
        self.assertNotEqual(
            self.sud.recommendation_three_status,
            self.task_with_only_alter_tracker_values.task_template.on_complete_sud_update["recommendation_two_status"],
        )
        self.assertFalse(self.sud.recommendation_three_status)
        self.assertFalse(self.sud.recommendation_four_status)

        # Complete with manager, make sure statuses update
        mgr.complete_task()
        self.sud.refresh_from_db()
        self.assertEqual(
            self.sud.recommendation_one_status,
            self.task_with_only_alter_tracker_values.task_template.on_complete_sud_update["recommendation_one_status"],
        )
        self.assertEqual(
            self.sud.recommendation_two_status,
            self.task_with_only_alter_tracker_values.task_template.on_complete_sud_update["recommendation_two_status"],
        )
        self.assertFalse(self.sud.recommendation_three_status)
        self.assertFalse(self.sud.recommendation_four_status)

    def test_update_sud_on_create(self):
        # Test that when we create task, SUDs are updated properly
        mgr = TaskManager(self.task)
        self.assertNotEqual(
            self.sud.transcript_status, self.task.task_template.on_assign_sud_update["transcript_status"]
        )
        self.assertNotEqual(
            self.sud.test_scores_status, self.task.task_template.on_assign_sud_update["test_scores_status"]
        )
        mgr.create_update_task_sud()
        self.sud.refresh_from_db()
        self.assertEqual(self.sud.transcript_status, self.task.task_template.on_assign_sud_update["transcript_status"])
        self.assertEqual(
            self.sud.test_scores_status, self.task.task_template.on_assign_sud_update["test_scores_status"]
        )

        self.task.delete()
        self.sud.test_scores_status = ""
        self.sud.transcript_status = ""
        self.sud.save()

        # Now create with viewset. Same result
        self.client.force_login(self.counselor.user)
        url = reverse("tasks-list")
        data = {
            "title": "1",
            "for_user": self.student.user.pk,
            "task_template": self.task_template.pk,
            "student_university_decisions": [self.sud.pk],
        }
        # Doesn't update since not due
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.sud.refresh_from_db()
        self.assertEqual(self.sud.test_scores_status, "")

        # Does update when IS due
        data["due"] = timezone.now().isoformat()
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.sud.refresh_from_db()
        self.assertEqual(
            self.sud.test_scores_status, self.task.task_template.on_assign_sud_update["test_scores_status"]
        )

        # Add an SUD. It also gets updated
        new_sud, _ = StudentUniversityDecisionManager.create(
            university=University.objects.create(name="2"), student=self.student
        )
        data["student_university_decisions"] = [new_sud.pk]
        url = reverse("tasks-detail", kwargs={"pk": Task.objects.last().pk})
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        new_sud.refresh_from_db()
        self.assertEqual(new_sud.test_scores_status, self.task.task_template.on_assign_sud_update["test_scores_status"])
        self.assertEqual(new_sud.transcript_status, self.task.task_template.on_assign_sud_update["transcript_status"])

    def test_update_sud_view(self):
        """ Test completing task via view does same thing as above """
        self.client.force_login(self.student.user)
        task_url = reverse("tasks-detail", kwargs={"pk": self.task.pk})
        response = self.client.patch(
            task_url, json.dumps({"completed": timezone.now().isoformat()}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.sud.refresh_from_db()
        self.assertEqual(
            self.sud.transcript_status, self.task.task_template.on_complete_sud_update["transcript_status"]
        )
        self.assertEqual(
            self.sud.test_scores_status, self.task.task_template.on_complete_sud_update["test_scores_status"]
        )

    def test_update_sud_on_create_with_only_alter_tracker_values(self):
        # Test that when we create task, SUDs are updated properly
        mgr = TaskManager(self.task_with_only_alter_tracker_values)
        self.assertNotEqual(
            self.sud.recommendation_one_status,
            self.task_with_only_alter_tracker_values.task_template.on_assign_sud_update["recommendation_one_status"],
        )
        self.assertNotEqual(
            self.sud.recommendation_two_status,
            self.task_with_only_alter_tracker_values.task_template.on_assign_sud_update["recommendation_two_status"],
        )
        self.assertFalse(self.sud.recommendation_three_status)
        self.assertFalse(self.sud.recommendation_four_status)

        mgr.create_update_task_sud()
        self.sud.refresh_from_db()
        self.assertEqual(
            self.sud.recommendation_one_status,
            self.task_with_only_alter_tracker_values.task_template.on_assign_sud_update["recommendation_one_status"],
        )
        self.assertEqual(
            self.sud.recommendation_two_status,
            self.task_with_only_alter_tracker_values.task_template.on_assign_sud_update["recommendation_two_status"],
        )

        self.task_with_only_alter_tracker_values.delete()
        self.sud.recommendation_one_status = "required"
        self.sud.recommendation_two_status = "optional"
        self.sud.save()

        # Now create with viewset. Same result
        self.client.force_login(self.counselor.user)
        url = reverse("tasks-list")
        data = {
            "title": "2",
            "for_user": self.student.user.pk,
            "task_template": self.task_template_with_only_alter_tracker_values.pk,
            "student_university_decisions": [self.sud.pk],
        }
        # Doesn't update since not due
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.sud.refresh_from_db()
        self.assertEqual(self.sud.recommendation_one_status, "required")
        self.assertEqual(self.sud.recommendation_two_status, "optional")
        self.assertFalse(self.sud.recommendation_three_status)
        self.assertFalse(self.sud.recommendation_four_status)

        # Does update when IS due
        data["due"] = timezone.now().isoformat()
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.sud.refresh_from_db()
        self.assertEqual(
            self.sud.recommendation_one_status,
            self.task_with_only_alter_tracker_values.task_template.on_assign_sud_update["recommendation_one_status"],
        )
        self.assertEqual(
            self.sud.recommendation_two_status,
            self.task_with_only_alter_tracker_values.task_template.on_assign_sud_update["recommendation_two_status"],
        )
        self.assertFalse(self.sud.recommendation_three_status)
        self.assertFalse(self.sud.recommendation_four_status)

        # Add an SUD. It also gets updated
        new_sud, _ = StudentUniversityDecisionManager.create(
            university=University.objects.create(
                name="3", required_other_recommendations=2, optional_teacher_recommendations=1,
            ),
            student=self.student,
        )
        data["student_university_decisions"] = [new_sud.pk]
        url = reverse("tasks-detail", kwargs={"pk": Task.objects.last().pk})
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        new_sud.refresh_from_db()
        self.assertEqual(
            new_sud.recommendation_one_status,
            self.task_with_only_alter_tracker_values.task_template.on_assign_sud_update["recommendation_one_status"],
        )
        self.assertEqual(
            new_sud.recommendation_two_status,
            self.task_with_only_alter_tracker_values.task_template.on_assign_sud_update["recommendation_two_status"],
        )
        self.assertEqual(
            new_sud.recommendation_three_status,
            self.task_with_only_alter_tracker_values.task_template.on_assign_sud_update["recommendation_three_status"],
        )
        self.assertFalse(new_sud.recommendation_four_status)
