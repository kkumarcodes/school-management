""" Test CRUD and proper permissions on CounselorNote
    python manage.py test sncounseling.tests.test_counselor_notes
"""
import json
from django.test import TestCase
from django.shortcuts import reverse
from django.contrib.auth.models import User
from snusers.models import Student, Counselor, Parent, Tutor, Administrator
from sncounseling.models import CounselorMeeting, CounselorNote
from sncounseling.constants.counselor_note_category import NOTE_CATEGORY_PRIVATE, NOTE_CATEGORY_MAJORS


class TestCounselorNoteViewset(TestCase):
    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.admin = Administrator.objects.first()
        self.counselor = Counselor.objects.first()
        self.parent = Parent.objects.first()
        self.student.counselor = self.counselor
        self.student.parent = self.parent
        self.student.save()
        self.counselor_meeting = CounselorMeeting.objects.create(student=self.student)
        self.tutor = Tutor.objects.first()

        # Different student, counselor
        self.bad_counselor = Counselor.objects.create(user=User.objects.create_user("badcounselor"))
        self.bad_student = Student.objects.create(
            user=User.objects.create_user("student2"), counselor=self.bad_counselor
        )
        self.bad_meeting = CounselorMeeting.objects.create(student=self.bad_student)

    def test_create_update(self):
        url = reverse("counselor_notes-list")
        payload = {
            "counselor_meeting": self.counselor_meeting.pk,
            "category": NOTE_CATEGORY_MAJORS,
            "note": "Great note, right?",
        }
        # Login required
        response = self.client.post(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 401)

        # Student, parent, tutor cant create
        for user in (self.student.user, self.parent.user, self.tutor.user):
            self.client.force_login(user)
            response = self.client.post(url, json.dumps(payload), content_type="application/json")
            self.assertEqual(response.status_code, 403)

        # Counselor creates note, and admin creates private note
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        major_note: CounselorNote = CounselorNote.objects.get(pk=json.loads(response.content)["pk"])

        self.client.force_login(self.admin.user)
        payload["category"] = NOTE_CATEGORY_PRIVATE
        response = self.client.post(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        private_note: CounselorNote = CounselorNote.objects.get(pk=json.loads(response.content)["pk"])
        self.assertEqual(private_note.category, NOTE_CATEGORY_PRIVATE)

        # Counselor and admin can update both notes
        for note, user in ((major_note, self.admin.user), (private_note, self.counselor.user)):
            self.client.force_login(user)
            response = self.client.patch(
                reverse("counselor_notes-detail", kwargs={"pk": note.pk}),
                json.dumps({"note": "2"}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.content)["note"], "2")
            note.refresh_from_db()
            self.assertEqual(note.note, "2")

        # Student can't update note
        self.client.force_login(self.student.user)
        response = self.client.patch(
            reverse("counselor_notes-detail", kwargs={"pk": major_note.pk}),
            json.dumps({"note": "3"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        # Note must either counselor_meeting note or a non-counselor_meeting note (date_note)
        payload["date_note"] = "2021-05-05"
        self.client.force_login(self.counselor.user)
        response = self.client.post(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 201)

    def test_retrieve(self):
        note = CounselorNote.objects.create(counselor_meeting=self.counselor_meeting, category=NOTE_CATEGORY_MAJORS,)
        # Student can't retrieve note for meeting that's not finalized
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.get(reverse("counselor_notes-detail", kwargs={"pk": note.pk})).status_code, 404)

        self.counselor_meeting.notes_finalized = True
        self.counselor_meeting.save()
        # Student and parent can each retrieve note unless it is invisible to them or private
        for user in (self.student.user, self.parent.user, self.counselor.user):
            self.client.force_login(user)
            result = self.client.get(reverse("counselor_notes-detail", kwargs={"pk": note.pk}))
            self.assertEqual(result.status_code, 200)
            self.assertEqual(json.loads(result.content)["category"], NOTE_CATEGORY_MAJORS)

        # Parent and student can't retrieve note for counselor meeting that isn't finalized
        self.counselor_meeting.notes_finalized = False
        self.counselor_meeting.save()
        self.client.force_login(self.parent.user)
        self.assertEqual(self.client.get(reverse("counselor_notes-detail", kwargs={"pk": note.pk})).status_code, 404)

        self.client.force_login(self.student.user)
        self.assertEqual(self.client.get(reverse("counselor_notes-detail", kwargs={"pk": note.pk})).status_code, 404)
        # Admin and counselor can
        for user in (self.counselor.user, self.admin.user):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("counselor_notes-detail", kwargs={"pk": note.pk})).status_code, 200
            )

        # Notes marked visible can't be retrieved if they are private
        note.category = NOTE_CATEGORY_PRIVATE
        note.save()
        self.counselor_meeting.notes_finalized = True
        self.counselor_meeting.save()
        for user in (self.counselor.user, self.admin.user):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("counselor_notes-detail", kwargs={"pk": note.pk})).status_code, 200
            )
        for user in (self.parent.user, self.student.user):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("counselor_notes-detail", kwargs={"pk": note.pk})).status_code, 404
            )

        # Counselor can't retrieve note for another counselor's meeting
        self.client.force_login(self.counselor.user)
        bad_note = CounselorNote.objects.create(
            category=NOTE_CATEGORY_MAJORS, counselor_meeting=self.bad_meeting, note="hh"
        )
        self.assertEqual(
            self.client.get(reverse("counselor_notes-detail", kwargs={"pk": bad_note.pk})).status_code, 404
        )

    def test_list(self):
        url = reverse("counselor_notes-list")
        note = CounselorNote.objects.create(counselor_meeting=self.counselor_meeting, category=NOTE_CATEGORY_MAJORS,)
        CounselorNote.objects.create(
            counselor_meeting=self.counselor_meeting, category=NOTE_CATEGORY_PRIVATE,
        )
        # Counselor gets their notes by default
        # Student gets their notes
        self.counselor_meeting.notes_finalized = True
        self.counselor_meeting.save()
        for user in (self.counselor.user, self.student.user):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            self.assertEqual(len(result), 1 if hasattr(user, "student") else 2)
            if hasattr(user, "student"):
                self.assertEqual(result[0]["pk"], note.pk)

        # Unless they aren't allowed to see them
        note.category = NOTE_CATEGORY_PRIVATE
        note.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 0)

        # Parent must identify student they want notes for
        note.category = NOTE_CATEGORY_MAJORS
        note.save()
        self.client.force_login(self.parent.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        response = self.client.get(f"{url}?student={self.student.pk}")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pk"], note.pk)

        # Admin can get all notes
        self.client.force_login(self.admin.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)

        # Admin gets notes for a counselor
        response = self.client.get(f"{url}?counselor={self.counselor.pk}")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)

    def test_update_note_title(self):
        """
            Custom endpoint should bulk update note_title on all non-meeting notes for
            given student on give note_date passed as query params
        """
        non_meeting_note_1 = CounselorNote.objects.create(
            category=NOTE_CATEGORY_MAJORS,
            note_title="Non-meeting note title",
            note_student=self.student,
            note_date="2021-10-06",
        )
        non_meeting_note_2 = CounselorNote.objects.create(
            category=NOTE_CATEGORY_MAJORS,
            note_title="Non-meeting note title",
            note_student=self.student,
            note_date="2021-10-06",
        )
        non_meeting_note_2 = CounselorNote.objects.create(
            category=NOTE_CATEGORY_MAJORS,
            note_title="Non-meeting note title",
            note_student=self.student,
            note_date="2021-10-07",
        )
        non_meeting_note_3 = CounselorNote.objects.create(
            category=NOTE_CATEGORY_MAJORS,
            note_title="Other student note title",
            note_student=self.bad_student,
            note_date="2021-10-06",
        )
        url = reverse("counselor_notes-update_note_title")
        payload = {"note_title": "updated note title"}
        self.client.force_login(self.counselor.user)
        response = self.client.patch(
            f"{url}?student={self.student.pk}&note_date=2021-10-06",
            json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        results = json.loads(response.content)
        self.assertEqual(len(results), 2)
        result = results[0]
        self.assertEqual(result["note_title"], payload["note_title"])
