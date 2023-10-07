""" This module is used to facilitate points of integration with the Prompt API that are specific to
    the counseling platform.
    This includes
    1) Pulling assignments and due dates from Prompt API

    Note that there is also Prompt API stuff in snusers (this is where UMS endpoints that Prompt uses
    to obtain user and org details exist)
"""
import json
import requests
import sentry_sdk
import dateparser
from django.conf import settings
from django.utils import timezone
from snusers.models import Student
from snusers.utilities.prompt_api_manager import PromptAPIManager
from cwuniversities.models import StudentUniversityDecision
from cwtasks.models import Task, TaskTemplate

ENDPOINT = "/api/assignment-list/"  # Prepended by PROMPT_API_BASE; appended by student's UMS ID
TEST_STUDENT_SLUG = "ce80f4c6-57b4-45fe-8f11-87b23803eff6"
TEST_COUNSELOR_SLUG = "d4daacd1-3ff8-4a5e-8e90-57bf5f3e7373"


class CounselingPromptAPIManagerException(Exception):
    pass


class CounselingPromptAPIManager:
    def __init__(self):
        if not (settings.PROMPT_API_BASE and settings.PROMPT_API_TOKEN):
            raise CounselingPromptAPIManagerException("Missing Prompt API Details")

    def update_assignment_tasks(self, student: Student):
        """ Pull assignments (with due dates) for a student from Prompt. Create tasks in UMS
            Returns queryset of student's Prompt Task obejcts
        """
        # Obtain the tasks from prompt
        slug = str(student.slug) if not (settings.DEBUG or settings.TESTING) else TEST_STUDENT_SLUG
        school_list = list(
            student.student_university_decisions.filter(is_applying=StudentUniversityDecision.YES).values_list(
                "university__iped", flat=True
            )
        )
        response = requests.post(
            f"{settings.PROMPT_API_BASE}{ENDPOINT}{slug}/",
            json={"schools": school_list},
            headers={"Authorization": f"Token {settings.PROMPT_API_TOKEN}"},
        )
        if response.status_code == 404:
            # Try to obtain JWT for student, which creates their Prompt account if it doesn't exist
            prompt_user_api_manager = PromptAPIManager()
            prompt_user_api_manager.obtain_jwt(student)
            response = requests.post(
                f"{settings.PROMPT_API_BASE}{ENDPOINT}{slug}/",
                json={"schools": school_list},
                headers={"Authorization": f"Token {settings.PROMPT_API_TOKEN}"},
            )

        if response.status_code != 200:
            with sentry_sdk.configure_scope() as scope:
                scope.set_context(
                    "Prompt Assignment List Request",
                    {"student": slug, "status": response.status_code, "response": response.content},
                )
                ex = CounselingPromptAPIManagerException("Prompt API Error (AssignmentList)")
                if settings.DEBUG or settings.TESTING:
                    print(f"Prompt API Manager response {response.status_code}")
                    print(response.content)
                else:
                    sentry_sdk.capture_exception(ex)
                raise ex

        data = json.loads(response.content)
        for assignment in data["assignments"]:
            # Create task due date
            task, _ = Task.objects.get_or_create(
                for_user=student.user, prompt_id=assignment["id"], task_type=TaskTemplate.ESSAY
            )
            task.title = assignment["name"]
            if len(assignment["ipeds"]) == 1:
                task.student_university_decisions.set(
                    list(student.student_university_decisions.filter(university__iped__in=assignment["ipeds"]))
                )
            task.due = dateparser.parse(assignment["next_due_date"]) if assignment.get("next_due_date") else None

            # Tasks with due date need to be made visible to students so they appear in reminders
            task.visible_to_counseling_student = bool(task.due)

            task.completed = timezone.now() if assignment["marked_complete"] else None
            task.save()

        # Delete all of the tasks that no longer come over from Prompt
        Task.objects.filter(task_type=TaskTemplate.ESSAY, for_user=student.user).exclude(prompt_id="").exclude(
            prompt_id__in=[x["id"] for x in data["assignments"]]
        ).delete()

        return Task.objects.filter(for_user=student.user, task_type=TaskTemplate.ESSAY).exclude(prompt_id="")
