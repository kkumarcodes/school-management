from datetime import timedelta
import dateparser
from django.db.models.query_utils import Q
from django.db import transaction
from django.http.response import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.viewsets import ModelViewSet

from cwcounseling.constants.counselor_note_category import NOTE_CATEGORY_PRIVATE
from cwcounseling.errors import CounselorMeetingManagerSchedulingException
from cwcounseling.models import (
    AgendaItem,
    AgendaItemTemplate,
    CounselorEventType,
    CounselorMeeting,
    CounselorMeetingTemplate,
    CounselorNote,
    Roadmap,
)
from cwcounseling.serializers.counselor_meeting import (
    AgendaItemSerializer,
    AgendaItemTemplateSerializer,
    CounselorMeetingSerializer,
    CounselorMeetingTemplateSerializer,
    CounselorNoteSerializer,
    CounselorEventTypeSerializer,
)
from cwcounseling.utilities.counselor_meeting_manager import CounselorMeetingManager
from cwtasks.models import Task
from cwtasks.serializers import TaskSerializer
from cwusers.mixins import AccessStudentPermission
from cwusers.models import Counselor, Student


class CounselorMeetingViewset(ModelViewSet, AccessStudentPermission):
    permission_classes = (IsAuthenticated,)
    queryset = (
        CounselorMeeting.objects.all()
        .select_related("student__user", "counselor_meeting_template", "student__counselor__user")
        .prefetch_related("tasks", "agenda_items")
    )
    serializer_class = CounselorMeetingSerializer

    def check_permissions(self, request):
        super().check_permissions(request)
        is_admin = hasattr(request.user, "administrator")
        is_counselor = hasattr(request.user, "counselor")
        is_student = hasattr(request.user, "student")
        is_parent = hasattr(request.user, "parent")

        # Only counselors and admins can delete meetings
        if request.method.lower() in ["delete"] and not (is_counselor or is_admin):
            self.permission_denied(request)
        if request.method.lower() in ["post"]:
            if is_student:
                if not request.user.student.pk == request.data.get("student"):
                    self.permission_denied(request)
            if is_parent:
                if not Student.objects.get(pk=request.data.get("student")) in request.user.parent.students.all():
                    self.permission_denied(request)

    def check_object_permissions(self, request, obj: CounselorMeeting):
        """Note that there are certain ~fields~ that only admin/counselor can edit, but restricting those
        fields is handled in serializer based on context
        """
        super().check_object_permissions(request, obj)
        if not self.has_access_to_student(obj.student):
            self.permission_denied(request)

    def get_queryset(self):
        """Queryset based on what the user has permission for"""
        queryset = self.queryset
        if hasattr(self.request.user, "administrator"):
            return queryset
        if hasattr(self.request.user, "counselor"):
            return queryset.filter(student__counselor=self.request.user.counselor)
        if hasattr(self.request.user, "parent"):
            return queryset.filter(student__parent=self.request.user.parent, cancelled=None)
        if hasattr(self.request.user, "student"):
            return queryset.filter(student=self.request.user.student, cancelled=None)
        return CounselorMeeting.objects.none()

    def filter_queryset(self, queryset):
        """Query params supported for filtering:
        (Including multiple ANDs them together)
        start {date} NOT DATETIME
        end {date} NOT DATETIME
        student {PK}
        counselor {PK}
        """
        query_params = self.request.query_params
        if query_params.get("start"):
            start = dateparser.parse(query_params["start"])
            if not start:
                raise ValueError(f"Invalid start: {query_params['start']}")
            queryset = queryset.filter(start__gte=start)
        if query_params.get("end"):
            end = dateparser.parse(query_params["end"])
            if not end:
                raise ValueError(f"Invalid end: {query_params['end']}")
            queryset = queryset.filter(start__lte=end)
        if query_params.get("student"):
            queryset = queryset.filter(student=query_params["student"])
        if query_params.get("counselor"):
            queryset = queryset.filter(counselor=query_params["counselor"])
        return queryset

    @action(methods=["POST"], detail=True, url_name="send_notes_message", url_path="send-notes-message")
    def send_notes_message(self, request, *args, **kwargs):
        """Send a message with our notes to student and/or parent.
        Uses CounselorMeetingManager.send_notes
        FIELDS for note on counselor meeting must be set before hitting this action
        Arguments:
            send_to_parent {bool}
            send_to_student {bool}
            link_schedule_meeting_pk {Number; Optional}
        Returns: Updated CounselorMeeting
        """
        counselor_meeting: CounselorMeeting = self.get_object()
        mgr = CounselorMeetingManager(counselor_meeting)

        if request.data.get("link_schedule_meeting_pk"):
            # If we're providing a link to schedule a meeting, we need to make sure that meeting is...schedulable :)
            schedule_meeting: CounselorMeeting = get_object_or_404(
                CounselorMeeting, pk=request.data["link_schedule_meeting_pk"]
            )
            schedule_meeting.student_schedulable = True
            schedule_meeting.save()
            # Just in case the meeting we're sending notes for is the one that's schedulable
            counselor_meeting.refresh_from_db()

        # Supports overwriting with None
        counselor_meeting.link_schedule_meeting_pk = request.data.get("link_schedule_meeting_pk")
        counselor_meeting.save()

        counselor_meeting = mgr.send_notes(request.data.get("send_to_student"), request.data.get("send_to_parent"))
        return Response(self.get_serializer(counselor_meeting).data)

    def get_serializer_context(self):
        """We include whether or not to send notification in serializer context, for cases where counselor meeting
        is getting scheduled/rescheduled/cancelled
        """
        context = super().get_serializer_context()
        context["send_notification"] = self.request.data.get("send_notification", True)
        return context

    def update(self, request, *args, **kwargs):
        """We update using the same params as create (below). We return the same value as create (below)
         We accept the following create data params in addition to the fields on CounselorMeetingSerializer:
        - agenda_item_templates: PKs of templates for agenda items that should be used to create new agenda items
            for this meeting
        - custom_agenda_items: Strings representing titles of custom agenda items to create
        - agenda_items: <Optional> PKs of agenda items that should be associated with the meeting.
            Agenda items that are associated with the meeting but aren't in this set will be deleted
        - send_notification: Boolean (default: True) indicating whether or not to send notification
            for rescheduled meeting
        We return the created meeting, created agenda items, and created tasks. It looks like this:
        {
            'meeting': <CounselorMeeting>,
            'agenda_items: <CounselorMeetingAgendaItem[]>,
            'tasks': <Task[]>
        }
        """
        with transaction.atomic():
            meeting: CounselorMeeting = self.get_object()
            serializer: CounselorMeetingSerializer = self.get_serializer(meeting, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)

            # Just a teensy bit of extra validation: Students/parents can't schedule for less than counselor's buffer
            if not (hasattr(request.user, "counselor") or hasattr(request.user, "administrator")):
                counselor: Counselor = meeting.student.counselor
                counselor_schedule_cutoff = timezone.now() + timedelta(
                    hours=counselor.student_schedule_meeting_buffer_hours
                )
                new_start = serializer.validated_data.get("start")
                new_end = serializer.validated_data.get("end")
                mgr = CounselorMeetingManager(meeting)
                mgr.validate_new_schedule_time(new_start, new_end)

                scheduling_to_bad_time = (
                    new_start and new_start > timezone.now() and new_start < counselor_schedule_cutoff
                )
                if scheduling_to_bad_time:
                    raise CounselorMeetingManagerSchedulingException(
                        f"Cannot schedule meetings to/from the next {counselor.student_schedule_meeting_buffer_hours} hours"
                    )

            # Outlook interop happens in serializer here
            counselor_meeting: CounselorMeeting = serializer.save()

            mgr = CounselorMeetingManager(counselor_meeting)
            # Obviously important that we remove extra agenda items before creating new ones, lest the new ones get removed!
            if "agenda_items" in request.data:
                bad_agenda_items = counselor_meeting.agenda_items.exclude(pk__in=request.data["agenda_items"])
                [mgr.remove_agenda_item(x) for x in bad_agenda_items]

            if request.data.get("agenda_item_templates"):
                for template_pk in request.data["agenda_item_templates"]:
                    if not counselor_meeting.agenda_items.filter(agenda_item_template=template_pk).exists():
                        mgr.create_agenda_item(
                            agenda_item_template=get_object_or_404(AgendaItemTemplate, pk=template_pk)
                        )
            if request.data.get("custom_agenda_items"):
                for custom_title in request.data["custom_agenda_items"]:
                    mgr.create_agenda_item(custom_agenda_item=custom_title)

            return_data = {
                "meeting": self.get_serializer(counselor_meeting).data,
                "agenda_items": AgendaItemSerializer(counselor_meeting.agenda_items.all(), many=True).data,
                "tasks": TaskSerializer(counselor_meeting.tasks.all(), many=True, context={"request": request}).data,
            }
            return Response(return_data)

    def create(self, request, *args, **kwargs):
        """This is a little confusing so read carefully: we create by first using counselor meeting manager's
        create_meeting method, which allows us to create agenda items and tasks.
        We then perform_update using data passed to POST in case some of the other fields (start, end, notes)
        were included.
        We accept the following create data params in addition to the fields on CounselorMeetingSerializer:
        - agenda_item_templates: PKs of templates for agenda items that should be used to create new agenda items
            for this meeting
        - custom_agenda_items: Strings representing titles of custom agenda items to create
        - tasks: PKs of EXISTING task objects that should be associated with meeting
        - send_notification: Boolean (default: True) indicating whether or not to send notification
            for scheduled meeting

        We return the created meeting, created agenda items, and created tasks. It looks like this:
        {
            'meeting': <CounselorMeeting>,
            'agenda_items: <CounselorMeetingAgendaItem[]>,
            'tasks': <Task[]>
        }
        """
        # We use serializer to validate incoming data
        agenda_item_template_pks = request.data.pop("agenda_item_templates", [])
        custom_agenda_items = request.data.pop("custom_agenda_items", [])
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tasks = Task.objects.filter(
            for_user__student=serializer.validated_data["student"], pk__in=request.data.get("tasks", [])
        )
        if tasks.count() != len(request.data.get("tasks", [])):
            raise ValidationError(detail="Invalid task(s)")

        # But then we don't use serializer to save, instead we use our meeting manager
        agenda_item_templates = AgendaItemTemplate.objects.filter(pk__in=agenda_item_template_pks)

        counselor_meeting = CounselorMeetingManager.create_meeting(
            serializer.validated_data["student"],
            counselor_meeting_template=serializer.validated_data.get("counselor_meeting_template"),
            agenda_item_templates=list(agenda_item_templates),
            custom_agenda_items=custom_agenda_items,
        )
        # Update our tasks so that they are associated with our new meeting
        for task in tasks:
            task.counselor_meetings.add(counselor_meeting)

        # We update the meeting with our serializer to set other fields that may have been included
        # in request.data
        # If start was included, then we will send confirmation email
        update_serializer = self.get_serializer(counselor_meeting, data=request.data, partial=True)
        update_serializer.is_valid(raise_exception=True)
        counselor_meeting = update_serializer.save()

        return_data = {
            "meeting": update_serializer.data,
            "agenda_items": AgendaItemSerializer(counselor_meeting.agenda_items.all(), many=True).data,
            "tasks": TaskSerializer(counselor_meeting.tasks.all(), many=True, context={"request": request}).data,
        }
        return Response(return_data, status=status.HTTP_201_CREATED)

    def handle_exception(self, exc):
        if isinstance(exc, CounselorMeetingManagerSchedulingException):
            return Response(
                {"detail": "Unable to schedule for the selected time. Please select a different time."},
                status=status.HTTP_400_BAD_REQUEST,
                exception=True,
            )
        return super().handle_exception(exc)


