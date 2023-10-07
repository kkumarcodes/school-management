"""
    This module handles business logic associated with tasks, such as
    sending notifications
"""
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from snnotifications.generator import create_notification
from snnotifications.models import Notification
from sntasks.constants import TASK_TEMPLATE_TASK_UPDATE_FIELDS
from sntasks.models import Task, TaskTemplate
from snusers.models import Administrator, Counselor, Student

# Deprecated
NOTIFICATION_TYPES = {
    "score_diagnostic": "score_diagnostic",
    "recommend_diagnostic": "recommend_diagnostic",
}


class TaskManagerException(Exception):
    pass


class TaskManager:
    def __init__(self, task):
        self.task: Task = task

    def _get_notification_type(self):
        """ Utility method to determine notification type for our self.task """
        if self.task.task_type in NOTIFICATION_TYPES:
            return NOTIFICATION_TYPES[self.task.task_type]
        elif self.task.diagnostic:
            return "task_diagnostic"
        return "task"

    def _get_notification_data(self):
        """ Utility method to grab metadata that can be used to create a noti from our task
            The notifications' primary related object is the task, unless the task has a primary related object
            in which case the task's primary related object becomes the notification's primary related object,
            leaving the task as a lone third wheel AKA the secondary related object
        """
        data = {
            "actor": self.task.created_by,
            "notification_type": self._get_notification_type(),
        }
        if self.task.related_object_content_type:
            data["related_object_content_type"] = self.task.related_object_content_type
            data["related_object_pk"] = self.task.related_object_pk
            data["secondary_related_object_content_type"] = ContentType.objects.get_for_model(Task)
            data["secondary_related_object_pk"] = self.task.pk
        else:
            data["related_object_content_type"] = ContentType.objects.get_for_model(Task)
            data["related_object_pk"] = self.task.pk

        return data

    @staticmethod
    def apply_counselor_task_template_override(
        task_template: TaskTemplate, counselor=None, update_complete_tasks=False
    ):
        """ When a counselor creates a new task template that overrides a roadmap task template, we
            need to update existing tasks that have been assigned with that task template.
            This method does that.
            Arguments:
                task_template. The task template that we need to update existing
                    tasks
                counselor: The counselor whose student's tasks need to be updated. If not set, then we look
                    for counselor who created task_template
        """
        if not task_template.roadmap_key:
            return
        if counselor:
            tasks_to_update = Task.objects.filter(
                task_template__roadmap_key=task_template.roadmap_key, for_user__student__counselor=counselor,
            ).distinct()
        else:
            if not (task_template.created_by and hasattr(task_template.created_by, "counselor")):
                raise TaskManagerException("Can only update tasks for task templates created by a counselor")
            tasks_to_update = Task.objects.filter(
                task_template__roadmap_key=task_template.roadmap_key,
                for_user__student__counselor__user=task_template.created_by,
            ).distinct()
        if not update_complete_tasks:
            tasks_to_update = tasks_to_update.filter(completed=None)
        tasks_to_update.exclude(task_template__roadmap_key="").update(task_template=task_template)

        # This actually updates the properties on the tasks to be copied from task template
        TaskManager.update_tasks_for_template(task_template, update_resources=True, counselor=counselor)

    @staticmethod
    def get_task_template_for_counselor(counselor: Counselor, roadmap_key: str):
        """ Counselors can override roadmap task templates with their own creations. This method gets the task
            template that should be used for a given roadmap key (identifying a TaskTemplate on a roadmap). If
            counselor has their own version of this roadmap task template, we return it. Otherwise we return the
            roadmap task template
        """
        counselor_template = TaskTemplate.objects.filter(
            created_by=counselor.user, roadmap_key=roadmap_key, archived=None
        ).first()
        return (
            counselor_template
            if counselor_template
            else TaskTemplate.objects.filter(roadmap_key=roadmap_key, created_by=None, archived=None).first()
        )

    @staticmethod
    def create_task(user, task_template=None, *args, **kwargs):
        """ One stop shop for creating a task
            If creating task from task template, we get the task template for counselor to ensure that if counselor has
            overridden task template, we use their override
        """
        if (
            task_template
            and task_template.roadmap_key
            and hasattr(user, "student")
            and user.student.counselor
            and not task_template.created_by
        ):
            task_template = TaskManager.get_task_template_for_counselor(
                user.student.counselor, task_template.roadmap_key
            )

        task: Task = Task.objects.create(for_user=user, task_template=task_template, **kwargs)
        if task_template:
            task.title = task_template.title
            task.description = task_template.description
            task.created_by = task_template.created_by
            task.updated_by = task_template.updated_by
            task.resources.set(task_template.resources.all())
            task.diagnostic = task_template.diagnostic
            task.form = task_template.form
            task.allow_content_submission = task_template.allow_content_submission
            task.require_content_submission = task_template.require_content_submission
            task.allow_file_submission = task_template.allow_file_submission
            task.require_file_submission = task_template.require_file_submission
            task.allow_form_submission = task_template.allow_form_submission
            task.require_form_submission = task_template.require_form_submission
            task.task_type = task_template.task_type
            task.task_template = task_template
            task.save()

        if (not task.is_cap) or task.visible_to_counseling_student:
            task.assigned_time = timezone.now()
            task.save()
        return task

    @staticmethod
    def update_tasks_for_template(task_template: TaskTemplate, update_resources: bool, update_pre_agenda_item_templates: bool, counselor=None):
        """ Update all of the tasks associated with a task template when its properties change """
        update_data = {x: getattr(task_template, x) for x in TASK_TEMPLATE_TASK_UPDATE_FIELDS}
        # This shouldn't be necessary, but is an extra guard to prevent against updating tasks that should not be updated
        if not task_template.created_by:
            if not counselor:
                raise TaskManagerException("Can only update tasks for task templates created by a counselor")
            tasks = task_template.tasks.filter(for_user__student__counselor=counselor)
        else:
            tasks = task_template.tasks.filter(for_user__student__counselor__user=task_template.created_by)
        tasks.update(**update_data)
        if update_resources or update_pre_agenda_item_templates:
            for task in tasks:
                if update_resources:
                    task.resources.set(task_template.resources.all())
                if update_pre_agenda_item_templates:
                    task.pre_agenda_item_templates.set(task_template.pre_agenda_item_templates.all())

        return tasks

    def send_task_created_notification(self, actor=None, allow_duplicate=False):
        """
            Send notification to person task is assigned to that task has been created
            Arguments:
                allow_duplicate: If True, then notification will be sent even if task created
                    noti has already been sent for self.task. Defaults to False

            Note that the task created notification is no longer actually sent. It is just used
            for the activity log.

            Returns: Task
        """
        # Students who are CAP but don't have access to CAP platform don't get notifications
        if (
            hasattr(self.task.for_user, "student")
            and (not self.task.for_user.student.has_access_to_cap)
            and self.task.is_cap
        ):
            return self.task
        if not allow_duplicate and Notification.objects.filter(**self._get_notification_data()).exists():
            return self.task
        create_notification(self.task.for_user, **self._get_notification_data())
        return self.task

    def complete_task(self, actor=None, send_notification=True) -> Task:
        """ A task has been completed. We mark it as such, then:
            1. If the task is for a counseling student, we update the student's StudentUniversityDecision
                objects as dictated by TaskTemplate.on_complete_sud_update
            2. Send notification (all tasks, if send_notification is True)
        """
        self.task.completed = timezone.now()
        self.task.save()
        if self.task.task_template and self.task.task_template.on_complete_sud_update:
            for sud in self.task.student_university_decisions.all():
                [
                    setattr(sud, key, val)
                    for (key, val) in self.task.task_template.on_complete_sud_update.items()
                    if (
                        len(self.task.task_template.only_alter_tracker_values) == 0
                        or getattr(sud, key) in self.task.task_template.only_alter_tracker_values
                    )
                ]
                sud.save()
        if send_notification:
            return self.send_task_completed_notification(actor=actor)
        return self.task

    def create_update_task_sud(self, student_university_decisions=None):
        """ When a task is created or updated and has related student university decisions
            and also has a related task template with on_assign_sud_update
            THEN when student university decisions get added to the task (including upon creation)
            we update the SUD's values as dictated by on_assign_sud_update.
            Arguments:
                student_university_decisions {StudentUniversityDecision} objects to update.
                    Must be associated with self.task
                    If not provided, we will update all student university decisions associated
                    with task
            Returns:
                None
        """
        if not (
            self.task.task_template
            and self.task.task_template.on_assign_sud_update
            and len(self.task.task_template.on_assign_sud_update.items())
        ):
            return
        suds = (
            student_university_decisions.filter(tasks=self.task)
            if student_university_decisions
            else self.task.student_university_decisions.all()
        )
        for sud in suds:
            [
                setattr(sud, key, val)
                for (key, val) in self.task.task_template.on_assign_sud_update.items()
                if (
                    len(self.task.task_template.only_alter_tracker_values) == 0
                    or getattr(sud, key) in self.task.task_template.only_alter_tracker_values
                )
            ]
            sud.save()

    def send_task_completed_notification(self, allow_duplicate=False, actor=None):
        """
            Send notification to person who assigned task, notifying them that task is completed
            Arguments:
                allow_duplicate: If True, then notification will be sent even if task completed
                    noti has already been sent for self.task. Defaults to False
            Returns: Task
        """
        data = {
            "actor": actor,
            "related_object_content_type": ContentType.objects.get_for_model(Task),
            "related_object_pk": self.task.pk,
            "notification_type": "task_complete",
            "is_cc": False,
        }
        # We have a completion on our hands!!! Notify whoever created that task!
        if not allow_duplicate and Notification.objects.filter(**data).exists():
            return self.task
        if self.task.created_by:
            create_notification(self.task.created_by, **data)
        elif hasattr(self.task.for_user, "student") and self.task.for_user.student.counselor:
            create_notification(self.task.for_user.student.counselor.user, **data)
        return self.task

    def send_self_assigned_admin_notification(self, actor=None, allow_duplicate=False):
        """
            Send notification to all admins when a student self-assigns a diagnostic
        """
        student = Student.objects.get(user=self.task.for_user.pk)
        for admin in Administrator.objects.all():
            create_notification(
                admin.user,
                notification_type="student_self_assigned_diagnostic",
                related_object_pk=self.task.pk,
                related_object_content_type=ContentType.objects.get_for_model(Task),
                secondary_related_object_content_type=ContentType.objects.get_for_model(Student),
                secondary_related_object_pk=student.pk,
            )
        return self.task
