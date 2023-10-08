""" Test snuniversities.views
    python manage.py test snuniversities.tests.test_views
"""
import json

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.shortcuts import reverse
from django.test import TestCase


from rest_framework import status
from snuniversities.managers.student_university_decision_manager import StudentUniversityDecisionManager

from snuniversities.models import (
    Deadline,
    DeadlineCategory,
    DeadlineType,
    StudentUniversityDecision,
    University,
    UniversityList,
)
from snusers.models import Administrator, Counselor, Parent, Student, Tutor
from snusers.constants.counseling_student_types import NOT_TOO_LATE

WASHU_IPED = "179867"
WASHU_DATA_POINTS = 191  # Count of datapoints for washu
SN_DATA_KEYS = [
    "Class of",
    "Admission Decision",
    "GPA",
    "ACT",
    "SAT Single",
    "Major",
    "AP/IB/Coll",
    "Honors",
    "App Deadline",
    "Home State",
    "Applied Test Optional",
]


class TestDeadlineAndDecisionViewsets(TestCase):
    """ python manage.py test snuniversities.tests.test_views:TestDeadlineAndDecisionViewsets """

    fixtures = ("fixture.json",)

    @classmethod
    def setUpTestData(cls):
        cls.urls = {
            "deadline": reverse("deadlines-list"),
            "decision": reverse("student_university_decisions-list"),
        }
        cls.deadline_type = DeadlineType.objects.create(abbreviation="TYP", name="Test type")
        cls.deadline_category = DeadlineCategory.objects.create(abbreviation="CAT", name="Test category")
        cls.university = University.objects.create(name="Moo U", long_name="Cow College")
        cls.deadline = Deadline.objects.create(
            university=cls.university, category=cls.deadline_category, type_of=cls.deadline_type
        )
        cls.users = {
            "admin": Administrator.objects.first(),
            "counselor": Counselor.objects.first(),
            "parent": Parent.objects.first(),
            "student": Student.objects.first(),
            "tutor": Tutor.objects.first(),
        }
        students = {
            "one": cls.users["student"],
            "two": Student.objects.create(user=User.objects.create_user("StudentMcTest")),
        }
        for student in students.values():
            student.counselor = cls.users["counselor"]
            student.parent = cls.users["parent"]
            student.save()
        cls.students = students
        cls.universities = {}
        for user_type in cls.users:
            cls.universities[user_type] = University.objects.create(name=user_type, long_name=f"U of {user_type}")

    def test_deadlines(self):
        """ python manage.py test snuniversities.tests.test_views:TestDeadlineAndDecisionViewsets.test_deadlines """
        data = {
            "category": self.deadline_category.pk,
            "type_of": self.deadline_type.pk,
        }
        # Unauthenticated users cannot create Deadlines
        data["university"] = self.university.pk
        response = self.client.post(self.urls["deadline"], json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Only Admin users can create Deadlines
        for user_type, user_obj in self.users.items():
            data["university"] = self.universities[user_type].pk
            self.client.force_login(user_obj.user)
            response = self.client.post(self.urls["deadline"], json.dumps(data), content_type="application/json")
            if user_type != "admin":
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            else:
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertTrue(Deadline.objects.filter(pk=response.data["pk"]).exists())

        # Deadlines must be unique for University + Category + Type
        self.client.force_login(self.users["admin"].user)
        data["university"] = self.universities["admin"].pk
        self.assertRaises(
            IntegrityError,
            lambda: self.client.post(self.urls["deadline"], json.dumps(data), content_type="application/json"),
        )

    def test_decisions(self):
        """ python manage.py test snuniversities.tests.test_views:TestDeadlineAndDecisionViewsets.test_decisions """
        data = {
            "student": self.students["one"].pk,
            "deadline": self.deadline.pk,
        }
        # Unauthenticated users cannot create Decisions
        data["university"] = self.university.pk
        response = self.client.post(self.urls["decision"], json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Admins, Students, Parents, and Counselors can create Decisions
        decision_pks = {}
        for user_type, user_obj in self.users.items():
            data["university"] = self.universities[user_type].pk
            self.client.force_login(user_obj.user)
            response = self.client.post(self.urls["decision"], json.dumps(data), content_type="application/json")

            if user_type in {"admin", "parent", "student", "counselor"}:
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertTrue(StudentUniversityDecision.objects.filter(pk=response.data["pk"]).exists())
                decision_pks[user_type] = response.data["pk"]
            else:
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Admins, Students, Parents, and Counselors can read a Student's
        # Decisions
        student_decision_url = self.urls["decision"] + str(decision_pks["student"]) + "/"
        for user_type, user_obj in self.users.items():
            self.client.force_login(user_obj.user)
            response = self.client.get(student_decision_url)
            if user_type in {"admin", "parent", "student", "counselor"}:
                self.assertEqual(response.status_code, status.HTTP_200_OK)
            else:
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Admins, Students, Parents, and Counselors can update a Student's
        # Decision
        for user_type, user_obj in self.users.items():
            patch_data = {"note": f"Note by a {user_type}"}
            self.client.force_login(user_obj.user)
            response = self.client.patch(student_decision_url, json.dumps(patch_data), content_type="application/json")
            if user_type in {"admin", "parent", "student", "counselor"}:
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data["note"], patch_data["note"])
            else:
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Queries can be filtered by Student
        # (For this test, we need a decision by a second Student...)
        data = {
            "student": self.students["two"].pk,
            "deadline": self.deadline.pk,
            "university": self.university.pk,
        }
        self.client.force_login(self.users["admin"].user)
        response = self.client.post(self.urls["decision"], json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(StudentUniversityDecision.objects.filter(pk=response.data["pk"]).exists())

        response = self.client.get(self.urls["decision"] + f"?student={self.students['one'].pk}")
        self.assertEqual(len(response.data), len(decision_pks))
        response = self.client.get(self.urls["decision"] + f"?student={self.students['two'].pk}")
        self.assertEqual(len(response.data), 1)

        # Only allowed user types can delete decisions
        for user_type, user_obj in self.users.items():
            if user_type not in {"admin", "parent", "student", "counselor"}:
                self.client.force_login(user_obj.user)
                response = self.client.delete(student_decision_url)
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Parents can delete Student decisions
        self.client.force_login(self.users["parent"].user)
        response = self.client.delete(student_decision_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_decision_private_fields(self):
        """ Test that counselor-only fields are not exposed to student """
        sud_data = {
            "application_status_note": "Test Note",
            "transcript_note": "Test Note",
            "test_scores_note": "Test Note",
            "recommendation_one_note": "Test Note",
        }
        decision, _ = StudentUniversityDecisionManager.create(
            student=self.users["student"], university=University.objects.first(), **sud_data
        )

        # Login required
        url = reverse("student_university_decisions-detail", kwargs={"pk": decision.pk})
        self.assertEqual(self.client.get(url).status_code, 401)

        # Counselor gets fields
        counselor = Counselor.objects.first()
        self.users["student"].counselor = counselor
        self.users["student"].save()
        self.client.force_login(counselor.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        for key in sud_data.keys():
            self.assertEqual(result[key], sud_data[key])

        # Student does not get fields
        self.client.force_login(self.users["student"].user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        for key in sud_data.keys():
            self.assertNotIn(key, result)


class TestUniversityViewset(TestCase):
    """ python manage.py test snuniversities.tests.test_views:TestUniversityViewset """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.list_url = reverse("universities-list")
        users = {
            "admin": Administrator.objects.first(),
            "counselor": Counselor.objects.first(),
            "parent": Parent.objects.first(),
            "student": Student.objects.first(),
            "tutor": Tutor.objects.first(),
        }
        self.users = users

    def test_create(self):
        # Admin users can create a University
        self.client.force_login(self.users["admin"].user)
        data = {
            "name": "JU, Callisto",
            "long_name": "The University of Jupiter (Callisto campus)",
        }
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(University.objects.filter(pk=response.data["pk"]).exists())

        # Other user types cannot
        for user_type, user_obj in self.users.items():
            if user_type != "admin":
                self.client.force_login(user_obj.user)
                response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_applying_students(self):
        # Make it so that student is applying
        uni: University = University.objects.create(name="uni")
        student: Student = self.users["student"]
        StudentUniversityDecisionManager.create(university=uni, student=student)
        url = reverse("universities-applying_students", kwargs={"pk": uni.pk})

        # Student, parent, tutor can't retrieve this endpoint
        for user_type in ("student", "parent", "tutor"):
            self.client.force_login(self.users[user_type].user)
            self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

        # Counselor gets nothing back because student is not assigned to them
        self.client.force_login(self.users["counselor"].user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(json.loads(response.content)[StudentUniversityDecision.MAYBE]), 0)

        # But admin gets to see the student
        self.client.force_login(self.users["admin"].user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = json.loads(response.content)[StudentUniversityDecision.MAYBE]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.users["student"].pk)

        # And counselor can see after student is assigned to them
        self.users["student"].counselor = self.users["counselor"]
        self.users["student"].save()
        self.client.force_login(self.users["counselor"].user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(json.loads(response.content)[StudentUniversityDecision.MAYBE]), 1)


class TestUniversityListViewset(TestCase):
    """ python manage.py test snuniversities.tests.test_views:TestUniversityListViewset """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.list_url = reverse("university_lists-list")
        users = {
            "admin": Administrator.objects.first(),
            "counselor": Counselor.objects.first(),
            "parent": Parent.objects.first(),
            "student": Student.objects.first(),
            "tutor": Tutor.objects.first(),
        }
        self.users = users
        students = {
            "one": self.users["student"],
            "two": Student.objects.create(user=User.objects.create_user("StudentMcTest")),
        }
        for student in students.values():
            student.counselor = self.users["counselor"]
            student.parent = self.users["parent"]
            student.save()
        self.students = students

    def test_authentication(self):
        """ python manage.py test snuniversities.tests.test_views:TestUniversityListViewset.test_authentication """
        # Unauthenticated users cannot create lists
        data = {
            "name": "This List Should Be Impossible to Create!",
            "owned_by": self.users["student"].user.id,
        }
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create(self):
        """ python manage.py test snuniversities.tests.test_views:TestUniversityListViewset.test_create """
        # UniversityLists can only be owned by Student or Counselor users
        for user_type, user_obj in self.users.items():
            data = {
                "name": "Fancy University List",
                "owned_by": user_obj.user.id,
            }
            self.client.force_login(user_obj.user)
            response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
            if user_type in {"counselor", "student"}:
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertTrue(UniversityList.objects.filter(pk=response.data["pk"]).exists())
            else:
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Admins and Parents (and Students) can create UniversityLists for Students
        for user_type, user_obj in self.users.items():
            data = {
                "name": "A List for a Student",
                "owned_by": self.users["student"].user.id,
            }
            self.client.force_login(user_obj.user)
            response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
            if user_type in {"admin", "parent", "student"}:
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertTrue(UniversityList.objects.filter(pk=response.data["pk"]).exists())
            else:
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Admins (and Counselors) can create UniversityLists for Counselors
        for user_type, user_obj in self.users.items():
            data = {
                "name": "A List for a counselor",
                "owned_by": self.users["counselor"].user.id,
            }
            self.client.force_login(user_obj.user)
            response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
            if user_type in {"admin", "counselor"}:
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertTrue(UniversityList.objects.filter(pk=response.data["pk"]).exists())
            else:
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update(self):
        """ python manage.py test snuniversities.tests.test_views:TestUniversityListViewset.test_update """
        # (Create a list for this test to update)
        counselor = self.users["counselor"]
        self.client.force_login(counselor.user)
        data = {"name": "A Counselor's List", "owned_by": counselor.user_id}
        response = self.client.post(self.list_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(UniversityList.objects.filter(pk=response.data["pk"]).exists())

        # Universities can be added to lists
        uni1 = University.objects.create(name="uni1")
        uni2 = University.objects.create(name="uni2")
        patch_data = {"universities": [uni1.id, uni2.id]}
        patch_url = self.list_url + str(response.data["pk"]) + "/"
        response = self.client.patch(patch_url, json.dumps(patch_data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["universities"]), 2)

        # Universities can be removed from lists
        patch_data = {"universities": []}
        response = self.client.patch(patch_url, json.dumps(patch_data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["universities"]), 0)
        self.assertFalse(UniversityList.objects.filter(pk=response.data["pk"]).first().assigned_to.exists())

        # Students can be added to lists
        patch_data = {"assigned_to": [self.students["one"].user_id, self.students["two"].user_id]}
        response = self.client.patch(patch_url, json.dumps(patch_data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["assigned_to"]), 2)

        # Students can be removed from lists
        patch_data = {"assigned_to": []}
        response = self.client.patch(patch_url, json.dumps(patch_data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["assigned_to"]), 0)
        self.assertFalse(UniversityList.objects.filter(pk=response.data["pk"]).first().assigned_to.exists())

    def test_read(self):
        """ python manage.py test snuniversities.tests.test_views:TestUniversityListViewset.test_read """
        # (Create lists for this test to read)
        student = self.students["one"]
        university_list = UniversityList.objects.create(name="A Student's List", owned_by=student.user)
        student_one_list_url = self.list_url + str(university_list.id) + "/"
        self.assertTrue(UniversityList.objects.filter(pk=university_list.pk).exists())

        counselor = self.users["counselor"]
        university_list = UniversityList.objects.create(name="A Counselor's List", owned_by=counselor.user)
        self.assertTrue(UniversityList.objects.filter(pk=university_list.pk).exists())

        for student in self.students.values():
            university_list.assigned_to.add(student.user)
        university_list.save()
        self.assertTrue(len(UniversityList.objects.get(pk=university_list.pk).assigned_to.all()), 2)

        # Unauthenticated users cannot read lists
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Counselors can see their own lists, and their Students' lists
        self.client.force_login(counselor.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        # Students can see their own lists, and the lists they are assigned to
        student = self.students["one"]
        self.client.force_login(student.user)
        response = self.client.get(student_one_list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["owned_by"], student.user.pk)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        # Users cannot see other Users lists
        student_two = self.students["two"]
        self.client.force_login(student_two.user)
        response = self.client.get(student_one_list_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestSNUniversityDataView(TestCase):
    """ python manage.py test snuniversities.tests.test_views:TestSNUniversityDataView """

    fixtures = ("fixture.json", "ten_universities.json")

    def setUp(self):
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.parent = Parent.objects.first()
        self.tutor = Tutor.objects.first()
        self.uni = University.objects.get(iped=WASHU_IPED)
        self.url = reverse("cw_university_data", kwargs={"pk": self.uni.pk})

    def test_success(self):
        self.student.counseling_student_types_list.append(NOT_TOO_LATE)
        self.student.parent = self.parent
        self.student.save()

        for user in (self.student.user, self.parent.user, self.counselor.user):
            self.client.force_login(user)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(json.loads(response.content)), WASHU_DATA_POINTS)

        # We only need to test the contents rigorously once
        result = json.loads(response.content)
        self.assertTrue(all([(key in datapoint) for datapoint in result for key in SN_DATA_KEYS]))

    def test_failure(self):
        # Login required
        self.assertEqual(self.client.get(self.url).status_code, 401)
        # Non counseling student, parent and tutor can't access
        for user in (self.student.user, self.parent.user, self.tutor.user):
            self.client.force_login(user)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 403)