class CounselorMeetingTemplateViewset(ModelViewSet):
    queryset = CounselorMeetingTemplate.objects.all()
    serializer_class = CounselorMeetingTemplateSerializer
    permission_classes = (IsAuthenticated,)

    def check_permissions(self, request):
        # Admins can create/update. Anyone can view
        super().check_permissions(request)
        if request.method.lower() != "get" and not hasattr(request.user, "administrator"):
            self.permission_denied(request)

    def perform_destroy(self, instance):
        # Oh no you don't - destroying counselor meeting templates is not allowed
        raise NotImplementedError()


class CounselorMeetingTemplateView(ListAPIView, RetrieveAPIView):
    queryset = CounselorMeetingTemplate.objects.all()
    serializer_class = CounselorMeetingTemplateSerializer
    permission_classes = (IsAuthenticated,)


class CounselorNoteViewset(AccessStudentPermission, ModelViewSet):
    """Here ye have yer basic crud operations upon the CounselorNote model. A couple of special things you can do:
    Filter query params (LIST action):
    ?counselor to provide all notes for a counselor
    ?student to get all notes for a student

    Use the special send_email action to email notes to student/parents
    """

    queryset = CounselorNote.objects.all()
    serializer_class = CounselorNoteSerializer
    permission_classes = (IsAuthenticated,)

    def check_permissions(self, request):
        super().check_permissions(request)
        if hasattr(request.user, "administrator"):
            return True
        # Other than admins, only counselors can create/update
        if request.method not in SAFE_METHODS and not hasattr(request.user, "counselor"):
            self.permission_denied(request)

    def perform_create(self, serializer):
        # Note must either be a meeting note or a non-meeting note (date-note)
        if serializer.validated_data.get("counselor_meeting", None) and serializer.validated_data.get(
            "note_date", None
        ):
            return ValidationError("Note cannot contain both counselor_meeting and note_date field")
        if hasattr(self.request.user, "counselor"):
            # Meeting note case:
            if serializer.validated_data.get("counselor_meeting", None):
                # Counselor must be creating note for one of their student's counselor meetings
                if (not serializer.validated_data["counselor_meeting"].student.counselor) or serializer.validated_data[
                    "counselor_meeting"
                ].student.counselor.user != self.request.user:
                    self.permission_denied(self.request)
            # Non-meeting note case (date_note)
            if serializer.validated_data.get("note_date", None):
                # Non-meeting notes must explicitly provide associated student
                if not serializer.validated_data["note_student"]:
                    return ValidationError("Non-meeting note must include note_student")
                student = get_object_or_404(Student, pk=self.request.data["note_student"])
                # Counselor's can only create notes for their students
                if student.counselor.user != self.request.user:
                    self.permission_denied(self.request)
                instance = serializer.save(note_student=student)
                return instance
        super().perform_create(serializer)

    def check_object_permissions(self, request, obj: CounselorNote):
        super().check_object_permissions(request, obj)
        if hasattr(request.user, "administrator"):
            return True
        if obj.counselor_meeting and not self.has_access_to_student(obj.counselor_meeting.student):
            self.permission_denied(request)
        if obj.note_student and not self.has_access_to_student(obj.note_student):
            self.permission_denied(request)
        # If not counselor, then can't get private note
        if hasattr(request.user, "counselor"):
            return True
        if obj.category == NOTE_CATEGORY_PRIVATE or not obj.counselor_meeting.notes_finalized:
            self.permission_denied(request)

    def filter_queryset(self, queryset):
        student = counselor = None
        if self.request.query_params.get("student"):
            student = get_object_or_404(Student, pk=self.request.query_params["student"])
        elif hasattr(self.request.user, "student"):
            student = self.request.user.student
        if self.request.query_params.get("counselor"):
            counselor = get_object_or_404(Counselor, pk=self.request.query_params["counselor"])
        elif hasattr(self.request.user, "counselor"):
            counselor = self.request.user.counselor

        # Do some perms checks based on filter
        if student and not self.has_access_to_student(student):
            self.permission_denied(self.request)
        elif counselor and not (hasattr(self.request.user, "administrator") or counselor.user == self.request.user):
            self.permission_denied(self.request)
        elif (
            not self.kwargs.get("pk") and not (student or counselor) and not hasattr(self.request.user, "administrator")
        ):
            self.permission_denied(self.request)

        if counselor:
            queryset = queryset.filter(
                Q(counselor_meeting__student__counselor=counselor) | Q(note_student__counselor=counselor)
            )
        if student:
            queryset = queryset.filter(
                counselor_meeting__student=student, counselor_meeting__notes_finalized=True
            ).exclude(category=NOTE_CATEGORY_PRIVATE)
        if hasattr(self.request.user, "parent"):
            queryset = queryset.filter(
                counselor_meeting__student__parent=self.request.user.parent, counselor_meeting__notes_finalized=True
            ).exclude(category=NOTE_CATEGORY_PRIVATE)

        return queryset

    @action(methods=["PATCH"], detail=False, url_name="update_note_title", url_path="update-note-title")
    def update_note_title(self, request, *args, **kwargs):
        """ Bulk update note_title on all non-meeting notes for given student on the given note_date
            Query Params:
                ?note_date: datestring (YYYY-MM-DD)
                ?student {PK} student the notes are for
            Patch Data:
                note_title: string
            Returns updated CounselorNotes
        """
        if not request.query_params.get("note_date") or not request.query_params.get("student"):
            return HttpResponseBadRequest("Must provide student (PK) and note_date (YYYY-MM-DD) query param")
        student = get_object_or_404(Student, pk=request.query_params.get("student"))
        if not self.has_access_to_student(student):
            self.permission_denied(request)
        if request.data.get("note_title") is None:
            return HttpResponseBadRequest("Must provide note_title in body")
        non_meeting_notes = CounselorNote.objects.filter(
            note_student=request.query_params.get("student"), note_date=request.query_params.get("note_date")
        )
        non_meeting_notes.update(note_title=request.data["note_title"])
        return Response(CounselorNoteSerializer(non_meeting_notes, many=True).data)


