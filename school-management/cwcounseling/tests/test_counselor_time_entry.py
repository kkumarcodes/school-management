""" Test CRUD and proper permissions on CounselorTimeEntry
    python manage.py test cwcounseling.tests.test_counselor_time_entry
"""
import decimal
import json
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.shortcuts import reverse
from rest_framework import status

from cwcounseling.models import CounselorTimeEntry
from cwusers.models import Administrator, Counselor, Student


class TestCounselorTimeEntry(TestCase):
    # python manage.py test cwcounseling.tests.test_counselor_time_entry:TestCounselorTimeEntry -s
    fixtures = ("fixture.json",)

    def setUp(self) -> None:
        self.counselor = Counselor.objects.first()
        self.admin = Administrator.objects.first()
        self.student = Student.objects.first()
        self.student.is_paygo = True
        self.student.save()
        self.time_entry = CounselorTimeEntry.objects.create(counselor=self.counselor, date=timezone.now())
        self.time_entry_with_student = CounselorTimeEntry.objects.create(
            counselor=self.counselor, date=timezone.now(), student=self.student
        )

    def test_create(self):
        """ Counselor can create without student specified. If student specified,
        must be counselors student.
        Admin can create for any student
        """
        url = reverse("counselor_time_entry-list")
        payload = {"date": (timezone.now() - timedelta(days=3)).isoformat(), "hours": 1, "student": self.student.pk}
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.student.counselor = self.counselor
        self.student.save()
        response = self.client.post(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        time_entry = CounselorTimeEntry.objects.filter(date=payload["date"], counselor=self.counselor.pk).first()
        self.assertTrue(time_entry)

    def test_update(self):
        """Counselor can update for any entry they created and if student
        associated is their student.
        Admin can update for any student and any counselor
        """
        url = reverse("counselor_time_entry-detail", kwargs={"pk": self.time_entry.pk})

        # SUCCESS update with no associated student
        payload = {"hours": 2.00}
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(decimal.Decimal(response.data["hours"]), (payload["hours"]))

        # SUCCESS admin can update for this student
        self.client.force_login(self.admin.user)
        payload = {"student": self.student.pk}
        response = self.client.patch(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["student"], self.student.pk)

        # FAILURE counselor cannot update when student is not theirs
        payload = {"hours": 1.00}
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # SUCCESS counselor can update for their own student
        self.student.counselor = self.counselor
        self.student.save()
        payload = {"hours": 1.00}
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(decimal.Decimal(response.data["hours"]), payload["hours"])

    def test_delete(self):
        self.client.force_login(self.admin.user)
        url = reverse("counselor_time_entry-detail", kwargs={"pk": self.time_entry.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_retrieve(self):
        """ Counselor can retrieve for their own entries and for their own students
        Admins can retrieve for any student and any counselor

        filtering fields: counselor, student, start_date, end_date
        """
        url = f"{reverse('counselor_time_entry-list')}"

        # # SUCCESS - counselor retrieve own entry
        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for x in response.data:
            self.assertEqual(x["counselor"], self.counselor.pk)
            if x["student"]:
                self.assertEqual(x["student"], self.counselor.pk)

        # SUCCESS - admin retrieves ALL
        self.client.force_login(self.admin.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), len(CounselorTimeEntry.objects.all()))

        # SUCCESS - associate student with counselor, student is in results for
        self.student.counselor = self.counselor
        self.student.save()
        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for x in response.data:
            self.assertEqual(x["counselor"], self.counselor.pk)
            if x["student"]:
                self.assertEqual(x["student"], self.counselor.pk)

        # SUCCESS - admin filter by counselor, student, start_date, end_date
        self.time_entry_with_student1 = CounselorTimeEntry.objects.create(
            counselor=self.counselor, date=timezone.now() - timedelta(days=3), student=self.student, hours=1
        )
        self.time_entry_with_student2 = CounselorTimeEntry.objects.create(
            counselor=self.counselor, date=timezone.now() - timedelta(days=5), student=self.student, hours=1
        )
        self.time_entry_with_student3 = CounselorTimeEntry.objects.create(
            counselor=self.counselor, date=timezone.now() - timedelta(days=10), student=self.student, hours=2
        )

        self.time_entry_with_student4 = CounselorTimeEntry.objects.create(
            counselor=Counselor.objects.create(),
            date=timezone.now() - timedelta(days=6),
            student=self.student,
            hours=2,
        )

        # response successful
        # response includes ONLY those counselors
        self.client.force_login(self.admin.user)
        url = f"{reverse('counselor_time_entry-list')}?counselor={self.counselor.pk}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        [self.assertEqual(x["counselor"], self.counselor.pk) for x in response.data]

        # response successful
        # response includes ONLY this student
        url = f"{reverse('counselor_time_entry-list')}?student={self.student.pk}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        [self.assertEqual(x["student"], self.student.pk) for x in response.data]

        # response successful
        # response includes ONLY dates within range (7 days ago until now )
        start = (timezone.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"{reverse('counselor_time_entry-list')}?start={start}&end={end}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), len(CounselorTimeEntry.objects.filter(date__lte=end, date__gte=start)))

        # counselor only receives their own entries
        self.time_entry_with_student4.student = None
        self.time_entry_with_student4.save()
        self.client.force_login(self.counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 4)
