""" Test creation, sending, and filtering of bulletins

    python manage.py test cwnotifications.tests.test_bulletin
"""
from datetime import timedelta, timezone
import json

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import reverse
from django.utils import timezone
from django.test import TestCase
from cwcommon.models import FileUpload
from cwnotifications.constants import notification_types
from cwnotifications.models import Bulletin, Notification, NotificationRecipient
from cwnotifications.utilities.bulletin_manager import BulletinManager
from snusers.constants.counseling_student_types import PAYGO, PAYGO_ESSAY
from snusers.models import Administrator, Counselor, Parent, Student, Tutor
from snusers.serializers.users import ParentSerializer, StudentSerializer
from snusers.utilities.managers import StudentManager


class TestBulletinManager(TestCase):
    """ python manage.py test cwnotifications.tests.test_bulletin:TestBulletinManager """

    fixtures = ("fixture.json",)

    def setUp(self):
        # DRF Router Base URLs from snusers.urls
        self.admin = Administrator.objects.first()
        self.parent = Parent.objects.first()
        self.counselor = Counselor.objects.first()
        self.student: Student = Student.objects.first()
        self.student.counseling_student_types_list = [PAYGO_ESSAY]
        self.student.parent = self.parent
        self.student.save()
        self.tutor = Tutor.objects.first()
        self.bulletin: Bulletin = Bulletin.objects.create(
            created_by=self.admin.user, title="Bulletin", content="Bulletin"
        )
        self.students = [
            Student.objects.create(
                graduation_year=x * 100, user=User.objects.create_user(f"{x}"), counseling_student_types_list=[PAYGO]
            )
            for x in range(10)
        ]
        self.students.append(self.student)
        self.cas_student: Student = self.students[1]
        self.cas_student.counseling_student_types_list = []
        self.cas_student.save()
        for s in self.students:
            NotificationRecipient.objects.get_or_create(user=s.user)
        NotificationRecipient.objects.get_or_create(user=self.parent.user)
        NotificationRecipient.objects.get_or_create(user=self.counselor.user)
        NotificationRecipient.objects.get_or_create(user=self.tutor.user)
        NotificationRecipient.objects.get_or_create(user=self.admin.user)

    def test_set_visible(self):
        """ Testing BulletinManager.set_visible_to_notification_recipients for parents and students """
        # All CAP students (excludes our CAS student), and our parent
        self.bulletin.students = True
        self.bulletin.cap = True
        self.bulletin.save()
        mgr = BulletinManager(self.bulletin)
        bulletin = mgr.set_visible_to_notification_recipients()
        self.assertEqual(
            bulletin.visible_to_notification_recipients.count(), len(self.students))
        self.assertTrue(bulletin.visible_to_notification_recipients.filter(
            user__parent=self.parent).exists())

        # All CAS students
        self.bulletin.cap = False
        self.bulletin.cas = True
        self.bulletin.visible_to_notification_recipients.clear()
        self.bulletin.save()
        bulletin = mgr.set_visible_to_notification_recipients()
        self.assertEqual(
            bulletin.visible_to_notification_recipients.count(), 1)
        self.assertFalse(bulletin.visible_to_notification_recipients.filter(
            user__parent=self.parent).exists())
        self.assertTrue(bulletin.visible_to_notification_recipients.filter(
            user__student=self.cas_student).exists())

        # Filter on class year
        self.bulletin.cap = True
        self.bulletin.cas = True
        self.bulletin.parents = False
        self.bulletin.class_years = [4000]
        self.bulletin.visible_to_notification_recipients.clear()
        self.bulletin.save()
        self.student.graduation_year = 4000
        self.student.save()
        bulletin = mgr.set_visible_to_notification_recipients()
        self.assertEqual(
            bulletin.visible_to_notification_recipients.count(), 1)
        self.assertTrue(bulletin.visible_to_notification_recipients.filter(
            user__student=self.student).exists())

        # Filter on counseling student type
        self.bulletin.visible_to_notification_recipients.clear()
        self.bulletin.class_years = []
        self.bulletin.counseling_student_types = [PAYGO]
        self.bulletin.cas = False
        self.bulletin.save()
        bulletin = mgr.set_visible_to_notification_recipients()
        self.assertEqual(
            bulletin.visible_to_notification_recipients.count(), len(self.students) - 2)
        self.assertFalse(bulletin.visible_to_notification_recipients.filter(
            user__parent=self.parent).exists())
        self.assertFalse(bulletin.visible_to_notification_recipients.filter(
            user__student=self.student).exists())

        # Filter on tags
        # Expect student to receive bulletin since student.tags overlap with bulletin.tags
        # Similarly - a student's parent receives bulletin via student.tags overlap with bulletin.tags
        self.bulletin.visible_to_notification_recipients.clear()
        self.bulletin.parents = True
        self.bulletin.counseling_student_types = []
        self.bulletin.tags = ["SAT"]
        self.bulletin.save()
        self.student.tags = ["SAT"]
        self.student.save()
        bulletin = mgr.set_visible_to_notification_recipients()
        self.assertEqual(
            bulletin.visible_to_notification_recipients.count(), 2)
        self.assertTrue(bulletin.visible_to_notification_recipients.filter(
            user__parent=self.parent).exists())
        self.assertTrue(bulletin.visible_to_notification_recipients.filter(
            user__student=self.student).exists())

    def test_set_tutor_counselor(self):
        mgr = BulletinManager(self.bulletin)
        bulletin = mgr.set_visible_to_notification_recipients()
        self.assertFalse(bulletin.visible_to_notification_recipients.filter(
            user__tutor=self.tutor).exists())
        self.assertFalse(bulletin.visible_to_notification_recipients.filter(
            user__counselor=self.counselor).exists())
        # All counselors and tutors
        self.bulletin.counselors = self.bulletin.tutors = True
        self.bulletin.save()
        mgr = BulletinManager(self.bulletin)
        bulletin = mgr.set_visible_to_notification_recipients()
        self.assertTrue(bulletin.visible_to_notification_recipients.filter(
            user__tutor=self.tutor).exists())
        self.assertTrue(bulletin.visible_to_notification_recipients.filter(
            user__counselor=self.counselor).exists())

    def test_create_notifications(self):
        # Creates notifications for all visible NR
        self.bulletin.counselors = self.bulletin.tutors = self.bulletin.cap = self.bulletin.cas = True
        self.bulletin.save()
        mgr = BulletinManager(self.bulletin)
        bulletin = mgr.set_visible_to_notification_recipients()
        self.assertEqual(
            bulletin.visible_to_notification_recipients.count(), len(self.students) + 3)
        noti_count = Notification.objects.count()
        mgr.send_bulletin()
        self.assertEqual(Notification.objects.count(),
                         noti_count + len(self.students) + 3)
        notis = Notification.objects.filter(
            related_object_content_type=ContentType.objects.get_for_model(Bulletin), related_object_pk=bulletin.pk
        )
        self.assertTrue(
            all([notis.filter(recipient=x).exists()
                for x in bulletin.visible_to_notification_recipients.all()])
        )

        # Send to subset
        recipients = [self.student.user.notification_recipient,
                      self.counselor.user.notification_recipient]
        mgr.send_bulletin(notification_recipients=recipients)
        self.assertEqual(Notification.objects.count(),
                         noti_count + len(self.students) + 5)
        self.assertEqual(notis.filter(
            recipient=self.counselor.user.notification_recipient).count(), 2)
        self.assertEqual(notis.filter(
            recipient=self.student.user.notification_recipient).count(), 2)

    def test_get_bulletins_for_notification_recipient(self):
        self.bulletin.cap = self.bulletin.cas = True
        self.bulletin.save()
        mgr = BulletinManager(self.bulletin)
        mgr.set_visible_to_notification_recipients()
        self.assertEqual(
            BulletinManager.get_bulletins_for_notification_recipient(
                self.counselor.user.notification_recipient
            ).count(),
            0,
        )
        self.assertEqual(
            BulletinManager.get_bulletins_for_notification_recipient(
                self.tutor.user.notification_recipient).count(), 0
        )
        self.assertEqual(
            BulletinManager.get_bulletins_for_notification_recipient(
                self.student.user.notification_recipient).count(),
            1,
        )
        self.bulletin.visible_to_notification_recipients.remove(
            self.student.user.notification_recipient)
        self.assertEqual(
            BulletinManager.get_bulletins_for_notification_recipient(
                self.student.user.notification_recipient).count(),
            0,
        )

        # With the exception of admins, who can view all bullets
        self.assertEqual(
            BulletinManager.get_bulletins_for_notification_recipient(
                self.admin.user.notification_recipient).count(), 1
        )

    def test_student_parent_scope(self):
        """ Confirm that the scope of who gets added to visible notification recipients is determined
            by who created the bulletin
        """
        self.student.counselor = self.counselor
        self.student.save()
        self.student.tutors.add(self.tutor)

        # First we test that for admin, all students/parents are added
        self.bulletin.counselors = self.bulletin.tutors = self.bulletin.cap = self.bulletin.cas = True
        self.bulletin.save()
        mgr = BulletinManager(self.bulletin)
        bulletin = mgr.set_visible_to_notification_recipients()
        self.assertEqual(
            bulletin.visible_to_notification_recipients.count(), len(self.students) + 3)

        # Counselor only gets their student/parent and Tutor only gets their student/parent
        for user in (self.counselor.user, self.tutor.user):
            bulletin.visible_to_notification_recipients.clear()
            self.bulletin.created_by = user
            self.bulletin.save()
            mgr = BulletinManager(self.bulletin)
            bulletin = mgr.set_visible_to_notification_recipients()
            self.assertEqual(
                bulletin.visible_to_notification_recipients.count(), 2)
            self.assertTrue(bulletin.visible_to_notification_recipients.filter(
                user=self.student.user).exists())

        # Parent gets NOTHING!
        self.bulletin.created_by = self.parent.user
        self.bulletin.save()
        bulletin.visible_to_notification_recipients.clear()
        mgr = BulletinManager(self.bulletin)
        bulletin = mgr.set_visible_to_notification_recipients()
        self.assertFalse(bulletin.visible_to_notification_recipients.exists())

    def test_evergreen(self):
        """ Test to ensure evergreen bulletins get properly set on new students and counselors
            python manage.py test cwnotifications.tests.test_bulletin:TestBulletinManager.test_evergreen
        """
        # We use serializers (instead of object manager) to create users because that's how it happens
        # in practice on the platform, though the serializers do use object managers on the backend
        self.bulletin.all_class_years = self.bulletin.all_counseling_student_types = True
        self.bulletin.created_by = self.counselor.user
        self.bulletin.save()
        self.student.counselor = self.counselor
        self.student.save()
        student_data = {
            "first_name": "S",
            "last_name": "S",
            "email": "e@e.com",
            "graduation_year": 1000,
            "counselor": self.counselor.pk,
        }
        parent_data = {"first_name": "P",
                       "last_name": "S", "email": "e@ep.com"}

        def _test_create_student_parent(bulletins):
            """ Helper method that creates student and parent, and then confirms all bulletins in bulletins
                are visible to student/parent. Then deletes users so we can try again
            """
            student_serializer = StudentSerializer(data=student_data)
            student_serializer.is_valid(raise_exception=True)
            student = student_serializer.save()
            self.assertEqual(
                student.user.notification_recipient.bulletins.count(), len(bulletins))
            self.assertTrue(
                all([student.user.notification_recipient.bulletins.filter(
                    pk=x.pk).exists() for x in bulletins])
            )

            parent_serializer = ParentSerializer(data=parent_data)
            parent_serializer.is_valid(raise_exception=True)
            parent = parent_serializer.save()
            student_manager = StudentManager(student)
            student_manager.set_parent(parent)
            self.assertEqual(
                parent.user.notification_recipient.bulletins.count(), len(bulletins))
            self.assertTrue(
                all([parent.user.notification_recipient.bulletins.filter(
                    pk=x.pk).exists() for x in bulletins])
            )

            student.user.delete()
            parent.user.delete()

        # First we make sure bulletin NOT added to student or parent since it's not evergreen
        _test_create_student_parent([])

        # # Make bulletin evergreen. Should NOT get added because not visible to student/parent yet
        self.bulletin.students = self.bulletin.parents = False
        self.bulletin.evergreen = True
        self.bulletin.save()
        _test_create_student_parent([])

        # Now it is visible
        self.bulletin.students = self.bulletin.parents = True
        self.bulletin.save()
        _test_create_student_parent([self.bulletin])

        # Still visible with evergreen expiration in the future
        self.bulletin.evergreen_expiration = timezone.now() + timedelta(days=1)
        self.bulletin.save()
        _test_create_student_parent([self.bulletin])

        # Not visible because student class year not met
        self.bulletin.all_class_years = False
        self.bulletin.class_years = [4]
        self.bulletin.save()
        _test_create_student_parent([])

        # Not visible because of evergreen expiration
        self.bulletin.all_class_years = True
        self.bulletin.evergreen_expiration = timezone.now() - timedelta(hours=1)
        self.bulletin.save()
        _test_create_student_parent([])


