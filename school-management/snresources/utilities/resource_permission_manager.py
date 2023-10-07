"""
    Module with utilities for getting resources that a user has access to, including
    checking to see if user has access to a specific resource
"""
from django.db.models import Q

from snusers.models import Student, Counselor, Tutor, Administrator, Parent, get_cw_user
from snresources.models import Resource, ResourceGroup
from sntutoring.models import TutoringSessionNotes, Diagnostic
from sntasks.models import Task


def get_resources_for_user(user, include_archived_resources=False):
    """ Returns the set of resources that user has access to. Includes:
        - Public resources and resources in public groups
        - Resources associated with tasks for user
        - Resources associated with diagnostic for task for user

        Parents get access to all resources that their students have access to.
        Tutors and Counselors get access to all resources their students have access to, and all
            stock resources.
        Administrators have access to all resources.

        Arguments:
            user {auth.models.User}
            include_archived_resources {Boolean} Whether or not to include resources that are archived.
                Defaults to False
            include_public {Boolean} Whether or not to include all public resources for all students

        Returns:
            QUERYSET of Resource objects
    """
    cwuser = get_cw_user(user)
    queryset = Resource.objects.none()
    if not cwuser:
        return queryset
    if isinstance(cwuser, Administrator):
        queryset = Resource.objects.all()
    elif isinstance(cwuser, Student):
        # Students have access to all of
        groups = list(ResourceGroup.objects.filter(visible_students=cwuser).values_list("pk", flat=True))
        tasks = list(Task.objects.filter(for_user=user).values_list("pk", flat=True))
        diagnostics = list(Diagnostic.objects.filter(tasks__in=tasks).values_list("pk", flat=True))
        notes = list(
            TutoringSessionNotes.objects.filter(student_tutoring_sessions__student=cwuser).values_list("pk", flat=True)
        )
        big_filter = Q(
            Q(visible_students=cwuser)
            | Q(tasks__in=tasks)
            | Q(diagnostics__in=diagnostics)
            | Q(tutoring_session_notes__in=notes)
            # In group that is not stock that student has access to
            | Q(resource_group__in=groups)
        )
        if cwuser.counseling_student_types_list:
            big_filter = big_filter | Q(resource_group__cap=True, created_by=None)

        queryset = Resource.objects.filter(big_filter).distinct()
    elif isinstance(cwuser, Parent):
        queryset = queryset.union(
            *[get_resources_for_user(student.user) for student in cwuser.students.all()]
        ).distinct()
    elif isinstance(cwuser, Tutor) or isinstance(cwuser, Counselor):
        # Stock + Resources cwuser created + resources available to all students
        stock_or_created = Resource.objects.filter(Q(is_stock=True) | Q(created_by=cwuser.user)).distinct()
        # Getting resources for all of their students is too much. Just return those that they created or are public
        # and we assume that they get resources for their student individually
        queryset = queryset.union(stock_or_created)

    if not include_archived_resources:
        return queryset.filter(archived=False).distinct()

    return queryset.distinct()
