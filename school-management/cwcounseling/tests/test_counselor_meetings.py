""" python manage.py test cwcounseling.tests.test_counselor_meetings
"""

from decimal import Decimal
import json
import random
from datetime import timedelta
from rest_framework import status
from django.test import TestCase
from django.shortcuts import reverse
from django.utils import timezone
from django.core import mail
from django.contrib.contenttypes.models import ContentType
from cwcounseling.constants import counselor_time_entry_category
from cwcounseling.utilities.roadmap_manager import RoadmapManager
from cwcounseling.models import (
    AgendaItem,
    AgendaItemTemplate,
    CounselorAvailability,
    CounselorMeeting,
    CounselorMeetingTemplate,
    CounselorTimeEntry,
    CounselorEventType,
)
from cwcounseling.utilities.counselor_meeting_manager import CounselorMeetingManager, CounselorMeetingManagerException
from cwcounseling.fixtures.roadmaps import import_roadmap
from cwnotifications.models import Notification
from cwtasks.models import Task, TaskTemplate
from cwresources.models import Resource
from cwusers.models import Administrator, Student, Counselor, Parent


class TestCounselorMeetingManager(TestCase):
    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.counselor_meeting = CounselorMeeting.objects.create(student=self.student)
        self.counselor_meeting_with_tasks = CounselorMeeting.objects.create(student=self.student)
        self.tasks = Task.objects.bulk_create(
            [Task(for_user=self.student.user, title=f"Title {idx}") for idx in range(3)]
        )
        self.counselor_meeting_with_tasks.tasks.set(self.tasks)

    def test_schedule_meeting(self):
        self.counselor.zoom_url = "https://zoom.com"
        self.counselor.save()
        noti_count = Notification.objects.count()
        start = timezone.now() + timedelta(hours=26)
        end = start + timedelta(hours=1)
        mgr = CounselorMeetingManager(self.counselor_meeting)
        updated_meeting = mgr.schedule(start, end)
        self.assertEqual(updated_meeting.start, start)
        self.assertEqual(updated_meeting.end, end)
        # Confirm notification was sent to student
        self.assertEqual(Notification.objects.count(), noti_count + 1)
        noti = Notification.objects.last()
        self.assertEqual(noti.notification_type, "student_counselor_meeting_confirmed")
        self.assertEqual(noti.recipient.user, self.student.user)
        self.assertIsNotNone(noti.emailed)
        self.assertIsNone(noti.texted)

        # Confirm that counselor Zoom URL was in notification
        message = mail.outbox[-1]
        self.assertIn(self.counselor.zoom_url, str(message.alternatives[0][0]))

        # Confirm CounselorTimeEntry was created
        self.assertTrue(CounselorTimeEntry.objects.filter(counselor_meeting=updated_meeting).exists())
        self.assertEqual(updated_meeting.start, updated_meeting.counselor_time_entry.date)
        self.assertEqual(updated_meeting.counselor_time_entry.student, self.student)
        self.assertEqual(updated_meeting.counselor_time_entry.counselor, self.counselor)
        self.assertEqual(
            updated_meeting.counselor_time_entry.category, counselor_time_entry_category.TIME_CATEGORY_MEETING
        )

        # Can't reschedule with schedule method
        schedule = lambda mgr: mgr.schedule(timezone.now(), timezone.now())
        self.assertRaises(CounselorMeetingManagerException, schedule, mgr)

        # When a counselor schedules a meeting, a meeting's tasks due date is not automatically set
        mgr = CounselorMeetingManager(self.counselor_meeting_with_tasks)
        start = timezone.now()
        end = start + timedelta(hours=1)
        mgr.schedule(start, end, False, False, self.counselor.user)
        self.assertIsNone(self.counselor_meeting_with_tasks.tasks.first().due)
        # When a student schedules a meeting, a meeting's tasks without a due date are set to meeting start
        mgr.cancel(set_cancelled=False, send_notification=False)
        mgr.schedule(start, end, False, False, self.student.user)
        first_task = self.counselor_meeting_with_tasks.tasks.first()
        self.assertEqual(first_task.due, start)
        self.assertTrue(first_task.visible_to_counseling_student)

    def test_reschedule_meeting(self):
        # We create a time entry so that we can confirm it was manipulated
        counselor_time_entry: CounselorTimeEntry = CounselorTimeEntry.objects.create(
            student=self.student,
            counselor=self.counselor,
            date=timezone.now(),
            hours=40,
            counselor_meeting=self.counselor_meeting,
        )
        noti_count = Notification.objects.count()
        start = timezone.now() + timedelta(hours=26)
        end = start + timedelta(hours=1)
        # Cannot reschedule unscheduled meeting
        reschedule = lambda mgr: mgr.reschedule(start, end)
        self.assertRaises(CounselorMeetingManagerException, reschedule, CounselorMeetingManager(self.counselor_meeting))

        self.counselor_meeting.start = timezone.now()
        self.counselor_meeting.end = self.counselor_meeting.start + timedelta(hours=1)
        self.counselor_meeting.save()

        mgr = CounselorMeetingManager(self.counselor_meeting)
        updated_meeting = mgr.reschedule(start, end)
        self.assertEqual(updated_meeting.start, start)
        self.assertEqual(updated_meeting.end, end)
        # Confirm notification was sent to student
        self.assertEqual(Notification.objects.count(), noti_count + 1)
        noti = Notification.objects.last()
        self.assertEqual(noti.notification_type, "student_counselor_meeting_rescheduled")
        self.assertEqual(noti.recipient.user, self.student.user)
        self.assertIsNotNone(noti.emailed)
        self.assertIsNone(noti.texted)

        # Confirm time entry updated accordingly
        counselor_time_entry.refresh_from_db()
        self.assertEqual(counselor_time_entry.date, updated_meeting.start)
        self.assertEqual(counselor_time_entry.hours, Decimal(1))

        # Test again but suppress notification
        noti_count = Notification.objects.count()
        self.counselor_meeting.start = timezone.now()
        self.counselor_meeting.end = self.counselor_meeting.start + timedelta(hours=1)
        self.counselor_meeting.save()
        mgr = CounselorMeetingManager(self.counselor_meeting)
        mgr.reschedule(start, end, send_notification=False)
        self.assertEqual(Notification.objects.count(), noti_count)

        # When a student reschedules a meeting a meeting's tasks:
        # Tasks without a due date are set to meeting's new start -- self.tasks[0]
        # Tasks with due date same as old meeting start are updated to new meeting start -- self.tasks[1]
        # Tasks with custom date are left unchanged -- self.tasks[2]
        old_start = timezone.now()
        old_end = old_start + timedelta(hours=1)
        new_start = old_start + timedelta(days=1)
        new_end = new_start + timedelta(hours=1)
        custom_due = old_start - timedelta(days=1)
        # Tasks[0] => no due date, Tasks[1] => due == meeting.start, Tasks[2] => due == custom
        self.tasks[1].due = old_start
        self.tasks[1].save()
        self.tasks[2].due = custom_due
        self.tasks[2].save()
        self.counselor_meeting_with_tasks.start = old_start
        self.counselor_meeting_with_tasks.end = old_end
        self.counselor_meeting_with_tasks.save()
        mgr = CounselorMeetingManager(self.counselor_meeting_with_tasks)
        mgr.reschedule(new_start, new_end, False, self.student.user)
        self.assertEqual(self.counselor_meeting_with_tasks.tasks.first().due, new_start)
        self.assertTrue(self.counselor_meeting_with_tasks.tasks.first().visible_to_counseling_student)
        self.assertEqual(self.counselor_meeting_with_tasks.tasks.get(title__icontains="1").due, new_start)
        self.assertTrue(self.counselor_meeting_with_tasks.tasks.get(title__icontains="1").visible_to_counseling_student)
        self.assertEqual(self.counselor_meeting_with_tasks.tasks.last().due, custom_due)

    def test_cancel_meeting(self):
        CounselorTimeEntry.objects.create(
            student=self.counselor_meeting.student, counselor_meeting=self.counselor_meeting, hours=1
        )
        noti_count = Notification.objects.count()
        # Cannot cancel unscheduled meeting
        cancel = lambda mgr: mgr.cancel()
        self.assertRaises(CounselorMeetingManagerException, cancel, CounselorMeetingManager(self.counselor_meeting))

        self.counselor_meeting.start = timezone.now()
        self.counselor_meeting.end = self.counselor_meeting.start + timedelta(hours=1)
        self.counselor_meeting.save()

        self.assertIsNone(self.counselor_meeting.cancelled)
        mgr = CounselorMeetingManager(self.counselor_meeting)
        updated_meeting = mgr.cancel()
        self.assertIsNotNone(updated_meeting.cancelled)
        self.assertEqual(Notification.objects.count(), noti_count + 1)
        noti = Notification.objects.last()
        self.assertEqual(noti.notification_type, "student_counselor_meeting_cancelled")
        self.assertEqual(noti.recipient.user, self.student.user)
        self.assertIsNotNone(noti.emailed)
        self.assertIsNone(noti.texted)
        self.assertFalse(CounselorTimeEntry.objects.exists())


