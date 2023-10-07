""" Test CRUD and proper permissions on CounselorTimeEntry
    python manage.py test cwcounseling.tests.test_counselor_time_card
"""
import decimal
import json
import random
from datetime import timedelta
from django.contrib.auth.models import User

from django.shortcuts import reverse
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from cwcounseling.models import CounselingHoursGrant, CounselorTimeCard, CounselorTimeEntry
from cwcounseling.utilities.counselor_time_card_manager import (
    CounselorTimeCardManager,
    CounselorTimeCardManagerException,
)
from snusers.models import Administrator, Counselor, Parent, Student, Tutor


class TestCounselingHoursGrantViewset(TestCase):
    # python manage.py test cwcounseling.tests.test_counselor_time_card:TestCounselingHoursGrantViewset
    fixtures = ("fixture.json",)

    def setUp(self) -> None:
        self.counselor: Counselor = Counselor.objects.first()
        self.counselor.part_time = True
        self.counselor.save()
        self.admin = Administrator.objects.first()
        self.student = Student.objects.first()
        self.student.is_paygo = True
        self.student.save()
        self.parent = Parent.objects.first()  # Note this is NOT our student's parent
        self.tutor = Tutor.objects.first()  # Note this is NOT our student's tutor

    def test_create(self):
        url = reverse("counseling_hours_grants-list")
        data = {"number_of_hours": 7, "student": self.student.pk, "note": "Great Note!"}
        # Can't create except as admin
        bad_users = (self.student.user, self.tutor.user, self.parent.user, self.counselor.user)
        for u in bad_users:
            self.client.force_login(u)
            response = self.client.post(url, data=json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 403)

        # Successful create as admin
        self.client.force_login(self.admin.user)
        response = self.client.post(url, data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        grant: CounselingHoursGrant = CounselingHoursGrant.objects.get(pk=json.loads(response.content)["pk"])
        self.assertEqual(grant.student, self.student)
        self.assertEqual(grant.number_of_hours, data["number_of_hours"])
        self.assertEqual(grant.note, data["note"])
        self.assertEqual(grant.created_by, self.admin.user)

    def test_update_delete(self):
        entry: CounselingHoursGrant = CounselingHoursGrant.objects.create(student=self.student, number_of_hours=10)
        data = {"number_of_hours": 7, "note": "Great Note!"}
        url = reverse("counseling_hours_grants-detail", kwargs={"pk": entry.pk})
        # Can't update or delete except as admin
        bad_users = (self.student.user, self.tutor.user, self.parent.user, self.counselor.user)
        for u in bad_users:
            self.client.force_login(u)
            response = self.client.patch(url, data=json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 403)
            response = self.client.delete(url, data=json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 403)

        # Successful update as admin
        self.client.force_login(self.admin.user)
        response = self.client.patch(url, data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        grant: CounselingHoursGrant = CounselingHoursGrant.objects.get(pk=json.loads(response.content)["pk"])
        self.assertEqual(grant.number_of_hours, data["number_of_hours"])
        self.assertEqual(grant.note, data["note"])

        # Validation: Can't update student
        new_student = Student.objects.create(user=User.objects.create_user("test_user"))
        data["student"] = new_student.pk
        response = self.client.patch(url, data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)

        # Admin can delete
        response = self.client.delete(url, data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 204)


class TestCounselorTimeEntry(TestCase):
    # python manage.py test cwcounseling.tests.test_counselor_time_card:TestCounselorTimeEntry
    fixtures = ("fixture.json",)

    def setUp(self) -> None:
        self.counselor: Counselor = Counselor.objects.first()
        self.counselor.part_time = True
        self.counselor.save()
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

        # Can't log time for counselor who is not part time
        self.student.is_paygo = True
        self.student.save()
        self.counselor.part_time = False
        self.counselor.save()
        payload = {
            "date": (timezone.now() - timedelta(days=3)).isoformat(),
            "hours": 1,
            "counselor": self.counselor.pk,
        }
        self.assertEqual(self.client.post(url, json.dumps(payload), content_type="application/json").status_code, 400)
        self.counselor.part_time = True
        self.counselor.save()

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

    def test_determine_pay_rate(self):
        """ Test that we determine pay rate using:
            1. Pay rate on time entry
            2. Pay rate on time entry's student
            3. Pay rate on time card
            python manage.py test cwcounseling.tests.test_counselor_time_card:TestCounselorTimeEntry.test_determine_pay_rate
        """
        self.counselor.hourly_rate = 40
        self.counselor.save()
        self.time_entry.pay_rate = 180
        self.time_entry.hours = 1
        self.time_entry.save()
        self.time_entry_with_student.student.counselor_pay_rate = 110
        self.time_entry_with_student.student.save()
        self.time_entry_with_student.hours = 1
        self.time_entry_with_student.save()
        CounselorTimeEntry.objects.create(counselor=self.counselor, hours=1, date=timezone.now())
        time_card = CounselorTimeCardManager.create(
            self.counselor, timezone.now() - timedelta(days=2), timezone.now() + timedelta(days=1)
        )
        self.assertEqual(time_card.total, 40 + 180 + 110)

    def test_update_recalculate_total(self):
        """ Test that when we create a new counselor time entry on a time card or move a counselor time entry
            from one time card to another, that time card totals get updated properly
        """
        self.counselor.hourly_rate = 100
        self.counselor.save()
        self.time_entry_with_student.hours = 1.5
        self.time_entry_with_student.save()
        time_card = CounselorTimeCardManager.create(self.counselor, timezone.now() - timedelta(days=2), timezone.now())
        self.assertEqual(time_card.total, decimal.Decimal(150))

        # Create a new item, confirm total updates properly
        self.client.force_login(self.counselor.user)
        payload = {
            "date": timezone.now().isoformat(),
            "hours": 2,
            "counselor": self.counselor.pk,
            "counselor_time_card": time_card.pk,
            "pay_rate": 200,
        }
        response = self.client.post(
            reverse("counselor_time_entry-list"), json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        time_card.refresh_from_db()
        self.assertEqual(time_card.total, decimal.Decimal(550))
        time_entry = CounselorTimeEntry.objects.get(pk=json.loads(response.content)["pk"])

        # Move time item to new time card
        new_time_card = CounselorTimeCardManager.create(
            self.counselor, timezone.now() - timedelta(days=5), timezone.now() - timedelta(days=2)
        )
        payload = {"counselor_time_card": new_time_card.pk}
        response = self.client.patch(
            reverse("counselor_time_entry-detail", kwargs={"pk": time_entry.pk}),
            json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        time_card.refresh_from_db()
        self.assertEqual(time_card.total, decimal.Decimal(150))
        new_time_card.refresh_from_db()
        self.assertEqual(new_time_card.total, decimal.Decimal(400))

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
            counselor=self.counselor,
            date=timezone.now() - timedelta(days=3),
            student=self.student,
            hours=1,
            amount_paid=4,
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
        self.assertEqual(sum([int(x["amount_paid"]) for x in json.loads(response.content)]), 4)

        # response successful
        # response includes ONLY dates within range (7 days ago until now )
        start = (timezone.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"{reverse('counselor_time_entry-list')}?start={start}&end={end}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), len(CounselorTimeEntry.objects.filter(date__lte=end, date__gte=start)))


class TestCounselorTimeCardManager(TestCase):
    """ Test our time card manager.
        Note that we primarily test creation of time card with the manager here. Testing of creation tested
        through the view (test below)
    """

    # python manage.py test cwcounseling.tests.test_counselor_time_card:TestCounselorTimeCardManager
    fixtures = ("fixture.json",)

    def setUp(self) -> None:
        self.counselor: Counselor = Counselor.objects.first()
        self.counselor.part_time = True
        self.counselor.hourly_rate = 10
        self.counselor.save()
        self.admin = Administrator.objects.first()
        self.student = Student.objects.first()
        self.student.is_paygo = True
        self.student.save()
        self.time_entries = [
            CounselorTimeEntry.objects.create(
                counselor=self.counselor,
                student=self.student,
                hours=1,
                date=timezone.now() - timedelta(days=random.randint(1, 4)),
            )
            for x in range(5)
        ]

    def test_create_time_card(self):
        CounselorTimeEntry.objects.create(
            counselor=self.counselor, student=self.student, hours=1, date=timezone.now() - timedelta(days=100)
        )
        CounselorTimeEntry.objects.create(
            counselor=None, student=self.student, hours=1, date=timezone.now() - timedelta(days=1)
        )
        # Create a time card. Ensure it contains self.time_entries but should NOT contain either of the entries above
        time_card = CounselorTimeCardManager.create(self.counselor, timezone.now() - timedelta(days=10), timezone.now())
        self.assertEqual(time_card.counselor_time_entries.count(), 5)
        self.assertEqual(time_card.total, decimal.Decimal(50))
        self.assertEqual(time_card.counselor, self.counselor)
        self.assertIsNone(time_card.counselor_approval_time)
        self.assertIsNone(time_card.admin_approval_time)
        [self.assertTrue(time_card.counselor_time_entries.filter(pk=x.pk).exists()) for x in self.time_entries]

        # Test admin category for payrate
        admin_time_entry = CounselorTimeEntry.objects.create(
            counselor=self.counselor,
            student=self.student,
            hours=1,
            date=timezone.now() - timedelta(days=6),
            category="admin_training",
        )
        time_card.delete()
        time_card = CounselorTimeCardManager.create(self.counselor, timezone.now() - timedelta(days=10), timezone.now())
        admin_time_entry.refresh_from_db()
        self.assertEqual(admin_time_entry.pay_rate, 35)

    def test_create_time_card_fail(self):
        # Failes if counselor is not part time
        self.counselor.part_time = False
        self.counselor.save()
        func = lambda: CounselorTimeCardManager.create(
            self.counselor, timezone.now() - timedelta(days=10), timezone.now()
        )
        self.assertRaises(CounselorTimeCardManagerException, func)


class TestCounselorTimeCardView(TestCase):
    # python manage.py test cwcounseling.tests.test_counselor_time_card:TestCounselorTimeCardView

    fixtures = ("fixture.json",)

    def setUp(self) -> None:
        self.counselor: Counselor = Counselor.objects.first()
        self.counselor.part_time = True
        self.counselor.save()
        self.admin = Administrator.objects.first()
        self.student = Student.objects.first()
        self.student.is_paygo = True
        self.student.save()
        self.time_entries = [
            CounselorTimeEntry.objects.create(
                counselor=self.counselor,
                student=self.student,
                hours=1,
                date=timezone.now() - timedelta(days=random.randint(1, 4)),
            )
            for x in range(5)
        ]

    def test_create(self):
        data = json.dumps(
            {
                "counselors": [self.counselor.pk],
                "start": (timezone.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
                "end": timezone.now().strftime("%Y-%m-%d"),
            }
        )
        url = reverse("counselor_time_card-list")
        # Must be logged in
        self.assertEqual(self.client.post(url, data, content_type="application/json").status_code, 401)

        # No student access
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.post(url, data, content_type="application/json").status_code, 403)

        # Success :)
        self.client.force_login(self.admin.user)
        self.assertEqual(self.client.post(url, data, content_type="application/json").status_code, 201)
        self.assertTrue(CounselorTimeCard.objects.exists())
        # Note that we don't rigorously test time card was created properly, because that occurs in testing manager

    def test_approve(self):
        time_card = CounselorTimeCardManager.create(self.counselor, timezone.now() - timedelta(days=10), timezone.now())
        url = reverse("counselor_time_card-approve", kwargs={"pk": time_card.pk})
        # Requires login
        self.assertEqual(self.client.post(url, content_type="application/json").status_code, 401)

        # Counselor approvers
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, json.dumps({"note": "Great Note!"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertIsNotNone(result["counselor_approval_time"])
        self.assertFalse(result["admin_has_approved"])
        self.assertEqual(result["counselor_note"], "Great Note!")

        # Admin approves
        self.client.force_login(self.admin.user)
        response = self.client.post(url, json.dumps({"note": "HI"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertIsNotNone(result["counselor_approval_time"])
        self.assertEqual(result["admin_note"], "HI")
        self.assertIsNotNone(result["admin_approval_time"])


class TestStudentCounselingHoursViewset(TestCase):
    # python manage.py test cwcounseling.tests.test_counselor_time_card:TestStudentCounselingHoursViewset

    fixtures = ("fixture.json",)

    def setUp(self) -> None:
        self.counselor: Counselor = Counselor.objects.first()
        self.counselor.part_time = True
        self.counselor.save()
        self.admin = Administrator.objects.first()
        self.student = Student.objects.first()
        self.student.is_paygo = True
        self.student.save()

    def test_get_api_avaialble_to_admin_only(self):
        # Not allowed if not logged in
        url = reverse("student_counseling_hours-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

        # Not allowed if if not admin
        self.client.force_login(self.student.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        # login as admin
        self.client.force_login(self.admin.user)
        response = self.client.generic(method="GET", path=url, content_type="application/json")
        self.assertEqual(response.status_code, 200)
