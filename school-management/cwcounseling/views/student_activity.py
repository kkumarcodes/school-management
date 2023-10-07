from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from cwcounseling.serializers.student_activity import StudentActivitySerializer
from cwcounseling.models import StudentActivity
from snusers.models import Student, Counselor, Parent, Administrator
from snusers.mixins import AccessStudentPermission
from django.shortcuts import get_object_or_404


class StudentActivityViewset(ModelViewSet, AccessStudentPermission):
    """ Tutors have no access.
        For all queries: query_param: `?student_pk`
        Actions supported:
        GET:  any non-tutor with access to student.
              retrieves full list of a student's activities
        DELETE: any non-tutor with access to student. pk of activity to delete in url
                deletes single activity
        POST: any non-tutor with access to student.
        PUT/PATCH: any non-tutor with access to student.
                   pk of activity in url, update data in body
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = StudentActivitySerializer

    def check_permissions(self, request):
        """ Tutors do not have access to StudentActivities
                Parents/Counselors can only act on behalf of their student(s)
                Admins have access to everything
            """

        super(StudentActivityViewset, self).check_permissions(request)
        if hasattr(request.user, "tutor"):
            self.permission_denied(request)
        # if identifying info about student is provided, check permissions for
        # access to that student from requesting user. (otherwise filtering will
        # take place in get_queryset)
        student = None
        if request.query_params.get("student_pk"):
            student = Student.objects.get(pk=request.query_params.get("student_pk"))
        if self.kwargs.get("pk"):
            student = StudentActivity.objects.get(pk=self.kwargs["pk"]).student
        if request.data.get("student"):
            student = Student.objects.get(pk=request.data.get("student"))
        if student:
            if not self.has_access_to_student(student):
                self.permission_denied(request, message="No access to student")

    def check_object_permissions(self, request, obj: StudentActivity):
        super().check_object_permissions(request, obj)
        if not self.has_access_to_student(obj.student):
            self.permission_denied(request)

    def get_queryset(self):
        """ Returns activities
        """
        if self.request.query_params.get("student_pk"):
            pk = self.request.query_params["student_pk"]
            return StudentActivity.objects.filter(student=pk)
        elif hasattr(self.request.user, "student"):
            return StudentActivity.objects.filter(student=self.request.user.student)
        elif hasattr(self.request.user, "administrator"):
            return StudentActivity.objects.all()
        elif hasattr(self.request.user, "counselor"):
            return StudentActivity.objects.filter(student__counselor__user=self.request.user)
        elif hasattr(self.request.user, "parent"):
            return StudentActivity.objects.filter(student__parent__user=self.request.user)
        else:
            self.permission_denied(self.request, message="No access to student")

    def create(self, request, *args, **kwargs):
        student = request.data.get("student")
        student_activity_with_greatest_order: StudentActivity = StudentActivity.objects.filter(student=student).order_by('-order').first()
        # Set new student activity order to next highest order, or 0 if no student activity exist
        request.data["order"] = student_activity_with_greatest_order.order + 1 if student_activity_with_greatest_order else 0
        return super(StudentActivityViewset, self).create(request, *args, **kwargs)
