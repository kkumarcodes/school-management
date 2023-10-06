""" Use this script to import agenda items and tasks
    (specifically: agenda item templates and task templates), and associate them with meeting tempalates
    (which will also be created if they don't yet exist)
"""
import os
import csv
from django.conf import settings

from cwcounseling.models import AgendaItemTemplate, CounselorMeetingTemplate, Roadmap
from cwtasks.models import Form, TaskTemplate

""" COLUMNS:
- Meeting Name
- Meeting Key
- Meeting Counselor Instructions
- Dont Create With Roadmap
- Grade
- Semester
- Agenda Item Key
- Agenda Item Title
- Agenda Item Counselor Instructions
- Task Key pre/post
- Task Type
- Task Name
- Task Description
- Task User Type student/parent
- Form
"""

REPEAT_TASKS = [
    "Fill in Activity section in UMS",
    "Research and review summer ideas and programs assigned.",
    "Fill out any summer program applications",
    "Watch How to write an application essay (if essays required)",
    "Complete first essay draft for summer program application",
    "Read Testing FAQ",
    "Research suggested college list",
    "Fill in your Common Applications",
    "Ask your recommenders for letters",
    "Create and fill out Coalition App",
    "Create and fill out UC Application",
    "Create and fill out Apply Texas",
    "Create and fill out Cal State",
    "Create and fill out the school-specific application for the school listed",
    "Work on assigned applications",
    "Write the first draft of each essay",
    "Send transcripts for the schools listed",
    "Send the test scores listed to the schools listed",
    "Confirm letters of recommendation have been sent to all schools",
    "Send thank you notes to your recommenders once the letters are sent",
    "Submit application for the school listed!",
]

# Meetings that have this in their title do not get created when applying roadmap


def set_parent_tasks(roadmap_file, roadmap_name):
    """ Helper method that reads through a parsed roadmap to set tasks that should
        be parent tasks (Tasks for counseling parent)
    """
    roadmap, _ = Roadmap.objects.get_or_create(title=roadmap_name)
    # roadmap.counselor_meeting_templates.all().update(roadmap=None)  # They'll get recreated if they should still exist
    path = f"{settings.BASE_DIR}/cwcounseling/fixtures/roadmaps/2_21/parsed/{roadmap_file}_parsed.csv"
    if not os.path.exists(path):
        raise ValueError(f"No such file {roadmap_file}")
    with open(path) as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            task_key = row.get("Task Key")
            task_template: TaskTemplate = TaskTemplate.objects.filter(key=task_key).first()
            if task_template and row["Task User Type"] == "parent":
                task_template.counseling_parent_task = True
                task_template.save()
                print(task_template)


def import_roadmap_using_reference(
    roadmap_file, roadmap_name, reference_roadmap: Roadmap, missing_task_templates: list
):
    """ Helper method that imports a new roadmap but uses an existing roadmap as a reference for tasks.
        No new task templates are created; existed task templates are searched for on reference roadmap
        (by title).
    """
    roadmap, _ = Roadmap.objects.get_or_create(title=roadmap_name)
    # roadmap.counselor_meeting_templates.all().update(roadmap=None)  # They'll get recreated if they should still exist
    path = f"{settings.BASE_DIR}/cwcounseling/fixtures/roadmaps/7_21/parsed/{roadmap_file}_parsed.csv"
    if not os.path.exists(path):
        raise ValueError(f"No such file {roadmap_file}")

    missing_task_templates = []
    reference_task_templates = TaskTemplate.objects.filter(
        Q(pre_agenda_item_templates__counselor_meeting_template__roadmap=reference_roadmap)
        | Q(post_agenda_item_templates__counselor_meeting_template__roadmap=reference_roadmap)
    )
    with open(path) as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            meeting_key = row.get("Meeting Key")
            # Each row is a task, and we create the associated agenda item/meeting if they don't exist
            (meeting, created) = CounselorMeetingTemplate.objects.get_or_create(
                title=row.get("Meeting Name"), roadmap=roadmap
            )
            meeting.grade = row.get("Grade", meeting.grade) or None
            meeting.semester = row.get("Semester", meeting.semester) or None
            meeting.description = row.get("Meeting Description") or meeting.description
            meeting.counselor_instructions = row["Meeting Counselor Instructions"] or meeting.counselor_instructions
            meeting.key = meeting_key
            meeting.order = idx
            meeting.create_when_applying_roadmap = not row.get("Dont Create With Roadmap")
            meeting.save()

            ai_key = row.get("Agenda Item Key")
            agenda_item_template, created = AgendaItemTemplate.objects.get_or_create(
                counselor_meeting_template=meeting, key=ai_key
            )
            agenda_item_template.order = idx
            agenda_item_template.counselor_instructions = (
                row["Agenda Item Counselor Instructions"] or agenda_item_template.counselor_instructions
            )
            if created:
                agenda_item_template.student_title = agenda_item_template.counselor_title = row.get("Agenda Item Title")
            agenda_item_template.save()

            if row.get("Task Name"):
                existing_task_template = reference_task_templates.filter(title__iexact=row["Task Name"]).first()
                if existing_task_template:
                    print("Found existing task template", existing_task_template, existing_task_template.pk)
                    if existing_task_template.post_agenda_item_templates.all().exists():
                        agenda_item_template.post_meeting_task_templates.add(existing_task_template)
                    else:
                        agenda_item_template.pre_meeting_task_templates.add(existing_task_template)
                else:
                    missing_task_templates.append(row["Task Name"])


