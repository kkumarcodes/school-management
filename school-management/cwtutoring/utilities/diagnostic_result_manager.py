""" This module is a state machine, that transitions a DiagnosticResult through it's various STATES
    (defined as DiagnosticResult.STATES).
    With each transition, some peeps may get notified
"""

from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q


from cwtutoring.models import DiagnosticResult
from cwnotifications.generator import create_notification
from cwnotifications.models import Notification
from cwtasks.models import Task
from cwtasks.utilities.task_manager import TaskManager
from snusers.models import Administrator, Tutor

SCORE_NOTI = "score_diagnostic"
RECOMMEND_NOTI = "recommend_diagnostic"


class DiagnosticResultManagerException(Exception):
    pass


class DiagnosticResultManager:
    diagnostic_result = None

    def __init__(self, diagnostic_result):
        self.diagnostic_result = diagnostic_result
        if not self.diagnostic_result:
            raise ValueError("Invalid diagnostic result")

    @property
    def notification_data(self):
        """ Object with kwargs for creating a notification with self.diagnostic_result as related object
        """
        return {
            "actor": self.diagnostic_result.submitted_by,
            "related_object_content_type": ContentType.objects.get_for_model(DiagnosticResult),
            "related_object_pk": self.diagnostic_result.pk,
        }

    def transition_to_state(self, state, **kwargs):
        """ Transition self.diagnostic result to state identified by argument
            Arguments:
                state {One of DiagnosticResult.STATES}
                kwargs Keyword arguments for method on me that will be used to transition state
            Returns: updated DiagnosticResult
        """
        if state == DiagnosticResult.STATE_PENDING_SCORE:
            self.diagnostic_result.state = DiagnosticResult.STATE_PENDING_SCORE
            self.diagnostic_result.save()
            return self.diagnostic_result
        method_map = {
            DiagnosticResult.STATE_PENDING_REC: self.score,
            DiagnosticResult.STATE_PENDING_RETURN: self.recommend,
            DiagnosticResult.STATE_VISIBLE_TO_STUDENT: self.return_to_student,
        }
        # When transitioning state, we complete existing tasks
        # Transition existing score tasks to be completed (no noti)
        # While we don't create these sorts of tasks anymore, we still mark outstanding tasks complete
        # for backwards compatibility
        Task.objects.filter(
            task_type__in=["score_diagnostic", "recommend_diagnostic"],
            related_object_content_type=ContentType.objects.get_for_model(DiagnosticResult),
            related_object_pk=self.diagnostic_result.pk,
        ).update(archived=timezone.now())

        if state not in method_map:
            raise ValueError(f"Invalid state {state}")
        return method_map[state](**kwargs)

    def create(self, **kwargs):
        """ diagnostic result was created. Update related tasks, notify scorers that they have a new
            DiagnosticResult to score
            Returns: updated DiagnosticResult
        """
        # Related tasks are now complete
        tasks = Task.objects.filter(
            for_user=self.diagnostic_result.student.user,
            completed=None,
            diagnostic=self.diagnostic_result.diagnostic,
            archived=None,
        )
        tasks_list = list(tasks)
        tasks.update(completed=timezone.now())
        # Create diagnostic complete notification for person who assigned, plus student's counselors and tutors
        to_be_notified = User.objects.filter(
            Q(
                Q(counselor__students=self.diagnostic_result.student)
                | Q(tutor__students=self.diagnostic_result.student)
                | Q(created_tasks__in=tasks_list)
            )
        ).distinct()
        if to_be_notified.exists():
            [
                create_notification(x, notification_type="diagnostic_result", **self.notification_data)
                for x in to_be_notified
            ]

        # Notifications for people who need to know that a task has been completed
        for task in tasks_list:
            task_manager = TaskManager(task)
            task_manager.send_task_completed_notification(actor=self.diagnostic_result.submitted_by)

        self.diagnostic_result.state = DiagnosticResult.STATE_PENDING_SCORE
        self.diagnostic_result.save()
        self.send_notifications()

        return self.diagnostic_result

    def score(self, score=None, **kwargs):
        """ Diagnostic has been scored. Time to tell recommenders that they have a recommendation to write
            Returns: updated DiagnosticResult
        """
        if (not self.diagnostic_result.score) or score:
            self.diagnostic_result.score = score
        self.diagnostic_result.state = DiagnosticResult.STATE_PENDING_REC
        self.diagnostic_result.save()

        self.send_notifications()
        return self.diagnostic_result

    def recommend(self, recommendation_file_upload=None, return_to_student=False, **kwargs):
        """ A recommendation has been completed for diagnostic. Export of diagnostic score with recommendation
            Must be provided
            Arguments:
                recommendation_file_upload {FileUpload} Exported score report with recommendation (PDF)
                return_to_student {Bool; default False} If True, then we'll immediately transition to make
                    diagnostic result visible to student. Otherwise, move to state of pending counselor
                    action to make result visible to student
            Returns: updated DiagnosticResult
        """
        self.diagnostic_result.recommendation = recommendation_file_upload
        if return_to_student:
            self.diagnostic_result.save()
            return self.return_to_student()
        self.diagnostic_result.state = DiagnosticResult.STATE_PENDING_RETURN
        self.diagnostic_result.save()

        if self.diagnostic_result.student.counselor:
            create_notification(
                self.diagnostic_result.student.counselor.user,
                notification_type="counselor_diagnostic_result",
                **self.notification_data,
            )
        # Notify ops of diagnostic result pending return to student
        admins = Administrator.objects.filter(is_diagnostic_recommendation_writer=True)
        [
            create_notification(
                admin.user, notification_type="diagnostic_result_pending_return", **self.notification_data
            )
            for admin in admins
        ]

        return self.diagnostic_result

    def reassign(self, new_assignee: User):
        """ Reassign to a new SINGLE person.
            Notifies them, marks any outstanding tasks complete
        """
        if not (
            hasattr(new_assignee, "administrator")
            or Tutor.objects.filter(user=new_assignee, is_diagnostic_evaluator=True).exists()
        ):
            raise DiagnosticResultManagerException(
                f"Attempting to reassign diag result {self.diagnostic_result.pk} to invalid user {new_assignee.pk}"
            )

        self.diagnostic_result.assigned_to = new_assignee
        self.diagnostic_result.save()
        # Notify our new friend
        self.send_notifications()

        return self.diagnostic_result

    def send_notifications(self):
        """ Send notifications to either the person who is assigned the DiagnosticResult
            or all admins for the diagnostics current state which MUST be either
            requiring score or evaluation
        """
        if not self.diagnostic_result.state in [
            DiagnosticResult.STATE_PENDING_REC,
            DiagnosticResult.STATE_PENDING_SCORE,
            DiagnosticResult.STATE_PENDING_RETURN,
        ]:
            raise DiagnosticResultManagerException(
                f"Invalid state for sending notifications: {self.diagnostic_result.state} on DR {self.diagnostic_result.pk}"
            )

        # Note that recommend noti used both for pending rec and pending return to student states
        noti_type = (
            SCORE_NOTI if self.diagnostic_result.state == DiagnosticResult.STATE_PENDING_SCORE else RECOMMEND_NOTI
        )
        # We assume the correct peeps are already assigned (or noone is)
        if self.diagnostic_result.assigned_to:
            create_notification(
                self.diagnostic_result.assigned_to, notification_type=noti_type, **self.notification_data,
            )
        else:
            admins = (
                Administrator.objects.filter(is_diagnostic_scorer=True)
                if self.diagnostic_result.state == DiagnosticResult.STATE_PENDING_SCORE
                else Administrator.objects.filter(is_diagnostic_recommendation_writer=True)
            )
            for admin in admins:
                create_notification(
                    admin.user, notification_type=noti_type, **self.notification_data,
                )

    def return_to_student(self, **kwargs):
        """ Return DiagnosticResult - with it's recommendation - to student. This method is only allowed
            if recommendation file has been created
            Returns: updated DiagnosticResult
        """
        self.diagnostic_result.state = DiagnosticResult.STATE_VISIBLE_TO_STUDENT
        self.diagnostic_result.save()
        if self.diagnostic_result.recommendation:
            create_notification(
                self.diagnostic_result.student.user,
                notification_type="student_diagnostic_result",
                related_object_content_type=ContentType.objects.get_for_model(DiagnosticResult),
                related_object_pk=self.diagnostic_result.pk,
            )

        if self.diagnostic_result.student.counselor and not Notification.objects.filter(
            notification_type="counselor_diagnostic_result",
            related_object_content_type=self.notification_data["related_object_content_type"],
            related_object_pk=self.notification_data["related_object_pk"],
        ):
            create_notification(
                self.diagnostic_result.student.counselor.user,
                notification_type="counselor_diagnostic_result",
                **self.notification_data,
            )

        return self.diagnostic_result

