from django.shortcuts import get_object_or_404

from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from cwtutoring.serializers.diagnostics import TestResultSerializer
from cwtutoring.models import TestResult
from snusers.models import Administrator, Counselor, Student
from snusers.mixins import AccessStudentPermission


class TestResultViewset(ModelViewSet, AccessStudentPermission):
    serializer_class = TestResultSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        # Override queryset to only allow records for students that user has access to
        admin = Administrator.objects.filter(user=self.request.user).first()
        if admin:
            return TestResult.objects.all()
        counselor = Counselor.objects.filter(user=self.request.user).first()
        tutor = Counselor.objects.filter(user=self.request.user).first()
        # If counselor or tutor, we return test results for all of their students
        if counselor or tutor:
            kwargs = {}
            if counselor:
                kwargs["student__counselor"] = counselor
            if tutor:
                kwargs["student__tutors"] = tutor
            return TestResult.objects.filter(**kwargs)
        student = Student.objects.filter(user=self.request.user).first()
        if student:
            return student.test_results.all()
        return TestResult.objects.none()

    def check_object_permissions(self, request, obj):
        """ Ensure current user has access to TestResult """
        super(TestResultViewset, self).check_object_permissions(request, obj)
        if not self.has_access_to_student(obj.student, request=request):
            self.permission_denied(request)

    def check_permissions(self, request):
        """ Make sure that user has access to student when creating TestResult """
        super(TestResultViewset, self).check_permissions(request)

        if request.method.lower() == "post":
            student = get_object_or_404(Student, pk=request.data.get("student"))
            if not student and self.has_access_to_student(student, request=request):
                self.permission_denied(request)
