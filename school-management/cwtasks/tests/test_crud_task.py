"""
    Test creating/updating tasks, including special cases of creating types of tasks that have
    special behavior (diagnostics, ).
    Includes testing completing tasks (one form of updating them)

    python manage.py test cwtasks.tests.test_crud_task
"""
import json
from django.contrib.auth.models import User

from django.test import TestCase
from django.shortcuts import reverse
from django.core import mail
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from cwcounseling.models import CounselorMeeting
from cwresources.models import Resource
from cwuniversities.managers.student_university_decision_manager import StudentUniversityDecisionManager

from snusers.models import Student, Counselor, Tutor, Parent, Administrator
from cwtutoring.models import Diagnostic
from cwnotifications.models import Notification
from cwtasks.models import Task, TaskTemplate, Form
from cwtasks.serializers import TaskSerializer
from cwtasks.constants import TASK_TYPE_SCHOOL_RESEARCH, COLLEGE_RESEARCH_FORM_KEY
from cwcommon.models import FileUpload
from cwuniversities.models import StudentUniversityDecision, University


class TestCreateTask(TestCase):
    """ python manage.py test cwtasks.tests.test_crud_task:TestCreateTask """

    fixtures = (
        "fixture.json",
        "sat_diagnostic.json",
    )

    def setUp(self):
        self.student = Student.objects.first()
        self.parent = Parent.objects.first()
        self.student.parent = self.parent
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.admin = Administrator.objects.first()
        self.diagnostic = Diagnostic.objects.first()

        # Note that tutor should NOT have access to student
        self.tutor = Tutor.objects.first()

    def test_create_task(self):
        self.assertEqual(len(mail.outbox), 0)
        due = timezone.now()
        counselor_meeting = CounselorMeeting.objects.create(student=self.student)
        data = {
            "title": "Title",
            "description": "Description",
            "due": str(due),
            "for_user": self.student.user.pk,
            "allow_file_submission": True,
            "allow_content_submission": True,
            "counselor_meetings": [counselor_meeting.pk],
        }
        self.client.force_login(self.counselor.user)
        response = self.client.post(reverse("tasks-list"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        result = json.loads(response.content)
        data.pop("due")
        data.pop("counselor_meetings")
        for key in data:
            self.assertEqual(result[key], data[key])
        task = Task.objects.get(pk=result["pk"])
        self.assertTrue(task.counselor_meetings.filter(pk=counselor_meeting.pk).exists())
        # Confirm notification sent to
        self.assertTrue(
            Notification.objects.filter(
                related_object_content_type=ContentType.objects.get_for_model(Task), related_object_pk=result["pk"],
            ).exists()
        )
        self.assertEqual(len(mail.outbox), 1)

        # Confirm that admin can create task
        self.client.force_login(self.admin.user)
        response = self.client.post(reverse("tasks-list"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)

    def test_update_task_due_suds(self):
        """ In counseling platform, we often update a task's due date and associated schools.
        """
        task = Task.objects.create(for_user=self.student.user)
        sud, _ = StudentUniversityDecisionManager.create(
            university=University.objects.create(name="u1"),
            student=self.student,
            is_applying=StudentUniversityDecision.YES,
        )
        # Login required
        url = reverse("tasks-detail", kwargs={"pk": task.pk})
        data = {"student_university_decisions": [sud.pk], "due": timezone.now().isoformat()}
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Success
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertIsNotNone(result.get("due"))
        self.assertEqual(result["student_university_decisions"][0], sud.pk)
        task.refresh_from_db()
        self.assertEqual(task.student_university_decisions.count(), 1)

    def test_create_task_fail(self):
        data = {"title": "Title", "for_user": self.student.user.pk}
        # No login
        response = self.client.post(reverse("tasks-list"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # No access to student
        self.client.force_login(self.tutor.user)
        response = self.client.post(reverse("tasks-list"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

        # User not specified
        self.client.force_login(self.counselor.user)
        data.pop("for_user")
        response = self.client.post(reverse("tasks-list"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_destroy_task(self):
        task = Task.objects.create(for_user=self.student.user)
        url = reverse("tasks-detail", kwargs={"pk": task.pk})
        self.assertEqual(self.client.delete(url).status_code, 401)

        self.client.force_login(self.admin.user)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertTrue(task.archived)

        # If task has a template, then deleting sets visibility to False
        template = TaskTemplate.objects.create(title="Great!")
        task.due = timezone.now()
        task.visible_to_counseling_student = True
        task.archived = None
        task.task_template = template
        task.save()
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertIsNone(task.archived)
        self.assertFalse(task.visible_to_counseling_student)
        self.assertIsNone(task.due)

    def test_update_task_meeting(self):
        task = Task.objects.create(for_user=self.student.user)
        meeting = CounselorMeeting.objects.create(student=self.student)
        self.client.force_login(self.admin.user)

        # Test add meeting
        data = {"counselor_meetings": [meeting.pk]}
        url = reverse("tasks-detail", kwargs={"pk": task.pk})
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(task.counselor_meetings.filter(pk=meeting.pk).exists())
        self.assertTrue(meeting.tasks.filter(pk=task.pk).exists())

        # Remove meeting
        data["counselor_meetings"] = []
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(task.counselor_meetings.exists())
        self.assertFalse(meeting.tasks.exists())

    def test_get_create_school_research(self):
        form = Form.objects.create(key=COLLEGE_RESEARCH_FORM_KEY)
        sud, _ = StudentUniversityDecisionManager.create(
            student=self.student, university=University.objects.create(name="1")
        )
        url = reverse("tasks-create_research_task")
        data = json.dumps({"student_university_decision": sud.pk})
        self.assertEqual(self.client.post(url, data, content_type="application/json").status_code, 401)
        self.client.force_login(self.tutor.user)
        self.assertEqual(self.client.post(url, data, content_type="application/json").status_code, 403)

        # Counselor creates task
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, data, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        task = Task.objects.get(pk=json.loads(response.content)["pk"])
        self.assertEqual(task.for_user, self.student.user)
        self.assertEqual(task.form, form)
        self.assertEqual(task.task_type, TASK_TYPE_SCHOOL_RESEARCH)
        self.assertEqual(task.student_university_decisions.count(), 1)
        self.assertTrue(task.student_university_decisions.filter(pk=sud.pk).exists())
        task_count = Task.objects.count()

        # Idempotent. Hitting again does not create a second task
        response = self.client.post(url, data, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Task.objects.count(), task_count)

    def test_create_diagnostic(self):
        """ Test creating task related to diagnostic.
            Need to ensure student and parent get notified
        """
        self.client.force_login(self.counselor.user)
        # Create diagnostic task for student, confirm email
        data = {
            "for_user": self.student.user.pk,
            "diagnostic_id": self.diagnostic.pk,
            "allow_content_submission": False,
            "allow_file_submission": True,
            "title": "Complete %s diagnostic" % (self.diagnostic.title),
        }
        response = self.client.post(reverse("tasks-list"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        response_data = json.loads(response.content)
        task = Task.objects.filter(pk=response_data["pk"]).first()
        self.assertTrue(task)
        self.assertEqual(task.title, data["title"])
        self.assertEqual(task.diagnostic, self.diagnostic)
        self.assertEqual(task.created_by, self.counselor.user)
        self.assertEqual(task.for_user, self.student.user)
        # Ensure notification was created for task
        self.assertTrue(
            Notification.objects.filter(
                related_object_content_type=ContentType.objects.get_for_model(Task), related_object_pk=task.pk,
            ).exists()
        )

        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[-1]
        self.assertEqual(len(msg.recipients()), 2)
        self.assertIn(self.student.user.email, msg.recipients())
        self.assertIn(self.parent.user.email, msg.recipients())

    def test_bulk_create_tasks(self):
        """ python manage.py test cwtasks.tests.test_crud_task:TestCreateTask.test_bulk_create_tasks """
        students = [
            Student.objects.create(
                invitation_name=f"Student {i}",
                invitation_email=f"student_{i}@student.net",
                user=User.objects.create_user(f"student_{i}"),
            )
            for i in range(5)
        ]

        url = reverse("tasks-bulk-create")
        resource = Resource.objects.create(link="https://google.com")

        data = {
            "title": "Test Task",
            "task_type": "other",
            "set_resources": [resource.pk],
            "for_user_bulk_create": [s.user.pk for s in students],
        }

        # Test bulk create as admin
        self.client.force_login(self.admin.user)
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(json.loads(response.content)), len(students))
        for student in students:
            self.assertTrue(student.user.tasks.filter(title=data["title"], task_type=data["task_type"]).exists())

        # Test bulk create as counselor fails due to permissions
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

        # Test bulk create as counselor succeeds with TaskTemplate
        Student.objects.filter(pk__in=[x.pk for x in students]).update(counselor=self.counselor)
        task_template = TaskTemplate.objects.create(title="Great Task Template")
        data.update({"task_template": task_template.pk})
        response = self.client.post(url, json.dumps(data), content_type="application/json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(json.loads(response.content)), len(students))
        for student in students:
            self.assertTrue(
                student.user.tasks.filter(
                    title=data["title"], task_type=data["task_type"], task_template=task_template
                ).exists()
            )


class TestCompleteTask(TestCase):
    """ python manage.py test cwtasks.tests.test_crud_task:TestCompleteTask
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.parent = Parent.objects.first()
        self.student.parent = self.parent
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.tutor = Tutor.objects.first()
        self.tutor.students.add(self.student)

        self.task = Task.objects.create(title="Task Title", for_user=self.student.user, created_by=self.counselor.user,)

    def test_complete_basic_task(self):
        self.client.force_login(self.student.user)
        # Student completes task, ensure email was sent to creator
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": self.task.pk}),
            json.dumps({"completed": str(timezone.now())}),
            content_type="application/json",
        )
        response_data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response_data["completed"])
        self.task.refresh_from_db()
        self.assertTrue(self.task.completed)
        # Confirm email sent to task creator
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[-1]
        self.assertIn(self.counselor.user.email, msg.recipients())

        # Updating complete doesn't resend email
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": self.task.pk}),
            json.dumps({"completed": str(timezone.now())}),
            content_type="application/json",
        )
        self.assertEqual(len(mail.outbox), 1)

        # Student's tutor, counselor, parent can complete task
        for cwuser in (self.counselor, self.parent, self.tutor):
            self.assertTrue(cwuser.students.filter(pk=self.student.pk).exists())
            new_task = Task.objects.create(title="Task Title", for_user=self.student.user)
            self.client.force_login(cwuser.user)
            response = self.client.patch(
                reverse("tasks-detail", kwargs={"pk": new_task.pk}),
                json.dumps({"completed": str(timezone.now())}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            new_task.refresh_from_db()
            self.assertTrue(new_task.completed)

    def test_complete_file_upload(self):
        self.task.allow_file_submission = True
        self.task.created_by = self.counselor.user
        self.task.save()
        self.assertFalse(self.task.completed)
        file_upload = FileUpload.objects.create(file_resource="test.pdf")
        task_data = TaskSerializer(self.task).data
        task_data.update(
            {"completed": str(timezone.now()), "update_file_uploads": [str(file_upload.slug)],}
        )
        self.client.force_login(self.student.user)

        response = self.client.put(
            reverse("tasks-detail", kwargs={"pk": self.task.pk}),
            json.dumps(task_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertEqual(response_data["file_uploads"][0]["name"], file_upload.file_resource.name)
        self.assertEqual(response_data["file_uploads"][0]["slug"], str(file_upload.slug))
        self.assertTrue(response_data["completed"])
        self.task.refresh_from_db()
        self.assertTrue(self.task.completed)
        self.assertTrue(self.task.file_uploads.filter(pk=file_upload.pk).exists())

        # Confirm email sent to task creator
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[-1]
        self.assertIn(self.counselor.user.email, msg.recipients())

    def test_failure(self):
        # Unauthenticated
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": self.task.pk}),
            json.dumps({"completed": str(timezone.now())}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

        # Not tutor's student
        self.tutor.students.clear()
        self.client.force_login(self.tutor.user)
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": self.task.pk}),
            json.dumps({"completed": str(timezone.now())}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        # Not parent's student
        self.parent.students.clear()
        self.client.force_login(self.parent.user)
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": self.task.pk}),
            json.dumps({"completed": str(timezone.now())}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        # File submission not allowed
        self.task.allow_file_submission = self.task.allow_content_submission = False
        self.task.save()
        self.client.force_login(self.student.user)
        file_upload = FileUpload.objects.create(file_resource="test.pdf")
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": self.task.pk}),
            json.dumps({"completed": str(timezone.now()), "update_file_uploads": [str(file_upload.slug)],}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

        other_task = Task.objects.create(for_user=self.student.user)
        file_upload.task = other_task
        file_upload.save()

        # Invalid file submission (already on task)
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": self.task.pk}),
            json.dumps({"completed": str(timezone.now()), "update_file_uploads": [str(file_upload.slug)],}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

        # Content submission not allowed
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": self.task.pk}),
            json.dumps({"completed": str(timezone.now()), "content_submission": "Real great content",}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_complete_task_notification(self):
        self.client.force_login(self.student.user)
        # Tutor gets notified of completed task
        tutor_task = Task.objects.create(for_user=self.student.user, created_by=self.tutor.user)
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": tutor_task.pk}),
            json.dumps({"completed": str(timezone.now())}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            self.tutor.user.notification_recipient.notifications.filter(
                notification_type="task_complete", related_object_pk=tutor_task.pk
            ).exists()
        )
        # Counselor gets notified of completed task they created
        counselor_task = Task.objects.create(for_user=self.student.user, created_by=self.counselor.user)
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": counselor_task.pk}),
            json.dumps({"completed": str(timezone.now())}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            self.counselor.user.notification_recipient.notifications.filter(
                notification_type="task_complete", related_object_pk=counselor_task.pk
            ).exists()
        )

        # Counselor also gets notified of completed roadmap task they didn't create
        task_template = TaskTemplate.objects.create()
        roadmap_task = Task.objects.create(for_user=self.student.user, task_template=task_template)
        response = self.client.patch(
            reverse("tasks-detail", kwargs={"pk": roadmap_task.pk}),
            json.dumps({"completed": str(timezone.now())}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            self.counselor.user.notification_recipient.notifications.filter(
                notification_type="task_complete", related_object_pk=roadmap_task.pk
            ).exists()
        )

    def test_complete_task_with_file_upload_for_counselor_student(self):
        """
        For counseling student, if student uploads a file while marking a task
        complete, add that FileUpload to Student.counseling_file_uploads.

        python manage.py test cwtasks.tests.test_crud_task:TestCompleteTask.test_complete_task_with_file_upload_for_counselor_student

        """
        # # FAILURE - for Tutoring student, Student.counseling_file_uploads is not
        # # altered when a FileUpload is included with a task submission
        self.task.allow_file_submission = True
        self.task.created_by = self.counselor.user
        self.task.save()
        self.assertFalse(self.task.completed)
        file_upload = FileUpload.objects.create(file_resource="test.pdf")
        task_data = TaskSerializer(self.task).data
        task_data.update(
            {"completed": str(timezone.now()), "update_file_uploads": [str(file_upload.slug)],}
        )
        self.client.force_login(self.student.user)
        response = self.client.put(
            reverse("tasks-detail", kwargs={"pk": self.task.pk}),
            json.dumps(task_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(file_upload, self.student.counseling_file_uploads.all())

        # SUCCESS - counselor uploads file while marking task complete
        task2 = Task.objects.create(title="Task Title", for_user=self.student.user, created_by=self.counselor.user,)
        task2.allow_file_submission = True
        task2.created_by = self.counselor.user
        task2.save()
        self.assertFalse(task2.completed)
        file_upload = FileUpload.objects.create(file_resource="success.pdf")
        task_data = TaskSerializer(task2).data
        task_data.update(
            {"completed": str(timezone.now()), "update_file_uploads": [str(file_upload.slug)],}
        )
        self.student.counseling_student_types_list.append(Student.COUNSELING_STUDENT_BASIC)
        self.student.save()
        self.client.force_login(self.student.user)
        response = self.client.put(
            reverse("tasks-detail", kwargs={"pk": task2.pk}), json.dumps(task_data), content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(file_upload, self.student.counseling_file_uploads.all())


class TestTaskActions(TestCase):
    """ python manage.py test cwtasks.tests.test_crud_task:TestTaskActions """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.admin = Administrator.objects.first()
        self.tutor = Tutor.objects.first()
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()

        self.task = Task.objects.create(title="Task Title", for_user=self.student.user, created_by=self.admin.user,)
        self.url = reverse("tasks-reassign", kwargs={"pk": self.task.pk})

    def test_send_reminder(self):
        """ Test viewset action for sending a task reminder """
        self.task.due = timezone.now()
        self.task.save()
        url = reverse("tasks-remind", kwargs={"pk": self.task.pk})
        # Must be logged in
        self.assertEqual(self.client.post(url).status_code, 401)
        self.client.force_login(self.tutor.user)
        self.assertEqual(self.client.post(url).status_code, 403)

        # Counselor sends reminder
        self.client.force_login(self.counselor.user)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        content = json.loads(response.content)
        self.assertIsNotNone(content["last_reminder_sent"])
        self.task.refresh_from_db()
        self.assertIsNotNone(self.task.last_reminder_sent)

        noti: Notification = Notification.objects.last()
        self.assertEqual(noti.related_object, self.task)
        self.assertIsNotNone(noti.emailed)
        email = mail.outbox[-1]
        self.assertIn(self.task.title, email.subject)

        # No reminder fr completed task
        self.task.completed = timezone.now()
        self.task.save()
        self.assertEqual(self.client.post(url).status_code, 400)

        # No reminder for archived task
        self.task.archived = timezone.now()
        self.task.completed = None
        self.task.save()
        self.assertEqual(self.client.post(url).status_code, 400)

    def test_reassign(self):
        # Login required
        data = {"for_user": self.tutor.user.pk}
        response = self.client.put(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Student not allowed
        self.client.force_login(self.student.user)
        response = self.client.put(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

        # Success for Admin :)
        self.client.force_login(self.admin.user)
        response = self.client.put(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(json.loads(response.content)["for_user"], self.tutor.user.pk)

        # Noti for tutor
        noti = self.task.notifications.last()
        self.assertEqual(noti.recipient.user, self.tutor.user)