def import_roadmap(roadmap_file, roadmap_name):
    """ Helper method, that can be used in the shell or in tests, to create roadmap with associated meetings,
        agenda items, and tasks
    """
    roadmap, _ = Roadmap.objects.get_or_create(title=roadmap_name)
    # roadmap.counselor_meeting_templates.all().update(roadmap=None)  # They'll get recreated if they should still exist
    path = f"{settings.BASE_DIR}/cwcounseling/fixtures/roadmaps/2_21/parsed/{roadmap_file}_parsed.csv"
    if not os.path.exists(path):
        raise ValueError(f"No such file {roadmap_file}")
    with open(path) as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            meeting_key = row.get("Meeting Key")
            # Each row is a task, and we create the associated agenda item/meeting if they don't exist
            (meeting, created) = CounselorMeetingTemplate.objects.get_or_create(
                title=row.get("Meeting Name"), roadmap=roadmap
            )
            meeting.grade = row.get("Grade", meeting.grade) or None
            meeting.semester = row.get("Semester", meeting.semester) or None
            meeting.description = row.get("Meeting Description") or meeting.description
            meeting.counselor_instructions = row["Meeting Counselor Instructions"] or meeting.counselor_instructions
            meeting.key = meeting_key
            meeting.order = idx
            meeting.create_when_applying_roadmap = not row.get("Dont Create With Roadmap")
            meeting.save()

            ai_key = row.get("Agenda Item Key")
            agenda_item_template, created = AgendaItemTemplate.objects.get_or_create(
                counselor_meeting_template=meeting, key=ai_key
            )
            agenda_item_template.order = idx
            agenda_item_template.counselor_instructions = (
                row["Agenda Item Counselor Instructions"] or agenda_item_template.counselor_instructions
            )
            if created:
                agenda_item_template.student_title = agenda_item_template.counselor_title = row.get("Agenda Item Title")
            agenda_item_template.save()

            # Task template
            task_template = ""
            if row.get("Task Key"):
                # task_template = (
                #     TaskTemplate.objects.filter(title=row.get("Task Name"),)
                #     .filter(
                #         Q(pre_agenda_item_templates__counselor_meeting_template__roadmap=roadmap)
                #         | Q(post_agenda_item_templates__counselor_meeting_template__roadmap=roadmap)
                #     )
                #     .first()
                # )
                task_template = None
                if not task_template:
                    task_template, created = TaskTemplate.objects.get_or_create(roadmap_key=row.get("Task Key"))
                if not task_template.roadmap:
                    task_template.roadmap = roadmap
                if not task_template.title:
                    task_template.title = row.get("Task Name")
                if created:
                    task_template.description = row.get("Task Description")
                task_template.include_school_sud_values = task_template.on_complete_sud_update = {}
                if row.get("Include School Tracker Field") and row.get("Include School Tracker Value"):
                    task_template.include_school_sud_values = {
                        row.get("Include School Tracker Field"): row.get("Include School Tracker Value")
                    }
                if row.get("Complete Tracker Field") and row.get("Complete Tracker Value"):
                    task_template.on_complete_sud_update = {
                        row.get("Complete Tracker Field"): row.get("Complete Tracker Value")
                    }
                if row.get("Form") and Form.objects.filter(title=row.get("Form")).exists():
                    task_template.form = Form.objects.get(title=row.get("Form"))
                else:
                    task_template.allow_content_submission = task_template.allow_file_submission = True
                task_template.save()
                if row.get("Task Type", "pre") == "post":
                    agenda_item_template.post_meeting_task_templates.add(task_template)
                else:
                    agenda_item_template.pre_meeting_task_templates.add(task_template)

            if not settings.TESTING:
                print(task_template, "CREATED" if created else "")
    return roadmap