class TestCounselorMeetingViewset(TestCase):
    """ python manage.py test cwcounseling.tests.test_counselor_meetings:TestCounselorMeetingViewset
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.parent = Parent.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.roadmap = import_roadmap.import_roadmap("late_start_senior", "Late Start Senior")

    def test_create(self):
        # Test create w/o dates
        data = {"student": self.student.pk, "private_notes": "Test Private Note", "title": "Great title"}
        url = reverse("counselor_meetings-list")
        # Must be logged in
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Finally some success!
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        data = json.loads(response.content)
        for x in ("meeting", "tasks", "agenda_items"):
            self.assertIn(x, data)
        self.assertEqual(response.status_code, 201)
        meeting_data = data["meeting"]
        meeting = CounselorMeeting.objects.get(pk=meeting_data["pk"])
        self.assertEqual(meeting.student, self.student)
        self.assertIsNone(meeting.start)
        self.assertIsNone(meeting.end)
        self.assertEqual(meeting.private_notes, meeting_data["private_notes"])
        # No noti since there were no dates
        self.assertFalse(Notification.objects.filter(notification_type="student_counselor_meeting_confirmed").exists())

        # Test create by parent. Can only create for own student
        self.client.force_login(self.parent.user)
        data = {"student": self.student.pk, "private_notes": "Test Private Note", "title": "Parent cannot create"}
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.student.parent = self.parent
        self.student.save()

        self.client.force_login(self.parent.user)
        data = {"student": self.student.pk, "private_notes": "Test Private Note", "title": "Confirm created"}
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["meeting"]["student"], self.student.pk)
        self.assertEqual(response.data["meeting"]["title"], data["title"])

        # Test student can only create for self
        self.client.force_login(self.student.user)
        data = {"student": Student.objects.create().pk, "title": "should fail"}
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        data = {"student": self.student.pk, "title": "Student creating for self Confirm created"}
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["meeting"]["student"], self.student.pk)
        self.assertEqual(response.data["meeting"]["title"], data["title"])

        # Test create w/dates, confirm noti to student
        meeting_data["start"] = timezone.now().isoformat()
        meeting_data["end"] = (timezone.now() + timedelta(hours=1)).isoformat()
        response = self.client.post(url, json.dumps(meeting_data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Notification.objects.filter(
                recipient__user=self.student.user,
                notification_type="student_counselor_meeting_confirmed",
                related_object_pk=json.loads(response.content)["meeting"]["pk"],
                related_object_content_type=ContentType.objects.get_for_model(CounselorMeeting),
            ).exists()
        )

        # Unless we specify NOT sending notification
        meeting_data["send_notification"] = False
        response = self.client.post(url, json.dumps(meeting_data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(
            Notification.objects.filter(
                recipient__user=self.student.user,
                notification_type="student_counselor_meeting_confirmed",
                related_object_pk=json.loads(response.content)["meeting"]["pk"],
                related_object_content_type=ContentType.objects.get_for_model(CounselorMeeting),
            ).exists()
        )

    def test_create_custom(self):
        """ Test creating a meeting with custom set of tasks and agenda items
        """
        meeting_template: CounselorMeetingTemplate = self.roadmap.counselor_meeting_templates.first()
        self.assertTrue(meeting_template.agenda_item_templates.count() > 1)
        data = {"student": self.student.pk, "counselor_meeting_template": meeting_template.pk}
        # We only create an agenda item from one template
        data["agenda_item_templates"] = [meeting_template.agenda_item_templates.last().pk]
        # But we also create two custom agenda items!
        data["custom_agenda_items"] = ["cai1", "cai2"]
        # And we create a custom task to associate with meeting
        custom_task = Task.objects.create(for_user=self.student.user, title="Custom Task One!!")
        data["tasks"] = [custom_task.pk]

        self.client.force_login(self.counselor.user)
        response = self.client.post(
            reverse("counselor_meetings-list"), json.dumps(data), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        result = json.loads(response.content)
        self.assertEqual(len(result["agenda_items"]), 3)
        self.assertEqual(len(result["tasks"]), 1)

        meeting: CounselorMeeting = CounselorMeeting.objects.get(pk=result["meeting"]["pk"])
        self.assertEqual(meeting.counselor_meeting_template, meeting_template)
        self.assertEqual(meeting.agenda_items.count(), 3)
        self.assertTrue(meeting.agenda_items.filter(agenda_item_template=data["agenda_item_templates"][0]).exists())
        self.assertTrue(meeting.tasks.filter(pk=custom_task.pk).exists())

        original_agenda_items = [x.pk for x in meeting.agenda_items.all()]

        # Now we update that same meeting to have a different agenda item, a new custom agenda item, and a different task
        # We apply roadmap to student just to get other agenda items and tasks to work with
        mgr = RoadmapManager(self.roadmap)
        mgr.apply_to_student(self.student)
        agenda_items = [
            random.choice(
                AgendaItem.objects.filter(counselor_meeting__student=self.student).exclude(counselor_meeting=meeting)
            ).pk
            for x in range(3)
        ]
        data = {
            "agenda_items": agenda_items,
            "custom_agenda_items": ["NewAI"],
            "agenda_item_templates": [
                AgendaItemTemplate.objects.exclude(counselor_meeting_template=meeting_template)
                .exclude(agenda_items__in=agenda_items)
                .last()
                .pk
            ],
            "tasks": [self.student.user.tasks.last().pk],
        }
        response = self.client.patch(
            reverse("counselor_meetings-detail", kwargs={"pk": meeting.pk}),
            json.dumps(data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        meeting.refresh_from_db()
        self.assertFalse(meeting.tasks.filter(pk=custom_task.pk).exists())
        self.assertEqual(meeting.counselor_meeting_template, meeting_template)
        self.assertEqual(meeting.agenda_items.count(), 2 + len(set(data["agenda_items"])))
        self.assertTrue(meeting.agenda_items.filter(agenda_item_template=data["agenda_item_templates"][0]).exists())
        new_agenda_items = meeting.agenda_items.values_list("pk", flat=True)
        self.assertFalse(any([x in new_agenda_items for x in original_agenda_items]))

    def test_reschedule(self):
        meeting = CounselorMeeting.objects.create(student=self.student, start=timezone.now(), end=timezone.now())
        data = {
            "start": (timezone.now() + timedelta(hours=1)).isoformat(),
            "end": (timezone.now() + timedelta(hours=2)).isoformat(),
        }
        url = reverse("counselor_meetings-detail", kwargs={"pk": meeting.pk})
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Counselor reschedules. Confirm student is notified
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        meeting.refresh_from_db()
        self.assertIsNotNone(meeting.start)
        self.assertIsNotNone(meeting.end)
        self.assertTrue(
            Notification.objects.filter(
                recipient__user=self.student.user,
                notification_type="student_counselor_meeting_rescheduled",
                related_object_pk=json.loads(response.content)["meeting"]["pk"],
                related_object_content_type=ContentType.objects.get_for_model(CounselorMeeting),
            ).exists()
        )

        # Student reschedules. Confirm counselor is notified
        meeting.start = timezone.now() + timedelta(hours=36)
        meeting.end = timezone.now() + timedelta(hours=37)
        meeting.save()
        self.client.force_login(self.student.user)
        start = timezone.now() + timedelta(hours=72)
        data = {"start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()}
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        # First attempt fails because counselor is not available :(
        self.assertEqual(response.status_code, 400)

        CounselorAvailability.objects.create(
            counselor=self.student.counselor, start=start - timedelta(hours=1), end=start + timedelta(hours=2)
        )

        # Okay now counselor is available :)
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        meeting.refresh_from_db()
        self.assertIsNotNone(meeting.start)
        self.assertIsNotNone(meeting.end)
        self.assertTrue(
            Notification.objects.filter(
                recipient__user=self.counselor.user,
                notification_type="counselor_counselor_meeting_rescheduled",
                related_object_pk=json.loads(response.content)["meeting"]["pk"],
                related_object_content_type=ContentType.objects.get_for_model(CounselorMeeting),
            ).exists()
        )

        # Student can't reschedule to within counselor.student_schedule_meeting_buffer_hours hours
        start = timezone.now() + timedelta(hours=2)
        data = {"start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()}
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_cancel(self):
        # TODO
        pass

    def test_retrieve(self):
        # Test to ensure we get task types for task templates assocaited with counselor meeting
        counselor_meeting_template = CounselorMeetingTemplate.objects.create(
            title="Template 1",
            counselor_instructions="Counselor instructions",
            student_instructions="Student instructions",
        )
        resource = Resource.objects.create(link="test.com")
        counselor_meeting_template.counselor_resources.add(resource)

        # We create task templates for each task type
        task_templates = [
            TaskTemplate.objects.create(counselor_meeting_template=counselor_meeting_template, task_type=t[0])
            for t in TaskTemplate.TASK_TYPE_CHOICES
        ]
        meeting = CounselorMeeting.objects.create(
            counselor_meeting_template=counselor_meeting_template, student=self.student,
        )
        url = reverse("counselor_meetings-detail", kwargs={"pk": meeting.pk})

        # Must have access to student
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)
        parent = Parent.objects.first()
        self.client.force_login(parent.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        # Test related task type through TaskTemplates
        # self.student.parent = parent
        # self.student.save()
        # response = self.client.get(url)
        # self.assertEqual(response.status_code, 200)
        # result = json.loads(response.content)
        # self.assertEqual(set([x.task_type for x in task_templates]), set(result["related_task_types"]))

    def test_create_with_event_type(self):
        self.client.force_login(self.student.user)
        event_type = CounselorEventType.objects.create(title="Test Type", duration=60, created_by=self.counselor)
        data = {
            "student": self.student.pk,
            "title": "Great title",
            "event_type": CounselorEventType.objects.first().pk,
        }
        url = reverse("counselor_meetings-list")

        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["meeting"]["event_type"], event_type.pk)


class TestCounselorMeetingTemplateView(TestCase):
    """ python manage.py test cwcounseling.tests.test_counselor_meetings:TestCounselorMeetingTemplateView
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.admin = Administrator.objects.first()
        self.resource = Resource.objects.create(link="test.com")
        self.template_one = CounselorMeetingTemplate.objects.create(counselor_instructions="Counselor Instructions 1")
        self.template_one.counselor_resources.add(self.resource)
        self.template_two = CounselorMeetingTemplate.objects.create(counselor_instructions="Counselor Instructions 2")

    def test_list(self):
        url = reverse("counselor_meeting_templates-list")

        # No auth
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

        # TODO: When update after we implement Roadmap view
        # self.client.force_login(self.student.user)
        # response = self.client.get(url)
        # self.assertEqual(response.status_code, 403)

        # Success
        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)
        for res in result:
            pks = [self.template_two.pk, self.template_one.pk]
            self.assertTrue(all([x["pk"] in pks for x in result]))
            if res["pk"] == self.template_one.pk:
                self.assertEqual(res["counselor_resources"][0]["link"], self.resource.link)
                self.assertEqual(res["counselor_instructions"], self.template_one.counselor_instructions)
            elif res["pk"] == self.template_two.pk:
                self.assertEqual(res["counselor_instructions"], self.template_two.counselor_instructions)
                self.assertEqual(len(res["counselor_resources"]), 0)

    def test_create_update(self):
        # Admin (and not counselor) can create and update counselor meeting templates
        create_data = {"title": "CMT1"}
        self.client.force_login(self.counselor.user)
        url = reverse("counselor_meeting_templates-list")
        self.assertEqual(
            self.client.post(url, json.dumps(create_data), content_type="application/json").status_code, 403
        )
        self.client.force_login(self.admin.user)
        response = self.client.post(url, json.dumps(create_data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        cmt = CounselorMeetingTemplate.objects.get(pk=json.loads(response.content)["pk"])
        self.assertEqual(cmt.title, create_data["title"])

        update_data = {"title": "New Title!!", "grade": 10}
        url = reverse("counselor_meeting_templates-detail", kwargs={"pk": cmt.pk})
        response = self.client.patch(url, json.dumps(update_data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        cmt.refresh_from_db()
        self.assertEqual(cmt.grade, update_data["grade"])
        self.assertEqual(cmt.title, update_data["title"])


class TestAgendaItemViews(TestCase):
    """ Tests views for agenda items and agenda item templates
        python manage.py test cwcounseling.tests.test_counselor_meetings:TestAgendaItemViews
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.roadmap = import_roadmap.import_roadmap("late_start_senior", "Late Start Senior")
        self.counselor = Counselor.objects.first()
        self.student = Student.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        mgr = RoadmapManager(self.roadmap)
        mgr.apply_to_student(self.student)

    def test_get_agenda_items(self):
        meeting = self.student.counselor_meetings.exclude(agenda_items=None).first()
        url = f'{reverse("agenda_items")}?counselor_meeting={meeting.pk}'
        # Requires login
        self.assertEqual(self.client.get(url).status_code, 401)

        # Failure for random parent
        parent = Parent.objects.first()
        self.client.force_login(parent.user)
        self.assertEqual(self.client.get(url).status_code, 403)

        # Success for student
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.get(url).status_code, 200)

        # Success for counselor
        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), meeting.agenda_items.count())
        for x in result:
            self.assertTrue(meeting.agenda_items.filter(pk=x["pk"]).exists())


class TestAgendaItemTemplateViewset(TestCase):
    """ python manage.py test cwcounseling.tests.test_counselor_meetings:TestAgendaItemTemplateViewset
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.parent = Parent.objects.first()
        self.admin = Administrator.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.roadmap = import_roadmap.import_roadmap("late_start_senior", "Late Start Senior")
        mgr = RoadmapManager(self.roadmap)
        mgr.apply_to_student(self.student)

    def test_list(self):
        # Confirm counselor and admin can list agenda item templates
        url = f'{reverse("agenda_item_templates-list")}?student={self.student.pk}'
        for user in (self.counselor.user, self.admin.user):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(json.loads(response.content)), AgendaItemTemplate.objects.count())

    def test_create_update(self):
        # Test only admins can create/update agenda item templates
        task_template = TaskTemplate.objects.first()
        create_data = {
            "counselor_title": "1",
            "student_title": "2",
            "pre_meeting_task_templates": [task_template.pk],
        }
        url = reverse("agenda_item_templates-list")
        self.client.force_login(self.counselor.user)
        self.assertEqual(
            self.client.post(url, json.dumps(create_data), content_type="application/json").status_code, 403
        )
        self.client.force_login(self.admin.user)
        response = self.client.post(url, json.dumps(create_data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        ait: AgendaItemTemplate = AgendaItemTemplate.objects.get(pk=json.loads(response.content)["pk"])
        self.assertEqual(ait.counselor_title, create_data["counselor_title"])
        self.assertEqual(ait.student_title, create_data["student_title"])
        self.assertEqual(ait.pre_meeting_task_templates.count(), 1)
        self.assertTrue(ait.pre_meeting_task_templates.filter(pk=task_template.pk).exists())

        post_task_template = TaskTemplate.objects.last()
        update_data = {
            "order": 7,
            "pre_meeting_task_templates": [],
            "post_meeting_task_templates": [post_task_template.pk],
        }
        url = reverse("agenda_item_templates-detail", kwargs={"pk": ait.pk})
        response = self.client.patch(url, json.dumps(update_data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        ait.refresh_from_db()
        self.assertFalse(ait.pre_meeting_task_templates.exists())
        self.assertEqual(ait.post_meeting_task_templates.count(), 1)
        self.assertTrue(ait.post_meeting_task_templates.filter(pk=post_task_template.pk).exists())
        self.assertEqual(ait.order, update_data["order"])


class TestCounselorMeetingMessage(TestCase):
    """ Test creating and sending a message for a counselor meeting (as a counselor)
        python manage.py test cwcounseling.tests.test_counselor_meetings:TestCounselorMeetingMessage
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.roadmap = import_roadmap.import_roadmap("late_start_senior", "Late Start Senior")
        self.counselor: Counselor = Counselor.objects.first()
        self.student: Student = Student.objects.first()
        self.student.counselor = self.counselor
        self.parent = Parent.objects.first()
        self.student.parent = self.parent
        self.student.save()
        mgr = RoadmapManager(self.roadmap)
        mgr.apply_to_student(self.student)
        self.meeting: CounselorMeeting = self.student.counselor_meetings.first()
        self.meeting.notes_message_note = "Really great message note"
        self.meeting.notes_message_subject = "Really great message subject"
        self.meeting.save()
        self.meeting.notes_message_upcoming_tasks.add(*self.student.user.tasks.order_by("pk")[0:2])
        self.meeting.notes_message_completed_tasks.add(*self.student.user.tasks.order_by("pk")[2:4])
        self.meeting.notes_message_upcoming_tasks.all().update(due=timezone.now() + timedelta(days=10))
        self.meeting.notes_message_completed_tasks.all().update(completed=timezone.now())
        self.mgr = CounselorMeetingManager(self.meeting)

    def test_send_message_utility(self):
        # Send notes to student then parent
        noti_count = Notification.objects.count()
        self.assertIsNone(self.meeting.last_reminder_sent)
        self.assertFalse(self.meeting.notes_finalized)
        updated_meeting: CounselorMeeting = self.mgr.send_notes(send_to_parent=False)
        self.assertIsNotNone(updated_meeting.notes_message_last_sent)
        self.assertTrue(updated_meeting.notes_finalized)
        noti: Notification = Notification.objects.last()
        self.assertEqual(noti.recipient.user, self.student.user)
        message = mail.outbox[-1]
        self.assertEqual(message.subject, self.meeting.notes_message_subject)
        self.assertIn(self.meeting.notes_message_note, str(message.alternatives[0][0]))
        self.assertNotIn("to schedule your next meeting with", str(message.alternatives[0][0]))
        self.assertEqual(Notification.objects.count(), noti_count + 1)

        for x in list(self.meeting.notes_message_upcoming_tasks.all()) + list(
            self.meeting.notes_message_completed_tasks.all()
        ):
            self.assertIn(x.title, str(message.alternatives[0][0]))

        # Test CC Counselor
        self.counselor.cc_on_meeting_notes = True
        self.counselor.save()
        updated_meeting: CounselorMeeting = self.mgr.send_notes(send_to_parent=True, send_to_student=False)
        noti: Notification = Notification.objects.last()
        self.assertEqual(noti.cc_email, self.counselor.user.email)
        message = mail.outbox[-1]
        self.assertEqual(message.cc, [self.counselor.user.email])

        # And note to parent
        self.meeting.link_schedule_meeting_pk = self.meeting.pk
        self.meeting.save()
        self.mgr = CounselorMeetingManager(self.meeting)
        self.mgr.send_notes(send_to_student=False)
        self.assertEqual(Notification.objects.count(), noti_count + 3)
        noti: Notification = Notification.objects.last()
        self.assertEqual(noti.recipient.user, self.student.parent.user)
        self.assertEqual(len(mail.outbox), 3)
        message = mail.outbox[-1]
        self.assertIn("to schedule your next meeting with", str(message.alternatives[0][0]))

    def test_send_message_view(self):
        self.assertIsNone(self.meeting.last_reminder_sent)
        self.assertFalse(self.meeting.student_schedulable)
        url = reverse("counselor_meetings-send_notes_message", kwargs={"pk": self.meeting.pk})
        # Must be logged in
        data = {"send_to_parent": True, "send_to_student": True, "link_schedule_meeting_pk": self.meeting.pk}
        self.assertEqual(self.client.post(url, json.dumps(data), content_type="application/json").status_code, 401)

        self.client.force_login(self.counselor.user)
        noti_count = Notification.objects.count()
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(noti_count + 2, Notification.objects.count())
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.link_schedule_meeting_pk, self.meeting.pk)
        # Confirm meeting becomes student schedulable
        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.student_schedulable)

    def test_parent_student_have_no_access(self):
        """ Using default Django CRUD operations. Testing that only Counselors
        have access to said CRUD
        """
        url = reverse("counselor_event_type-list")
        self.client.force_login(self.student.user)
        response = self.client.post(url, json.dumps({"title": "rejected"}), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_login(self.parent.user)
        response = self.client.post(url, json.dumps({"title": "rejected"}), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestEventTypes(TestCase):
    """ Test CRUD actions for counselor EventTypes
    ONLY counselors can CRUD EventTypes
    python manage.py test cwcounseling.tests.test_counselor_meetings:TestEventTypes -s
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.roadmap = import_roadmap.import_roadmap("late_start_senior", "Late Start Senior")
        self.counselor = Counselor.objects.first()
        self.student: Student = Student.objects.first()

    def test_create(self):
        """ Counselor can create
        """
        url = reverse("counselor_event_type-list")

        self.client.force_login(self.counselor.user)
        response = self.client.post(
            url, json.dumps({"title": "counselor created", "duration": 60}), content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["created_by"], self.counselor.pk)

    def test_retrive(self):
        """ Counselors can retrieve ONLY EventTypes that they created
        """
        url = reverse("counselor_event_type-list")
        CounselorEventType.objects.create(duration=60, created_by=self.counselor, title="imitial meeting")
        CounselorEventType.objects.create(duration=45, created_by=self.counselor, title="sales")
        CounselorEventType.objects.create(duration=30, created_by=self.counselor, title="intake")
        CounselorEventType.objects.create(duration=30, created_by=Counselor.objects.create(), title="intake")
        CounselorEventType.objects.create(duration=30, created_by=Counselor.objects.create(), title="intake")

        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        [self.assertEqual(x["created_by"], self.counselor.pk) for x in response.data]

    def test_delete(self):
        event_1 = CounselorEventType.objects.create(duration=30, created_by=self.counselor, title="intake")
        event_2 = CounselorEventType.objects.create(duration=30, created_by=Counselor.objects.create(), title="intake")
        url = reverse("counselor_event_type-detail", kwargs={"pk": event_2.pk})

        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        url = reverse("counselor_event_type-detail", kwargs={"pk": event_1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update(self):
        # TODO
        pass
