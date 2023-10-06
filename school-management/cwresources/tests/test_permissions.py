""" Test cwresources.utilities
    python manage.py test cwresources.tests.test_permissions
"""
from django.test import TestCase
from django.utils import timezone
from django.shortcuts import reverse
from django.contrib.auth.models import User

from cwusers.models import Student, Counselor, Tutor, Administrator, Parent
from cwresources.models import Resource, ResourceGroup
from cwresources.utilities.resource_permission_manager import get_resources_for_user
from cwtutoring.models import Diagnostic, GroupTutoringSession, StudentTutoringSession
from cwtasks.models import Task


class TestResourcePermissionManager(TestCase):
    fixtures = ("fixture.json",)

    def setUp(self):
        self.student = Student.objects.first()
        self.parent = Parent.objects.first()
        self.counselor = Counselor.objects.first()
        self.tutor = Tutor.objects.first()
        self.admin = Administrator.objects.first()
        self.student.parent = self.parent
        self.student.save()

    def _confirm_access(self, resource, user, should_have_access):
        """ Utility method to confirm user does or does not have access to resource,
            including whether view to get resource returns resource or 403.
        """
        self.client.force_login(user)
        self.assertEqual(
            get_resources_for_user(user).filter(pk=resource.pk).exists(), should_have_access,
        )
        response = self.client.get(reverse("get_resource", kwargs={"resource_slug": str(resource.slug)}))
        self.assertEqual(response.status_code, 403 if not should_have_access else 302)
        self.client.logout()

    def test_student_gts_resource_access(self):
        """ Super targeted test to address a bug: When a student is registered for a GTS, they get access to that
            GTS's resources
        """
        pass
        # self.assertFalse(get_resources_for_user(self.student.user).exists())
        # gts_resource = Resource.objects.create(link="google.com", title="Test")
        # gts = GroupTutoringSession.objects.create(primary_tutor=self.tutor, start=timezone.now(), end=timezone.now())
        # gts.resources.add(gts_resource)
        # sts = StudentTutoringSession.objects.create(student=self.student, group_tutoring_session=gts)
        # self.assertEqual(get_resources_for_user(self.student.user).count(), 1)
        # self.assertEqual(get_resources_for_user(self.student.user).first(), gts_resource)

    def test_get_resources_for_user_success(self):
        """ Test successful instances of resource a user should have access to being
            in returned queryset of get_resources_for_user.
            ALSO TESTS GET RESOURCE VIEW
        """
        # Student visible resource
        resource_one = Resource.objects.create(link="google.com", title="Test")
        resource_one.visible_students.add(self.student)
        self._confirm_access(resource_one, self.student.user, True)
        self._confirm_access(resource_one, self.parent.user, True)

        # Student visible resource group
        resource_group = ResourceGroup.objects.create(title="TestGroup")
        resource_group.visible_students.add(self.student)
        resource = Resource.objects.create(link="google.com", title="Test", resource_group=resource_group)
        self._confirm_access(resource, self.student.user, True)
        self._confirm_access(resource, self.parent.user, True)

        # Student diagnostic resource
        diagnostic = Diagnostic.objects.create(title="diag")
        diag_resource = Resource.objects.create(link="google.com", title="Test")
        diagnostic.resources.add(diag_resource)
        Task.objects.create(for_user=self.student.user, diagnostic=diagnostic)
        self._confirm_access(resource, self.student.user, True)
        self._confirm_access(resource, self.parent.user, True)

        # Counselor access any resource they created
        # pylint: disable=expression-not-assigned
        resource_one.created_by = self.counselor.user
        resource_one.save()
        diag_resource.is_stock = True
        diag_resource.save()
        [self._confirm_access(resource_one, x.user, True) for x in (self.admin, self.counselor, self.tutor)]
        [self._confirm_access(diag_resource, x.user, True) for x in (self.admin, self.counselor, self.tutor)]

    def test_get_resources_for_user_failure(self):
        """ Test successful instances of resource a user should have access to NOT being
            in returned queryset of get_resources_for_user
            ALSO TESTS GET RESOURCE VIEW
        """
        # Student/Parent access non-public resource
        resource_one = Resource.objects.create(link="google.com", title="Test")
        # pylint: disable=expression-not-assigned
        [self._confirm_access(resource_one, x.user, False) for x in (self.student, self.parent)]

        # Student/Parent access resource visible to another student
        other_student = Student.objects.create(user=User.objects.create_user("otherstudent"))
        other_student.visible_resources.add(resource_one)
        # pylint: disable=expression-not-assigned
        [self._confirm_access(resource_one, x.user, False) for x in (self.student, self.parent)]
