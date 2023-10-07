""" python manage.py test cwcounseling.tests.test_student_activity -s
"""

import json
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from cwcounseling.models import StudentActivity
from snusers.models import Parent, Student, Tutor, Counselor, Administrator


class TestStudentActivity(TestCase):
    """ python manage.py test cwcounseling.tests.test_student_activity:TestStudentActivity -s
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.parent = Parent.objects.first()
        self.counselor = Counselor.objects.first()
        self.tutor = Tutor.objects.first()
        self.administrator = Administrator.objects.first()

        self.activity_1 = StudentActivity.objects.create(
            category="Other",
            student=self.student,
            years_active=[9, 10],
            hours_per_week=3,
            weeks_per_year=24,
            awards="Best impression",
            name="Stand-up",
            description="Stand up comedy club",
            order=0
        )

        self.activity_2 = StudentActivity.objects.create(
            category="Work Experience",
            student=self.student,
            years_active=[12],
            hours_per_week=1,
            weeks_per_year=50,
            name="FBLA",
            description="business club",
            order=1
        )

        self.activity_3 = StudentActivity.objects.create(
            category="Summer Activity",
            student=self.student,
            years_active=[12],
            hours_per_week=3,
            weeks_per_year=24,
            name="world traveler",
            description="go places",
            order=2
        )

    def test_create_activity(self):
        """ Student can create for self
            Parent can create for own student
            Counselor can create for own student
            Tutor cannot create
            Activity order is set properly
        """
        url = reverse("student_activity-list")
        data1 = {
            "category": "Other",
            "student": self.student.pk,
            "years_active": [9, 10],
            "hours_per_week": 3,
            "weeks_per_year": 24,
            "awards": "Best impression",
            "name": "Stand-up",
            "description": "Stand up comedy club",
        }
        # student can create activity for self
        self.client.force_login(self.student.user)
        response = self.client.post(url, json.dumps(data1), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # check that order is set properly
        self.assertEqual(response.data["order"], 3)
        # parent cannot create for a student they don't have access to
        self.client.force_login(self.parent.user)
        response = self.client.post(url, json.dumps(data1), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.student.parent = self.parent
        self.student.save()
        # parent can create for their student
        response = self.client.post(url, json.dumps(data1), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data2 = {
            "category": "Work Experience",
            "student": self.student.pk,
            "years_active": [9, 10, 11, 12],
            "hours_per_week": 3,
            "weeks_per_year": 24,
            "name": "Barista",
            "description": "Make coffee",
        }

        # tutor cannot create
        self.client.force_login(self.tutor.user)
        response = self.client.post(url, json.dumps(data2), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # counselor cannot create for a student they don't have access to
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, json.dumps(data2), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # counselor can create for their student
        self.student.counselor = self.counselor
        self.student.save()
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, json.dumps(data2), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_delete_single_activity(self):
        """ Student can delete for self
            Parent can delete for own student
            Counselor can delete for own student
            Admin can delete for any student
            Tutor cannot delete
        """
        activity_3 = StudentActivity.objects.create(
            category="Summer Activity",
            student=self.student,
            years_active=[12],
            hours_per_week=3,
            weeks_per_year=24,
            name="world traveler",
            description="go places",
            order=4
        )
        # student can delete own activity
        url = reverse("student_activity-detail", kwargs={"pk": activity_3.pk})
        self.client.force_login(self.student.user)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(StudentActivity.objects.filter(pk=activity_3.pk).exists())

        url = reverse("student_activity-detail", kwargs={"pk": self.activity_1.pk})
        # # parent cannot delete if not their student
        self.client.force_login(self.parent.user)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # parent can delete for own student
        self.student.parent = self.parent
        self.student.save()
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # counselor can only delete for own student
        url = reverse("student_activity-detail", kwargs={"pk": self.activity_2.pk})
        self.client.force_login(self.counselor.user)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # counselor can delete for own student
        self.student.counselor = self.counselor
        self.student.save()
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_update_single_activity(self):
        """ Student can update for self
            Parent can update for own student
            Counselor can update for own student
            Admin can update for any student
            Tutor cannot update
        """
        url = reverse("student_activity-detail", kwargs={"pk": self.activity_1.pk})
        # student can update activity for self
        self.client.force_login(self.student.user)

        response = self.client.patch(url, json.dumps({"description": "Stand down"}), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["description"], "Stand down")

        # parent cannot update for a student they don't have access to
        self.client.force_login(self.parent.user)
        response = self.client.patch(url, json.dumps({"description": "Not allowed"}), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.student.parent = self.parent
        self.student.save()
        # parent can update for their student
        response = self.client.patch(url, json.dumps({"description": "coffee maker"}), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["description"], "coffee maker")

        # tutor cannot update
        self.client.force_login(self.tutor.user)
        response = self.client.patch(url, json.dumps({"description": "not allowed"}), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # counselor cannot update for a student they don't have access to
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url, json.dumps({"description": "not allowed"}), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # counselor can update for their student
        self.student.counselor = self.counselor
        self.student.save()
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url, json.dumps({"description": "Make coffee"}), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["description"], "Make coffee")

    def test_retrieve_list_activities_for_student(self):
        """ Student can retrieve for self
            Parent can retrieve for own student
            Counselor can retrieve for own student
            Admin can retrieve for any student
            Tutor cannot retrieve
        """
        url = f"{reverse('student_activity-list')}?student_pk={self.student.pk}"
        url2 = reverse("student_activity-list")
        # student can get own activities
        self.client.force_login(self.student.user)
        response = self.client.get(url2)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        self.assertEqual(response.data[1]["name"], "FBLA")

        # tutor cannot get
        self.client.force_login(self.tutor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # counselor can get for own student
        self.student.counselor = self.counselor
        self.student.save()
        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        self.assertEqual(response.data[1]["name"], "FBLA")

        # parent must be associated with student
        self.client.force_login(self.parent.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.student.parent = self.parent
        self.student.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        self.assertEqual(response.data[1]["name"], "FBLA")

        # admin can get activities for student
        self.client.force_login(self.administrator.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        self.assertEqual(response.data[1]["name"], "FBLA")