class TestBulletinViewset(TestCase):
    """ python manage.py test cwnotifications.tests.test_bulletin:TestBulletinManager """

    fixtures = ("fixture.json",)

    def setUp(self):
        # DRF Router Base URLs from snusers.urls
        self.admin = Administrator.objects.first()
        self.parent = Parent.objects.first()
        self.counselor = Counselor.objects.first()
        self.student = Student.objects.first()
        self.tutor = Tutor.objects.first()
        self.second_student = Student.objects.create(
            user=User.objects.create_user("1"))
        NotificationRecipient.objects.get_or_create(user=self.parent.user)
        NotificationRecipient.objects.get_or_create(user=self.counselor.user)
        NotificationRecipient.objects.get_or_create(user=self.student.user)
        NotificationRecipient.objects.get_or_create(user=self.tutor.user)
        NotificationRecipient.objects.get_or_create(user=self.admin.user)
        self.users = (self.parent.user, self.student.user,
                      self.counselor.user, self.tutor.user)

        self.file_upload = FileUpload.objects.create(
            link="https://google.com", title="Google!")

    def test_read(self):
        bulletin: Bulletin = Bulletin.objects.create(
            created_by=self.counselor.user, title="Bulletin!")
        url = reverse("bulletins-read", kwargs={"pk": bulletin.pk})
        # Login required
        self.assertEqual(self.client.post(url).status_code, 401)

        # Test student and parent reading bulletin.
        for user in (self.parent.user, self.student.user):
            self.client.force_login(user)
            bulletin.visible_to_notification_recipients.add(
                user.notification_recipient)
            self.assertEqual(self.client.post(url).status_code, 200)
            self.assertTrue(
                bulletin.read_notification_recipients.filter(user=user).exists())

        # And confirm student and parent names are returned to counselor as having read bulletin
        self.client.force_login(self.counselor.user)
        bulletin_response = self.client.get(
            reverse("bulletins-detail", kwargs={"pk": bulletin.pk}))
        self.assertEqual(bulletin_response.status_code, 200)
        result = json.loads(bulletin_response.content)
        self.assertIn(self.parent.invitation_name, result["read_parent_names"])
        self.assertIn(self.student.invitation_name,
                      result["read_student_names"])

    def test_create(self):
        url = reverse("bulletins-list")
        # Admin creates for all tutors and counselors
        data = {
            "counselors": True,
            "tutors": True,
            "students": False,
            "parents": False,
            "update_file_uploads": [str(self.file_upload.slug)],
        }
        self.assertEqual(self.client.post(url, json.dumps(
            data), content_type="application/json").status_code, 401)
        self.client.force_login(self.admin.user)
        result = self.client.post(url, json.dumps(
            data), content_type="application/json")
        self.assertEqual(result.status_code, 201)
        bulletin: Bulletin = Bulletin.objects.get(
            pk=json.loads(result.content)["pk"])
        self.assertEqual(bulletin.created_by, self.admin.user)
        self.assertEqual(
            bulletin.visible_to_notification_recipients.count(), 2)
        self.assertEqual(Notification.objects.filter(
            notification_type=notification_types.BULLETIN).count(), 2)
        self.assertTrue(bulletin.visible_to_notification_recipients.filter(
            user=self.counselor.user).exists())
        self.assertTrue(bulletin.visible_to_notification_recipients.filter(
            user=self.tutor.user).exists())
        self.assertEqual(bulletin.file_uploads.count(), 1)
        self.assertEqual(json.loads(result.content)[
                         "file_uploads"][0]["slug"], str(self.file_upload.slug))

        # Counselor creates for subset of students
        del data["update_file_uploads"]
        data["cas"] = True
        data["cap"] = True
        data["students"] = True
        data["parents"] = True
        data["visible_to_notification_recipients"] = [
            self.student.user.notification_recipient.pk]
        self.client.force_login(self.counselor.user)
        result = self.client.post(url, json.dumps(
            data), content_type="application/json")
        self.assertEqual(result.status_code, 201)
        bulletin: Bulletin = Bulletin.objects.get(
            pk=json.loads(result.content)["pk"])
        self.assertEqual(
            bulletin.visible_to_notification_recipients.count(), 1)
        self.assertTrue(bulletin.visible_to_notification_recipients.filter(
            user=self.student.user).exists())
        self.assertFalse(bulletin.file_uploads.exists())

        # Parent and Student cant create
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.post(url, json.dumps(
            data), content_type="application/json").status_code, 403)
        self.client.force_login(self.parent.user)
        self.assertEqual(self.client.post(url, json.dumps(
            data), content_type="application/json").status_code, 403)

    def test_list(self):
        # All users can list, get only bulletins visible to them
        url = reverse("bulletins-list")
        bulletin_one = Bulletin.objects.create(created_by=self.admin.user)
        Bulletin.objects.create(created_by=self.admin.user)
        for u in self.users:
            bulletin_one.visible_to_notification_recipients.add(
                u.notification_recipient)
        for u in self.users:
            self.client.force_login(u)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(json.loads(response.content)), 1)
        # With the exception of admins, who get everything
        self.client.force_login(self.admin.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json.loads(response.content)), 2)

    def test_update(self):
        # Counselor can update visible_to_notification_recipients. Confirm sent noti
        bulletin_one = Bulletin.objects.create(created_by=self.counselor.user,)
        bulletin_one.visible_to_notification_recipients.add(
            self.student.user.notification_recipient)
        url = reverse("bulletins-detail", kwargs={"pk": bulletin_one.pk})
        data = {"visible_to_notification_recipients": [],
                "update_file_uploads": [str(self.file_upload.slug)]}
        self.assertEqual(self.client.patch(url, json.dumps(
            data), content_type="application/json").status_code, 401)
        self.client.force_login(self.counselor.user)
        response = self.client.patch(url, json.dumps(
            data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            bulletin_one.visible_to_notification_recipients.exists())
        self.assertEqual(bulletin_one.file_uploads.count(), 1)
        self.assertEqual(json.loads(response.content)[
                         "file_uploads"][0]["slug"], str(self.file_upload.slug))

        # Can't update when not creator
        self.client.force_login(self.tutor.user)
        self.assertEqual(self.client.patch(url, json.dumps(
            data), content_type="application/json").status_code, 403)

        # Admin updates title and content
        self.client.force_login(self.admin.user)
        data["title"] = "Great new title"
        data["content"] = "Great new content"
        data["update_file_uploads"] = []
        response = self.client.patch(url, json.dumps(
            data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        bulletin_one.refresh_from_db()
        self.assertEqual(bulletin_one.title, data["title"])
        self.assertEqual(bulletin_one.content, data["content"])
        self.assertFalse(bulletin_one.file_uploads.exists())

    def test_delete(self):
        # Creator can delete, but not another user
        bulletin_one = Bulletin.objects.create(created_by=self.counselor.user,)
        bulletin_one.visible_to_notification_recipients.add(
            self.student.user.notification_recipient)
        url = reverse("bulletins-detail", kwargs={"pk": bulletin_one.pk})
        self.assertEqual(self.client.delete(url).status_code, 401)
        self.client.force_login(self.parent.user)
        self.assertEqual(self.client.delete(url).status_code, 403)

        self.client.force_login(self.counselor.user)
        self.assertEqual(self.client.delete(url).status_code, 204)
