"""
    This module contains views for interacting with group and individual tutoring sessions,
    tutors' availabilities, and tutoring session notes
"""
from datetime import datetime, timedelta
from django.conf import settings

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, F, Q
from django.http import FileResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.utils import dateparse, timezone
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework import status
import sentry_sdk

from cwcommon.mixins import CSVMixin
from cwcommon.utilities.availability_manager import AvailabilityManager
from cwnotifications.generator import create_notification
from cwtutoring.constants import NOTIFY_ADMIN_GROUP_HOUR_THRESHOLD, NOTIFY_ADMIN_INDIVIDUAL_HOUR_THRESHOLD
from cwtutoring.models import GroupTutoringSession, StudentTutoringSession, TutoringService
from cwtutoring.serializers.tutoring_sessions import (
    GroupTutoringSessionSerializer,
    StudentTutoringSessionSerializer,
    TutoringServiceSerializer,
)
from cwtutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager
from cwtutoring.utilities.tutoring_session_manager import TutoringSessionManager
from cwtutoring.utilities.tutoring_session_notes_generator import generate_pdf
from cwusers.mixins import AccessStudentPermission
from cwusers.models import Administrator, Student, Tutor
from cwusers.permissions import IsAdministratorPermission, MayReadOnly
from cwusers.utilities.graph_helper import outlook_create, outlook_delete, outlook_update, GraphHelperException
import json
from cwusers.utilities.zoom_manager import PRO_ZOOM_URLS
import dateutil.parser


# Helper for logging graph helper exceptions in Sentry
def _handle_graph_exception(session, ex: GraphHelperException):
    if settings.TESTING or settings.DEBUG:
        print(ex)
    else:
        with sentry_sdk.configure_scope() as scope:
            scope.set_context(
                "Tutoring Session", {"type": str(type(session)), "pk": session.pk,},
            )
            sentry_sdk.capture_exception(ex)


