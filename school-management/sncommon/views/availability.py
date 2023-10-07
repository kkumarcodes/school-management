from datetime import datetime, timedelta
from typing import Union

import pytz

from django.shortcuts import get_object_or_404
from django.utils import dateparse
from django.http import HttpResponseBadRequest
from django.contrib.contenttypes.models import ContentType
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.generics import (
    CreateAPIView,
    ListAPIView,
    RetrieveAPIView,
    DestroyAPIView,
    UpdateAPIView,
)
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from snusers.models import Counselor, Tutor, Administrator
from snusers.constants import user_types
from sntutoring.models import Location, TutorAvailability, RecurringTutorAvailability
from sntutoring.serializers.tutoring_sessions import (
    TutorAvailabilitySerializer,
    RecurringTutorAvailabilitySerializer,
)
from snnotifications.generator import create_notification
from sncounseling.models import CounselorAvailability, RecurringCounselorAvailability
from sncounseling.serializers.counselor_meeting import (
    CounselorAvailabilitySerializer,
    RecurringCounselorAvailabilitySerializer,
)
from sncommon.utilities.availability_manager import AvailabilityManager

NULL_STRING = "null"


class RecurringAvailabilityView(RetrieveAPIView, CreateAPIView, DestroyAPIView, UpdateAPIView):
    """ Viewset for getting, and creating (or updating) availability for a tutor or counselor
        Expects tutor or counselor (and user type) in URL
        Supports: GET (based on tutor/counselor PK)
            POST/PUT (create or update full set of recurring availability for tutor/counselor)
                expect data to be dictionary where keys are lowercase string days of week and values are
                arrays of timespan objects (dicts with keys start and end and values of !UTC! timestrings)
                EX:
                {
                    'monday': [{start: "1:00", end: "22:00"}],
                    'tuesday': [{start: "1:00", end: "22:00"}, {start: "23:00", end: "24:00"}],
                    ... all days must be present (there should be exactly 7 keys)
                }
            NOTE that POST/PUT is no longer just the availabilities object, but is an object with two keys:
                { trimester: spring/summer/fall, availabilities }
                AND an optional third key for locations
                So the full payload can be { trimester, availabilities, locations}
                Like the availabilities, the locations should be a single dictionary where keys are days, values are
                    default location for that day.
            DELETE: Resets recurring availability to be empty on every day (does not delete
                RecurringAvailability object)
    """

    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        if self.kwargs.get("user_type") == user_types.COUNSELOR:
            return RecurringCounselorAvailability.objects.all()
        return RecurringTutorAvailability.objects.all()

    def get_serializer_class(self):
        return (
            RecurringTutorAvailabilitySerializer
            if self.kwargs["user_type"] == user_types.TUTOR
            else RecurringCounselorAvailabilitySerializer
        )

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if hasattr(request.user, "administrator"):
            return True
        if (hasattr(obj, "tutor") and request.user == obj.tutor.user) or (
            hasattr(obj, "counselor") and request.user == obj.counselor.user
        ):
            return True
        self.permission_denied(request)

    def get_object(self) -> Union[RecurringTutorAvailability, RecurringCounselorAvailability]:
        """ We get tutor or counselor, and then create recurring availability if needed
        """
        if self.kwargs.get("user_type") == user_types.COUNSELOR:
            cw_user = get_object_or_404(Counselor, pk=self.kwargs.get("pk"))
        elif self.kwargs.get("user_type") == user_types.TUTOR:
            cw_user = get_object_or_404(Tutor, pk=self.kwargs.get("pk"))
        else:
            return Response({"detail": "Invalid user type"}, status=status.HTTP_400_BAD_REQUEST)

        mgr = AvailabilityManager(cw_user)
        availability, _ = mgr.get_or_create_recurring_availability()
        self.check_object_permissions(self.request, availability)
        return availability

    def _perform_save_create(self):
        """ Get data for serializer (to save or create) from self.request
        """
        recurring_availability_object = self.get_object()
        new_availability = recurring_availability_object.availability.copy()
        new_locations = recurring_availability_object.locations.copy()
        if not self.request.data.get("trimester"):
            raise ValidationError(detail="Invalid trimester")
        new_availability[self.request.data.get("trimester")] = self.request.data["availability"]
        if "locations" in self.request.data:
            new_locations[self.request.data.get("trimester")] = self.request.data["locations"]
        serializer = self.get_serializer(
            recurring_availability_object,
            data={
                self.kwargs["user_type"]: self.kwargs.get("pk"),
                "availability": new_availability,
                "locations": new_locations,
                "active": True,
            },
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data["availability"])

    def post(self, request, *args, **kwargs):
        return self._perform_save_create()

    def update(self, request, *args, **kwargs):
        return self._perform_save_create()

    def perform_destroy(self, instance):
        """ Override destroy to just reset availability to default (we don't actually delete obj) """
        self.http_method_not_allowed(self.request)