class AgendaItemTemplateViewset(ModelViewSet):
    """List the counselor meeting agenda item TEMPLATES for a given meeting (counselors)
    Provides admins with full CRUD operations on AgendaItemTemplate
    Accepts the following query params:
        counselor_meeting_template
        roadmap
        student (returns agenda item templates for student's applied roadmap(s))
    """

    queryset = AgendaItemTemplate.objects.all()
    permission_classes = (IsAuthenticated,)
    serializer_class = AgendaItemTemplateSerializer

    def check_permissions(self, request):
        if not (hasattr(request.user, "administrator") or hasattr(request.user, "counselor")):
            self.permission_denied(request)
        if request.method.lower() != "get" and not hasattr(request.user, "administrator"):
            self.permission_denied(request)

    def filter_queryset(self, queryset):
        if self.request.query_params.get("counselor_meeting_template"):
            counselor_meeting_template = get_object_or_404(
                CounselorMeetingTemplate, pk=self.request.query_params["counselor_meeting_template"]
            )
            return queryset.filter(counselor_meeting_template=counselor_meeting_template)
        elif self.request.query_params.get("roadmap"):
            roadmap = get_object_or_404(Roadmap, pk=self.request.query_params["roadmap"])
            return queryset.filter(counselor_meeting_template__roadmap=roadmap).distinct()
        elif self.request.query_params.get("student"):
            student = get_object_or_404(Student, pk=self.request.query_params["student"])
            return queryset.filter(counselor_meeting_template__roadmap__students=student).distinct()
        return queryset


