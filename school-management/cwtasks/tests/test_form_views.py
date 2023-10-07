"""
    Test creating/updating forms and form submissions.
    python manage.py test cwtasks.tests.test_form_views
"""

import json

from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import reverse
from django.test import TestCase
from django.utils import timezone

from rest_framework import status

from cwtasks.models import Task, Form, FormSubmission, FormField, FormFieldEntry
from cwtasks.serializers import FormSubmissionSerializer
from snusers.models import Student, Counselor, Parent, Administrator


class TestForm(TestCase):
    """
    python manage.py test cwtasks.tests.test_form_views:TestForm -s
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.url = reverse("forms-list")
        self.student = Student.objects.first()
        self.parent = Parent.objects.first()
        self.student.parent = self.parent
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.admin = Administrator.objects.first()
        self.form = Form.objects.create(
            title="Test Form Title", description="Test Form Description", created_by=self.admin.user
        )
        self.url_detail = reverse("forms-detail", kwargs={"pk": self.form.pk})
        self.non_admin_users = [self.student, self.counselor, self.parent]
        self.form_fields = [
            FormField.objects.create(form=self.form, key="name", order=0, created_by=self.admin.user),
            FormField.objects.create(form=self.form, key="interests", order=1, created_by=self.admin.user),
            FormField.objects.create(
                form=self.form,
                key="universities",
                input_type=FormField.SELECT,
                choices=["UCB", "MIT"],
                order=2,
                created_by=self.admin.user,
            ),
            FormField.objects.create(
                form=self.form, key="custom", order=3, created_by=self.counselor.user, editable=True
            ),
            FormField.objects.create(
                form=self.form,
                key="custom_other",
                order=4,
                created_by=Counselor.objects.create(user=User.objects.create_user("newcounselor")).user,
                editable=True,
            ),
            FormField.objects.create(
                form=self.form, key="hidden_field", order=5, created_by=self.admin.user, hidden=True
            ),
        ]

    def test_create_form(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestForm.test_create_form -s
        """
        data = {"title": "Another Form Title", "description": "Another Form Description"}
        # Admin can create a form
        self.client.force_login(user=self.admin.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        result = json.loads(response.content)
        self.assertEqual(result["title"], data["title"])
        self.assertEqual(result["description"], data["description"])
        form = Form.objects.get(pk=result["pk"])
        self.assertEqual(form.title, data["title"])
        self.assertEqual(form.description, data["description"])
        self.assertEqual(form.created_by, self.admin.user)

        # Non-Admin Users cannot create a form
        for user_type in self.non_admin_users:
            self.client.force_login(user=user_type.user)
            response = self.client.post(self.url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_form_with_nested_form_fields(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestForm.test_create_form_with_nested_form_fields -s
        """
        form_fields_write = [
            {"key": "name", "order": 0,},
            {"key": "interests", "order": 1,},
            {"key": "universities", "input_type": FormField.SELECT, "choices": ["UCB", "MIT"], "order": 2,},
        ]
        data = {
            "title": "Another Form Title",
            "description": "Another Form Description",
            "form_fields_write": form_fields_write,
        }
        # Admin can create a form with nested form fields
        self.client.force_login(user=self.admin.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        result = json.loads(response.content)
        self.assertEqual(len(result["form_fields"]), len(form_fields_write))
        self.assertEqual(result["title"], data["title"])
        self.assertEqual(result["description"], data["description"])
        self.assertEqual(result["form_fields"][0]["key"], form_fields_write[0]["key"])
        self.assertEqual(result["form_fields"][0]["order"], form_fields_write[0]["order"])
        self.assertEqual(result["form_fields"][2]["key"], form_fields_write[2]["key"])
        self.assertEqual(result["form_fields"][2]["order"], form_fields_write[2]["order"])
        self.assertEqual(result["form_fields"][2]["input_type"], form_fields_write[2]["input_type"])
        self.assertEqual(result["form_fields"][2]["choices"], form_fields_write[2]["choices"])
        form = Form.objects.get(pk=result["pk"])
        self.assertEqual(form.title, data["title"])
        self.assertEqual(form.description, data["description"])
        self.assertEqual(form.form_fields.count(), len(form_fields_write))
        self.assertEqual(form.form_fields.last().key, form_fields_write[2]["key"])
        self.assertEqual(form.form_fields.last().order, form_fields_write[2]["order"])
        self.assertEqual(form.form_fields.last().input_type, form_fields_write[2]["input_type"])
        self.assertEqual(form.form_fields.last().choices, form_fields_write[2]["choices"])

    def test_list_forms(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestForm.test_list_forms -s
        """
        # All authenticated users can read forms
        for user_type in [*self.non_admin_users, self.admin]:
            self.client.force_login(user=user_type.user)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # Nested form fields not included in list action
            result = json.loads(response.content)
            self.assertEqual(len(result), 1)
            self.assertIsNone(result[0].get("form_fields"))

    def test_retrieve_form(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestForm.test_retrieve_form -s
        """
        # Admin users can retrieve a form that includes only standard fields (editable=False, hidden=False)
        self.client.force_login(user=self.admin.user)
        response = self.client.get(self.url_detail)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertEqual(result["title"], self.form.title)
        # Nested form fields are included in retrieve action
        self.assertIsNotNone(result["form_fields"])
        self.assertCountEqual(
            [form_field["pk"] for form_field in result["form_fields"]],
            FormField.objects.filter(form=self.form, hidden=False)
            .filter(Q(editable=False))
            .values_list("pk", flat=True),
        )
        # All non-admin users can retrieve a form that includes the standard fields
        for user_type in [*self.non_admin_users]:
            self.client.force_login(user=user_type.user)
            response = self.client.get(self.url_detail)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            result = json.loads(response.content)
            self.assertEqual(result["title"], self.form.title)
            # Nested form fields are included in retrieve action
            self.assertIsNotNone(result["form_fields"])
            self.assertCountEqual(
                [form_field["pk"] for form_field in result["form_fields"]],
                FormField.objects.filter(form=self.form, hidden=False)
                .filter(Q(editable=False))
                .values_list("pk", flat=True),
            )

    def test_update_form(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestForm.test_update_form -s
        """
        data = {"title": "Update Form Title"}
        # Admin can update a form
        self.client.force_login(user=self.admin.user)
        response = self.client.patch(self.url_detail, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertEqual(result["title"], data["title"])
        self.form.refresh_from_db()
        self.assertEqual(self.form.title, data["title"])
        self.assertEqual(self.form.updated_by, self.admin.user)

        # NonAdmin Users cannot update a form
        for user_type in self.non_admin_users:
            self.client.force_login(user=user_type.user)
            response = self.client.patch(self.url_detail, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_form(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestForm.test_delete_form -s
        """
        # NonAdmin Users cannot delete a form
        for user_type in self.non_admin_users:
            self.client.force_login(user=user_type.user)
            response = self.client.delete(self.url_detail)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Admin can delete a form
        self.client.force_login(user=self.admin.user)
        response = self.client.delete(self.url_detail)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class TestFormField(TestCase):
    """
    python manage.py test cwtasks.tests.test_form_views:TestFormField -s
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.url = reverse("form_fields-list")
        self.student = Student.objects.first()
        self.parent = Parent.objects.first()
        self.student.parent = self.parent
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.admin = Administrator.objects.first()
        self.form = Form.objects.create(
            title="Test Form Title", description="Test Form Description", created_by=self.admin.user
        )
        self.form_other = Form.objects.create(
            title="Other Form Title", description="Other Form Description", created_by=self.admin.user
        )

        self.form_fields_admin = [
            FormField.objects.create(form=self.form, key="name", order=0, created_by=self.admin.user),
            FormField.objects.create(form=self.form_other, key="other_name", order=0, created_by=self.admin.user),
            FormField.objects.create(
                form=self.form, key="hidden_field", order=1, created_by=self.admin.user, hidden=True
            ),
            FormField.objects.create(
                form=self.form_other, key="hidden_field", order=1, created_by=self.admin.user, hidden=True
            ),
        ]
        self.form_fields_counselor = [
            FormField.objects.create(
                form=self.form, key="interests", order=2, created_by=self.counselor.user, editable=True
            ),
            FormField.objects.create(
                form=self.form_other, key="other_interests", order=2, created_by=self.counselor.user, editable=True,
            ),
        ]
        other_counselor = Counselor.objects.create(user=User.objects.create_user("other_counselor"))
        self.form_fields_other_counselor = [
            FormField.objects.create(
                form=self.form, key="not_associated", order=3, created_by=other_counselor.user, editable=True,
            ),
            FormField.objects.create(
                form=self.form_other,
                key="other_not_associated",
                order=3,
                created_by=other_counselor.user,
                editable=True,
            ),
        ]
        self.form_fields_all = self.form_fields_admin + self.form_fields_counselor + self.form_fields_other_counselor
        self.task = Task.objects.create(
            for_user=self.student.user,
            title="Test Form Task",
            due=timezone.now(),
            form=self.form,
            allow_form_submission=True,
        )
        self.read_only_users = [self.student, self.parent]

    def test_create_form_field(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormField.test_create_form_field -s
        """
        data = {"form": self.form.pk, "key": "new_key", "title": "New title"}
        # Parents and Students cannot create form fields
        for user_type in self.read_only_users:
            self.client.force_login(user_type.user)
            response = self.client.post(self.url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Admin can create form fields; Generated form fields are editable = False
        self.client.force_login(self.admin.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        result = json.loads(response.content)
        self.assertEqual(result["form"], data["form"])
        self.assertEqual(result["key"], data["key"])
        self.assertEqual(result["title"], data["title"])
        form_field = FormField.objects.get(pk=result["pk"])
        self.assertEqual(form_field.form.pk, data["form"])
        self.assertEqual(form_field.key, data["key"])
        self.assertEqual(form_field.title, data["title"])
        self.assertFalse(form_field.editable)
        # Counselor can create form fields; Generated form fields are editable = True
        data = {
            "form": self.form.pk,
            "key": "checkbox_field",
            "title": "New Checkbox field",
            "input_type": FormField.CHECKBOX,
            "choices": [True, False],
        }
        self.client.force_login(self.counselor.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        result = json.loads(response.content)
        self.assertEqual(result["form"], data["form"])
        self.assertEqual(result["key"], data["key"])
        self.assertEqual(result["title"], data["title"])
        self.assertEqual(result["input_type"], data["input_type"])
        self.assertEqual(result["choices"], data["choices"])
        form_field = FormField.objects.get(pk=result["pk"])
        self.assertTrue(form_field.editable)
        self.assertEqual(form_field.title, data["title"])
        self.assertEqual(form_field.form.pk, data["form"])
        self.assertEqual(form_field.key, data["key"])
        self.assertEqual(form_field.title, data["title"])
        self.assertEqual(form_field.input_type, data["input_type"])
        self.assertEqual(form_field.choices, data["choices"])

    def test_list_form_fields(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormField.test_list_form_fields -s
        """
        # Admin has access to standard form fields (editable=False, hidden=False)
        self.client.force_login(self.admin.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertEqual(len(result), FormField.objects.filter(editable=False, hidden=False).count())
        self.assertCountEqual(
            [form_field["pk"] for form_field in result],
            FormField.objects.filter(editable=False, hidden=False).values_list("pk", flat=True),
        )
        # Counselor has access to standard form fields and their own form fields
        self.client.force_login(self.counselor.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertCountEqual(
            [form_field["pk"] for form_field in result],
            FormField.objects.filter(hidden=False)
            .filter(Q(editable=False) | Q(created_by=self.counselor.user))
            .values_list("pk", flat=True),
        )
        # Student has access to standard form fields and those created by their counselor
        self.client.force_login(self.student.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertCountEqual(
            [form_field["pk"] for form_field in result],
            FormField.objects.filter(hidden=False)
            .filter(Q(editable=False) | Q(created_by=self.student.counselor.user))
            .values_list("pk", flat=True),
        )
        # Parent has access to standard form fields and those created by their students' counselor
        self.client.force_login(self.parent.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        counselor_users = [student.counselor.user for student in self.parent.students.all()]
        self.assertCountEqual(
            [form_field["pk"] for form_field in result],
            FormField.objects.filter(hidden=False)
            .filter(Q(editable=False) | Q(created_by__in=counselor_users))
            .distinct()
            .values_list("pk", flat=True),
        ),

    def test_update_form_field(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormField.test_update_form_field -s
        """
        form_field_admin = self.form_fields_admin[0]
        form_field_counselor = self.form_fields_counselor[0]
        url_form_field_admin_detail = reverse("form_fields-detail", kwargs={"pk": form_field_admin.pk})
        url_form_field_counselor_detail = reverse("form_fields-detail", kwargs={"pk": form_field_counselor.pk})
        data = {"key": "changed_key"}
        # Admin can update only standard form fields
        self.client.force_login(self.admin.user)
        response = self.client.patch(url_form_field_admin_detail, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertEqual(result["key"], data["key"])
        form_field = FormField.objects.get(pk=result["pk"])
        self.assertEqual(form_field.key, data["key"])
        data = {"key": "another_changed_key"}
        response = self.client.patch(url_form_field_counselor_detail, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Counselor can only update their own form fields
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url_form_field_admin_detail, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        data = {"key": "final_changed_key"}
        response = self.client.patch(url_form_field_counselor_detail, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertEqual(result["key"], data["key"])
        form_field = FormField.objects.get(pk=result["pk"])
        self.assertEqual(form_field.key, data["key"])
        # Parents and Students can't update form fields
        for user_type in self.read_only_users:
            self.client.force_login(user_type.user)
            response = self.client.patch(url_form_field_admin_detail, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            response = self.client.patch(
                url_form_field_counselor_detail, json.dumps(data), content_type="application/json"
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_form_field(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormField.test_delete_form_field -s
        """
        form_field_admin = self.form_fields_admin[0]
        form_field_counselor = self.form_fields_counselor[0]
        url_form_field_admin_detail = reverse("form_fields-detail", kwargs={"pk": form_field_admin.pk})
        url_form_field_counselor_detail = reverse("form_fields-detail", kwargs={"pk": form_field_counselor.pk})
        # Admin and counselor can only delete their own form fields (*delete actually sets hidden=True*)
        self.client.force_login(self.admin.user)
        response = self.client.delete(url_form_field_counselor_detail)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.client.force_login(self.counselor.user)
        response = self.client.delete(url_form_field_admin_detail)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_login(self.admin.user)
        response = self.client.delete(url_form_field_admin_detail)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.client.force_login(self.counselor.user)
        response = self.client.delete(url_form_field_counselor_detail)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # No Fields were actually deleted
        self.assertEqual(FormField.objects.count(), len(self.form_fields_all))
        form_field_admin.refresh_from_db()
        form_field_counselor.refresh_from_db()
        # But form_field.hidden set to True
        self.assertTrue(form_field_admin.hidden)
        self.assertTrue(form_field_counselor.hidden)
        # Student and Parent can't "delete" form fields
        for user_type in self.read_only_users:
            self.client.force_login(user_type.user)
            response = self.client.delete(url_form_field_admin_detail)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            response = self.client.delete(url_form_field_counselor_detail)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestFormSubmission(TestCase):
    """
    python manage.py test cwtasks.tests.test_form_views:TestFormSubmission -s
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.url = reverse("form_submissions-list")
        self.student = Student.objects.first()
        self.parent = Parent.objects.first()
        self.student.parent = self.parent
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.admin = Administrator.objects.first()
        self.form = Form.objects.create(
            title="Test Form Title", description="Test Form Description", created_by=self.admin.user
        )
        self.form_other = Form.objects.create(
            title="Other Form Title", description="Other Form Description", created_by=self.admin.user
        )
        self.form_college_research = Form.objects.create(
            title="College Research Form",
            description="Other Form Description",
            key="college_research",
            created_by=self.admin.user,
        )

        other_counselor = Counselor.objects.create(user=User.objects.create_user("other_counselor"))
        self.form_fields_main_form = [
            FormField.objects.create(form=self.form, key="name", order=0, created_by=self.admin.user),
            FormField.objects.create(
                form=self.form, key="interests", order=1, created_by=self.counselor.user, editable=True
            ),
        ]
        FormField.objects.create(form=self.form, key="hidden_field", order=2, created_by=self.admin.user, hidden=True)
        FormField.objects.create(
            form=self.form, key="not_associated", order=3, created_by=other_counselor.user, editable=True,
        )
        self.form_fields_other_form = [
            FormField.objects.create(form=self.form_other, key="other_name", order=0, created_by=self.admin.user),
            FormField.objects.create(
                form=self.form_other, key="other_interests", order=1, created_by=self.counselor.user, editable=True,
            ),
        ]
        self.form_fields_form_college_research = [
            FormField.objects.create(
                form=self.form_college_research, key="rating", order=0, created_by=self.admin.user
            ),
            FormField.objects.create(
                form=self.form_college_research,
                key="closing_thoughts",
                order=1,
                created_by=self.counselor.user,
                editable=True,
            ),
        ]
        FormField.objects.create(
            form=self.form_other, key="hidden_field", order=2, created_by=self.admin.user, hidden=True
        ),
        FormField.objects.create(
            form=self.form_other, key="other_not_associated", order=3, created_by=other_counselor.user, editable=True,
        )
        self.task = Task.objects.create(
            for_user=self.student.user,
            title="Test Form Task",
            due=timezone.now(),
            form=self.form,
            allow_form_submission=True,
        )
        self.task_other = Task.objects.create(
            for_user=self.student.user,
            title="Other Form Task",
            due=timezone.now(),
            form=self.form_other,
            allow_form_submission=True,
        )
        self.task_school_research = Task.objects.create(
            for_user=self.student.user,
            title="School/College Research Form Task",
            due=timezone.now(),
            form=self.form_college_research,
            allow_form_submission=True,
        )
        self.task_parent = Task.objects.create(
            for_user=self.parent.user,
            title="Parent Form Task",
            due=timezone.now(),
            form=self.form,
            allow_form_submission=True,
        )
        other_student = Student.objects.create(user=User.objects.create_user("other_student"))
        self.task_other_student = Task.objects.create(
            for_user=other_student.user,
            title="Other Student Form Task",
            due=timezone.now(),
            form=self.form,
            allow_form_submission=True,
        )
        other_parent = Parent.objects.create(user=User.objects.create_user("other_parent"))
        self.task_other_parent = Task.objects.create(
            for_user=other_parent.user,
            title="Other Parent Form Task",
            due=timezone.now(),
            form=self.form,
            allow_form_submission=True,
        )

        self.form_submission_task = FormSubmission.objects.create(
            form=self.form, task=self.task, submitted_by=self.student.user
        )
        FormFieldEntry.objects.bulk_create(
            [
                FormFieldEntry(
                    form_submission=self.form_submission_task,
                    form_field=form_field,
                    created_by=self.student.user,
                    content=str(idx),
                )
                for idx, form_field in enumerate(self.form_fields_main_form)
            ]
        )

        self.form_submission_task_other = FormSubmission.objects.create(
            form=self.form_other, task=self.task_other, submitted_by=self.student.user,
        )
        FormFieldEntry.objects.bulk_create(
            [
                FormFieldEntry(
                    form_submission=self.form_submission_task_other,
                    form_field=form_field,
                    created_by=self.student.user,
                    content=str(idx),
                )
                for idx, form_field in enumerate(self.form_fields_other_form)
            ]
        )

        self.form_submission_task_parent = FormSubmission.objects.create(
            form=self.form, task=self.task_parent, submitted_by=self.parent.user,
        )
        FormFieldEntry.objects.bulk_create(
            [
                FormFieldEntry(
                    form_submission=self.form_submission_task_parent,
                    form_field=form_field,
                    created_by=self.parent.user,
                    content=str(idx),
                )
                for idx, form_field in enumerate(self.form_fields_main_form)
            ]
        )

        self.form_submission_task_school_research = FormSubmission.objects.create(
            form=self.form_college_research, task=self.task_school_research, submitted_by=self.student.user
        )
        FormFieldEntry.objects.bulk_create(
            [
                FormFieldEntry(
                    form_submission=self.form_submission_task_school_research,
                    form_field=form_field,
                    created_by=self.student.user,
                    content=str(idx),
                )
                for idx, form_field in enumerate(self.form_fields_form_college_research)
            ]
        )

        self.form_submission_other_student = FormSubmission.objects.create(
            form=self.form, task=self.task_other_student, submitted_by=other_student.user,
        )
        self.form_submission_other_parent = FormSubmission.objects.create(
            form=self.form, task=self.task_other_parent, submitted_by=other_parent.user,
        )

    def test_create_form_submission_success(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormSubmission.test_create_form_submission_success -s
        """
        form_field_entries = []
        form_field_entries_other = []

        for idx, form_field in enumerate(self.form_fields_main_form):
            form_field_entries.append({"content": str(idx), "form_field": form_field.pk})

        for idx, form_fields_other in enumerate(self.form_fields_other_form):
            form_field_entries_other.append({"content": str(idx), "form_field": form_fields_other.pk})

        # Student can create a form submission
        task = Task.objects.create(
            for_user=self.student.user,
            title="New Form Task",
            due=timezone.now(),
            form=self.form,
            allow_form_submission=True,
        )
        data = {
            "form": self.form.pk,
            "task": task.pk,
            "submitted_by": self.student.user.pk,
            "form_field_entries": form_field_entries,
        }
        self.client.force_login(self.student.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        result = json.loads(response.content)
        self.assertEqual(result["form"], data["form"])
        self.assertEqual(result["task"], data["task"])
        self.assertEqual(len(result["form_field_entries"]), len(data["form_field_entries"]))
        form_submission = FormSubmission.objects.get(pk=result["pk"])
        self.assertEqual(form_submission.form.pk, data["form"])
        self.assertEqual(form_submission.task.pk, data["task"])
        self.assertEqual(form_submission.submitted_by.pk, data["submitted_by"])
        self.assertCountEqual(
            form_submission.form_field_entries.values_list("pk", flat=True),
            [form_field_entry["pk"] for form_field_entry in result["form_field_entries"]],
        )
        self.assertEqual(form_submission.form_field_entries.first().form_field.pk, form_field_entries[0]["form_field"])
        self.assertEqual(form_submission.form_field_entries.first().content, form_field_entries[0]["content"])
        self.assertEqual(form_submission.form_field_entries.last().form_field.pk, form_field_entries[-1]["form_field"])
        self.assertEqual(form_submission.form_field_entries.last().content, form_field_entries[-1]["content"])
        # Parent can create a form submission
        task = Task.objects.create(
            for_user=self.parent.user,
            title="New Form Task",
            due=timezone.now(),
            form=self.form,
            allow_form_submission=True,
        )
        data = {
            "form": self.form.pk,
            "task": task.pk,
            "submitted_by": self.parent.user.pk,
            "form_field_entries": form_field_entries,
        }
        self.client.force_login(self.parent.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        result = json.loads(response.content)
        self.assertEqual(result["form"], data["form"])
        self.assertEqual(result["task"], data["task"])
        self.assertEqual(len(result["form_field_entries"]), len(data["form_field_entries"]))
        form_submission = FormSubmission.objects.get(pk=result["pk"])
        self.assertEqual(form_submission.form.pk, data["form"])
        self.assertEqual(form_submission.task.pk, data["task"])
        self.assertEqual(form_submission.submitted_by.pk, data["submitted_by"])
        self.assertCountEqual(
            form_submission.form_field_entries.values_list("pk", flat=True),
            [form_field_entry["pk"] for form_field_entry in result["form_field_entries"]],
        )
        self.assertEqual(form_submission.form_field_entries.first().form_field.pk, form_field_entries[0]["form_field"])
        self.assertEqual(form_submission.form_field_entries.first().content, form_field_entries[0]["content"])
        self.assertEqual(form_submission.form_field_entries.last().form_field.pk, form_field_entries[-1]["form_field"])
        self.assertEqual(form_submission.form_field_entries.last().content, form_field_entries[-1]["content"])
        # Counselor can create a form submission for their student
        task = Task.objects.create(
            for_user=self.student.user,
            title="New Form Task",
            due=timezone.now(),
            form=self.form_other,
            allow_form_submission=True,
        )
        data = {
            "form": self.form_other.pk,
            "task": task.pk,
            "submitted_by": self.counselor.user.pk,
            "form_field_entries": form_field_entries_other,
        }
        self.client.force_login(self.counselor.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        result = json.loads(response.content)
        self.assertEqual(result["form"], data["form"])
        self.assertEqual(result["task"], data["task"])
        self.assertEqual(len(result["form_field_entries"]), len(data["form_field_entries"]))
        form_submission = FormSubmission.objects.get(pk=result["pk"])
        self.assertEqual(form_submission.form.pk, data["form"])
        self.assertEqual(form_submission.task.pk, data["task"])
        self.assertEqual(form_submission.submitted_by.pk, data["submitted_by"])
        self.assertCountEqual(
            form_submission.form_field_entries.values_list("pk", flat=True),
            [form_field_entry["pk"] for form_field_entry in result["form_field_entries"]],
        )
        self.assertEqual(
            form_submission.form_field_entries.first().form_field.pk, form_field_entries_other[0]["form_field"]
        )
        self.assertEqual(form_submission.form_field_entries.first().content, form_field_entries_other[0]["content"])
        self.assertEqual(
            form_submission.form_field_entries.last().form_field.pk, form_field_entries_other[-1]["form_field"]
        )
        self.assertEqual(form_submission.form_field_entries.last().content, form_field_entries_other[-1]["content"])
        self.assertEqual(FormSubmission.objects.count(), 9)

    def test_create_form_submission_failure(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormSubmission.test_create_form_submission_failure -s
        """
        form_field_entries = []
        form_field_entries_other = []

        for idx, form_field in enumerate(self.form_fields_main_form):
            form_field_entries.append({"content": str(idx), "form_field": form_field.pk})

        for idx, form_fields_other in enumerate(self.form_fields_other_form):
            form_field_entries_other.append({"content": str(idx), "form_field": form_fields_other.pk})

        # Student can't submit a task form assigned to a different student
        new_student = Counselor.objects.create(user=User.objects.create_user("newstudent"))
        data = {
            "form": self.form.pk,
            "task": self.task.pk,
            "submitted_by": new_student.user.pk,
            "form_field_entries": form_field_entries,
        }
        self.client.force_login(new_student.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Counselor can't submit a task form for an unassociated student
        new_counselor = Counselor.objects.create(user=User.objects.create_user("newcounselor"))
        data["submitted_by"] = (new_counselor.user.pk,)
        self.client.force_login(new_counselor.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Parent can't submit a task form for an unassociated student
        new_parent = Parent.objects.create(user=User.objects.create_user("newparent"))
        data["submitted_by"] = (new_parent.user.pk,)
        self.client.force_login(new_parent.user)
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_form_submissions(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormSubmission.test_list_form_submissions -s
        """
        # Admins have access to all form submissions
        self.client.force_login(self.admin.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertEqual(len(result), FormSubmission.objects.count())
        # Nested form_field_entries absent on list action
        self.assertIsNone(result[0].get("form_field_entries", None))

        # Students have access to their form submissions
        self.client.force_login(self.student.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertCountEqual(
            [form_submission["pk"] for form_submission in result],
            FormSubmission.objects.filter(task__for_user=self.student.user).values_list("pk", flat=True),
        )

        # Counselors have access to their students' submissions and their students parent's submission
        self.client.force_login(self.counselor.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertCountEqual(
            [form_submission["pk"] for form_submission in result],
            FormSubmission.objects.filter(
                Q(task__for_user__student__counselor=self.counselor)
                | Q(task__for_user__parent__in=[student.parent for student in self.counselor.students.all()])
            )
            .distinct()
            .values_list("pk", flat=True),
        )

        # Parents have access to their own submissions and their students' submissions
        self.client.force_login(self.parent.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertCountEqual(
            [form_submission["pk"] for form_submission in result],
            FormSubmission.objects.filter(
                Q(task__for_user=self.parent.user) | Q(task__for_user__student__parent=self.parent)
            ).values_list("pk", flat=True),
        )

        # Custom endpoint `college-research` returns student's college_research form submission list
        self.client.force_login(self.student.user)
        response = self.client.get(reverse("form_submissions-college_research"), {"student": self.student.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = json.loads(response.content)
        self.assertEqual(len(results), 1)
        # check that returned form submission is indeed associated with a `college_research` form
        result = results[0]
        self.assertEqual(result["form"], Form.objects.get(key="college_research").pk)

    def test_retrieve_form_submission_success(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormSubmission.test_retrieve_form_submission_success -s
        """
        form_submission_student = self.form_submission_task
        form_submission_parent = self.form_submission_task_parent
        url_form_submission_student_detail = reverse(
            "form_submissions-detail", kwargs={"pk": form_submission_student.pk}
        )
        url_form_submission_parent_detail = reverse("form_submissions-detail", kwargs={"pk": form_submission_parent.pk})
        # Students can retrieve their form submission with nested form fields
        self.client.force_login(self.student.user)
        response = self.client.get(url_form_submission_student_detail)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertIsNotNone(result.get("form_field_entries", None))
        self.assertDictEqual(
            result, FormSubmissionSerializer(FormSubmission.objects.get(pk=form_submission_student.pk)).data
        )

        # Parents can retrieve their form submission with nested form fields
        self.client.force_login(self.parent.user)
        response = self.client.get(url_form_submission_parent_detail)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertIsNotNone(result.get("form_field_entries", None))
        self.assertDictEqual(
            result, FormSubmissionSerializer(FormSubmission.objects.get(pk=form_submission_parent.pk)).data
        )

        # Parents can retrieve their students' form submission with nested form fields
        self.client.force_login(self.parent.user)
        response = self.client.get(url_form_submission_student_detail)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertIsNotNone(result.get("form_field_entries", None))
        self.assertDictEqual(
            result, FormSubmissionSerializer(FormSubmission.objects.get(pk=form_submission_student.pk)).data
        )

        # Counselor can retrieve their students' submission and their students' parent's submission
        self.client.force_login(self.counselor.user)
        response = self.client.get(url_form_submission_student_detail)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertIsNotNone(result.get("form_field_entries", None))
        self.assertDictEqual(
            result, FormSubmissionSerializer(FormSubmission.objects.get(pk=form_submission_student.pk)).data
        )
        response = self.client.get(url_form_submission_parent_detail)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        self.assertIsNotNone(result.get("form_field_entries", None))
        self.assertDictEqual(
            result, FormSubmissionSerializer(FormSubmission.objects.get(pk=form_submission_parent.pk)).data
        )
        # Admin can retrieve any form submission with nested form field entries
        form_submission_pks = FormSubmission.objects.all().values_list("pk", flat=True)
        self.client.force_login(self.admin.user)
        for form_submission_pk in form_submission_pks:
            url = reverse("form_submissions-detail", kwargs={"pk": form_submission_pk})
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            result = json.loads(response.content)
            self.assertIsNotNone(result.get("form_field_entries", None))
            self.assertDictEqual(
                result, FormSubmissionSerializer(FormSubmission.objects.get(pk=form_submission_pk)).data
            )

    def test_retrieve_form_submission_failure(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormSubmission.test_retrieve_form_submission_failure -s
        """
        form_submission_other_student = self.form_submission_other_student
        form_submission_other_parent = self.form_submission_other_parent
        form_submission_parent = self.form_submission_task_parent

        url_form_submission_other_student_detail = reverse(
            "form_submissions-detail", kwargs={"pk": form_submission_other_student.pk}
        )
        url_form_submission_other_parent_detail = reverse(
            "form_submissions-detail", kwargs={"pk": form_submission_other_parent.pk}
        )
        url_form_submission_parent_detail = reverse("form_submissions-detail", kwargs={"pk": form_submission_parent.pk})
        # Student can't retrieve other students' submission
        self.client.force_login(self.student.user)
        response = self.client.get(url_form_submission_other_student_detail)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Student can't retrieve their parent's submission
        response = self.client.get(url_form_submission_parent_detail)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Parent can't retrieve other parent's submission
        self.client.force_login(self.parent.user)
        response = self.client.get(url_form_submission_other_parent_detail)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Parent can't retrieve other student's submission
        response = self.client.get(url_form_submission_other_student_detail)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Counselor can't retrieve other student's or other parent's submission
        self.client.force_login(self.counselor.user)
        response = self.client.get(url_form_submission_other_student_detail)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.get(url_form_submission_other_parent_detail)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_form_submission(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormSubmission.test_update_form_submission -s
        """
        form_submission_student = self.form_submission_task
        form_submission_parent = self.form_submission_task_parent
        url_form_submission_student_detail = reverse(
            "form_submissions-detail", kwargs={"pk": form_submission_student.pk}
        )
        url_form_submission_parent_detail = reverse("form_submissions-detail", kwargs={"pk": form_submission_parent.pk})
        # Updating form submission is not allowed. Update form field entries instead.
        data = {"updated_by": self.admin.user.pk}
        self.client.force_login(self.admin.user)
        # TODO: FIX TEST
        # response = self.client.patch(
        #     url_form_submission_student_detail, json.dumps(data), content_type="application/json"
        # )
        # self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        # response = self.client.patch(
        #     url_form_submission_parent_detail, json.dumps(data), content_type="application/json"
        # )
        # self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_destroy_form_submission(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormSubmission.test_destroy_form_submission -s
        """
        form_submission_student = self.form_submission_task
        form_submission_parent = self.form_submission_task_parent
        url_form_submission_student_detail = reverse(
            "form_submissions-detail", kwargs={"pk": form_submission_student.pk}
        )
        url_form_submission_parent_detail = reverse("form_submissions-detail", kwargs={"pk": form_submission_parent.pk})
        self.client.force_login(self.admin.user)
        response = self.client.delete(url_form_submission_student_detail)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Form Submission was archived; not deleted
        result = json.loads(response.content)
        self.assertIsNotNone(FormSubmission.objects.get(pk=result["pk"]).archived)
        response = self.client.delete(url_form_submission_parent_detail)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Form Submission was archived; not deleted
        result = json.loads(response.content)
        self.assertIsNotNone(FormSubmission.objects.get(pk=result["pk"]).archived)


class TestFormFieldEntry(TestCase):
    """
    python manage.py test cwtasks.tests.test_form_views:TestFormFieldEntry -s
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.url = reverse("form_field_entries-list")
        self.student = Student.objects.first()
        self.parent = Parent.objects.first()
        self.student.parent = self.parent
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.admin = Administrator.objects.first()
        self.form = Form.objects.create(
            title="Test Form Title", description="Test Form Description", created_by=self.admin.user
        )

        self.form_fields_main_form = [
            FormField.objects.create(form=self.form, key="name", order=0, created_by=self.admin.user),
            FormField.objects.create(
                form=self.form, key="interests", order=1, created_by=self.counselor.user, editable=True
            ),
        ]
        self.task = Task.objects.create(
            for_user=self.student.user,
            title="Student Form Task",
            due=timezone.now(),
            form=self.form,
            allow_form_submission=True,
        )
        self.task_parent = Task.objects.create(
            for_user=self.parent.user,
            title="Parent Form Task",
            due=timezone.now(),
            form=self.form,
            allow_form_submission=True,
        )

        self.form_submission_student = FormSubmission.objects.create(
            form=self.form, task=self.task, submitted_by=self.student.user
        )
        form_field_entries_student = []
        for idx, form_field in enumerate(self.form_fields_main_form):
            form_field_entries_student.append(
                FormFieldEntry.objects.create(
                    form_submission=self.form_submission_student,
                    form_field=form_field,
                    created_by=self.student.user,
                    content=str(idx),
                )
            )
        self.form_field_entries_student = form_field_entries_student
        self.form_submission_parent = FormSubmission.objects.create(
            form=self.form, task=self.task_parent, submitted_by=self.parent.user,
        )
        form_field_entries_parent = []
        for idx, form_field in enumerate(self.form_fields_main_form):
            form_field_entries_parent.append(
                FormFieldEntry.objects.create(
                    form_submission=self.form_submission_parent,
                    form_field=form_field,
                    created_by=self.parent.user,
                    content=str(idx),
                )
            )
        self.form_field_entries_parent = form_field_entries_parent

    def test_list_form_field_entries(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormFieldEntry.test_list_form_field_entries -s
        """
        # Admins have access to all form field entries
        self.client.force_login(self.admin.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = json.loads(response.content)
        self.assertEqual(len(results), FormFieldEntry.objects.count())
        result = results[0]
        form_field_entry = FormFieldEntry.objects.get(pk=result["pk"])
        self.assertEqual(result["form_submission"], form_field_entry.form_submission.pk)
        self.assertEqual(result["form_field"], form_field_entry.form_field.pk)
        self.assertEqual(result["content"], form_field_entry.content)

        # Student have access to their form field entries
        self.client.force_login(self.student.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = json.loads(response.content)
        form_field_entries = FormFieldEntry.objects.filter(created_by=self.student.user)
        self.assertEqual(len(results), form_field_entries.count())
        self.assertCountEqual([result["pk"] for result in results], form_field_entries.values_list("pk", flat=True))
        result = results[0]
        form_field_entry = FormFieldEntry.objects.get(pk=result["pk"])
        self.assertEqual(result["form_submission"], form_field_entry.form_submission.pk)
        self.assertEqual(result["form_field"], form_field_entry.form_field.pk)
        self.assertEqual(result["content"], form_field_entry.content)

        # Parent have access to their form field entries and their student-child
        self.client.force_login(self.parent.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = json.loads(response.content)
        form_field_entries = FormFieldEntry.objects.filter(
            Q(created_by=self.parent.user) | Q(created_by=self.student.user)
        )
        self.assertEqual(len(results), form_field_entries.count())
        self.assertCountEqual([result["pk"] for result in results], form_field_entries.values_list("pk", flat=True))
        result = results[0]
        form_field_entry = FormFieldEntry.objects.get(pk=result["pk"])
        self.assertEqual(result["form_submission"], form_field_entry.form_submission.pk)
        self.assertEqual(result["form_field"], form_field_entry.form_field.pk)
        self.assertEqual(result["content"], form_field_entry.content)

    def test_update_form_field_entry(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormFieldEntry.test_update_form_field_entry -s
        """

        form_field_entry_student = self.form_field_entries_student[0]
        form_field_entry_parent = self.form_field_entries_parent[0]

        url_detail_student = reverse("form_field_entries-detail", kwargs={"pk": form_field_entry_student.pk})
        url_detail_parent = reverse("form_field_entries-detail", kwargs={"pk": form_field_entry_parent.pk})

        data = {"content": "new student content"}
        # Student can update their form field entry content
        self.client.force_login(self.student.user)
        self.assertIsNone(form_field_entry_student.updated_by)
        self.assertIsNone(form_field_entry_student.form_submission.updated_by)
        response = self.client.patch(url_detail_student, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        form_field_entry_student.refresh_from_db()
        self.assertEqual(result["content"], data["content"])
        self.assertEqual(form_field_entry_student.content, data["content"])
        # Updated by was properfly updated on form field entry and associated form submission
        self.assertEqual(form_field_entry_student.updated_by.pk, self.student.user.pk)
        self.assertEqual(form_field_entry_student.form_submission.updated_by.pk, self.student.user.pk)

        # Student cannot update others' form field entry content
        response = self.client.patch(url_detail_parent, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        data = {"content": "new parent content"}
        # Parent can update their form field entry content
        self.client.force_login(self.parent.user)
        self.assertIsNone(form_field_entry_parent.updated_by)
        self.assertIsNone(form_field_entry_parent.form_submission.updated_by)
        response = self.client.patch(url_detail_parent, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        form_field_entry_parent.refresh_from_db()
        self.assertEqual(result["content"], data["content"])
        self.assertEqual(form_field_entry_parent.content, data["content"])
        # Updated by was properfly updated on form field entry and associated form submission
        self.assertEqual(form_field_entry_parent.updated_by.pk, self.parent.user.pk)
        self.assertEqual(form_field_entry_parent.form_submission.updated_by.pk, self.parent.user.pk)

        # Parent can update their student-child form field entry
        response = self.client.patch(url_detail_student, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        form_field_entry_student.refresh_from_db()
        self.assertEqual(result["content"], data["content"])
        self.assertEqual(form_field_entry_student.content, data["content"])
        self.assertEqual(form_field_entry_student.updated_by.pk, self.parent.user.pk)
        self.assertEqual(form_field_entry_student.form_submission.updated_by.pk, self.parent.user.pk)

        data = {"content": "new counselor content"}
        # Counselor can update their students' form field entry content
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url_detail_student, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        form_field_entry_student.refresh_from_db()
        self.assertEqual(result["content"], data["content"])
        self.assertEqual(form_field_entry_student.content, data["content"])
        # Updated by was properfly updated on form field entry and associated form submission
        self.assertEqual(form_field_entry_student.updated_by.pk, self.counselor.user.pk)
        self.assertEqual(form_field_entry_student.form_submission.updated_by.pk, self.counselor.user.pk)

        # Counselor can update their students' parent's form field entry
        response = self.client.patch(url_detail_parent, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)
        form_field_entry_parent.refresh_from_db()
        self.assertEqual(result["content"], data["content"])
        self.assertEqual(form_field_entry_parent.content, data["content"])
        self.assertEqual(form_field_entry_parent.updated_by.pk, self.counselor.user.pk)
        self.assertEqual(form_field_entry_parent.form_submission.updated_by.pk, self.counselor.user.pk)

    def test_destroy_form_field_entry(self):
        """
        python manage.py test cwtasks.tests.test_form_views:TestFormFieldEntry.test_destroy_form_field_entry -s
        """
        # Method not allowed
        form_field_entry_student = self.form_field_entries_student[0]
        form_field_entry_parent = self.form_field_entries_parent[0]

        url_detail_student = reverse("form_field_entries-detail", kwargs={"pk": form_field_entry_student.pk})
        url_detail_parent = reverse("form_field_entries-detail", kwargs={"pk": form_field_entry_parent.pk})

        self.client.force_login(self.admin.user)
        response = self.client.delete(url_detail_student)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        response = self.client.delete(url_detail_parent)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
