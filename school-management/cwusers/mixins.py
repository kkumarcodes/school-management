"""
    View Mixins related to users and authentication
"""
from django.db.models import Q

from snusers.models import Parent, Student


class AccessStudentPermission:
    """ Mixin that adds has_access_to_student(student) method """

    def has_access_to_student(self, student, request=None):
        request = request or self.request
        if not (request.user and request.user.is_authenticated):
            return None

        if hasattr(request.user, "administrator"):
            return True
        return (
            Student.objects.filter(pk=student.pk)
            .filter(
                Q(
                    Q(user=request.user)
                    | Q(counselor__user=request.user)
                    | Q(tutors__user=request.user)
                    | Q(parent__user=request.user)
                )
            )
            .exists()
        )

    def has_access_to_parent(self, parent: Parent, request=None):
        request = request or self.request
        if not (request.user and request.user.is_authenticated):
            return None

        if hasattr(request.user, "administrator"):
            return True
        return any([self.has_access_to_student(x) for x in parent.students.all()])


class UserPermissionsHelpers:
    """
    Helper functions to granularly, succinctly, and consistently determine user
    permissions.
    """

    def user_is_admin(self, user):
        """
        This user in an Administrator
        """
        return hasattr(user, "administrator")

    def user_is_object_owner(self, user, owner_pk):
        """
        This user is the "owner" of a given object.

        "Ownership" is a fuzzy concept, determined on an ad hoc basis by
        different fields on different models (or JSON objects). This
        function mainly exists to provide a clarifying name to a fuzzy concept.
        """
        return user.id == owner_pk

    def user_is_parent_of_student(self, user, owner_pk):
        """
        This user is the Parent of an object's Student "owner".
        """
        return hasattr(user, "parent") and user.parent.students.filter(user_id=owner_pk).exists()

    def user_is_counselor_of_student(self, user, owner_pk):
        """
        This user is the Counselor of an object's Student "owner".
        """
        return hasattr(user, "counselor") and user.counselor.students.filter(user_id=owner_pk).exists()
