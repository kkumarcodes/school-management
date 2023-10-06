""" Manager for applying a roadmap to a specific student. Will generate each
task and meeting object for the student
"""
from typing import List
from django.utils import timezone
from django.db.models import Q
from cwcounseling.models import CounselorMeeting, CounselorMeetingTemplate, Roadmap
from cwcounseling.types import RoadmapMeeting
from cwcounseling.utilities.counselor_meeting_manager import CounselorMeetingManager
from cwtasks.models import TaskTemplate
from cwtasks.utilities.task_manager import TaskManager
from cwusers.models import Student


class RoadmapManagerException(Exception):
    pass


class RoadmapManager:
    """ Used for generating all Task and Meeting objects associated with a Roadmap """

    def __init__(self, roadmap):
        self.roadmap: Roadmap = roadmap

    def unapply_from_student(self, student: Student) -> Student:
        """ Remove a roadmap from a student. This process removes future and unscheduled meetings from roadmap,
            and deletes unsubmitted tasks from roadmap.
        """
        if not student.applied_roadmaps.filter(pk=self.roadmap.pk).exists():
            raise RoadmapManagerException(
                f"Trying to unapply roadmap {self.roadmap.pk} which has not been applied to student {student.pk}"
            )

        # Future meetings
        student.counselor_meetings.filter(counselor_meeting_template__roadmap=self.roadmap).filter(
            Q(end=None) | Q(end__gt=timezone.now())
        ).delete()

        # Unsubmitted tasks
        student.user.tasks.filter(completed=None).filter(
            Q(task_template__pre_agenda_item_templates__counselor_meeting_template__roadmap=self.roadmap)
            | Q(task_template__post_agenda_item_templates__counselor_meeting_template__roadmap=self.roadmap)
        ).delete()

        student.applied_roadmaps.remove(self.roadmap)
        return student

    def apply_to_student(self, student: Student, roadmap_meetings: List[RoadmapMeeting] = None) -> Student:
        """ Creates meetings and tasks for MeetingTemplates and TaskTemplates on self.roadmap.
            Return created meetings and tasks
        """
        meetings = []
        if roadmap_meetings is not None:
            meetings = [
                CounselorMeetingManager.create_meeting(
                    student,
                    counselor_meeting_template=roadmap_meeting["counselor_meeting_template"],
                    agenda_item_templates=roadmap_meeting["agenda_item_templates"],
                    custom_agenda_items=roadmap_meeting.get("custom_agenda_items", []),
                    title=roadmap_meeting.get("meeting_title", roadmap_meeting["counselor_meeting_template"].title),
                )
                for roadmap_meeting in roadmap_meetings
            ]

        else:
            meetings = [
                CounselorMeetingManager.create_meeting(student, counselor_meeting_template=template,)
                for template in self.roadmap.counselor_meeting_templates.all()
            ]

        # We have to create tasks for all task templates for agenda items on our new meetings.
        # Tasks get associated with the relevant meeting
        task_templates = (
            TaskTemplate.objects.filter(
                Q(pre_agenda_item_templates__agenda_items__counselor_meeting__in=meetings)
                | Q(post_agenda_item_templates__agenda_items__counselor_meeting__in=meetings),
            )
            .exclude(tasks__for_user__student=student)
            .distinct()
        )
        task_template_pks = list(task_templates.values_list("pk", flat=True))
        tasks = [TaskManager.create_task(student.user, task_template=x) for x in task_templates]
        for task in tasks:
            # Counselor may have moved agenda items between meetings, so we need to look at actual agenda items
            # on meetings
            task.counselor_meetings.set(
                list(
                    student.counselor_meetings.filter(
                        Q(
                            agenda_items__agenda_item_template__pre_meeting_task_templates__roadmap_key=task.task_template.roadmap_key
                        )
                        | Q(
                            agenda_items__agenda_item_template__post_meeting_task_templates__roadmap_key=task.task_template.roadmap_key
                        )
                    ).distinct()
                )
            )

        # Then we create tasks for all of the task templates NOT in included meetings. Students get tasks created
        # for all roadmap tasks (so that these tasks appear in task bank) even if they don't have all metings
        non_meeting_task_templates = (
            TaskTemplate.objects.filter(
                Q(pre_agenda_item_templates__counselor_meeting_template__roadmap=self.roadmap)
                | Q(post_agenda_item_templates__counselor_meeting_template__roadmap=self.roadmap)
            )
            .exclude(pk__in=task_template_pks)
            .distinct()
        )
        non_meeting_tasks = [TaskManager.create_task(student.user, task_template=x) for x in non_meeting_task_templates]
        for task in non_meeting_tasks:
            cmt = CounselorMeetingTemplate.objects.filter(
                Q(agenda_item_templates__pre_meeting_task_templates=task.task_template)
                | Q(agenda_item_templates__post_meeting_task_templates=task.task_template)
            ).first()
            task.counselor_meeting_template = cmt
            task.save()
        student.applied_roadmaps.add(self.roadmap)
        return {"meetings": meetings, "tasks": tasks + non_meeting_tasks}