class AgendaItemListView(AccessStudentPermission, ListAPIView):
    """Retreive agenda items for a counselor meeting
    Accepts ?counselor_meeting query param. If not provided, agenda items for all of the user's
        meetings are returned
    """

    queryset = AgendaItem.objects.all().select_related("agenda_item_template")
    permission_classes = (IsAuthenticated,)
    serializer_class = AgendaItemSerializer

    def check_permissions(self, request):
        if self.request.query_params.get("counselor_meeting"):
            counselor_meeting = get_object_or_404(CounselorMeeting, pk=request.query_params.get("counselor_meeting"))
            student = counselor_meeting.student
            if not self.has_access_to_student(student):
                self.permission_denied(request)

    def filter_queryset(self, queryset):
        if self.request.query_params.get("counselor_meeting"):
            return queryset.filter(counselor_meeting=self.request.query_params["counselor_meeting"])
        elif hasattr(self.request.user, "student"):
            return queryset.filter(counselor_meeting__student=self.request.user.student)
        elif hasattr(self.request.user, "parent"):
            return queryset.filter(counselor_meeting__student__parent=self.request.user.parent)
        elif hasattr(self.request.user, "counselor"):
            return queryset.filter(counselor_meeting__student__counselor=self.request.user.counselor)
        raise ValidationError("Missing counselor_meeting param")


class CounselorEventTypeViewset(ModelViewSet):
    """Provide CRUD operations for Counselors (only) on EventTypes
    Counselor can retrieve, delete, update only EventTypes that they created
    """

    queryset = CounselorEventType.objects.all()
    serializer_class = CounselorEventTypeSerializer
    permission_classes = (IsAuthenticated,)

    def check_permissions(self, request):
        if not hasattr(request.user, "counselor") and not hasattr(request.user, "administrator"):
            self.permission_denied(request, "You do not have access")

    def check_object_permissions(self, request, obj):
        if not obj.created_by == request.user.counselor and not hasattr(request.user, "administrator"):
            self.permission_denied(request, "You do not have access")

    def filter_queryset(self, queryset):
        if hasattr(self.request.user, "counselor"):
            counselor = self.request.user.counselor
            return queryset.filter(created_by=counselor.pk)
        elif hasattr(self.request.user, "administrator"):
            return queryset
        else:
            return CounselorEventType.objects.none()

    def perform_create(self, serializer):
        event_type = serializer.save()
        if hasattr(self.request.user, "counselor"):
            event_type.created_by = self.request.user.counselor
            event_type.save()
        return event_type
