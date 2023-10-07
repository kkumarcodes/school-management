from django.conf import settings
from django.db.models import Q
from rest_framework import permissions

from snusers.models import Administrator, Student, Tutor, Parent, Counselor


class MayReadOnly(permissions.BasePermission):
    """
    DRF permission class permitting only `GET`, `OPTIONS`, and `HEAD` requests.
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.method in permissions.SAFE_METHODS


class IsAdminOrPrompt(permissions.BasePermission):
    """DRF permission class that only permits admins or users whose username matches settings.PROMPT_USERNAME
    """

    message = "Admin or Partner API access required"

    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            hasattr(request.user, "administrator") or request.user.username == settings.PROMPT_USERNAME
        )


class IsOnCounselingPlatform(permissions.BasePermission):
    """DRF Permission class that only permits users who have access to counseling platform. That is: admins, counselors
        students on counseling platform and their parents
    """

    message = "UMS counseling access required"

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if hasattr(request.user, "counselor") or request.user.is_staff:
            return True

        return (
            Student.objects.filter(~Q(counseling_student_types_list=[]))
            .filter(Q(user=request.user) | Q(parent__user=request.user))
            .exists()
        )


class IsAdministratorPermission(permissions.BasePermission):
    """DRF permission class that only permits users w/associated cwuser.Administrator
    """

    message = "Admin permissions required"

    def has_permission(self, request, view):
        return request.user.is_authenticated and Administrator.objects.filter(user=request.user).exists()


class IsAdministratorOrSelfPermission(permissions.BasePermission):
    """DRF permission class that only permits administrators or users
        accessing their own profile
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if Administrator.objects.filter(user=request.user).exists():
            return True
        if not view.queryset:
            return False

        return (
            view.queryset.model in [Student, Tutor, Parent, Counselor]
            and view.queryset.filter(user=request.user).exists()
        )


class IsAdministratorOrSelfOrRelated(permissions.BasePermission):
    """DRF permission class that only permits administrators or users
        accessing their own profile AS WELL AS users who are related
        to the object attempting to be accessed.
        Logged in students can access their: Parents, Tutors, Counselor
        Logged in parents, tutors, and counselors can access their: Students, and all objects their students can access
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if Administrator.objects.filter(user=request.user).exists():
            return True
        if not view.queryset:
            return False

        return (
            view.queryset.model in [Student, Tutor, Parent, Counselor]
            and view.queryset.filter(user=request.user).exists()
        )
