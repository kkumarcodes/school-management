""" This script creates a single task template (with related form) for new colleges earch questionnaire
"""

from sncounseling.models import AgendaItemTemplate
from sntasks.models import FormField, TaskTemplate

description = """
<p>These questions are meant to guide our conversation about the college search, with the goal of building an initial college list together in our next meeting. We won’t necessarily discuss all of these but I’d love for you to think about the below questions before we meet next!</p>
<ul>
<li>What surprised you about the two videos you watched (overview of colleges/what do I want out of a college)? What did you learn that you didn&rsquo;t know before?</li>
<li>What priorities did you start to think about as you watched them?</li>
<li>Are there any particular colleges you already find interesting, or colleges that you would like to learn more about? Which ones? Why have those ones stood out to you?</li>
<li>Are there any particular schools that your family wants you to apply to? Which ones?</li>
<li>How comfortable have you been with change in your life so far (changing schools, being new, having to find new friends, jumping into new experiences in general)?</li>
<li>How would you describe your friends, or the people you tend to feel most yourself around?</li>
<li>What sort of activities do you like to do for fun, say on your ideal Saturday?</li>
<li>Which of these events is something you&rsquo;d most want to participate in or have access to in college (pick any that stand out to you!): live music concerts, a big game, political speakers, theatre performances, political demonstrations or protests, outdoor sports (hiking, skiing, etc), going to a professional sports game, going to a local coffee shop or restaurant off-campus, walking around a big city</li>
<li>Say you&rsquo;re in the dining hall at your school &ndash; what conversations do you want to hear? Discussions from class, politics, the big game, a mix of all that?</li>
<li>What do you want to avoid repeating from your high school experience?</li>
<li>Are there any majors or topics you want to be able to explore in college?</li>
<li>Are there any areas of the country where you&rsquo;d like to focus your search (or avoid)?</li>
<li>Have your parents talked about your college budget, and if aid (scholarships, in-state tuition) will be a guiding part of your search?</li>
</ul>
"""

(form, _) = Form.objects.get_or_create(title="College Search Questions")
if form.form_fields.count() > 1:
    raise Exception("Invalid form fields on existing form", form.form_fields.all())
form.description = description
form.save()

# We need a single field
(form_field, _) = FormField.objects.get_or_create(
    form=form,
    input_type=FormField.TEXTAREA,
    field_type=FormField.STRING,
    title="College Research",
    key="college_research",
)

# Now we need to ensure each Roadmap has a TaskTemplate with this revered form
for roadmap in (
    Roadmap.objects.exclude(counselor_meeting_templates__agenda_item_templates__pre_meeting_task_templates__form=form)
    .filter(counselor_meeting_templates__agenda_item_templates__student_title="College Research & First List")
    .distinct()
):
    agenda_item_template = AgendaItemTemplate.objects.get(
        counselor_meeting_template__roadmap=roadmap, student_title="College Research & First List"
    )
    task_template = TaskTemplate.objects.create(
        task_type="survey",
        key=f"{roadmap.title}_college_search_questions",
        title="Think about what you want in a college",
        description="Think about these questions as we’ll be discussing them in your next meeting",
        form=form,
    )
    agenda_item_template.pre_meeting_task_templates.add(task_template)
    print(task_template, task_template.key)

""" COLLEGE SEARCH TASK """
# We deactivate the old form
print(Form.objects.filter(title="Student College Search Questionnaire").update(active=False))
old_tasks = Task.objects.filter(form__title="Student College Search Questionnaire")
delete_tasks = old_tasks.filter(completed__isnull=False)
if input(f"Delete {delete_tasks.count()} tasks?") == "y":
    print(delete_tasks.delete())

# And we create task (in task bank) for each student with meeting that contains new form
from sntasks.utilities.task_manager import TaskManager

meeting_templates = CounselorMeetingTemplate.objects.filter(
    agenda_item_templates__pre_meeting_task_templates__form=form
).distinct()
for student in Student.objects.filter(counselor_meetings__counselor_meeting_template__in=meeting_templates).distinct():
    task_template = TaskTemplate.objects.filter(
        title="College Search Questions",
        pre_agenda_item_templates__counselor_meeting_template__counselor_meetings__student=student,
    ).first()
    if not Task.objects.filter(for_user__student=student, task_template=task_template).exists():
        task = TaskManager.create_task(student.user, task_template=task_template)
        task.counselor_meetings.set(
            list(
                student.counselor_meetings.filter(
                    counselor_meeting_template__agenda_item_templates__pre_meeting_task_templates=task.task_template
                ).distinct()
            )
        )
        print(task)
