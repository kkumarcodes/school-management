""" Views related to CounselingPromptAPIManager
"""
from rest_framework.views import APIView
from rest_framework.response import Response

from django.shortcuts import get_object_or_404
from cwusers.models import Student
from cwusers.mixins import AccessStudentPermission
from cwcounseling.utilities.counseling_prompt_api_manager import (
    CounselingPromptAPIManagerException,
    CounselingPromptAPIManager,
)
from cwtasks.serializers import TaskSerializer


class SyncPromptAssignmentsView(AccessStudentPermission, APIView):
    """ View to start assignment sync process with Prompt (updates tasks in UMS to match assignments and
        due dates in Prompt).
        Returns all essay tasks for student
    """

    def post(self, request, *args, **kwargs):
        student = get_object_or_404(Student, pk=kwargs.get("student"))
        if not self.has_access_to_student(student):
            self.permission_denied(request)

        mgr = CounselingPromptAPIManager()
        tasks = mgr.update_assignment_tasks(student)
        return Response(TaskSerializer(tasks, many=True).data)
