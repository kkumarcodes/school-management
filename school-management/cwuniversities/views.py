import os
import json
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.conf import settings

from cwuniversities.utilities.queryset_filters import get_student_university_decisions

from snusers.models import Student
from snusers.mixins import UserPermissionsHelpers
from snusers.permissions import (
    IsAdministratorPermission,
    MayReadOnly,
    IsOnCounselingPlatform,
)

from .models import Deadline, StudentUniversityDecision, University, UniversityList
from .serializers import (
    DeadlineSerializer,
    StudentUniversityDecisionSerializer,
    UniversitySerializer,
    UniversityListSerializer,
)

# Where JSON files that contain CW-specific uni data live
CW_UNI_DATA_PATH = os.path.join(settings.BASE_DIR, "cwuniversities", "data", "by_school")


class DeadlineViewset(ModelViewSet):
    """
    Basic CRUD operations for `Deadline` objects.

    Admin users can CRUD. Other authenticated user types can only Read.

    Fields required to create:
        - university (pk) : The University this deadline applies to
        - category (pk) : The DeadlineCategory (e.g., Admissions, Financial)
        - type_of (pk) : The DeadlineType (e.g., Early Decision)
    """

    permission_classes = [IsAdministratorPermission | MayReadOnly]
    queryset = Deadline.objects.all()
    serializer_class = DeadlineSerializer

    def filter_queryset(self, queryset):
        """ Can filter on the following args
            student (gets all deadlines for SUD for student)
            counselor (gets all deadlines for all SUC for all of counselor's students)
            university (gets all deadlines for a university)
        """
        query_params = self.request.query_params
        if query_params.get("student"):
            return queryset.filter(university__student_university_decisions__student__pk=query_params["student"])
        if query_params.get("counselor"):
            return queryset.filter(
                university__student_university_decisions__student__counselor__pk=query_params["counselor"]
            )
        if query_params.get("university"):
            return queryset.filter(university__pk=query_params["university"])
        return queryset


class StudentUniversityDecisionViewset(ModelViewSet, UserPermissionsHelpers):
    """
    CRUD operations for `StudentUniversityDecision` objects.
        - Admins, Students, and Parents can CRUD.
        - Counselors can read.

    Fields required to create:
        - student (pk) : Student making this decision
        - university (pk) : University this decision regards
        - deadline (pk) : Deadline this decision must be finalized by
    """

    permission_classes = [IsAuthenticated]
    queryset = StudentUniversityDecision.objects.all()
    serializer_class = StudentUniversityDecisionSerializer

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method.upper() == "POST":
            student = get_object_or_404(Student, pk=request.data["student"])
            if not (
                self.user_is_admin(request.user)
                | self.user_is_object_owner(request.user, student.user.pk)
                | self.user_is_parent_of_student(request.user, student.user.pk)
                | self.user_is_counselor_of_student(request.user, student.user.pk)
            ):
                self.permission_denied(request, message="Permission denied for this User type")

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if not (
            self.user_is_admin(request.user)
            | self.user_is_object_owner(request.user, obj.student.user.pk)
            | self.user_is_parent_of_student(request.user, obj.student.user.pk)
            | self.user_is_counselor_of_student(request.user, obj.student.user.pk)
        ):
            self.permission_denied(request, message="Permission denied for this User type")

    def filter_queryset(self, queryset):
        return get_student_university_decisions(self.request, queryset)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if hasattr(self.request.user, "administrator"):
            context["admin"] = self.request.user.administrator
        if hasattr(self.request.user, "counselor"):
            context["counselor"] = self.request.user.counselor
        return context


