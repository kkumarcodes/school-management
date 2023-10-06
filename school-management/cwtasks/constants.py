# Time between reminders on overdue tasks - HOURS
OVERDUE_TASK_NOTIFICATION_BUFFER = 48

# The fields we copy from TaskTemplate to task when updating a task template (if user opts to update associated tasks)
# Note that we also update resources
TASK_TEMPLATE_TASK_UPDATE_FIELDS = [
    "allow_content_submission",
    "require_content_submission",
    "allow_file_submission",
    "require_file_submission",
    "form",
    "description",
    "title",
    "task_type",
]

COLLEGE_RESEARCH_FORM_KEY = "college_research"
TASK_TYPE_SCHOOL_RESEARCH = "school_research"
