""" Test our file upload related views
    python manage.py test cwcommon.tests.test_file_upload
"""
import json

from django.test import TestCase
from django.shortcuts import reverse
from django.core.files.base import ContentFile

from cwusers.models import Student, Counselor, Tutor, Parent
from cwcommon.models import FileUpload

TEST_GOOGLE_DOC_ID = "1V9mLgzBjGuz7qD_Bv76MaQS0lgkdc41I"
TEST_GOOGLE_REFRESH_TOKEN = (
    "1//04fLWfoEAVNGUCgYIARAAGAQSNwF-L9IroueJrk4KK18XJ6x6ez20_zcWxBGFKsxNeG-Gu4c9g3aJPRRwO37-V9MkznAAhyiGN8c"
)


class TestFileUploadCreate(TestCase):
    """ python manage.py test cwcommon.tests.test_file_upload:TestFileUploadCreate
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.tutor = Tutor.objects.first()
        self.parent = Parent.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.tutor.students.add(self.student)

    def test_create_google_drive_file_upload(self):
        # We attempt creating a file upload
        pass
        # url = reverse("file_upload_google_drive")
        # data = {
        #     "file_id": TEST_GOOGLE_DOC_ID,
        #     "access_token": TEST_GOOGLE_ACCESS_TOKEN,  # Just need something here since Test Google Doc is public
        #     "filename": "Eric Lander",
        #     "counseling_student": self.student.pk,
        # }
        # self.assertEqual(self.client.post(url, json.dumps(data), content_type="application/json").status_code, 401)
        # self.client.force_login(self.student.user)
        # response = self.client.post(url, json.dumps(data), content_type="application/json")
        # self.assertEqual(response.status_code, 201)
        # file_upload = FileUpload.objects.get(slug=json.loads(response.content)["slug"])
        # self.assertEqual(file_upload.title, data["filename"])
        # self.assertEqual(file_upload.counseling_student, self.student)


class TestFileUploadListUpdate(TestCase):
    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.tutor = Tutor.objects.first()
        self.parent = Parent.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.tutor.students.add(self.student)
        self.file_upload = FileUpload.objects.create(
            created_by=self.counselor.user, title="fu1", tags=["tag1", "tag2"], counseling_student=self.student
        )
        self.file_upload.file_resource.save("test.pdf", ContentFile("Real cool content"))

    def test_update(self):
        """ Update title and tags on file upload """
        data = {"title": "Cool new name", "tags": ["hyrule", "link"]}
        url = reverse("file_upload_list_update-detail", kwargs={"slug": str(self.file_upload.slug)})
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Student cannot update
        self.client.force_login(self.student.user)
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

        # Counselor can update
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.file_upload.refresh_from_db()
        self.assertEqual(self.file_upload.title, data["title"])
        self.assertEqual(self.file_upload.tags, data["tags"])

        # Counseling student can NOT be updated
        data["counseling_student"] = None
        response = self.client.patch(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_destroy(self):
        # Conform sets inactive
        url = reverse("file_upload_list_update-detail", kwargs={"slug": str(self.file_upload.slug)})
        self.assertEqual(self.client.delete(url).status_code, 401)
        self.client.force_login(self.counselor.user)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 204)
        self.file_upload.refresh_from_db()
        self.assertFalse(self.file_upload.active)

        # Wehn getting student, this file upload is not associated with them
        student_url = reverse("students-detail", kwargs={"pk": self.student.pk})
        response = self.client.get(f"{student_url}?platform=counseling")
        self.assertEqual(response.status_code, 200)
        self.assertListEqual(json.loads(response.content)["file_uploads"], [])

    def test_counselor_file_uploads_on_student(self):
        """ Test adding file uploads to a student """
        self.file_upload.counseling_student = None
        self.file_upload.save()
        self.client.force_login(self.counselor.user)
        url = reverse("students-detail", kwargs={"pk": self.student.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json.loads(response.content).get("file_uploads", [])), 0)

        update_data = {"update_file_uploads": [str(self.file_upload.slug)]}
        response = self.client.patch(url, json.dumps(update_data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        # Can't update via student
        self.assertEqual(len(result["file_uploads"]), 0)

        self.student.counseling_student_types_list = ["PAYGO"]
        self.student.save()
        fu_url = reverse("file_upload_list_update-detail", kwargs={"slug": str(self.file_upload.slug)})
        data = {"counseling_student": self.student.pk}
        update_response = self.client.patch(fu_url, json.dumps(data), content_type="application/json")
        self.assertEqual(update_response.status_code, 200)
        response = self.client.get(f"{url}?platform=counseling")
        result = json.loads(response.content)
        self.assertEqual(len(result["file_uploads"]), 1)
        self.assertEqual(result["file_uploads"][0]["slug"], str(self.file_upload.slug))
        self.assertTrue(self.student.counseling_file_uploads.filter(slug=self.file_upload.slug).exists())

    def test_list(self):
        # Create some extra file uploads so we can actually list something!
        additional_file_uploads = [
            FileUpload.objects.create(
                created_by=self.counselor.user, title="fu1", tags=["tag1", "tag2"], counseling_student=self.student
            )
            for x in range(5)
        ]
        additional_file_uploads[-1].counseling_student = None
        additional_file_uploads[-1].save()

        url = f"{reverse('file_upload_list_update-list')}?counseling_student={self.student.pk}"

        # Disconnected parent can't do this search
        self.client.force_login(self.parent.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Unless they belong to student
        self.student.parent = self.parent
        self.student.save()
        for user in (self.student.user, self.parent.user, self.counselor.user):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            # We should get all of the items in additional file uploads, except the last one, plus the one
            # created in setUp
            result = json.loads(response.content)
            self.assertEqual(len(result), len(additional_file_uploads))
            self.assertTrue(all([x["tags"] == ["tag1", "tag2"] for x in result]))

