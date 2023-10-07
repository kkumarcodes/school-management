from typing import List
from django.shortcuts import get_object_or_404
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import MethodNotAllowed
from sncounseling.serializers.roadmap import RoadmapSerializer
from sncounseling.serializers.counselor_meeting import CounselorMeetingSerializer
from sncounseling.models import AgendaItemTemplate, CounselorMeetingTemplate, Roadmap
from sncounseling.utilities.roadmap_manager import RoadmapManager
from sncounseling.types import RoadmapMeeting
from snusers.models import Student
from sntasks.models import TaskTemplate
from snusers.serializers.users import StudentSerializerCounseling
from sntasks.serializers import TaskSerializer
from django.db.models.query_utils import Q

class RoadmapViewset(ModelViewSet):
    queryset = Roadmap.objects.all()
    serializer_class = RoadmapSerializer
    permission_classes = (IsAuthenticated,)

    def check_permissions(self, request):
        super().check_permissions(request)

        # Must be either Administrator or Counselor
        if not (hasattr(request.user, "administrator") or hasattr(request.user, "counselor")):
            self.permission_denied(request)

        if (
            request.method.lower() == "post"
            and not self.kwargs.get("pk")
            and not hasattr(request.user, "administrator")
        ):
            self.permission_denied(request)

    def destroy(self):
        raise MethodNotAllowed("delete")

    @action(detail=True, methods=["POST"], url_path="unapply-roadmap", url_name="unapply_roadmap")
    def unapply_roadmap(self, request, *args, **kwargs):
        """ See RoadmapManager.unapply_from_student
            Post data:
                student_id: number
        """
        roadmap = self.get_object()
        student = get_object_or_404(Student, pk=request.data.get("student_id"))
        roadmap_manager = RoadmapManager(roadmap)
        student = roadmap_manager.unapply_from_student(student)
        return Response(StudentSerializerCounseling(student).data)

    @action(detail=True, methods=["POST"], url_path="apply-roadmap", url_name="apply_roadmap")
    def apply_roadmap_to_student(self, request, *args, **kwargs):
        """
        Will apply a roadmap to a student by creating each Task and Meeting needed from all TaskTemplates and
        CounselorMeetingTemplates on the Roadmap.

        Body:
            student_id: number
            counselor_meetings: List of objects like this: {
                counselor_meeting_template: <CounselorMeetingTemplatePK> will create meeting for this template
                agenda_item_templates: <PK of AgendaItemTemplates> that should be created for meeting
                    NOTE THAT TASKS FOR ALL PRE MEETING TASKS FOR ALL TASK TEMPLATES WILL ALSO GET CREATED
                        and added to student's task "bank" (that is, tasks will have no due date)
            }

        Returns: {
            'meetings': All CounselorMeeting objects that were created for student
            'tasks': All new tasks created to satisfy agenda item requirements for created meetings
        }

        """
        roadmap = self.get_object()
        student = get_object_or_404(Student, pk=request.data.get("student_id"))
        # We need to convert our payload into a list of RoadmapMeeting objects, returning 404 for missing objects
        # along the way
        roadmap_meetings: List[RoadmapMeeting] = [
            {
                "counselor_meeting_template": get_object_or_404(
                    CounselorMeetingTemplate, pk=x.get("counselor_meeting_template")
                ),
                "agenda_item_templates": [
                    get_object_or_404(AgendaItemTemplate, pk=y) for y in x.get("agenda_item_templates")
                ],
            }
            for x in request.data.get("counselor_meetings", [])
        ]
        mgr = RoadmapManager(roadmap)

        result = mgr.apply_to_student(
            student, roadmap_meetings=roadmap_meetings if "counselor_meetings" in request.data else None
        )
        data = {
            "meetings": CounselorMeetingSerializer(result["meetings"], many=True).data,
            "tasks": TaskSerializer(result["tasks"], many=True, context={"request": self.request}).data,
        }
        return Response(data, status=201)
