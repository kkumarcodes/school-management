""" General manager for working with tutor and counselor
    availability and recurring availability
"""
from typing import Union, Tuple
from datetime import datetime, time, timedelta, date
from django.db.models.query_utils import Q
from django.utils import timezone, dateparse
from django.conf import settings
import sentry_sdk
from rest_framework.serializers import ValidationError
import pytz

from snusers.utilities.graph_helper import (
    outlook_retrieve,
    GraphHelperException,
)
from snusers.models import Counselor, Tutor
from snusers.constants.user_types import COUNSELOR, TUTOR
from cwcounseling.models import CounselorMeeting, RecurringCounselorAvailability
from cwcommon.serializers.availability import AvailableTimespanSerializer
from cwtutoring.models import GroupTutoringSession, Location, RecurringTutorAvailability


class AvailabilityManagerException(Exception):
    pass


class AvailabilityManager:
    cw_user: Union[Counselor, Tutor] = None

    def __init__(self, cw_user: Union[Counselor, Tutor]) -> None:
        """ user {User for Tutor or Counselor we are managing availability for} """
        super().__init__()
        if not (isinstance(cw_user, Tutor), isinstance(cw_user, Counselor)):
            raise AvailabilityManagerException("Can only manage availability for tutors and counselors")
        self.cw_user = cw_user

    def get_or_create_recurring_availability(
        self,
    ) -> Tuple[Union[RecurringTutorAvailability, RecurringCounselorAvailability], bool]:
        self.cw_user.refresh_from_db()
        if hasattr(self.cw_user, "recurring_availability"):
            return (self.cw_user.recurring_availability, False)
        if isinstance(self.cw_user, Tutor):
            return (RecurringTutorAvailability.objects.create(tutor=self.cw_user), True)
        return (RecurringCounselorAvailability.objects.create(counselor=self.cw_user), True)

    def get_outlook_sessions(self, start, end):
        """ Helper method that can be used to get all outlook sessions for self.cw_user. Note that if user syncs their
            UMS calendar with Outlook, this WILL include timespans of UMS sessions
        """
        outlook_list = []
        try:
            if self.cw_user.microsoft_token:
                outlook_list = outlook_retrieve(self.cw_user, start, end)
        except GraphHelperException as err:
            if settings.TESTING or settings.DEBUG:
                print(err)
            else:
                with sentry_sdk.configure_scope() as scope:
                    scope.set_context("Outlook", {"start": str(start), "end": str("end"), "user": str(self.cw_user)})
                    scope.set_tag("debugging", "outlook")
                    sentry_sdk.capture_exception(err)
        # 1. For any 'all day' outlook events, put start/end times into timezone of tutor.
        # 2. Remove from list any events we already have an outlook_event_id for.
        for x in outlook_list:
            if x.is_all_day:
                tutor_tz_object = pytz.timezone(self.cw_user.timezone)
                naive_start = timezone.make_naive(x.start)
                aware_start = timezone.make_aware(naive_start, tutor_tz_object)
                naive_end = timezone.make_naive(x.end)
                aware_end = timezone.make_aware(naive_end, tutor_tz_object)
                x.start = aware_start
                x.end = aware_end
        return outlook_list

    def get_availability(
        self,
        start=None,
        end=None,
        return_date_objects=False,
        remove_scheduled_sessions=True,
        use_recurring_availability=True,
        location: Location = None,
        all_locations_and_remote=True,
        join_availabilities_at_different_location=True,
        apply_counselor_max_meetings=True,
    ):
        """ Retrieve a list of AvailableTimespanSerializer data objects representing
            spans of time that tutor is available for individual sessions.
            We exclude times tha are already booked.
            Arguments:
                start {datetime} (defaults now)
                end {datetime} (defaults four weeks from now)
                return_date_objects {bool} Determines whether date objects are returned, or
                    a serialized list of AvailableTimespanSerializer objects are returned
                remove_scheduled_sessions {bool} Whether or not scheduled sessions should be removed
                    from availability.
                    Excludes StudentTutoringSession/GroupTutoringSession for tutors, and CounselorMeeting for counselors
                use_recurring_availability {bool default: True} When True, we'll use recurring availability
                    for days that do not explicitly have other availability set
                all_locations_and_remote:
                    Whether or not we should return all of the user's availability, regardless of whether it is
                    for in-person or remote.
                    If False, then we look at location argument.
                location:
                    Ignored if all_locations_and_remote is true
                    The specific location we are getting availability for; remote availability returned if this is None
                join_availabilities_at_different_location:
                    We adjoin availabilities that abutting (end of one = start of next). This setting allows disabling
                    the joining of availabilities if they are at different locations
                apply_counselor_max_meetings:
                    Whether or not the max meetings for a counselor should be applied, in which case availability
                    won't be returned for days when counselor already has their max meetings
            Returns: Array of availability objects
        """
        if not start:
            now = timezone.now()
            start = datetime(now.year, now.month, now.day).astimezone(pytz.UTC)
        if not end:
            end = start + timedelta(weeks=4)

        availability_filter_kwargs = {"start__lte": end, "end__gte": start}

        include_all_availability = all_locations_and_remote or (
            self.cw_user.include_all_availability_for_remote_sessions and location is None
        )
        if not include_all_availability:
            availability_filter_kwargs["location"] = location

        availabilities = list(
            self.cw_user.availabilities.filter(**availability_filter_kwargs).order_by("start").distinct()
        )

        availabilities = [
            {
                "start": x.start.astimezone(pytz.timezone(self.cw_user.timezone)),
                "end": x.end.astimezone(pytz.timezone(self.cw_user.timezone)),
                self.cw_user.user_type: self.cw_user.pk,
                "location": x.location.pk if x.location else None,
            }
            for x in availabilities
        ]

        (recurring_availability, created_recurring_availability,) = self.get_or_create_recurring_availability()
        # We add availabilities based on recurring availabilities for days with no availabilities
        if use_recurring_availability and not created_recurring_availability:
            days = set(
                [
                    x["start"].astimezone(pytz.timezone(self.cw_user.timezone)).strftime("%y-%m-%d")
                    for x in availabilities
                ]
            )
            current_day = start
            while current_day < end:
                # If we don't have specific availability set for this day, we get recurring availability for this
                # weekday
                if current_day.strftime("%y-%m-%d") not in days:
                    ra_schedule = recurring_availability.get_availability_for_date(current_day)

                    # We loop through all recurring availabilities for the weekday that is current_day
                    weekday = RecurringTutorAvailability.ORDERED_WEEKDAYS[current_day.weekday()]
                    trimester = recurring_availability.get_trimester_for_date(current_day)

                    # We only use recurring availability if it matches our filtered location (or we are
                    # getting availability for all locations)
                    recurring_availability_schedule = ra_schedule[weekday]
                    # recurring_availability_location = recurring_availability.get_location_for_date(current_day)
                    # # Escape hatch to not use recurring availability if it is for the wrong location
                    # if (not include_all_availability) and recurring_availability_location != (
                    #     location.pk if location else None
                    # ):
                    #     recurring_availability_schedule = []

                    for recurring_availability_span in recurring_availability_schedule:

                        # Create span with times in tutor's timezone
                        availability_start = datetime(
                            current_day.year,
                            current_day.month,
                            current_day.day,
                            dateparse.parse_time(recurring_availability_span["start"]).hour,
                            dateparse.parse_time(recurring_availability_span["start"]).minute,
                            0,
                        ).astimezone(pytz.timezone(self.cw_user.timezone))

                        availability_end = datetime(
                            current_day.year,
                            current_day.month,
                            current_day.day,
                            dateparse.parse_time(recurring_availability_span["end"]).hour,
                            dateparse.parse_time(recurring_availability_span["end"]).minute,
                            0,
                        ).astimezone(pytz.timezone(self.cw_user.timezone))

                        # We exclude this availability if it's on a day that IS in days
                        # to account for the fact that recurring availability is timezone-independent
                        if (
                            availability_start.strftime("%y-%m-%d") in days
                            and availability_end.strftime("%y-%m-%d") in days
                        ):
                            continue

                        # We also exclude this availability if it's actually on a day that is not the correct location
                        recurring_availability_location = recurring_availability.get_location_for_date(availability_end)
                        if (not include_all_availability) and recurring_availability_location != (
                            location.pk if location else None
                        ):
                            continue

                        # But there's a GOTCHYA! If the date is after fall back or after spring forward, we need
                        # to adjust accordingly
                        if (
                            trimester == RecurringTutorAvailability.TRIMESTER_FALL
                            and availability_start.dst().seconds == 0
                        ):
                            availability_start += timedelta(seconds=3600)
                            availability_end += timedelta(seconds=3600)

                        elif (
                            trimester == RecurringTutorAvailability.TRIMESTER_SPRING
                            and availability_start.dst().seconds > 0
                        ):
                            pass
                            # availability_start -= timedelta(seconds=3600)
                            # availability_end -= timedelta(seconds=3600)

                        availabilities.append(
                            {
                                "start": availability_start,
                                "end": availability_end,
                                self.cw_user.user_type: self.cw_user.pk,
                                "location": recurring_availability_location,
                            }
                        )
                current_day += timedelta(days=1)

            # We have to re-sort our list
            availabilities.sort(key=lambda x: x["start"].isoformat())

        # Availablities that end at :59 ar really a hack for ending at 00 the next day, we just can't store
        # dates that way. So we hadd a minute to all of those
        for availability in availabilities:
            if availability["end"].minute == 59:
                availability["end"] += timedelta(minutes=1)

        # If counselor has reached their max meetings per day for a day, then we remove all availabilities for that day]
        if (
            isinstance(self.cw_user, Counselor)
            and self.cw_user.max_meetings_per_day is not None
            and apply_counselor_max_meetings
        ):
            bad_days = []
            current_day = datetime(start.year, start.month, start.day).astimezone(pytz.timezone(self.cw_user.timezone))
            while current_day <= end.astimezone(pytz.timezone(self.cw_user.timezone)):
                current_day_start = datetime(current_day.year, current_day.month, current_day.day).astimezone(
                    pytz.timezone(self.cw_user.timezone)
                )
                sessions = CounselorMeeting.objects.filter(
                    start__gte=current_day_start,
                    start__lte=current_day_start + timedelta(hours=24),
                    student__counselor=self.cw_user,
                )

                if sessions.count() >= self.cw_user.max_meetings_per_day:
                    [bad_days.append(x.start.strftime("%y-%m-%d")) for x in sessions]
                current_day += timedelta(hours=24)
            if bad_days:
                availabilities = [x for x in availabilities if x["start"].strftime("%y-%m-%d") not in bad_days]

        # Do a pass to adjoin abutting availabilities
        idx = 0
        while idx < len(availabilities) - 1:
            first = availabilities[idx]
            second = availabilities[idx + 1]
            if first["end"] == second["start"] and (
                first["location"] == second["location"] or join_availabilities_at_different_location
            ):
                first["end"] = second["end"]
                availabilities.pop(idx + 1)
            else:
                idx += 1

        if remove_scheduled_sessions:
            if isinstance(self.cw_user, Tutor):
                individual_sessions = self.cw_user.student_tutoring_sessions.filter(
                    start__lte=end, end__gte=start, set_cancelled=False
                )
                group_sessions = GroupTutoringSession.objects.filter(
                    Q(Q(primary_tutor=self.cw_user) | Q(support_tutors=self.cw_user))
                ).filter(start__lte=end, end__gte=start, cancelled=False)
                sessions = list(individual_sessions) + list(group_sessions)
            else:
                sessions = list(
                    CounselorMeeting.objects.filter(
                        student__counselor=self.cw_user, cancelled=None, start__lte=end, end__gte=start
                    )
                )

            # If user is counselor and they have buffer time between meetings, add buffer to end of all sessions
            if isinstance(self.cw_user, Counselor) and self.cw_user.minutes_between_meetings:
                for session in sessions:
                    session.end += timedelta(minutes=self.cw_user.minutes_between_meetings)
                    session.start -= timedelta(minutes=self.cw_user.minutes_between_meetings)

            # Sanitize sessions to get rid of seconds on their start/end
            for session in sessions:
                session.start = datetime(
                    session.start.year,
                    session.start.month,
                    session.start.day,
                    session.start.hour,
                    session.start.minute,
                    tzinfo=session.start.tzinfo,
                )
                session.end = datetime(
                    session.end.year,
                    session.end.month,
                    session.end.day,
                    session.end.hour,
                    session.end.minute,
                    tzinfo=session.end.tzinfo,
                )

            # For each availability, we find sessions that overlap with it
            # We create new availability objects that represent availability from our availability, less any
            # time included in a session
            # filter out cancelled sessions first
            outlook_ids = set([i.outlook_event_id for i in sessions])
            outlook_list = self.get_outlook_sessions(start, end)

            combined_sessions = sessions + [x for x in outlook_list if not x.object_id in outlook_ids]
            combined_sessions.sort(key=lambda x: x.start)

            # The below algorithm only works when combined sessions are non-overlapping. So... we de-overlap them!
            idx = 0
            while idx < len(combined_sessions) - 1:
                # Since sessions are already sorted, we know they overlap iff a session starts before the previous
                # session ends
                if combined_sessions[idx + 1].start < combined_sessions[idx].end:
                    combined_sessions[idx].end = max(combined_sessions[idx + 1].end, combined_sessions[idx].end)
                    del combined_sessions[idx + 1]
                    continue
                idx += 1

            if len(combined_sessions) > 0:
                new_availabilities = []
                for availability in availabilities:
                    avail_start = availability["start"]
                    avail_end = availability["end"]
                    filtered_sessions = [x for x in combined_sessions if x.start <= avail_end and x.end >= avail_start]

                    for session in filtered_sessions:
                        # Note that this is explicitly not >=, because we don't want to create a timespan
                        # with the same start and end time. Useless!
                        if session.start > avail_start:
                            new_availabilities.append(
                                {
                                    "start": avail_start.astimezone(pytz.timezone(self.cw_user.timezone)),
                                    "end": session.start.astimezone(pytz.timezone(self.cw_user.timezone)),
                                    self.cw_user.user_type: self.cw_user.pk,
                                    "location": availability["location"],
                                }
                            )
                        avail_start = session.end
                    if avail_start < avail_end:
                        new_availabilities.append(
                            {
                                "start": avail_start.astimezone(pytz.timezone(self.cw_user.timezone)),
                                "end": avail_end.astimezone(pytz.timezone(self.cw_user.timezone)),
                                self.cw_user.user_type: self.cw_user.pk,
                                "location": availability["location"],
                            }
                        )
                availabilities = new_availabilities
        # Timespansans have counselor and tutor fields. Our serializer will complain if both of those keys aren't
        # on our availability objects
        user_type = TUTOR if self.cw_user.user_type == COUNSELOR else COUNSELOR
        for x in availabilities:
            x[user_type] = None

        return availabilities if return_date_objects else AvailableTimespanSerializer(availabilities, many=True,).data

    def individual_time_is_available(self, start, end):
        """ Confirm that time with user is available """
        # Make sure tutor has an availability that fully covers our desired time
        availabilities = self.get_availability(start=start, end=end, return_date_objects=True)
        return any([x["end"] >= end and x["start"] <= start for x in availabilities])

    @staticmethod
    def updated_availabilities_are_valid(day_date, availability_objects, timezone_object):
        """ This utility methods checks whether a set of availability objects are
            valid for a tutor, for a given day.
            Raises TypeError if any date in availability_objects can't be parsed.
            Returns False if any date in availability_objects starts or ends NOT on date
            THIS IS NO LONGER TRUE -> Returns False if and only if proposed availability_objects fail to cover an
                already scheduled, uncancelled StudentTutoringSession or GroupTutoringSession
                for tutor. <- THIS IS NO LONGER TRUE
            Returns False if any availabilities overlap

            Arguments:
                day_date {DateTime} representing start of day we are checking availabilities for. Will
                    apply timezone_object to day_date!
                tutor {Tutor} tutor availabilities are for
                availability_objects {Array<{ 'start', 'end' }>} List of objects with start and end properties,
                    representing ALL of the new availabilities for tutor on date (where date is date param).
                    All availability_objects must start and end on date.
                    It is assumed that availability_objects represent entirety of tutor's proposed new
                        availability for date
                timezone_object {Pytz timezone} User's local timezone.
            Returns Tuple (bool, string):
                Boolean indicating whether or not availabilities are valid, string is user-readable error message
        """
        # We apply timezone to date, to get correct start and end for user's day
        if isinstance(day_date, date):
            day_start = datetime(day_date.year, day_date.month, day_date.day, 0, tzinfo=timezone_object)
        elif isinstance(day_date, datetime):
            day_start = day_date.astimezone(timezone_object)
        day_end = day_start + timedelta(days=1)
        # We parse all dates in availability_objects
        # Note that these datetimes will come via UTC, but were created in user's timezone
        datetimed_availabilities = sorted(
            [[dateparse.parse_datetime(x["start"]), dateparse.parse_datetime(x["end"]),] for x in availability_objects],
            key=lambda x: x[0],
        )

        # Loop through our availabilities, join connected or overlapping availabilities
        idx = 0
        while idx < len(datetimed_availabilities) - 1:
            # Overlap check
            if datetimed_availabilities[idx][1] > datetimed_availabilities[idx + 1][0]:
                return (
                    False,
                    f"Overlapping availabilities at {datetimed_availabilities[idx][1]} > {datetimed_availabilities[idx + 1][0]}",
                )
            # Join adjacent availabilities
            if datetimed_availabilities[idx][1] == datetimed_availabilities[idx + 1][0]:
                datetimed_availabilities[idx][1] = datetimed_availabilities[idx + 1][1]
                datetimed_availabilities.pop(idx + 1)
            idx += 1

        if datetimed_availabilities and datetimed_availabilities[-1][1] > day_end:
            return (False, "Dates span multiple days")

        return (True, "")

    def validate_locations(self, new_locations: dict, raise_exception=True) -> bool:
        """ Validate the default locations data that is to be set on RecurringAvailability.locations """
        # Ensure that each trimester key and day in data, and then ensure that value is either null
        # or a valid location
        try:
            locations = set([])
            for trimester_key in (
                RecurringTutorAvailability.TRIMESTER_FALL,
                RecurringTutorAvailability.TRIMESTER_SPRING,
                RecurringTutorAvailability.TRIMESTER_SUMMER,
            ):
                if not trimester_key in new_locations:
                    raise ValidationError(f"Missing Trimester in Locations: {trimester_key}")
                for day_key in RecurringTutorAvailability.ORDERED_WEEKDAYS:
                    trimester_val = new_locations[trimester_key]
                    if day_key not in trimester_val:
                        raise ValidationError(f"Missing day key in Locations.{trimester_key}: {day_key}")
                    val = trimester_val[day_key]
                    if val is None:
                        continue
                    locations.add(val)
                for location_pk in locations:
                    if not Location.objects.filter(pk=location_pk).exists():
                        raise ValidationError(f"Invalid location: {location_pk}")
        except ValidationError as err:
            if raise_exception:
                raise err
            return False

    def validate_recurring_availability(self, new_availability: dict, raise_exception=True) -> bool:
        """ This method validates a new set of recurring availability (as JSON)
        """

        def parse_time_or_type_error(time: str) -> time:
            val = dateparse.parse_time(time)
            if not val:
                raise TypeError(f"Invalid time: {time}")
            return val

        try:
            for trimester_key in (
                RecurringTutorAvailability.TRIMESTER_FALL,
                RecurringTutorAvailability.TRIMESTER_SPRING,
                RecurringTutorAvailability.TRIMESTER_SUMMER,
            ):
                if not trimester_key in new_availability:
                    raise ValidationError(f"Missing Trimester: {trimester_key}")
                for day_key in RecurringTutorAvailability.ORDERED_WEEKDAYS:
                    trimester_val = new_availability[trimester_key]
                    if day_key not in trimester_val:
                        raise ValidationError(f"Missing day key: {day_key}")
                    # Confirm no overlapping availability. Also confirms values are valid times
                    try:
                        sorted_time_objects = sorted(
                            trimester_val[day_key], key=lambda x: parse_time_or_type_error(x["start"])
                        )
                        # Just to ensure end times are also valid. Except they may end at

                        [parse_time_or_type_error(x["end"]) for x in trimester_val[day_key] if x["end"] != "24:00"]
                    except (TypeError, ValueError) as err:
                        raise ValidationError(
                            f"Invalid time on {trimester_key} {day_key} val {trimester_val[day_key]}: {err}"
                        )
                    if len(sorted_time_objects) > 1:
                        for idx in range(len(sorted_time_objects) - 1):
                            if dateparse.parse_time(sorted_time_objects[idx]["start"]) >= dateparse.parse_time(
                                sorted_time_objects[idx]["end"]
                            ):
                                raise ValidationError(f"Invalid time span on {day_key}: {sorted_time_objects[idx]}")
                            if dateparse.parse_time(sorted_time_objects[idx]["end"]) > dateparse.parse_time(
                                sorted_time_objects[idx + 1]["start"]
                            ):
                                raise ValidationError(f"Overlapping availability on {day_key}")
            return True
        except ValidationError as err:
            if raise_exception:
                raise err
            return False
