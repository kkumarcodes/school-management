""" Use this script to parse a roadmap as SN gives it to us. Namely we break tasks into separate rows
    (specifically: agenda item templates and task templates), and associate them with meeting tempalates
    (which will also be created if they don't yet exist)
"""
import os
import csv
import re
import inflection
from django.conf import settings

from sncounseling.models import AgendaItemTemplate, CounselorMeetingTemplate, Roadmap
from sntasks.models import Form, TaskTemplate

COUNSELOR_MEETING_INSTRUCTIONS = {
    "Time Management & Organizationl Habits (To be held with a CAS team member if desired and needed)": {
        "Title": "Time Management & Organizationl Habits",
        "Instructions": "(To be held with a CAS team member if desired and needed)",
        "dont_create_with_roadmap": 1,
    },
    "Testing (To be held with CAS team member and counselor)": {
        "Title": "Testing",
        "Instructions": "(To be held with CAS team member and counselor)",
        "dont_create_with_roadmap": "",
    },
    "Summer Discussion & Applications (if needed)": {
        "Title": "Summer Discussion & Applications",
        "Instructions": "(if needed)",
        "dont_create_with_roadmap": 1,
    },
    "Check- in Meeting (ad hoc)": {
        "Title": "Check-in Meeting",
        "Instructions": "(ad hoc)",
        "dont_create_with_roadmap": 1,
    },
    "Check- n Meeting (ad hoc)": {
        "Title": "Check-in Meeting",
        "Instructions": "(ad hoc)",
        "dont_create_with_roadmap": 1,
    },
    "Senior Season Check-in Meetings (ad hoc)": {
        "Title": "Senior Season Check-in Meeting",
        "Instructions": "(ad hoc)",
        "dont_create_with_roadmap": 1,
    },
    "Post-Application Check-in Meeting (ad hoc)": {
        "Title": "Post-Application Check-in Meeting",
        "Instructions": "(ad hoc)",
        "dont_create_with_roadmap": 1,
    },
}

""" READ Columns:
- Title
- Prep Homework
- Agenda Item Title
- Agenda Item Details -> Agenda Item Counselor Instructions
- To Do Item
- Roadmap One-Line Description
- Content
- Year/Semester
"""

""" WRITE COLUMNS:
- Meeting Name
- Meeting Key
- Agenda Item Key
- Agenda Item Title
- Task Key pre/post
- Task Type
- Task Name
- Task Description
- Task User Type student/parent
- Form
- Content
- Grade
- Semester
"""

WRITE_ROWS = [
    "Meeting Name",
    "Meeting Key",
    "Meeting Description",
    "Grade",
    "Semester",
    "Agenda Item Key",
    "Agenda Item Title",
    "Dont Create With Roadmap",
    "Agenda Item Counselor Instructions",
    "Meeting Counselor Instructions",
    "Task Key",
    "Task Name",
    "Task Description",
    "Task Type",
    "Task User Type",
    "Form",
    "Repeats",
    "Content",
]


all_content = []

"""Helper function that returns the write data for a task"""


def get_task_data(task_name, roadmap_file, task_type, user_type=""):
    if not user_type:
        user_type = "parent" if "FOR PARENTS: " in task_name else "student"
    if "FOR PARENTS: " in task_name:
        task_name = task_name.split("FOR PARENTS: ")[1]

    form = ""
    if user_type == "parent" and "Intake Questionnaire" in task_name:
        form = "Parent Intake Questionnaire"
    elif "Complete Getting to Know You" in task_name:
        form = "Getting To Know You!"
    elif user_type == "parent" and "College Questionnaire" in task_name:
        form = "Parent College Search Questionnaire"
    return {
        "Task Key": inflection.dasherize(f"{roadmap_file} {task_name}"),
        "Task Name": task_name,
        "Task Type": task_type,
        "Task Description": "",
        "Task User Type": user_type,
        "Form": form,
    }