COMPREHENSIVE = {
    "comprehensive_8": "Comprehensive (Pre-9th)",
    "comprehensive_9_1": "Comprehensive 9th - 1st Semester",
    "comprehensive_9_2": "Comprehensive 9th - 2nd Semester",
    "comprehensive_10_1": "Comprehensive 10th - 1st Semester",
    "comprehensive_10_2": "Comprehensive 10th - 2nd Semester",
    "comprehensive_11_1": "Comprehensive 11th - 1st Semester",
    "comprehensive_11_2": "Comprehensive 11th - 2nd Semester",
}
PREMIER = {
    "premier_8": "Premier (Pre-9th)",
    "premier_9_1": "Premier 9th - 1st Semester",
    "premier_9_2": "Premier 9th - 2nd Semester",
    "premier_10_1": "Premier 10th - 1st Semester",
    "premier_10_2": "Premier 10th - 2nd Semester",
    "premier_11_1": "Premier 11th - 1st Semester",
    "premier_11_2": "Premier 11th - 2nd Semester",
}

MARCH_2_IMPORT = {
    "transfer": "Transfer",
    "uc_essay": "UC Essay",
    "essay": "Essay",
    "paygo": "Paygo",
    "single_school_supplement": "Single School Supplement",
}


# def do_initial_import():
if not settings.TESTING:
    # import_roadmap("premier_11_1", "Premier 11th - 1st Semester")
    if input("Delete existing content y/N") == "y" and input("Are you sure? y/N") == "y":
        print(Roadmap.objects.all().delete())
        print(TaskTemplate.objects.all().delete())
        print(CounselorMeetingTemplate.objects.all().delete())
        print(AgendaItemTemplate.objects.all().delete())

    for (filename, title) in list(COMPREHENSIVE.items()) + list(PREMIER.items()):
        import_roadmap(filename, title)
        # set_parent_tasks(filename, title)

    # Summer program stands alone
    # set_parent_tasks("summer_program", "Summer Program")

    """ Below are updates we do afer roadmaps are imported """
    # print("Setting Repeat Tasks")
    # repeat_tasks = TaskTemplate.objects.filter(title__in=REPEAT_TASKS)
    # print(repeat_tasks.update(repeatable=True))

PARENT_ROADMAP_TASKS = [
    "Complete Intake Questionnaire (parents)",
    "Watch Welcome to Collegewise (parent)",
    "Fill out College Questionnaire",
    "Review our Letter to Parents on the essay process",
    "Optional - Listen to Get Wise Podcast. Episode 1 & 2",
    "Read Making Caring Common",
    "Listen to Get Wise Podcast. Episode 3",
    "Listen to Get Wise Podcast. Episode 4",
    "Watch The College Planning Opportunity Many Juniors Miss",
    "Listen to Get Wise Podcast. Episode 5",
    "Listen to Get Wise Podcast. Episode 6",
    "Listen to Get Wise Podcast. Episode 7",
    "Listen to Get Wise Podcast. Episode 8",
]
for title in PARENT_ROADMAP_TASKS:
    print(title, TaskTemplate.objects.filter(title__icontains=title).update(counseling_parent_task=True))


# Import just our comp late start roadmap
# reference = Roadmap.objects.get(title__icontains="Comprehensive 9th - 1")
# missing_task_templates = []
# import_roadmap_using_reference(
#     "comprehensive_late_start", "Comprehensive Late Start", reference, missing_task_templates
# )
# print("Missing Task Templates")
# print(missing_task_templates)