class StudentTutoringSessionViewset(CSVMixin, ModelViewSet, AccessStudentPermission):
    """
    CRUD actions on student tutoring session.
    User must have access to student that session is for.

    LIST
        Can filter on: student, tutor
        AND: past, future
        AND: individual, group

        Note that tutors and admins get tentative sessions

    CREATE fields differ from serializer in this way:
        tutor {number} field is used in lieu of tutor_availability to book an individual
            tutoring session. Valid availability will be found based on tutor and start time
    """

    serializer_class = StudentTutoringSessionSerializer
    permission_classes = (IsAuthenticated,)
    queryset = StudentTutoringSession.objects.all().order_by("start")

    def filter_queryset(self, queryset):
        """See tutoringThunks for filter properties"""
        filter_params = {}
        query_params = self.request.query_params

        # Student or tutor filter must be provided, or must be admin
        if not (
            query_params.get("student")
            or query_params.get("tutor")
            or hasattr(self.request.user, "administrator")
            # If using detail view, we don't require filter params because check_object_perms will kick in
            or self.kwargs.get("pk")
        ):
            self.permission_denied(self.request)

        if query_params.get("student"):
            # Filter for a specific student
            filter_params["student"] = query_params["student"]
        if query_params.get("past"):
            filter_params["start__lte"] = timezone.now()
        if query_params.get("future"):
            filter_params["end__gte"] = timezone.now()
        if query_params.get("individual"):
            filter_params["individual_session_tutor__isnull"] = False
        if query_params.get("group"):
            filter_params["group_tutoring_session__isnull"] = False

        queryset = queryset.filter(**filter_params)

        # Filter out tentative sessions unless both user is (tutor or admin) and ?tentative is in query params
        is_tutor_or_admin = hasattr(self.request.user, "tutor") or hasattr(self.request.user, "administrator")
        if not is_tutor_or_admin:
            queryset = queryset.filter(is_tentative=False)

        if query_params.get("tutor"):
            return queryset.filter(
                Q(individual_session_tutor=self.request.query_params["tutor"])
                | Q(group_tutoring_session__primary_tutor=self.request.query_params["tutor"])
                | Q(group_tutoring_session__support_tutors=self.request.query_params["tutor"])
            )

        return queryset.filter(student__isnull=False)

    @action(methods=["GET"], detail=True, url_path="pdf", url_name="pdf")
    def genenerate_pdf(self, request, *args, **kwargs):
        """View that returns PDF file with tutoring session notes, if available"""
        session = self.get_object()
        # Check notes visibility
        if session.tutoring_session_notes and not (
            hasattr(request.user, "administrator") or hasattr(request.user, "tutor")
        ):
            notes = session.tutoring_session_notes
            if not (
                notes.visible_to_parent
                and hasattr(request.user, "parent")
                or (notes.visible_to_student and hasattr(request.user, "student"))
            ):
                self.permission_denied(request)

        try:
            response_file = generate_pdf(session)
            return FileResponse(
                response_file, content_type="application/pdf", filename=response_file.name, as_attachment=True,
            )
        except ValueError as exc:
            return HttpResponseBadRequest(content=str(exc))

    def check_permissions(self, request):
        super(StudentTutoringSessionViewset, self).check_permissions(request)
        if request.method.lower() == "post" and not self.kwargs.get("pk"):
            student = get_object_or_404(Student, pk=request.data.get("student"))
            if not self.has_access_to_student(student):
                self.permission_denied(request, message="No access to student")

    def check_object_permissions(self, request, obj):
        super(StudentTutoringSessionViewset, self).check_object_permissions(request, obj)
        if obj.student and not self.has_access_to_student(obj.student):
            self.permission_denied(request, message="No access to student")
        is_tutor_or_admin = hasattr(self.request.user, "tutor") or hasattr(self.request.user, "administrator")
        if not is_tutor_or_admin and obj.is_tentative:
            self.permission_denied(request, message="No access to tentative sessions")

    def perform_create(self, serializer, create_data: dict = None):
        """Confirm student has enough hours to create the session"""
        create_data = create_data or self.request.data
        student = get_object_or_404(Student, pk=create_data.get("student"))
        group_session: GroupTutoringSession = None
        if create_data.get("is_tentative") and not (
            hasattr(self.request.user, "tutor") or hasattr(self.request.user, "administrator")
        ):
            raise ValidationError("Cannot create tentative session")

        if create_data.get("group_tutoring_session"):
            group_session = get_object_or_404(GroupTutoringSession, pk=create_data["group_tutoring_session"])
            if not TutoringSessionManager.student_can_join_group_session(student, group_session):
                raise ValidationError("Cannot join group session")
        elif create_data.get("individual_session_tutor"):
            tutor = get_object_or_404(Tutor, pk=create_data["individual_session_tutor"])
            try:
                start = dateparse.parse_datetime(create_data.get("start"))
                end = dateparse.parse_datetime(create_data.get("end"))
            except TypeError:
                raise ParseError(detail="Invalid start or end")

            # If not admin or tutor, then time must be valid
            is_admin_or_tutor = bool(
                hasattr(self.request.user, "administrator") or hasattr(self.request.user, "tutor")
            )
            if not is_admin_or_tutor:
                mgr = AvailabilityManager(tutor)
                if not mgr.individual_time_is_available(start, end):
                    raise ParseError(detail="Time is not available")
                # If not admin or tutor, then tutor must allow students to book with them
                tutor = get_object_or_404(Tutor, pk=create_data["individual_session_tutor"])
                if not tutor.students_can_book:
                    self.permission_denied(self.request, message="Cannot book session with tutor")
        session = serializer.save()

        if group_session:
            session.start = group_session.start
            session.end = group_session.end
            if group_session.charge_student_duration is not None:
                session.duration_minutes = group_session.charge_student_duration
                session.save()
            session.save()

        # Only create Outlook calendar event if this is a new wisernet event.
        # Do not create Outlook event if this is a student being added to a GTS
        # Check that tutor has microsoft_token
        if (
            not session.group_tutoring_session
            and not session.is_tentative
            and (
                (session.individual_session_tutor is not None and session.individual_session_tutor.microsoft_token)
                or (group_session and group_session.primary_tutor.microsoft_token)
            )
        ):
            try:
                event_id = outlook_create(session)
                session.outlook_event_id = event_id
                session.save()
            except GraphHelperException as e:
                _handle_graph_exception(session, e)

        # Create notifications
        data = {
            "actor": self.request.user,
            "related_object_content_type": ContentType.objects.get_for_model(StudentTutoringSession),
            "related_object_pk": session.pk,
        }

        if session.individual_session_tutor and session.start > timezone.now() and not session.is_tentative:
            create_notification(
                session.individual_session_tutor.user, notification_type="individual_tutoring_session_tutor", **data,
            )
        if session.start > timezone.now() and not session.is_tentative:
            create_notification(
                session.student.user, notification_type="student_tutoring_session_confirmation", **data,
            )

        hours_manager = StudentTutoringPackagePurchaseManager(session.student)
        hours_remaining = hours_manager.get_available_hours()
        if session.duration_minutes > 0 and not session.is_tentative:
            if (
                (
                    hours_remaining["individual_test_prep"] < NOTIFY_ADMIN_INDIVIDUAL_HOUR_THRESHOLD
                    and session.individual_session_tutor
                    and session.session_type == StudentTutoringSession.SESSION_TYPE_TEST_PREP
                )
                or (
                    hours_remaining["individual_curriculum"] < NOTIFY_ADMIN_INDIVIDUAL_HOUR_THRESHOLD
                    and session.individual_session_tutor
                    and session.session_type == StudentTutoringSession.SESSION_TYPE_CURRICULUM
                )
                or (
                    hours_remaining["group_test_prep"] < NOTIFY_ADMIN_GROUP_HOUR_THRESHOLD
                    and session.group_tutoring_session
                )
            ):
                create_notification(
                    session.student.user,
                    notification_type="student_student_low_on_hours",
                    actor=self.request.user,
                    related_object_content_type=ContentType.objects.get_for_model(Student),
                    related_object_pk=session.student.pk,
                )

    ## Convert_tentative action allows a tentative tutoring session to be confirmed as a real tutoring session.
    @action(methods=["POST"], detail=True, url_path="convert", url_name="convert")
    def convert(self, request, *args, **kwargs):
        tentative_session = self.get_object()
        session = StudentTutoringSessionSerializer(tentative_session)
        tentative_session_data = session.data

        ## Stripping object of a PK and setting is_tentative to false will allow it be be recreated as a new session.
        tentative_session_data.pop("pk")
        tentative_session_data["is_tentative"] = False

        non_tentative_session = StudentTutoringSessionSerializer(data=tentative_session_data)
        non_tentative_session.is_valid()

        self.perform_create(non_tentative_session, create_data=tentative_session_data)
        tentative_session.delete()
        return Response(non_tentative_session.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """We override update to:
        - Validate new times if rescheduling individual session
        - Use TutoringSessionManager to reschedule or cancel, ensuring proper notis are sent
        """
        # Confirm we aren't trying to change session type
        og_object = self.get_object()
        data = self.request.data
        # There are some fields we can't update
        data.pop("individual_session_tutor", None)
        data.pop("group_tutoring_session", None)

        set_cancelled = data.pop("set_cancelled", None)
        late_cancel = data.get("late_cancel")

        if (
            not hasattr(request.user, "administrator")
            and not set_cancelled
            and not late_cancel
            and og_object.set_cancelled
        ):
            raise ValidationError("Cannot un-cancel session")
        if set_cancelled and not og_object.set_cancelled and og_object.missed:
            raise ValidationError("Cannot cancel missed session")

        start = dateparse.parse_datetime(data.pop("start", ""))
        end = dateparse.parse_datetime(data.pop("end", ""))

        # Validate new start and end before we go a savin'
        rescheduling = False
        is_admin_or_tutor = bool(hasattr(self.request.user, "administrator") or hasattr(self.request.user, "tutor"))

        # If not admin nor tutor, then can't cancel a session within 24 hours of it occuring
        if not is_admin_or_tutor and set_cancelled and timezone.now() + timedelta(hours=24) > og_object.start:
            raise ValidationError("Cannot cancel a session within 24 hours")

        if (start and start != og_object.start) or (end and end != og_object.end):
            rescheduling = True
            if og_object.group_tutoring_session:
                raise ValidationError("Cannot reschedule group session")

            # If not admin nor tutor, then can't reschedule a session within 24 hours of it occuring
            if not is_admin_or_tutor and timezone.now() + timedelta(hours=24) > og_object.start:
                raise ValidationError("Cannot reschedule a session within 24 hours")

            # If not admin or tutor, then time must be valid
            if not is_admin_or_tutor and not AvailabilityManager(
                og_object.individual_session_tutor
            ).individual_time_is_available(start, end):
                raise ValidationError("Cannot reschedule session to this time")

            if not og_object.individual_session_tutor.students_can_book and not is_admin_or_tutor:
                raise ValidationError("Cannot reschedule session with this tutor")

        serializer = self.get_serializer(og_object, data=data, partial=kwargs.pop("partial", False))
        serializer.is_valid(raise_exception=True)
        updated_object = serializer.save()
        mgr = TutoringSessionManager(updated_object)
        # If we need to cancel
        if set_cancelled and not og_object.set_cancelled:
            updated_object = mgr.cancel(actor=request.user)
        elif not set_cancelled and og_object.set_cancelled and hasattr(request.user, "administrator"):
            updated_object = mgr.uncancel(actor=request.user)

        elif rescheduling:
            updated_object = mgr.reschedule(start, end, actor=request.user)
        return Response(self.get_serializer(updated_object).data)


class TutorTutoringSessionsView(RetrieveAPIView):
    """This view allows a tutor to retrieve their upcoming (or past) tutoring sessions, including
    upcoming sessions where they are primary or support tutor, and individual sessions where they
    are individual session tutor.
    Only supports GET action with tutor PK in URL.
    Optional query params:
        include_past {boolean; default False} whether or not past sessions should be included
            (sessions with an end before now)
    Returns:
        {
            group_tutoring_sessions: GroupTutoringSession[],
            individual_tutoring_sessions: StudentTutoringSession[],
        }
        Note that missed and cancelled sessions ARE included.
    """

    queryset = Tutor.objects.all()
    permission_classes = (IsAuthenticated,)

    def check_object_permissions(self, request, obj):
        """Must be admin or tutor retrieving sessions for themself"""
        super(TutorTutoringSessionsView, self).check_object_permissions(request, obj)
        if not (hasattr(request.user, "administrator") or obj.user == request.user):
            self.permission_denied(request)

    def retrieve(self, request, *args, **kwargs):
        """See class docstring for filter params and return type"""
        include_past = request.query_params.get("include_past", False)
        tutor = self.get_object()
        individual_sessions = StudentTutoringSession.objects.filter(individual_session_tutor=tutor)
        group_sessions = GroupTutoringSession.objects.filter(Q(primary_tutor=tutor) | Q(support_tutors=tutor))
        if not include_past:
            individual_sessions = individual_sessions.filter(end__gte=timezone.now())
            group_sessions = group_sessions.filter(end__gte=timezone.now())

        return Response(
            {
                "individual_tutoring_sessions": StudentTutoringSessionSerializer(individual_sessions, many=True).data,
                "group_tutoring_sessions": GroupTutoringSessionSerializer(
                    group_sessions, many=True, context={"include_student_names": True}
                ).data,
            }
        )


class TutoringServiceViewset(CSVMixin, ModelViewSet):
    """Viewset offering basic CRUD operations on TutoringServices"""

    permission_classes = [IsAdministratorPermission | MayReadOnly]
    serializer_class = TutoringServiceSerializer
    queryset = TutoringService.objects.all()


class GroupTutoringSessionViewset(CSVMixin, ModelViewSet):
    """This Viewset offers Create, Update, and List actions
    for the GroupTutoringSession model.
    When listing sessions, the following query params are available:
        start_date {date} Defaults to today. Return only sessions that
            start on or after this date
        end_date {date} Defaults to 180 days after start_date (unless tutor param provided).
            Return only sessions that start before this date (NOT INCLUSIVE)
        location {pk} Default's to a student/tutor's location(s) or all locations
            for admins. Restricts sessions to only those held at specified location
        include_cancelled {boolean} Defaults to false. If True AND CURRENT USER IS ADMIN
            then cancelled and un-cancelled sessions will be returned.
        exclude_classes Defaults to false. If True, sessions that are part of a Course will not be returned

    Admins can "Delete" a session by updating it to be cancelled. THIS WILL NOTIFY
    ALL REGISTERED STUDENTS AND TUTORS THAT THE SESSION HAS BEEN CANCELLED.
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = GroupTutoringSessionSerializer
    queryset = GroupTutoringSession.objects.all()

    def filter_queryset(self, queryset):
        """Filter for:
        start/end date
        location
        whether or not cancelled sessions should be included (admin only)
        """
        query_params = self.request.query_params
        # Admins can choose to include cancelled sessions
        if not (query_params.get("include_cancelled") and hasattr(self.request.user, "administrator")):
            queryset = queryset.filter(cancelled=False)

        start_date = datetime(timezone.now().year, timezone.now().month, timezone.now().day)
        if query_params.get("start_date"):
            try:
                start_date = dateparse.parse_date(query_params["start_date"])
            except ValueError:
                raise ParseError(detail="Invalid start date")

        end_date = start_date + timedelta(days=180)
        if query_params.get("end_date"):
            try:
                end_date = dateparse.parse_date(query_params["end_date"])
            except ValueError:
                raise ParseError(detail="Invalid end date")

        filter_data = {}
        if (not hasattr(self.request.user, "administrator")) or (
            query_params.get("start_date") or query_params.get("end_date")
        ):
            filter_data = {"start__gte": start_date, "end__lt": end_date}
        if query_params.get("location"):
            queryset = queryset.filter(Q(location=query_params["location"]) | Q(location__is_remote=True))
        elif hasattr(self.request.user, "student") and self.request.user.student.location:
            queryset = queryset.filter(Q(location=self.request.user.student.location.pk) | Q(location__is_remote=True))

        if query_params.get("exclude_classes"):
            queryset = queryset.filter(courses=None)

        if query_params.get("diagnostic"):
            queryset = queryset.filter(diagnostic__isnull=False)

        # Finally, only admins and tutors can see Group Tutoring Sessions
        if not (
            hasattr(self.request.user, "administrator")
            or hasattr(self.request.user, "tutor")
            or hasattr(self.request.user, "counselor")
        ):
            queryset = queryset.exclude(Q(set_charge_student_duration=0) & Q(title__icontains="diagnostic"))

        return queryset.filter(**filter_data).distinct()

    def perform_update(self, serializer):
        """Send notifications when cancelling a session"""
        og_obj = self.get_object()
        updated_obj = serializer.save()
        if updated_obj.cancelled and not og_obj.cancelled:
            updated_obj: GroupTutoringSession = TutoringSessionManager.cancel_group_tutoring_session(updated_obj)
        else:
            for session in StudentTutoringSession.objects.filter(group_tutoring_session=updated_obj.pk):
                # If primary tutor has been updated & set_duration_minutes is None, assign session student to updated primary tutor
                if og_obj.primary_tutor != updated_obj.primary_tutor and updated_obj.set_charge_student_duration != 0:
                    updated_obj.primary_tutor.students.add(session.student)
                    # if primary tutor has been updated, delete event from primary
                    # tutor calendar and create event on new tutor calendar
                    # make sure cancelled event has an outlook_event_id
                    try:
                        if og_obj.outlook_event_id and og_obj.primary_tutor.microsoft_token:
                            outlook_delete(og_obj)
                        if og_obj.primary_tutor.microsoft_token:
                            outlook_id = outlook_create(updated_obj)
                            if outlook_id:
                                updated_obj.outlook_event_id = outlook_id
                                updated_obj.save()
                    except GraphHelperException as e:
                        if settings.TESTING:
                            print(e)
                else:
                    # if tutor hasn't changed, update session on tutor calendar
                    try:
                        if og_obj.outlook_event_id and og_obj.primary_tutor.microsoft_token:
                            outlook_update(updated_obj)
                    except GraphHelperException as e:
                        if settings.TESTING:
                            print(e)

                mgr = TutoringSessionManager(session)
                mgr.reschedule_individual_sessions(
                    updated_obj.start, updated_obj.end, updated_obj.charge_student_duration, actor=self.request.user,
                )

        return updated_obj

    def delete(self, request, *args, **kwargs):
        """To delete a session, set it to cancelled"""
        return HttpResponseNotAllowed("")

    def check_permissions(self, request):
        """Only admins can create/update"""
        super(GroupTutoringSessionViewset, self).check_permissions(request)
        if request.method.lower() != "get" and not hasattr(request.user, "administrator"):
            self.permission_denied(request)

    def check_object_permissions(self, request, obj):
        """Only admins can retrieve or update individual objects"""
        super(GroupTutoringSessionViewset, self).check_object_permissions(request, obj)
        if not hasattr(request.user, "administrator"):
            self.permission_denied(request)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if hasattr(self.request.user, "administrator") or (
            hasattr(self.request.user, "tutor") and self.request.query_params.get("include_student_names") == "true"
        ):
            context["include_student_names"] = True

        return context

    def perform_create(self, serializer):
        session = serializer.save()
        # put this event on tutor's outlook calendar. If that was successful, update
        # STS object with outlook_event_id
        if session.primary_tutor.microsoft_token:
            try:
                event_id = outlook_create(session)
                if event_id:
                    session.outlook_event_id = event_id
                    session.save()
            except GraphHelperException as e:
                _handle_graph_exception(session, e)
        return session


class DiagnosticGTSView(ListAPIView):
    """This API view returns all future diagnostic sessions
    This view is publicly accessible
    """

    permission_classes = (AllowAny,)
    serializer_class = GroupTutoringSessionSerializer
    queryset = (
        GroupTutoringSession.objects.filter(
            start__gt=timezone.now() + timedelta(days=1),
            cancelled=False,
            include_in_catalog=True,
            set_charge_student_duration=0,
            title__icontains="diagnostic",
        )
        .annotate(s=Count("student_tutoring_sessions", filter=Q(student_tutoring_sessions__set_cancelled=False)))
        .filter(Q(capacity=None) | Q(s__lt=F("capacity")))
    )


class AvailabelZoomURLView(APIView):
    """ Simple view that returns array of available pro zoom urls for particular time slots list
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request, *args, **kwargs):

        if not hasattr(request.user, "administrator"):
            self.permission_denied(request)

        session_time_slots = request.data
        overlapping_group_session_urls = []
        overlapping_individual_session_urls = []

        for time_slot in session_time_slots:
            start, end = (
                dateutil.parser.isoparse(time_slot.get("start")).replace(
                    second=59, microsecond=99999
                ),  # converts iso format to python obj & replaced sec and ms to handle corner cases
                dateutil.parser.isoparse(time_slot.get("end")).replace(second=0, microsecond=0),
            )

            overlapping_group_session_urls_queryset = (
                GroupTutoringSession.objects.filter(cancelled=False)
                .exclude(
                    Q(end__lte=start) | Q(start__gte=end)
                )  # existing sessions ending at proposed start time and sessions starting at prposed end time can not said to be overlapping
                .values_list("zoom_url", flat=True)
            )
            overlapping_group_session_urls += list(overlapping_group_session_urls_queryset)

            # values_list("zoom_url") can not be called, zoom_url is not db field in StudentTutoringSession
            overlapping_individual_sessions = (
                StudentTutoringSession.objects.filter(set_cancelled=False, late_cancel=False)
                .exclude(Q(end__lte=start) | Q(start__gte=end))
                .only("id", "individual_session_tutor", "location", "group_tutoring_session")
            )
            overlapping_individual_session_urls += [session.zoom_url for session in overlapping_individual_sessions]

        all_overlapping_urls = overlapping_group_session_urls + overlapping_individual_session_urls
        all_available_urls = set(PRO_ZOOM_URLS) - set(all_overlapping_urls)

        return Response(data=all_available_urls)

