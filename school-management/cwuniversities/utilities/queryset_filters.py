"""
Utilities for filtering queryset request results.
"""
from django.db.models import Q


def get_student_university_decisions(request, queryset):
    """
    Filter and return a queryset of StudentUniversityDecisions

    Filters by query_params and User types.
    Accepts these query parameters and values:
    - is_applying: 'YES', 'NO', 'MAYBE'
    - student: (a Student object pk)
    - counselor: (a Counselor object pk)
    """
    query = Q()

    # Filter by query_params
    query_params = request.query_params
    if query_params.get("is_applying"):
        query &= Q(is_applying=query_params["is_applying"].upper())

    if query_params.get("student"):
        query &= Q(student=query_params["student"])

    if query_params.get("counselor"):
        query &= Q(student__counselor=query_params["counselor"])

    # Filter by user type
    user = request.user
    if hasattr(user, "administrator"):
        return queryset.filter(query)

    if hasattr(user, "student"):
        query &= Q(student=user.student)
        return queryset.filter(query)

    if hasattr(user, "parent"):
        query &= Q(student__parent=user.parent)
        return queryset.filter(query)

    if hasattr(user, "counselor"):
        query &= Q(student__counselor=user.counselor)
        return queryset.filter(query)

    return queryset.none()