class AvailabilityView(ListAPIView, CreateAPIView):
    """
        Retrieve, create, or delete availability.
        LIST will return availability for tutor identified by 'tutor' or counselor identified by 'counselor'
            query param. If tutor or counselor='all' and user is admin, then availability
            for all tutors/counselors is returned.
            Additional filter args:
                location USE THIS
                    Either the pk of a location, or the actual string "null" to retrieve remote availability
                start {datetime WITH TZ INFO} default: now
                end {datetime WITH TZ INFO} default: 2 weeks from now
                exclude_sessions {bool default: True}
                use_recurring_availability {bool default: True} When True, we'll use recurring availability
                    for days that do not explicitly have other availability set
                for_availability_view: If provided, then we asume we are listing availability for the counselor/tutor
                    availability view and thus WONT apply counselor max meetings and WONT join availabilities at
                    the same location

        CREATE: See docstring on create action
    """

    permission_classes = (IsAuthenticated,)

    def _get_object_manager(self):
        return TutorAvailability if self.kwargs.get("user_type") == user_types.TUTOR else CounselorAvailability

    def get_queryset(self):
        return self._get_object_manager().objects.all()

    def get_serializer_class(self):
        return (
            TutorAvailabilitySerializer
            if self.kwargs.get("user_type") == user_types.TUTOR
            else CounselorAvailabilitySerializer
        )

    def list(self, request, *args, **kwargs):
        query_params = request.query_params
        filter_kwargs = {
            "remove_scheduled_sessions": query_params.get("exclude_sessions", "true") == "true",
            "use_recurring_availability": query_params.get("use_recurring_availability", "true") == "true",
        }
        if query_params.get("for_availability_view"):
            filter_kwargs["join_availabilities_at_different_location"] = False
            filter_kwargs["apply_counselor_max_meetings"] = False
        if query_params.get("location"):
            filter_kwargs["all_locations_and_remote"] = False
            if query_params.get("location") != NULL_STRING:
                filter_kwargs["location"] = get_object_or_404(Location, pk=query_params["location"])
            else:
                filter_kwargs["location"] = None
        else:
            filter_kwargs["all_locations_and_remote"] = True
        if query_params.get("start"):
            start = dateparse.parse_datetime(query_params.get("start"))
            if not start.tzinfo:
                start = start.astimezone(pytz.UTC)
            filter_kwargs["start"] = start
        if query_params.get("end"):
            end = dateparse.parse_datetime(query_params.get("end"))
            if not end.tzinfo:
                end = end.astimezone(pytz.UTC)
            filter_kwargs["end"] = end

        if (query_params.get("counselor") and self.kwargs["user_type"] != user_types.COUNSELOR) or (
            query_params.get("tutor") and self.kwargs["user_type"] != user_types.TUTOR
        ):
            raise ValidationError("Invalid query params (counselor/tutor) for user type")

        user_object_manager = Tutor if self.kwargs["user_type"] == user_types.TUTOR else Counselor
        user_type = self.kwargs["user_type"]

        if query_params.get(user_type) == "all" and hasattr(request.user, "administrator"):
            availabilities = []
            for user in user_object_manager.objects.all():
                availability_manager = AvailabilityManager(user)
                availabilities += availability_manager.get_availability(**filter_kwargs)
        else:
            user = get_object_or_404(user_object_manager, pk=self.kwargs.get("pk"))
            availability_manager = AvailabilityManager(user)
            availabilities = availability_manager.get_availability(**filter_kwargs)
        return Response(availabilities)

    def create(self, request, *args, **kwargs):
        """ Replace tutor/counselor's availability on given days with sets of provided availabilities
            post data is object that contains tutor/counselor's PK and availabilities, by day, for that user.
                These availabilities are referred to as "availability objects". They are objects
                with two properties: a start and end datetime

            !! Start and End times should be INCLUSIVE (i.e. start: 4pm, end: 5pm)
            Availability objects cannot overlap (but the start of one can = the end of another)

            Example:
                {
                    tutor/counselor {number}: <Tutor/Counselor pk>,
                    timezone_offset {number} Offset in minutes of user's local browser time to UTC (result
                        of https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Date/getTimezoneOffset)
                        NOTE THAT FIXEDOFFSET (FROM PYTZ) IS LOCAL TIME - UTC (I.E. -300 FOR EASTERN TIME)
                            BUT IN JS (WHAT WE GET AS PARAMETER HERE) IS UTC - LOCAL TIME.

                    Pass an empty array to indicate that tutor has no availability for that day (i.e. their
                        recurring availability should NOT apply)

                    availability: {
                        '2020-02-01': [{ start: '<datetime>', end: '<datetime>' }, { start: '<datetime>', end: '<datetime>' }]
                        '2020-03-03': [{ start: '<datetime>', end: '<datetime>' }]
                        '2020-03-04': [] // Recurring availability will not be used for this day
                            (stored as an availability object on day with same start and end time)
                    }
                }
            Returns:
                Serialized TutorAvailability objects FOR ONLY THE DAYS PASSED AS KEYS IN POST DATA
        """
        cw_user = get_object_or_404(
            Tutor if self.kwargs["user_type"] == user_types.TUTOR else Counselor, pk=self.kwargs["pk"]
        )

        # Extract days we have availabilities for
        try:
            dates = [(dateparse.parse_date(x), x) for x in request.data["availability"].keys()]
        except ValueError:
            return HttpResponseBadRequest("Invalid date")

        try:
            # We want LOCAL TIME - UTC for pytz
            offset_timezone = pytz.FixedOffset(-1 * int(request.data.get("timezone_offset")))
        except TypeError:
            return HttpResponseBadRequest("Invalid timezone offset")

        # Validate
        for date, date_string in dates:
            validation_result = AvailabilityManager.updated_availabilities_are_valid(
                date, request.data["availability"][date_string], offset_timezone
            )
            if not validation_result[0]:
                return HttpResponseBadRequest(f"Validation error for date {date_string}: {validation_result[1]}")

        # Delete availabilities that already exist on our extracted days
        # Use timezone to determine actual start and end of user's day
        AvailabilityObject = self._get_object_manager()
        queryset = AvailabilityObject.objects.none()
        for date, date_string in dates:
            date_start = datetime(date.year, date.month, date.day, tzinfo=offset_timezone)
            filter_data = {
                "start__gte": date_start,
                "end__lte": (date_start + timedelta(days=1)),
                self.kwargs["user_type"]: cw_user,
            }

            queryset |= AvailabilityObject.objects.filter(**filter_data)

        altering_existing_availabilities = queryset.exists()
        queryset.filter(**{self.kwargs["user_type"]: cw_user}).delete()

        # Create new availabilities and return them
        # Note that we default to recurring availability location if location is undefined (but NOT NULL) for
        # an availability
        availabilities = []
        for date, sessions in request.data["availability"].items():
            # If there are no sessions, then value for date is empty list. So we make this a day that recurring
            # availability does not apply to by creating an availability object with same start and end
            if len(sessions) == 0:
                date_obj = dateparse.parse_date(date)
                date_start = datetime(date_obj.year, date_obj.month, date_obj.day, 12, tzinfo=offset_timezone,)
                availabilities.append(
                    AvailabilityObject.objects.create(
                        **{self.kwargs["user_type"]: cw_user, "start": date_start, "end": date_start}
                    )
                )
            for session in sessions:
                availabilities.append(
                    AvailabilityObject.objects.create(
                        **{
                            self.kwargs["user_type"]: cw_user,
                            "start": dateparse.parse_datetime(session["start"]),
                            "end": dateparse.parse_datetime(session["end"]),
                            "location_id": session.get("location"),
                        }
                    )
                )

        if altering_existing_availabilities and self.kwargs["user_type"] == user_types.TUTOR:
            for admin in Administrator.objects.all():
                create_notification(
                    admin.user,
                    notification_type="tutor_altered_availability",
                    related_object_content_type=ContentType.objects.get_for_model(Tutor),
                    related_object_pk=cw_user.pk,
                    additional_args={"start_date": dates[0][0]},
                )

        # We return list of TutorAvailability objects
        SerializerClass = (
            TutorAvailabilitySerializer if AvailabilityObject == TutorAvailability else CounselorAvailabilitySerializer
        )
        return Response(SerializerClass(availabilities, many=True).data)

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method.lower() == "post":
            cw_user = get_object_or_404(
                Tutor if self.kwargs["user_type"] == user_types.TUTOR else Counselor, pk=self.kwargs["pk"]
            )
            # User must be admin or this tutor
            if not (hasattr(request.user, "administrator") or cw_user.user == request.user):
                self.permission_denied(request, message=f"No access to {cw_user.user_type}")