def parse_roadmap(roadmap_file, all_content):
    path = f"{settings.BASE_DIR}/sncounseling/fixtures/roadmaps/7_21/{roadmap_file}.csv"
    write_path = f"{settings.BASE_DIR}/sncounseling/fixtures/roadmaps/7_21/parsed/{roadmap_file}_parsed.csv"
    if not os.path.exists(path):
        raise ValueError(f"No such file {roadmap_file}")
    meeting_title = ""
    year_semester = year = semester = ""
    dont_create_with_roadmap = ""
    meeting_instructions = ""
    with open(path) as f, open(write_path, "w+") as w:
        reader = csv.DictReader(f)
        writer = csv.DictWriter(w, WRITE_ROWS)
        writer.writeheader()
        for row in reader:
            if not row.get("Agenda Item Title"):
                continue
            meeting_title = row.get("Title") or meeting_title
            meeting_title = meeting_title.strip(" \t\n\r")
            if meeting_title in COUNSELOR_MEETING_INSTRUCTIONS:
                meeting_title_to_use = COUNSELOR_MEETING_INSTRUCTIONS[meeting_title]["Title"]
                meeting_instructions = COUNSELOR_MEETING_INSTRUCTIONS[meeting_title]["Instructions"]
                dont_create_with_roadmap = COUNSELOR_MEETING_INSTRUCTIONS[meeting_title]["dont_create_with_roadmap"]
            else:
                meeting_title_to_use = meeting_title
                meeting_instructions = ""
                dont_create_with_roadmap = ""

            agenda_item_title = row["Agenda Item Title"]
            agenda_item_key = inflection.parameterize(f"{roadmap_file} {agenda_item_title}")
            year_semester = row.get("Year/Semester") or year_semester
            if year_semester:
                year = year_semester.split("th")[0]
                if year == "Pre-9":
                    year = 8
                semester = year_semester.split(".")[1]
                if "1" in semester:
                    semester = 1
                elif "2" in semester:
                    semester = 2
                else:
                    semester = 3

            meeting_key = inflection.parameterize(f"{roadmap_file} {meeting_title} {year} {semester}")

            pre_task_user_type = "parent" if "FOR PARENTS:" in row.get("Prep Homework") else "student"
            post_task_user_type = "parent" if "FOR PARENTS:" in row.get("To Do Item") else "student"
            pre_tasks = re.split(r"\d+\.", row.get("Prep Homework", ""))
            pre_tasks = [s.strip(" \t\n\r") for s in pre_tasks]
            post_tasks = re.split(r"\d+\.", row.get("To Do Item", ""))
            post_tasks = [s.strip(" \t\n\r") for s in post_tasks]
            new_content = re.split(r"\.", row.get("Content", ""))
            new_content = [s.strip(" \t\n\r") for s in new_content]
            all_content += new_content
            data = {
                "Meeting Name": meeting_title_to_use,
                "Meeting Key": meeting_key,
                "Meeting Description": row.get("Roadmap One-Line Description"),
                "Meeting Counselor Instructions": meeting_instructions,
                "Dont Create With Roadmap": dont_create_with_roadmap,
                "Agenda Item Key": agenda_item_key,
                "Agenda Item Title": agenda_item_title,
                "Agenda Item Counselor Instructions": row["Agenda Item Details"],
                "Grade": year,
                "Semester": semester,
                "Content": row.get("Content"),
            }
            if not row.get("Prep Homework") and not row.get("To Do Item"):
                data.update()
            pre_tasks = [x for x in pre_tasks if x and x not in ("FOR PARENTS:", "FOR STUDENTS:")]
            post_tasks = [x for x in post_tasks if x and x not in ("FOR PARENTS:", "FOR STUDENTS:")]
            for t in pre_tasks:
                data.update(get_task_data(t, roadmap_file, "pre", pre_task_user_type))
                writer.writerow(data)
            for t in post_tasks:
                data.update(get_task_data(t, roadmap_file, "post", post_task_user_type))
                writer.writerow(data)
            if not (pre_tasks or post_tasks):
                writer.writerow(data)


containing_dir = f"{settings.BASE_DIR}/sncounseling/fixtures/roadmaps/7_21/"
from os import listdir
from os.path import isfile, join

onlyfiles = [f for f in listdir(containing_dir) if isfile(join(containing_dir, f)) and "DS_" not in f]
# onlyfiles = [f for f in onlyfiles if "premier_11_1" in f]

for fname in onlyfiles:
    roadmap_name = fname.split(".")[0]
    parse_roadmap(roadmap_name, all_content)
