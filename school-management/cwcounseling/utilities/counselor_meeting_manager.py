""" Utility for scheduling/rescheduling meetings with counselor
"""
from decimal import Decimal
from datetime import datetime
from typing import List
import sentry_sdk
from rest_framework.exceptions import ValidationError

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from cwcommon.utilities.availability_manager import AvailabilityManager
from cwcounseling.constants import counselor_time_entry_category
from cwcounseling.errors import CounselorMeetingManagerException, CounselorMeetingManagerSchedulingException
from cwcounseling.models import CounselorMeeting, AgendaItem, AgendaItemTemplate, CounselorTimeEntry
from cwnotifications.generator import create_notification
from cwnotifications.constants.notification_types import (
    COUNSELOR_COUNSELOR_MEETING_SCHEDULED,
    COUNSELOR_MEETING_SCHEDULED,
    COUNSELOR_MEETING_CANCELLED,
)
from cwtasks.models import Task
from snusers.models import Counselor
from snusers.utilities.graph_helper import GraphHelperException, outlook_create, outlook_delete, outlook_update


class CounselorMeetingManager:
    """ Used for scheduling, rescheduling, and cancelling CounselorMeetings
        This manager takes care of notifications
    """

    counselor_meeting: CounselorMeeting = None

    def __init__(self, counselor_meeting: CounselorMeeting):
        self.counselor_meeting = counselor_meeting

    def validate_new_schedule_time(self, start: datetime, end: datetime):
        """ We are going to attempt to reschedule. We want to confirm that the start/end time are available for the
            counselor
        """
        mgr = AvailabilityManager(self.counselor_meeting.student.counselor)
        if not mgr.individual_time_is_available(start, end):
            raise CounselorMeetingManagerSchedulingException(
                "This time is no longer available. Please select another time"
            )

    def send_notes(self, send_to_student=True, send_to_parent=True) -> CounselorMeeting:
        """ Send notes for a counselor meeting. Assumes that notes_message_* fields on self.counselor_meeting
            have already been set!
            Arguments:
                send_to_student: Boolean indicating whether or not student will recieve a Notification with notes
                send_to_parent: Boolean indicating whether or not parent will receive a Notification with notes
            Returns: CounselorMeeting with updated notes_message_last_sent
        """
        if not (send_to_parent or send_to_student):
            raise ValidationError("Must send notes to either student or parent")
        # Pretty easy - we just create Notification objects
        if send_to_student:
            create_notification(
                self.counselor_meeting.student.user,
                notification_type="counselor_meeting_message",
                related_object_pk=self.counselor_meeting.pk,
                related_object_content_type=ContentType.objects.get_for_model(CounselorMeeting),
            )
        if send_to_parent and self.counselor_meeting.student.parent:
            ## CC if counselor wants that sort of thing
            counselor: Counselor = self.counselor_meeting.student.counselor
            cc_email = counselor.user.email if counselor.cc_on_meeting_notes else ""
            create_notification(
                self.counselor_meeting.student.parent.user,
                notification_type="counselor_meeting_message",
                related_object_pk=self.counselor_meeting.pk,
                related_object_content_type=ContentType.objects.get_for_model(CounselorMeeting),
                cc_email=cc_email,
            )
        self.counselor_meeting.notes_message_last_sent = timezone.now()
        self.counselor_meeting.notes_finalized = True
        self.counselor_meeting.save()
        return self.counselor_meeting

    def _handle_graph_exception(self, ex: GraphHelperException):
        if settings.TESTING or settings.DEBUG:
            print(ex)
        else:
            with sentry_sdk.configure_scope() as scope:
                scope.set_tag("debugging", "outlook")
                scope.set_context(
                    "CounselorMeeting",
                    {
                        "pk": self.counselor_meeting.pk,
                        "counselor_pk": self.counselor_meeting.student.counselor.pk,
                        "counselor": self.counselor_meeting.student.counselor.invitation_name,
                    },
                )
                sentry_sdk.capture_exception(ex)

    def schedule(
        self, start: datetime, end: datetime, create_time_entry=True, send_notification=True, actor: User = None
    ) -> CounselorMeeting:
        if self.counselor_meeting.start:
            raise CounselorMeetingManagerException("Cannot schedule meeting that is already scheduled")

        self.counselor_meeting.start = start
        self.counselor_meeting.end = end
        self.counselor_meeting.save()
        # When a student schedules a meeting, if task has no due date,
        # automatically set meeting's tasks due date to meeting start date
        if hasattr(actor, "student"):
            self.counselor_meeting.tasks.filter(due__isnull=True).update(
                due=self.counselor_meeting.start, visible_to_counseling_student=True
            )
        if self.counselor_meeting.student.counselor.microsoft_token:
            try:
                event_id = outlook_create(self.counselor_meeting)
                if event_id:
                    self.counselor_meeting.outlook_event_id = event_id
                    self.counselor_meeting.save()
            except GraphHelperException as exception:
                self._handle_graph_exception(exception)

        if create_time_entry:
            CounselorTimeEntry.objects.create(
                date=self.counselor_meeting.start,
                hours=Decimal((self.counselor_meeting.end - self.counselor_meeting.start).total_seconds() / 3600.0),
                category=counselor_time_entry_category.TIME_CATEGORY_MEETING,
                student=self.counselor_meeting.student,
                counselor=self.counselor_meeting.student.counselor,
                counselor_meeting=self.counselor_meeting,
            )

        # Create notification for student
        if send_notification:
            create_notification(
                self.counselor_meeting.student.user,
                notification_type=COUNSELOR_MEETING_SCHEDULED,
                related_object_pk=self.counselor_meeting.pk,
                related_object_content_type=ContentType.objects.get_for_model(CounselorMeeting),
            )
            if actor and actor != self.counselor_meeting.student.counselor.user:
                create_notification(
                    self.counselor_meeting.student.counselor.user,
                    notification_type=COUNSELOR_COUNSELOR_MEETING_SCHEDULED,
                    related_object_pk=self.counselor_meeting.pk,
                    related_object_content_type=ContentType.objects.get_for_model(CounselorMeeting),
                )
        return self.counselor_meeting

    def reschedule(
        self, start: datetime, end: datetime, send_notification=True, actor: User = None
    ) -> CounselorMeeting:
        """ Arguments:
                start, end New start and end for meeting
                send_notification Whether or not student or counselor should be notified of rescheduling
                actor User who rescheduled the meeting
        """
        if not self.counselor_meeting.start:
            raise CounselorMeetingManagerException("Cannot reschedule unscheduled meeting")

        old_start = self.counselor_meeting.start
        self.counselor_meeting.start = start
        self.counselor_meeting.end = end
        self.counselor_meeting.save()

        # When a student reschedules a meeting,if task has no due date or due date shares meeting's old_start date,
        # automatically set task due date to new meeting start date
        if hasattr(actor, "student"):
            self.counselor_meeting.tasks.filter(Q(due__isnull=True) | Q(due=old_start)).update(
                due=self.counselor_meeting.start, visible_to_counseling_student=True
            )

        try:
            if self.counselor_meeting.student.counselor.microsoft_token:
                if self.counselor_meeting.outlook_event_id:
                    outlook_update(self.counselor_meeting)
                else:
                    event_id = outlook_create(self.counselor_meeting)
                    if event_id:
                        self.counselor_meeting.outlook_event_id = event_id
                        self.counselor_meeting.save()
        except GraphHelperException as exception:
            self._handle_graph_exception(exception)

        if hasattr(self.counselor_meeting, "counselor_time_entry") and self.counselor_meeting.counselor_time_entry:
            time_entry: CounselorTimeEntry = self.counselor_meeting.counselor_time_entry
            time_entry.date = self.counselor_meeting.start
            time_entry.hours = Decimal(
                (self.counselor_meeting.end - self.counselor_meeting.start).total_seconds() / 3600.0
            )
            # TODO: Don't change time entry if already on approved time card
            time_entry.save()

        if send_notification:
            # Notify student that the meeting was rescheduled
            notification_metadata = {
                "related_object_pk": self.counselor_meeting.pk,
                "related_object_content_type": ContentType.objects.get_for_model(CounselorMeeting),
            }
            create_notification(
                self.counselor_meeting.student.user,
                notification_type="student_counselor_meeting_rescheduled",
                **notification_metadata
            )
            # If rescheduled by student or parent, then notify counselor
            if actor and (hasattr(actor, "student") or hasattr(actor, "parent")):
                create_notification(
                    self.counselor_meeting.student.counselor.user,
                    notification_type="counselor_counselor_meeting_rescheduled",
                    **notification_metadata
                )
        self.counselor_meeting.last_reminder_sent = timezone.now()
        return self.counselor_meeting

    def cancel(self, send_notification=True, set_cancelled=True) -> CounselorMeeting:
        """ Cancel a CounselorMeeting.
            Associated CounselorTimeEntry gets deleted (if exists)
            Arguments:
                send_notification: Whether or not student should get a notification about cancellation
                set_cancelled: If True, cancelled prop gets set to current datetime, otherwise we just clear
                    start and end time.
        """
        if self.counselor_meeting.cancelled:
            raise CounselorMeetingManagerException("Cannot cancel meeting that is already cancelled")
        if not self.counselor_meeting.start and set_cancelled:
            raise CounselorMeetingManagerException("Cannot cancel unscheduled meeting (you can delete it)")

        if set_cancelled:
            self.counselor_meeting.cancelled = timezone.now()
            self.counselor_meeting.save()
        else:
            self.counselor_meeting.start = self.counselor_meeting.end = None
            self.counselor_meeting.save()

        try:
            if self.counselor_meeting.outlook_event_id:
                outlook_delete(self.counselor_meeting)
        except GraphHelperException as e:
            self._handle_graph_exception(e)

        if hasattr(self.counselor_meeting, "counselor_time_entry") and self.counselor_meeting.counselor_time_entry:
            self.counselor_meeting.counselor_time_entry.delete()

        if send_notification:
            create_notification(
                self.counselor_meeting.student.user,
                notification_type=COUNSELOR_MEETING_CANCELLED,
                related_object_pk=self.counselor_meeting.pk,
                related_object_content_type=ContentType.objects.get_for_model(CounselorMeeting),
            )

        return self.counselor_meeting

    def get_tasks_for_agenda_item(self, agenda_item: AgendaItem):
        """ Get the tasks associated with task templates associated with the agenda item template
            for an agenda item. i.e. get the tasks for a student that are associated with an agenda
            item on a CounselorMeeting for that student
            Returns dict {
                'pre_meeting_tasks': Task[],
                'post_meeting_tasks': Task[]
            }
        """
        if not agenda_item.counselor_meeting.counselor_meeting_template:
            raise ValueError("Agenda item not for meeting with meeting template")

        return {
            "pre_meeting_tasks": Task.objects.filter(
                for_user__student=agenda_item.counselor_meeting.student,
                task_template__pre_agenda_item_templates__agenda_items=agenda_item,
            ).distinct(),
            "post_meeting_tasks": Task.objects.filter(
                for_user__student=agenda_item.counselor_meeting.student,
                task_template__post_agenda_item_templates__agenda_items=agenda_item,
            ).distinct(),
        }

    def get_tasks(self):
        """ Returns all tasks associated with agenda items associated with this meeting """
        return {
            "pre_meeting_tasks": Task.objects.filter(
                for_user__student=self.counselor_meeting.student,
                task_template__pre_agenda_item_templates__agenda_items__counselor_meeting=self.counselor_meeting,
            ).distinct(),
            "post_meeting_tasks": Task.objects.filter(
                for_user__student=self.counselor_meeting.student,
                task_template__post_agenda_item_templates__agenda_items__counselor_meeting=self.counselor_meeting,
            ).distinct(),
        }

    def remove_agenda_item(self, agenda_item: AgendaItem):
        if agenda_item.counselor_meeting != self.counselor_meeting:
            raise CounselorMeetingManagerException("Cannot remove agenda item that's not on counselor meeting")
        agenda_item.delete()

    def create_agenda_item(
        self, agenda_item_template: AgendaItemTemplate = None, custom_agenda_item: str = None
    ) -> AgendaItem:
        """ Create a new agenda item either from a template or as a custom agenda item and associate
            it with this meeting.
            Arguments:
                agenda_item_template: AgendaItemTemplate to create AgendaItem from
                custom_agenda_item: String to use to create custom agenda item
            Returns: AgendaItem
        """
        if agenda_item_template:
            return AgendaItem.objects.create(
                counselor_meeting=self.counselor_meeting,
                counselor_title=agenda_item_template.counselor_title,
                student_title=agenda_item_template.student_title,
                order=agenda_item_template.order,
                agenda_item_template=agenda_item_template,
            )
        elif custom_agenda_item:
            return AgendaItem.objects.create(
                counselor_meeting=self.counselor_meeting,
                counselor_title=custom_agenda_item,
                student_title=custom_agenda_item,
            )
        raise ValueError("agenda_item_template or custom_agenda_item required")

    @staticmethod
    def create_meeting(
        student,
        counselor_meeting_template=None,
        agenda_item_templates: List[AgendaItemTemplate] = None,
        custom_agenda_items: List[str] = [],
        *args,
        **kwargs
    ) -> CounselorMeeting:
        """ Create a new meeting.
            Arguments:
                student: Student meeting is with
                counselor_meeting_template: Template being used to create the meeting
                agenda_item_templates: Agenda item templates that we should create agenda items from for this meeting
                    Will use templates for counselor meeting template if meeting template is provided and agenda
                    item templates are not
                agenda_items: Strings of titles for new custom agenda meeting items
        """
        meeting: CounselorMeeting = CounselorMeeting.objects.create(
            student=student, counselor_meeting_template=counselor_meeting_template, **kwargs
        )

        # Create an agenda item for each agenda item template
        if counselor_meeting_template and agenda_item_templates is None:
            agenda_item_templates = counselor_meeting_template.agenda_item_templates.all()

        mgr = CounselorMeetingManager(meeting)
        [mgr.create_agenda_item(agenda_item_template=a) for a in agenda_item_templates]
        [mgr.create_agenda_item(custom_agenda_item=a) for a in custom_agenda_items]

        if counselor_meeting_template:
            # We default to title passed as kwarg so that user can override template title if they want
            meeting.title = kwargs.get("title", counselor_meeting_template.title)
            meeting.counselor_meeting_template = counselor_meeting_template

        meeting.save()

        return meeting
