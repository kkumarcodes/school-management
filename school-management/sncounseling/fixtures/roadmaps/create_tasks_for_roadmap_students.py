from datetime import timedelta
from sntasks.utilities.task_manager import TaskManager

# tt = TaskTemplate.objects.filter(title__icontains="Watch Finalizing Your List: Part I")
roadmaps = Roadmap.objects.filter(
    Q(counselor_meeting_templates__agenda_item_templates__pre_meeting_task_templates__in=tt)
    | Q(counselor_meeting_templates__agenda_item_templates__post_meeting_task_templates__in=tt)
).distinct()

# new_templates = (
#     TaskTemplate.objects.filter(created__gt=timezone.now() - timedelta(minutes=100))
#     .filter(
#         Q(pre_agenda_item_templates__counselor_meeting_template__roadmap__in=roadmaps)
#         | Q(post_agenda_item_templates__counselor_meeting_template__roadmap__in=roadmaps)
#     )
#     .distinct()
# )

students = Student.objects.filter(applied_roadmaps__in=roadmaps)
for student in students:
    student_templates = tt.filter(
        Q(pre_agenda_item_templates__counselor_meeting_template__roadmap__in=student.applied_roadmaps.all())
        | Q(post_agenda_item_templates__counselor_meeting_template__roadmap__in=student.applied_roadmaps.all())
    )
    for template in student_templates:
        if not student.user.tasks.filter(task_template=template).exists():
            task = TaskManager.create_task(student.user, task_template=template)
            # Associate task with meetings
            task.counselor_meetings.set(
                list(
                    student.counselor_meetings.filter(
                        Q(agenda_items__agenda_item_template__pre_meeting_task_templates=template)
                        | Q(agenda_items__agenda_item_template__post_meeting_task_templates=template)
                    )
                )
            )
            print(task)
