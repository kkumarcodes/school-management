""" This script sets resources on newly created roadmap tasks by looking for task templates on other roadmaps
    with the same name that have resources
"""
from datetime import timedelta

# Set this variable to be all of the roadmaps we need to set resources on
roadmaps = Roadmap.objects.filter(created__gt=timezone.now() - timedelta(hours=2))
task_templates = TaskTemplate.objects.filter(
    Q(pre_agenda_item_templates__counselor_meeting_template__roadmap__in=roadmaps)
    | Q(post_agenda_item_templates__counselor_meeting_template__roadmap__in=roadmaps)
)

for tt in task_templates:
    existing_tt = TaskTemplate.objects.filter(
        created_by=None, title__icontains=tt.title, resources__isnull=False
    ).first()
    if existing_tt:
        tt.resources.set(list(existing_tt.resources.all()))
        print(tt, existing_tt, tt.resources.all())
