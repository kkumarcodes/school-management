""" python manage.py test cwcounseling.tests.test_roadmap
"""
from datetime import timedelta
import json

from django.contrib.auth.models import User
from django.db.models import Q
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from cwcounseling.fixtures.roadmaps import import_roadmap
from cwcounseling.models import AgendaItem, AgendaItemTemplate, CounselorMeetingTemplate, Roadmap
from cwcounseling.utilities.roadmap_manager import RoadmapManager
from cwtasks.models import Task, TaskTemplate
from cwusers.constants import counseling_student_types
from cwusers.models import Administrator, Counselor, Parent, Student, Tutor


class TestRoadmapCrud(TestCase):
    """
    python manage.py test cwcounseling.tests.test_roadmap:TestRoadmapCrud
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.tutor = Tutor.objects.first()
        self.counselor = Counselor.objects.first()
        self.administrator = Administrator.objects.first()
        self.parent = Parent.objects.first()

        self.roadmap = import_roadmap.import_roadmap("late_start_senior", "Late Start Senior")

    def test_roadmap_get(self):
        """
        Test retrieving all roadmaps. Limited to Admins and Counselors
        """

        url = reverse("roadmaps-list")

        self.client.force_login(self.administrator.user)
        response = self.client.get(url)
        roadmap = response.data[0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(roadmap["title"], self.roadmap.title)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(len(roadmap["counselor_meeting_templates"]), self.roadmap.counselor_meeting_templates.count())

        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.student.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.tutor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_roadmap_create(self):
        """ Test creating a roadmap with and without counselor meetings
        """
        url = reverse("roadmaps-list")
        data = {"title": "Roadmap1"}
        self.client.force_login(self.counselor.user)
        # Counselor can't create roadmap
        self.assertEqual(self.client.post(url, json.dumps(data), content_type="application/json").status_code, 403)

        # Admin can! Without counselor meeting templates
        self.client.force_login(self.administrator.user)
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        result = json.loads(response.content)
        roadmap = Roadmap.objects.get(pk=result["pk"])
        self.assertEqual(roadmap.title, data["title"])
        self.assertFalse(roadmap.counselor_meeting_templates.exists())

        # And with a counselor meeting template
        cmt = CounselorMeetingTemplate.objects.last()
        data["update_counselor_meeting_templates"] = [cmt.pk]
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        result = json.loads(response.content)
        roadmap = Roadmap.objects.get(pk=result["pk"])
        self.assertEqual(roadmap.title, data["title"])
        self.assertEqual(roadmap.counselor_meeting_templates.count(), 1)


class TestRoadmapApply(TestCase):
    """ python manage.py test cwcounseling.tests.test_roadmap:TestRoadmapApply
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.counselor = Counselor.objects.first()
        self.student = Student.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.student_two = Student.objects.create(
            user=User.objects.create_user("student2"),
            counseling_student_types_list=[counseling_student_types.ALL_INCLUSIVE_12],
            counselor=self.counselor,
        )
        self.tutor = Tutor.objects.first()

        self.roadmap = import_roadmap.import_roadmap("late_start_senior", "Late Start Senior")
        self.meeting_templates = CounselorMeetingTemplate.objects.filter(roadmap=self.roadmap)
        self.endpoint = reverse("roadmaps-apply_roadmap", kwargs={"pk": self.roadmap.pk})

    def test_apply_roadmap_failure(self):
        # Must be logged in
        payload = json.dumps({"student_id": self.student.pk})
        response = self.client.post(self.endpoint, payload, content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Perms issue
        self.client.force_login(self.tutor.user)
        response = self.client.post(self.endpoint, payload, content_type="application/json")
        self.assertEqual(response.status_code, 403)

        # Incorrect counselor meeting
        self.client.force_login(self.counselor.user)
        payload = {"student_id": self.student.pk, "counselor_meetings": [{"counselor_meeting_template": 1098}]}
        response = self.client.post(self.endpoint, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 404)

        # Incorrect agenda item template
        payload["counselor_meetings"] = [
            {"counselor_meeting_template": self.meeting_templates.first().pk, "agenda_item_templates": [9987, 8877],}
        ]
        response = self.client.post(self.endpoint, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 404)

    def test_default_apply_to_student(self):
        def _confirm_for_student(student):
            self.assertEqual(student.counselor_meetings.count(), self.meeting_templates.count())
            self.assertTrue(student.applied_roadmaps.filter(pk=self.roadmap.pk).exists())
            self.assertEqual(
                AgendaItem.objects.filter(counselor_meeting__student=student).count(),
                AgendaItemTemplate.objects.filter(counselor_meeting_template__in=self.meeting_templates).count(),
            )
            # Confirm that all tasks associated with roadmap were created
            self.assertEqual(
                student.user.tasks.count(),
                Task.objects.filter(
                    Q(task_template__pre_agenda_item_templates__counselor_meeting_template__in=self.meeting_templates)
                    | Q(
                        task_template__post_agenda_item_templates__counselor_meeting_template__in=self.meeting_templates
                    )
                )
                .distinct()
                .count(),
            )

            # Confirm that task has proper counselor_meetings
            task = student.user.tasks.order_by("pk").last()
            self.assertEqual(task.counselor_meetings.count(), 1)
            self.assertTrue(
                task.counselor_meetings.filter(
                    counselor_meeting_template=task.task_template.pre_agenda_item_templates.first().counselor_meeting_template
                ).exists()
            )

        # test the default applying of a roadmap
        self.student.user.tasks.all().delete()
        mgr = RoadmapManager(self.roadmap)
        mgr.apply_to_student(self.student)
        _confirm_for_student(self.student)

        # Test via endpoint
        self.student.user.tasks.all().delete()
        self.client.force_login(self.counselor.user)
        response = self.client.post(
            self.endpoint, json.dumps({"student_id": self.student_two.pk}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        _confirm_for_student(self.student_two)

    def test_custom_apply_to_student(self):
        """ python manage.py test cwcounseling.tests.test_roadmap:TestRoadmapApply.test_custom_apply_to_student
        """
        self.client.force_login(self.counselor.user)
        # We find two agenda items with tasks, and set them to be part of non-standard meeting when applying roadmap
        agenda_item_one = AgendaItemTemplate.objects.filter(pre_meeting_task_templates__isnull=False).first()
        agenda_item_two = (
            AgendaItemTemplate.objects.filter(pre_meeting_task_templates__isnull=False)
            .exclude(pk=agenda_item_one.pk)
            .first()
        )

        # Counselor overrides one of the task templates
        task_template = agenda_item_one.pre_meeting_task_templates.first()
        counselor_task_template = TaskTemplate.objects.create(
            roadmap_key=task_template.roadmap_key, created_by=self.counselor.user, title="Great custom title!!!!"
        )
        # counselor_task_template.pre_agenda_item_templates.add(*task_template.pre_agenda_item_templates.all())

        meetings_for_agenda_items = CounselorMeetingTemplate.objects.filter(
            agenda_item_templates__in=[agenda_item_one, agenda_item_two]
        ).distinct()
        meeting_payload = {
            "counselor_meeting_template": self.roadmap.counselor_meeting_templates.exclude(
                pk__in=meetings_for_agenda_items
            )
            .first()
            .pk,
            "agenda_item_templates": [agenda_item_two.pk, agenda_item_one.pk],
        }
        post_payload = [
            {"counselor_meeting_template": x.pk, "agenda_item_templates": []} for x in meetings_for_agenda_items
        ]
        post_payload.append(meeting_payload)
        response = self.client.post(
            self.endpoint,
            json.dumps({"student_id": self.student.pk, "counselor_meetings": post_payload}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        # Confirm all roadmap tasks created, but only some have meetings
        self.assertEqual(
            self.student.user.tasks.all().count(),
            Task.objects.filter(
                Q(task_template__pre_agenda_item_templates__counselor_meeting_template__roadmap=self.roadmap)
                | Q(task_template__post_agenda_item_templates__counselor_meeting_template__roadmap=self.roadmap)
            )
            .distinct()
            .count()
            + 1,
        )
        task_count = (
            agenda_item_one.pre_meeting_task_templates.count() + agenda_item_two.pre_meeting_task_templates.count()
        )
        self.assertEqual(self.student.user.tasks.filter(counselor_meetings__isnull=False).count(), task_count)

        # Confirm that tasks followed agenda items to the custom meeting
        meeting = self.student.counselor_meetings.get(
            counselor_meeting_template=meeting_payload["counselor_meeting_template"]
        )
        self.assertEqual(meeting.tasks.count(), task_count)
        # Confirm that non custom meeting was created
        self.assertTrue(
            self.student.counselor_meetings.filter(
                counselor_meeting_template=meetings_for_agenda_items.first().pk
            ).exists()
        )

        # Confirm that task was created for counselor task template but not task template
        self.assertTrue(self.student.user.tasks.filter(task_template=counselor_task_template).exists())
        task = self.student.user.tasks.get(task_template=counselor_task_template)
        self.assertEqual(task.title, counselor_task_template.title)
        self.assertFalse(self.student.user.tasks.filter(task_template=task_template).exists())

        # Confirm task without meetings still has correct counselor meeting template
        task = self.student.user.tasks.filter(counselor_meetings__isnull=True).last()
        self.assertTrue(task.counselor_meeting_template)
        # self.assertEqual(
        #     task.counselor_meeting_template,
        #     task.task_template.pre_agenda_item_templates.first().counselor_meeting_template,
        # )

        self.assertEqual(self.student.counselor_meetings.count(), 2)
        self.assertEqual(AgendaItem.objects.filter(counselor_meeting__student=self.student).count(), 2)
        self.assertTrue(
            AgendaItem.objects.filter(
                counselor_meeting__student=self.student, agenda_item_template=agenda_item_one
            ).exists()
        )
        self.assertTrue(
            AgendaItem.objects.filter(
                counselor_meeting__student=self.student, agenda_item_template=agenda_item_two
            ).exists()
        )

        # And finally we create a meeting with no agenda items
        self.student.counselor_meetings.all().delete()
        meeting_template = CounselorMeetingTemplate.objects.filter(agenda_item_templates__isnull=False).first().pk
        meeting_payload = {"counselor_meeting_template": meeting_template, "agenda_item_templates": []}
        response = self.client.post(
            self.endpoint,
            json.dumps({"student_id": self.student.pk, "counselor_meetings": [meeting_payload]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(AgendaItem.objects.filter(counselor_meeting__student=self.student).exists())


class TestRoadmapUnapply(TestCase):
    """ python manage.py test cwcounseling.tests.test_roadmap:TestRoadmapUnapply
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.counselor = Counselor.objects.first()
        self.student = Student.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.student_two = Student.objects.create(
            user=User.objects.create_user("student2"),
            counseling_student_types_list=[counseling_student_types.ALL_INCLUSIVE_12],
            counselor=self.counselor,
        )
        self.tutor = Tutor.objects.first()

        self.roadmap = import_roadmap.import_roadmap("late_start_senior", "Late Start Senior")
        self.meeting_templates = CounselorMeetingTemplate.objects.filter(roadmap=self.roadmap)
        self.endpoint = reverse("roadmaps-unapply_roadmap", kwargs={"pk": self.roadmap.pk})

    def test_manager(self):
        """ Here is where we do most of our special case testing
        """
        mgr = RoadmapManager(self.roadmap)
        mgr.apply_to_student(self.student)
        mgr.apply_to_student(self.student_two)

        submitted_task = self.student.user.tasks.first()
        submitted_task.completed = timezone.now()
        submitted_task.save()

        non_roadmap_task = self.student.user.tasks.last()
        non_roadmap_task.task_template = None
        non_roadmap_task.save()

        scheduled_meeting = self.student.counselor_meetings.first()
        scheduled_meeting.start = timezone.now() - timedelta(days=1)
        scheduled_meeting.end = scheduled_meeting.start + timedelta(hours=1)
        scheduled_meeting.save()

        student_two_task_count = self.student_two.user.tasks.count()
        student_two_meeting_count = self.student_two.counselor_meetings.count()

        # Confirm we only removed tasks and meetings for the right student
        updated_student = mgr.unapply_from_student(self.student)
        self.assertFalse(updated_student.applied_roadmaps.exists())
        self.assertEqual(self.student_two.applied_roadmaps.count(), 1)
        self.assertEqual(self.student_two.user.tasks.count(), student_two_task_count)
        self.assertEqual(self.student_two.counselor_meetings.count(), student_two_meeting_count)

        # Confirm that previous meeting isn't removed
        self.assertEqual(self.student.counselor_meetings.count(), 1)
        self.assertEqual(self.student.counselor_meetings.first().pk, scheduled_meeting.pk)

        # Confirm that only tasks for roadmap are removed
        self.assertEqual(self.student.user.tasks.count(), 2)
        self.assertTrue(self.student.user.tasks.filter(pk=submitted_task.pk).exists())
        self.assertTrue(self.student.user.tasks.filter(pk=non_roadmap_task.pk).exists())

    def test_view(self):
        # Simple test to make sure the view properly uses manager to unapply roadmap
        self.client.force_login(self.counselor.user)
        mgr = RoadmapManager(self.roadmap)
        mgr.apply_to_student(self.student)
        submitted_task = self.student.user.tasks.first()
        submitted_task.completed = timezone.now()
        submitted_task.save()

        response = self.client.post(
            self.endpoint, json.dumps({"student_id": self.student.pk}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result["roadmaps"]), 0)
        self.assertEqual(self.student.user.tasks.count(), 1)
        self.assertFalse(self.student.counselor_meetings.exists())
