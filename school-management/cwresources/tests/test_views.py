""" python manage.py test cwresources.tests.test_views
"""
import json

from django.test import TestCase
from django.core.files.base import ContentFile
from django.shortcuts import reverse

from cwresources.models import Resource, ResourceGroup
from cwresources.utilities.resource_permission_manager import get_resources_for_user
from cwusers.models import Student, Tutor, Counselor, Administrator, Parent
from cwcommon.models import FileUpload


class TestResourcePermissionManager(TestCase):
    fixtures = ("fixture.json",)

    def test_get_resource_view(self):
        """ This view is also tested in cwresources.tests.test_permissions.
            This test confirms access to unauthenticated users is only granted for
            public resources
        """
        resource = Resource.objects.create(link="google.com")
        response = self.client.get(reverse("get_resource", kwargs={"resource_slug": str(resource.slug)}))
        self.assertEqual(response.status_code, 302)


class TestResourceGroupViewset(TestCase):
    """ python manage.py test cwresources.tests.test_views:TestResourceGroupViewset """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.list_url = reverse("resource_groups-list")
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.admin = Administrator.objects.first()
        self.tutor = Tutor.objects.first()
        self.resource_group = ResourceGroup.objects.create(title="Test")
        self.client.force_login(self.admin.user)
        self.parent = Parent.objects.first()
        self.parent.students.clear()

    def test_create_update(self):
        data = {
            "title": "SAT Resources",
            "description": "SAT Resource Description",
            "public": True,
        }
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        result = json.loads(response.content)
        resource_group = ResourceGroup.objects.get(pk=result["pk"])
        self.assertEqual(resource_group.title, data["title"])
        self.assertEqual(resource_group.description, data["description"])

        response = self.client.patch(
            reverse("resource_groups-detail", kwargs={"pk": resource_group.pk}),
            json.dumps({"title": "GOOD TITLE"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        resource_group.refresh_from_db()
        self.assertEqual(resource_group.title, "GOOD TITLE")

    def test_list_retrieve(self):
        # Logged in as admin
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pk"], self.resource_group.pk)

        # Test Retrieve
        response = self.client.get(reverse("resource_groups-detail", kwargs={"pk": self.resource_group.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["title"], self.resource_group.title)

        # Student can list their own resource group
        self.student.visible_resource_groups.add(self.resource_group)
        self.client.force_login(self.student.user)
        response = self.client.get(reverse("resource_groups-detail", kwargs={"pk": self.resource_group.pk}))
        self.assertEqual(response.status_code, 200)
        response = self.client.get(self.list_url)
        self.assertEqual(len(json.loads(response.content)), 1)

        # Parent can get their student's resources
        self.parent.students.add(self.student)
        self.client.force_login(self.parent.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json.loads(response.content)), 1)

    def test_delete(self):
        response = self.client.delete(reverse("resource_groups-detail", kwargs={"pk": self.resource_group.pk}))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(ResourceGroup.objects.exists())

    def test_grant_student_access(self):
        """ Test scenarios for making a ResourceGroup visible to a student """
        url = reverse("students-detail", kwargs={"pk": self.student.pk})
        resource = Resource.objects.create(title="test", link="prompt.com", resource_group=self.resource_group)
        self.counselor.students.add(self.student)
        # Ensure tutor can't update student's resources
        self.client.force_login(self.tutor.user)
        response = self.client.patch(
            url, json.dumps({"visible_resource_groups": [self.resource_group.pk]}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

        # Success for our esteemed counselor!
        self.counselor.students.add(self.student)
        self.client.force_login(self.counselor.user)
        response = self.client.patch(
            url, json.dumps({"visible_resource_groups": [self.resource_group.pk]}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.student.visible_resource_groups.count(), 1)
        self.assertEqual(self.student.visible_resource_groups.first(), self.resource_group)

        self.assertTrue(get_resources_for_user(self.student.user).filter(pk=resource.pk).exists())

    def test_permissions(self):
        # 401 when no auth credentials
        self.client.logout()
        response = self.client.get(reverse("resource_groups-detail", kwargs={"pk": self.resource_group.pk}))
        self.assertEqual(response.status_code, 401)
        response = self.client.post(self.list_url, json.dumps({"title": "Test 2"}), content_type="application/json",)
        self.assertEqual(response.status_code, 401)

        # 403 when logged in as student, counselor, tutor
        for user in [self.student.user]:
            self.client.force_login(user)
            response = self.client.get(reverse("resource_groups-detail", kwargs={"pk": self.resource_group.pk}))
            self.assertEqual(response.status_code, 404)
            response = self.client.post(
                self.list_url, json.dumps({"title": "Test 2"}), content_type="application/json",
            )
            self.assertEqual(response.status_code, 403)

        # Parent can't get student's visible resource group
        self.student.visible_resource_groups.add(self.resource_group)
        self.client.force_login(self.parent.user)
        response = self.client.get(reverse("resource_groups-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json.loads(response.content)), 0)


class TestResourceViewset(TestCase):
    """ Test CRUD actions and the plethora of edge cases and restrictions
        in managing Resource objects
        python manage.py test cwresources.tests.test_views:TestResourceViewset
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.list_url = reverse("resources-list")
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.admin = Administrator.objects.first()
        self.tutor = Tutor.objects.first()
        self.counselor.students.add(self.student)
        self.tutor.students.add(self.student)
        self.resource_group = ResourceGroup.objects.create(title="SAT Resources")

    def test_create_success(self):
        # Admin create stock task
        self.client.force_login(self.admin.user)
        data = {
            "is_stock": True,
            "title": "Stock Resource",
            "link": "google.com",
            "description": "great description",
        }
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        result = json.loads(response.content)
        obj = Resource.objects.get(pk=result["pk"])
        for key in ["is_stock", "title", "description"]:
            self.assertEqual(result[key], data[key])
            self.assertEqual(getattr(obj, key), data[key])
        self.assertEqual(obj.view_count, 0)

        # Create resource in resource group (only available to admins)
        del data["is_stock"]
        data["resource_group"] = self.resource_group.pk
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        result = json.loads(response.content)
        obj = Resource.objects.get(pk=result["pk"])
        self.assertEqual(obj.resource_group, self.resource_group)
        self.assertEqual(result["resource_group_title"], self.resource_group.title)

        # Create task with file_upload
        self.client.force_login(self.tutor.user)
        del data["resource_group"]
        # FileUpload must be an action file since we have to copy it
        file_upload = FileUpload.objects.create()
        file_upload.file_resource.save(name="test.pdf", content=ContentFile("test"))
        data["file_upload"] = str(file_upload.slug)
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        result = json.loads(response.content)
        obj = Resource.objects.get(pk=result["pk"])
        self.assertFalse(obj.is_stock)
        self.assertTrue(obj.resource_file)
        self.assertTrue(
            result["url"], reverse("get_resource", kwargs={"resource_slug": str(obj.slug)}),
        )
        # Confirm created_by
        self.assertEqual(obj.created_by, self.tutor.user)

    def test_grant_student_access(self):
        """ Test scenarios for making a ResourceGroup visible to a student """
        url = reverse("students-detail", kwargs={"pk": self.student.pk})
        resource = Resource.objects.create(title="test", link="prompt.com", resource_group=self.resource_group)
        self.counselor.students.add(self.student)
        # Ensure tutor can't update student's resources
        self.client.force_login(self.tutor.user)
        response = self.client.patch(
            url, json.dumps({"visible_resources": [resource.pk]}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        # Counselor can't grant student resource that counselor doesn't have access to
        self.client.force_login(self.counselor.user)
        response = self.client.patch(
            url, json.dumps({"visible_resources": [resource.pk]}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.student.visible_resources.count(), 0)

        # Success!
        resource.created_by = self.counselor.user
        resource.save()
        response = self.client.patch(
            url, json.dumps({"visible_resources": [resource.pk]}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.student.visible_resources.count(), 1)
        self.assertEqual(self.student.visible_resources.first(), resource)

        self.assertTrue(get_resources_for_user(self.student.user).filter(pk=resource.pk).exists())

    def test_create_fail(self):
        # No login
        data = {
            "title": "Stock Resource",
            "link": "google.com",
            "description": "great description",
        }
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Only admin can create stock
        self.client.force_login(self.tutor.user)
        data["is_stock"] = True
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

        # Create resource in resourge group
        del data["is_stock"]
        data["resource_group"] = self.resource_group.pk
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)

        # Student can't create resource
        del data["resource_group"]
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        # Just making sure this request DOES work for tutors to ensure it doesn't for students
        self.assertEqual(response.status_code, 201)
        self.client.force_login(self.student.user)
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_list(self):
        stock_resource = Resource.objects.create(title="Stock", link="test.com", is_stock=True)
        unused_resource = Resource.objects.create(title="Unused", link="test.com")
        student_resource = Resource.objects.create(title="Student", link="test.com")
        group_resource = Resource.objects.create(title="group", link="test.com", resource_group=self.resource_group)
        student_resource.visible_students.add(self.student)
        tutor_created_resource = Resource.objects.create(title="Tutor", link="test2.com", created_by=self.tutor.user)

        # Student list (only include's student's resources)
        self.client.force_login(self.student.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pk"], student_resource.pk)
        self.resource_group.visible_students.add(self.student)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)

        # Tutor list for their student
        self.client.force_login(self.tutor.user)
        response = self.client.get(f"{self.list_url}?student={self.student.pk}")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)

        # Tutor list includes their student's resources plus other resources they made plus stock
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)
        pks = [x["pk"] for x in result]
        resource_pks = [x.pk for x in (tutor_created_resource, student_resource, group_resource, stock_resource,)]
        [self.assertIn(x, resource_pks) for x in pks]

        # Counselor list for their student
        self.client.force_login(self.counselor.user)
        response = self.client.get(f"{self.list_url}?student={self.student.pk}")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)

        # Counselor list for themself is the same plus a stock resource
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 1)

        # Admin retrieve all
        self.client.force_login(self.admin.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), Resource.objects.count())

        # Can't get resources for student we don't have access to
        self.tutor.students.clear()
        self.client.force_login(self.tutor.user)
        response = self.client.get(f"{self.list_url}?student={self.student.pk}")
        self.assertEqual(response.status_code, 403)

        # Only admin can get all
        self.client.force_login(self.counselor.user)
        response = self.client.get(f"{self.list_url}?all=true")
        self.assertEqual(response.status_code, 403)

    def test_archive(self):
        self.client.force_login(self.admin.user)
        resource = Resource.objects.create(title="Stock", link="test.com")

        for truthy in [True, False]:
            response = self.client.patch(
                reverse("resources-detail", kwargs={"pk": resource.pk}),
                json.dumps({"archived": truthy}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            # self.assertEqual(truthy, json.loads(response.content)["archived"])
            resource.refresh_from_db()
            self.assertEqual(truthy, resource.archived)
