""" This script creates unscheduled CounselorMeetings for students that have a roadmap applied
"""

from datetime import timedelta
from cwcounseling.utilities.counselor_meeting_manager import CounselorMeetingManager

roadmaps = Roadmap.objects.filter(title__icontains="Premier 11th - 2nd Semester")
counselor_meeting_templates = CounselorMeetingTemplate.objects.filter(
    roadmap__in=roadmaps,
    # Filter appropriately here!!
    title__icontains="Activity Assessment & Planning",
)

students = Student.objects.filter(applied_roadmaps__in=roadmaps)
for student in students:
    meeting_template = counselor_meeting_templates.filter(roadmap__students=student).first()
    if not student.counselor_meetings.filter(counselor_meeting_template=meeting_template).exists():
        print(CounselorMeetingManager.create_meeting(student, counselor_meeting_template=meeting_template))


# Update those meetings' tasks
meetings = CounselorMeeting.objects.filter(
    counselor_meeting_template__in=counselor_meeting_templates,
    student__in=students,
    created__gt=timezone.now() - timedelta(hours=1),
)
# Associate existing tasks with meetings
for meeting in meetings:
    tasks = meeting.student.user.tasks.filter(
        Q(task_template__pre_agenda_item_templates__counselor_meeting_template=meeting.counselor_meeting_template)
        | Q(task_template__post_agenda_item_templates__counselor_meeting_template=meeting.counselor_meeting_template)
    )
    print(meeting, tasks.count())
    for task in tasks:
        task.counselor_meetings.add(meeting)
