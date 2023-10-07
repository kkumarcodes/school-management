from django.test.testcases import QuietWSGIRequestHandler


""" Test creating, listing, deleting TaskTemplate
"""

import json

from django.test import TestCase
from django.shortcuts import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from sntasks.utilities.task_manager import TaskManager
from sntasks.models import Task, TaskTemplate
from snusers.models import Student, Counselor, Tutor, Parent, Administrator
from snresources.models import Resource


class TestTaskTemplateCRUD(TestCase):
    """ python manage.py test sntasks.tests.test_crud_task_template:TestTaskTemplateCRUD """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.parent = Parent.objects.first()
        self.student.parent = self.parent
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.admin = Administrator.objects.first()
        self.counselor_two = Counselor.objects.create(user=User.objects.create_user("counselor2"))

        # Note that tutor should NOT have access to student
        self.tutor = Tutor.objects.first()

    def test_create_task_template(self):
        url = reverse("task_templates-list")
        # Requires login
        data = {
            "title": "Great Task Template",
            "description": "Great Description",
            "allow_content_submission": True,
            "allow_file_submission": True,
        }
        self.assertEqual(self.client.post(url, json.dumps(data), content_type="application/json").status_code, 401)
        # Not available to student, parent, or tutor
        for user in (self.student.user, self.parent.user, self.tutor.user):
            self.client.force_login(user)
            self.assertEqual(self.client.post(url, json.dumps(data), content_type="application/json").status_code, 403)

        # Admin can create. No created_by set
        self.client.force_login(self.admin.user)
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        result = json.loads(response.content)

        task_template = TaskTemplate.objects.get(pk=json.loads(response.content)["pk"])
        for k, v in data.items():
            self.assertEqual(getattr(task_template, k), v)
            self.assertEqual(result.get(k), v)

        self.assertIsNone(task_template.created_by)

        # Counselor can create. Confirm created_by set properly
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        result = json.loads(response.content)
        task_template = TaskTemplate.objects.get(pk=json.loads(response.content)["pk"])
        for k, v in data.items():
            self.assertEqual(result.get(k), v)
            self.assertEqual(getattr(task_template, k), v)
        self.assertEqual(task_template.created_by, self.counselor.user)

    def test_create_roadmap_override(self):
        """ Test that when creating a task template that overrides roadmap, the correct values are copied over
        """
        roadmap_task_template = TaskTemplate.objects.create(
            on_assign_sud_update={"test": "1"},
            on_complete_sud_update={"test": "13"},
            include_school_sud_values={"test": "4"},
            roadmap_key="roadmap_key",
        )

        self.client.force_login(self.counselor.user)
        data = {"roadmap_key": roadmap_task_template.roadmap_key, "title": "Great"}
        response = self.client.post(reverse("task_templates-list"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        result = json.loads(response.content)
        tt = TaskTemplate.objects.get(pk=result["pk"])
        self.assertEqual(tt.created_by, self.counselor.user)
        for field in ("roadmap_key", "on_assign_sud_update", "on_complete_sud_update", "include_school_sud_values"):
            self.assertEqual(getattr(tt, field), getattr(roadmap_task_template, field))

        # Can't create a second override with same roadmap key
        response = self.client.post(reverse("task_templates-list"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)

        # But can if we archive the first one
        tt.archived = timezone.now()
        tt.save()
        response = self.client.post(reverse("task_templates-list"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)

    def test_roadmap_override_updates_tasks(self):
        """ Test that creating and deleting (archiving) a task template override updates existing tasks
            python manage.py test sntasks.tests.test_crud_task_template:TestTaskTemplateCRUD.test_roadmap_override_updates_tasks
        """
        roadmap_task_template = TaskTemplate.objects.create(
            on_assign_sud_update={"test": "1"},
            on_complete_sud_update={"test": "13"},
            include_school_sud_values={"test": "4"},
            roadmap_key="roadmap_key",
            title="Roadmap Task Template Title",
            description="Roadmap Task Template Description",
        )
        incomplete_task = Task.objects.create(
            task_template=roadmap_task_template, title="No Good Bad Title", for_user=self.student.user
        )
        complete_task = Task.objects.create(
            task_template=roadmap_task_template,
            title="No Good Bad Title",
            completed=timezone.now(),
            for_user=self.student.user,
        )

        self.client.force_login(self.counselor.user)

        data = {
            "roadmap_key": roadmap_task_template.roadmap_key,
            "title": "Great",
            "description": "Better",
            "update_tasks": True,
        }
        response = self.client.post(reverse("task_templates-list"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        task_template = TaskTemplate.objects.get(pk=json.loads(response.content)["pk"])

        # Confirm incomplete task got its properties updated
        incomplete_task.refresh_from_db()
        self.assertEqual(incomplete_task.title, data["title"])
        self.assertEqual(incomplete_task.description, data["description"])
        self.assertEqual(incomplete_task.task_template, task_template)
        self.assertNotEqual(complete_task.title, data["title"])
        self.assertNotEqual(complete_task.description, data["description"])

        # Deleting the task template should revert title to roadmap task's title
        response = self.client.delete(reverse("task_templates-detail", kwargs={"pk": task_template.pk}))
        self.assertEqual(response.status_code, 200)
        incomplete_task.refresh_from_db()
        self.assertEqual(incomplete_task.title, roadmap_task_template.title)
        self.assertEqual(incomplete_task.description, roadmap_task_template.description)
        self.assertEqual(incomplete_task.task_template, roadmap_task_template)

    def test_list(self):
        url = reverse("task_templates-list")
        tt1 = TaskTemplate.objects.create(title="tt1")
        tt_counselor = TaskTemplate.objects.create(title="tt2", created_by=self.counselor.user)
        TaskTemplate.objects.create(title="tt3", created_by=self.counselor_two.user)
        self.assertEqual(self.client.get(url).status_code, 401)

        # Admin can list all
        self.client.force_login(self.admin.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 3)

        # Counselor sees only their own
        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)
        pks = [x["pk"] for x in result]
        self.assertIn(tt1.pk, pks)
        self.assertIn(tt_counselor.pk, pks)

    def test_list_counselor_override(self):
        """ Test to ensure that if counselor has an un-archived task template that overrides roadmap
            task template, only counselor's task template is returned
        """
        url = f'{reverse("task_templates-list")}?student={self.student.pk}'
        tt1 = TaskTemplate.objects.create(title="1", roadmap_key="1")
        tt2 = TaskTemplate.objects.create(title="1", roadmap_key="2")
        ctt = TaskTemplate.objects.create(title="1", roadmap_key="3", created_by=self.counselor.user)
        TaskManager.create_task(self.student.user, task_template=tt1)
        TaskManager.create_task(self.student.user, task_template=tt2)
        TaskManager.create_task(self.student.user, task_template=ctt)
        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json.loads(response.content)), 3)

        # Counselor has a task template that overrides
        ctt.roadmap_key = tt1.roadmap_key
        ctt.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json.loads(response.content)), 2)
        pks = [x["pk"] for x in json.loads(response.content)]
        self.assertIn(ctt.pk, pks)
        self.assertIn(tt2.pk, pks)

        # But not if counselor's template is archived
        ctt.archived = timezone.now()
        ctt.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json.loads(response.content)), 2)
        pks = [x["pk"] for x in json.loads(response.content)]
        self.assertIn(tt1.pk, pks)
        self.assertIn(tt2.pk, pks)

    def test_update(self):
        tt = TaskTemplate.objects.create()
        tt_counselor = TaskTemplate.objects.create(created_by=self.counselor.user)
        tt_task = Task.objects.create(task_template=tt_counselor, for_user=self.student.user)
        resource = Resource.objects.create(title="1", link="1")
        data = {"allow_content_submission": True, "description": "Great Description"}
        # Only counselor and admin can update
        for user in (self.student.user, self.parent.user, self.tutor.user):
            self.client.force_login(user)
            for url in (
                reverse("task_templates-detail", kwargs={"pk": tt.pk}),
                reverse("task_templates-detail", kwargs={"pk": tt_counselor.pk}),
            ):
                self.assertEqual(
                    self.client.patch(url, json.dumps(data), content_type="application/json",).status_code, 403,
                )
        # Admin can update anything
        self.client.force_login(self.admin.user)
        for url in (
            reverse("task_templates-detail", kwargs={"pk": tt.pk}),
            reverse("task_templates-detail", kwargs={"pk": tt_counselor.pk}),
        ):
            response = self.client.patch(url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            task_template = TaskTemplate.objects.get(pk=result["pk"])
            for k, v in data.items():
                self.assertEqual(result.get(k), v)
                self.assertEqual(getattr(task_template, k), v)

        # Counselor can only update their own
        data["description"] = "Even Better Description!!"
        self.client.force_login(self.counselor.user)
        self.assertEqual(
            self.client.patch(
                reverse("task_templates-detail", kwargs={"pk": tt.pk}),
                json.dumps(data),
                content_type="application/json",
            ).status_code,
            403,
        )
        url = reverse("task_templates-detail", kwargs={"pk": tt_counselor.pk})
        response = self.client.patch(url, json.dumps(data), content_type="application/json",)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(result["description"], data["description"])

        # Test update with updating associated tasks
        data["update_tasks"] = True
        data["title"] = "New Title"
        data["description"] = "Great ND"
        data["resources"] = [resource.pk]
        response = self.client.patch(url, json.dumps(data), content_type="application/json",)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        tt_task.refresh_from_db()
        tt_counselor.refresh_from_db()
        for k, v in data.items():
            if k == "resources":
                self.assertEqual(tt_task.resources.count(), 1)
                self.assertTrue(tt_task.resources.filter(pk=resource.pk).exists())
            elif k != "update_tasks":
                self.assertEqual(getattr(tt_task, k), v)
                self.assertEqual(getattr(tt_counselor, k), v)

    def test_destroy(self):
        tt = TaskTemplate.objects.create()
        tt_counselor = TaskTemplate.objects.create(created_by=self.counselor.user)
        # Only counselor and admin
        for user in (self.student.user, self.parent.user, self.tutor.user):
            self.client.force_login(user)
            for url in (
                reverse("task_templates-detail", kwargs={"pk": tt.pk}),
                reverse("task_templates-detail", kwargs={"pk": tt_counselor.pk}),
            ):
                self.assertEqual(self.client.delete(url).status_code, 403)

        # Admin can destroy anything (sets to archived)
        url = reverse("task_templates-detail", kwargs={"pk": tt.pk})
        self.client.force_login(self.counselor.user)
        self.assertEqual(self.client.delete(url).status_code, 403)
        self.client.force_login(self.admin.user)
        self.assertEqual(self.client.delete(url).status_code, 200)
        tt.refresh_from_db()
        self.assertIsNotNone(tt.archived)

        # Counselor can destroy their own (sets to archived)
        self.client.force_login(self.counselor.user)
        self.assertEqual(
            self.client.delete(reverse("task_templates-detail", kwargs={"pk": tt_counselor.pk})).status_code, 200
        )
        tt_counselor.refresh_from_db()
        self.assertIsNotNone(tt_counselor.archived)