class UniversityViewset(ModelViewSet):
    """
    Basic CRUD operations for `University` objects.

    Admin users can Create, Update, and Delete. Other authenticated user types
    can only Read.

    Fields required to create:
        - name (str) : Short name of the University
        - long_name (str) : Long name of the University

    # TODO: Create separate list and detail serializers here
    """

    permission_classes = [IsAdministratorPermission | MayReadOnly]
    serializer_class = UniversitySerializer

    @action(detail=True, methods=["GET"], url_path="applying-students", url_name="applying_students")
    def retrieve__applying_students(self, request, *args, **kwargs):
        """ Retrieve a list of the PKs of students applying to specified university. What's returned is an object
                where keys are is_applying statuses, and the value is a list of PKs of students with this
                university in that applying status on their student list
            If counselor is getting this endpoint, we only return their students
            If admin is getting this endpoint, we return all students
            If someone else is hitting this endpoint, they get a 403. Like really?
        """
        uni = self.get_object()
        user = self.request.user
        if not user.is_authenticated or not (hasattr(user, "administrator") or hasattr(user, "counselor")):
            self.permission_denied(request)

        potential_students = Student.objects.all()
        if hasattr(user, "counselor"):
            potential_students = potential_students.filter(counselor=user.counselor)
        return_data = {}
        for is_applying in StudentUniversityDecision.IS_APPLYING_CHOICES:
            return_data[is_applying[0]] = list(
                potential_students.filter(
                    student_university_decisions__university=uni,
                    student_university_decisions__is_applying=is_applying[0],
                ).values_list("pk", flat=True)
            )
        return Response(return_data)

    def get_queryset(self):
        universities_with_student_decisions = University.objects.filter(
            active=True, student_university_decisions__isnull=False
        )
        universities_within_rank_limit = University.objects.filter(active=True, rank__lt=800)
        pks = list(universities_with_student_decisions.values_list('pk', flat=True)) + list(universities_within_rank_limit.values_list('pk', flat=True))
        queryset = University.objects.filter(pk__in=pks).distinct()
        return queryset


class CWUniversityDataView(RetrieveAPIView):
    """ This view returns CW-specific data for a university, to be used on school profile pages with UMS.
        Returns 404 if we don't have data for school (which is the case for most schools, because most schools
        don't have Collegewise students)

        For an example of return value, see any of the files in cwuniversities/data/byschool (file name are iped)
    """

    permission_classes = (IsOnCounselingPlatform,)
    queryset = University.objects.all()

    def retrieve(self, request, *args, **kwargs):
        """ Look ma! No serializer! """
        university: University = self.get_object()
        file_path = os.path.join(CW_UNI_DATA_PATH, f"{university.iped}.json")
        if not os.path.exists(file_path):
            return Response(status=status.HTTP_404_NOT_FOUND)
        with open(file_path) as f:
            data = json.loads(f.read())
        return Response(data)


class UniversityListViewset(ModelViewSet, UserPermissionsHelpers):
    """
    CRUD operations for `UniversityList` objects.
    - Lists can be created by Students, Parents, and Counselors.
    - Lists can be "owned" (and therefore modified) by Students and Counselors.
    - Parents have shadow ownership over their Students' lists.
    - Counselors can "assign" a list to multiple Students.

    Fields required to create:
        - name (str) : Short name of the list
        - owned_by (pk) : User id of the user who "owns" this list
    """

    permission_classes = [IsAuthenticated]
    queryset = UniversityList.objects.all()
    serializer_class = UniversityListSerializer

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method.upper() == "POST" and not (
            self.user_is_admin(request.user)
            | self.user_is_object_owner(request.user, request.data["owned_by"])
            | self.user_is_parent_of_student(request.user, request.data["owned_by"])
        ):
            self.permission_denied(request, message="Permission denied for this User type")

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if not (
            self.user_is_admin(request.user)
            | self.user_is_object_owner(request.user, obj.owned_by.pk)
            | self.user_is_parent_of_student(request.user, obj.owned_by.pk)
            | (self.user_is_counselor_of_student(request.user, obj.owned_by.pk) and request.method.upper() == "GET")
        ):
            self.permission_denied(request, message="Permission denied for this User type")

    def filter_queryset(self, queryset):
        user = self.request.user
        if hasattr(user, "administrator"):
            return queryset

        if hasattr(user, "student"):
            query = Q(owned_by=user)
            query |= Q(assigned_to=user)
            return queryset.filter(query)

        if hasattr(user, "parent"):
            query = Q(owned_by__student__parent=user.parent)
            return queryset.filter(query)

        if hasattr(user, "counselor"):
            query = Q(owned_by=user)
            query |= Q(owned_by__student__counselor=user.counselor)
            return queryset.filter(query)

        return queryset.filter(owned_by=user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
