""" Test availability manager and views (for tutors and counselors)
    python manage.py test sncommon.tests.test_availability
"""
import json
import random
from datetime import timedelta, datetime
from typing import Union
import pytz

from django.test import TestCase
from django.shortcuts import reverse
from django.utils import timezone, dateparse
from django.utils.http import urlencode
from sncommon.models import BaseRecurringAvailability, get_default_locations
from sncommon.utilities.availability_manager import AvailabilityManager
from sncounseling.models import CounselorAvailability, CounselorMeeting, RecurringCounselorAvailability

from snusers.models import Counselor, Student, Tutor, Administrator
from sntutoring.models import (
    Location,
    TutorAvailability,
    StudentTutoringSession,
    GroupTutoringSession,
    RecurringTutorAvailability,
)
from sntutoring.constants import (
    RECURRING_AVAILABILITY_SUMMER_START_MONTH,
    RECURRING_AVAILABILITY_FALL_START_MONTH,
)

# UTC offset from JS for Eastern Timezone
EASTERN_TIMEZONE_OFFSET = 300


def create_availability_dict():
    """ Create a dict of data like what would be recieved from frontend to create/update obj
    """
    data = {}
    for weekday in RecurringTutorAvailability.ORDERED_WEEKDAYS:
        data[weekday] = [
            {"start": f"{random.randint(0, 3)}:00", "end": f"{random.randint(4, 5)}:00",},
            {"start": f"{random.randint(7, 12)}:00", "end": f"{random.randint(20, 24)}:00",},
        ]
    # Good to have one day end at 24
    data["tuesday"][1]["end"] = "24:00"
    return data


class TestRecurringAvailabilityView(TestCase):
    """ python manage.py test sncommon.tests.test_availability:TestRecurringAvailabilityView
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.tutor = Tutor.objects.first()
        self.counselor = Counselor.objects.first()
        self.student = Student.objects.first()
        self.admin = Administrator.objects.first()

    def _create_dict(self):
        """ Create a dict of data like what would be recieved from frontend to create/update obj
        """
        return create_availability_dict()

    def test_create_update(self):
        """ Create or update availability """
        for cw_user in (self.tutor, self.counselor):
            # Create
            trimester = RecurringTutorAvailability.get_trimester_for_date(timezone.now())
            data = {
                "trimester": trimester,
                "availability": self._create_dict(),
                "locations": get_default_locations()[trimester],
            }
            self.client.force_login(cw_user.user)
            self.assertFalse(cw_user.availabilities.exists())
            url = reverse(f"{cw_user.user_type}_recurring_availability-detail", kwargs={"pk": cw_user.pk})
            response = self.client.post(url, json.dumps(data), content_type="application/json",)

            self.assertEqual(response.status_code, 200)
            availability = cw_user.recurring_availability
            self.assertDictEqual(availability.availability[trimester], data["availability"])

            # Then update
            updated_data = self._create_dict()
            updated_data["wednesday"] = []
            updated_data["friday"] = []
            updated_data["monday"] = [{"start": "3:20", "end": "22:00"}]

            updated_locations = data["locations"].copy()
            updated_locations["monday"] = Location.objects.first().pk

            response = self.client.put(
                url,
                json.dumps({"trimester": trimester, "availability": updated_data, "locations": updated_locations}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            availability.refresh_from_db()
            self.assertDictEqual(availability.availability[trimester], updated_data)
            self.assertEqual(availability.locations[trimester]["monday"], Location.objects.first().pk)

            # Finaly can create via update
            self.client.force_login(self.admin.user)
            RecurringTutorAvailability.objects.all().delete()
            response = self.client.put(
                url,
                json.dumps({"trimester": trimester, "availability": updated_data}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            cw_user.refresh_from_db()
            self.assertTrue(hasattr(cw_user, "recurring_availability"))

    def test_failure(self):
        # Login required
        data = {"trimester": "summer", "availability": self._create_dict()}
        response = self.client.post(
            reverse("tutor_recurring_availability-detail", kwargs={"pk": self.tutor.pk}),
            json.dumps(data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

        # Auth required
        self.client.force_login(self.student.user)
        data = self._create_dict()
        response = self.client.post(
            reverse("counselor_recurring_availability-detail", kwargs={"pk": self.counselor.pk}),
            json.dumps(data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        # Validation error
        data = self._create_dict()
        data["monday"] = [{"start": "NO", "end": "23:00"}]
        del data["tuesday"]
        for cw_user in (self.tutor, self.counselor):
            self.client.force_login(cw_user.user)
            response = self.client.post(
                reverse(f"{cw_user.user_type}_recurring_availability-detail", kwargs={"pk": cw_user.pk}),
                json.dumps({"trimester": "spring", "availability": data}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)

    def test_delete(self):
        # Resets to default availability
        availability = self._create_dict()
        RecurringTutorAvailability.objects.create(tutor=self.tutor, availability=availability)
        self.client.force_login(self.tutor.user)
        response = self.client.delete(reverse("tutor_recurring_availability-detail", kwargs={"pk": self.tutor.pk}))
        self.assertEqual(response.status_code, 405)

        RecurringCounselorAvailability.objects.create(counselor=self.counselor, availability=availability)
        self.client.force_login(self.counselor.user)
        response = self.client.delete(
            reverse("counselor_recurring_availability-detail", kwargs={"pk": self.counselor.pk})
        )
        self.assertEqual(response.status_code, 405)


class TestAvailabilityViewset(TestCase):
    """
        python manage.py test sncommon.tests.test_availability:TestAvailabilityViewset
        This class implicitly also tests tutoring session manager's get_availability, inclding
            ensuring scheduled sessions are removed from tutor's availability
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.tutor: Tutor = Tutor.objects.first()
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.location = Location.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.tutor.students.add(self.student)
        self.url = reverse("tutor_availability-detail", kwargs={"pk": self.tutor.pk})

        self.admin = Administrator.objects.first()
        # Available from 11-1 tomorrow and the next day
        now = timezone.now().astimezone(pytz.timezone("UTC"))
        tomorrow = now + timedelta(days=1)
        self.tomorrow = tomorrow
        dbltomorrow = tomorrow + timedelta(days=1)
        self.trimester = BaseRecurringAvailability.get_trimester_for_date(
            datetime(tomorrow.year, tomorrow.month, tomorrow.day, 11)
        )
        self.availabilities = {
            "tutor": [
                TutorAvailability.objects.create(
                    tutor=self.tutor,
                    start=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 11).astimezone(pytz.timezone("UTC")),
                    end=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 13).astimezone(pytz.timezone("UTC")),
                ),
                TutorAvailability.objects.create(
                    tutor=self.tutor,
                    start=datetime(dbltomorrow.year, dbltomorrow.month, dbltomorrow.day, 11).astimezone(
                        pytz.timezone("UTC")
                    ),
                    end=datetime(dbltomorrow.year, dbltomorrow.month, dbltomorrow.day, 13).astimezone(
                        pytz.timezone("UTC")
                    ),
                ),
            ],
            "counselor": [
                CounselorAvailability.objects.create(
                    counselor=self.counselor,
                    start=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 11).astimezone(pytz.timezone("UTC")),
                    end=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 13).astimezone(pytz.timezone("UTC")),
                ),
                CounselorAvailability.objects.create(
                    counselor=self.counselor,
                    start=datetime(dbltomorrow.year, dbltomorrow.month, dbltomorrow.day, 11).astimezone(
                        pytz.timezone("UTC")
                    ),
                    end=datetime(dbltomorrow.year, dbltomorrow.month, dbltomorrow.day, 13).astimezone(
                        pytz.timezone("UTC")
                    ),
                ),
            ],
        }

    def _confirm_availability_sans_session(
        self, session: Union[StudentTutoringSession, GroupTutoringSession, CounselorMeeting]
    ):
        # Helper method to confirm either CounselorMeeting, STS or GTS is excluded from availability
        self.client.force_login(self.student.user)
        if isinstance(session, CounselorMeeting):
            url = reverse("counselor_availability-detail", kwargs={"pk": self.counselor.pk})
            availabilities = self.availabilities["counselor"]
        else:
            url = reverse("tutor_availability-detail", kwargs={"pk": self.tutor.pk})
            availabilities = self.availabilities["tutor"]
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(len(result), 3)
        self.assertEqual(dateparse.parse_datetime(result[0]["start"]), availabilities[0].start)
        self.assertEqual(dateparse.parse_datetime(result[0]["end"]), session.start)

        self.assertEqual(dateparse.parse_datetime(result[1]["start"]), session.end)
        self.assertEqual(dateparse.parse_datetime(result[-1]["end"]), availabilities[1].end)

    def test_availability_with_session(self):
        # Add session in tomorrow's block, new availabilities

        session = StudentTutoringSession.objects.create(
            start=(self.availabilities["tutor"][0].start + timedelta(minutes=5)),
            end=(self.availabilities["tutor"][0].end - timedelta(minutes=5)),
            student=self.student,
            individual_session_tutor=self.tutor,
        )
        self._confirm_availability_sans_session(session)

        session.delete()
        GroupTutoringSession.objects.create(
            start=(self.availabilities["tutor"][0].start + timedelta(minutes=5)),
            end=(self.availabilities["tutor"][0].end - timedelta(minutes=5)),
            primary_tutor=self.tutor,
        )
        self._confirm_availability_sans_session(session)

        cm = CounselorMeeting.objects.create(
            student=self.student,
            start=(self.availabilities["counselor"][0].start + timedelta(minutes=5)),
            end=(self.availabilities["counselor"][0].end - timedelta(minutes=5)),
        )
        self._confirm_availability_sans_session(session)
        cm.delete()

    def test_failure(self):
        # Fails if not authenticated
        for cw_user in (self.tutor, self.counselor):
            self.client.logout()
            url = reverse(f"{cw_user.user_type}_availability-detail", kwargs={"pk": cw_user.pk})
            response = self.client.get(url)
            assert response.status_code == 401

            # Fails to create if no access to tutor/counselor
            self.client.force_login(self.student.user)
            data = {
                cw_user.user_type: cw_user.pk,
                "start": str(self.tomorrow),
                "end": str((self.tomorrow + timedelta(hours=4))),
            }
            response = self.client.post(self.url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 403)

    def test_filter_location(self):
        """ Test filtering availability (not recurring) on location. Includes testing retreiving recurring
            availability based on location as well
            python manage.py test sncommon.tests.test_availability:TestAvailabilityViewset.test_filter_location
        """
        availabilities = self.availabilities["tutor"]
        self.client.force_login(self.tutor.user)
        url = reverse(f"tutor_availability-detail", kwargs={"pk": self.tutor.pk})
        response = self.client.get(url)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)

        availabilities[0].location = self.location
        availabilities[0].save()
        location_url = url + f"?location={self.location.pk}"
        response = self.client.get(location_url)
        result = json.loads(response.content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["location"], self.location.pk)

        location_url = url + f"?location=null"
        response = self.client.get(location_url)
        result = json.loads(response.content)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["location"], None)

        # But if tutor has setting on to display all availability for remote sessions, then we should see
        # in-person availability again
        self.tutor.include_all_availability_for_remote_sessions = True
        self.tutor.save()
        response = self.client.get(location_url)
        result = json.loads(response.content)
        self.assertEqual(len(result), 2)

    def test_list(self):
        for cw_user in (self.tutor, self.counselor):
            self.client.force_login(self.student.user)
            availabilities = self.availabilities[cw_user.user_type]
            availabilities[1].start = availabilities[0].end
            availabilities[1].end = availabilities[1].start + timedelta(hours=1)
            availabilities[1].save()
            url = reverse(f"{cw_user.user_type}_availability-detail", kwargs={"pk": cw_user.pk})
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            revert_availability = availabilities[1]
            self.assertEqual(len(result), 1)
            # Confirm availabilities were combined
            self.assertEqual(
                dateparse.parse_datetime(result[0]["start"]), availabilities[0].start,
            )
            self.assertEqual(
                dateparse.parse_datetime(result[0]["end"]), availabilities[1].end,
            )

            revert_availability.save()

            # Filter to exclude based on start
            url_data = {
                "start": (availabilities[0].end + timedelta(hours=1)).isoformat(),
            }
            url = f"{self.url}?{urlencode(url_data)}"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            self.assertEqual(len(result), 1)

            # Filter based on end
            del url_data["start"]
            url_data["end"] = (availabilities[0].end + timedelta(hours=2)).isoformat()
            url = f"{self.url}?{urlencode(url_data)}"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            self.assertEqual(len(result), 1)

            # Sessions are removed from availability by default
            if isinstance(cw_user, Tutor):
                StudentTutoringSession.objects.create(
                    student=self.student,
                    individual_session_tutor=self.tutor,
                    start=availabilities[0].start,
                    end=availabilities[0].end,
                )
            else:
                CounselorMeeting.objects.create(
                    student=self.student, start=availabilities[0].start, end=availabilities[0].end,
                )
            url = reverse(f"{cw_user.user_type}_availability-detail", kwargs={"pk": cw_user.pk})
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            self.assertEqual(len(result), 1)

            # Test removing and including scheduled sessions in returned availabilities
            response = self.client.get(f"{url}?exclude_sessions=false")
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            self.assertEqual(len(result), 1)
            self.assertEqual(
                dateparse.parse_datetime(result[0]["start"]), availabilities[0].start,
            )
            self.assertEqual(
                dateparse.parse_datetime(result[0]["end"]), availabilities[1].end,
            )

            response = self.client.get(f"{url}?exclude_sessions=true")
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            self.assertEqual(len(result), 1)
            self.assertEqual(
                dateparse.parse_datetime(result[0]["start"]), availabilities[1].start,
            )
            self.assertEqual(
                dateparse.parse_datetime(result[0]["end"]), availabilities[1].end,
            )

    def _test_post_availabilities(self, data, availability_objects):
        """ Helper method to test posting availability objects and then confirming availabilities are correct
            Posts for both self.tutor and self.counselor
            Does not change logged in user
        """
        for cw_user in (self.tutor, self.counselor):
            self.client.force_login(cw_user.user)
            url = reverse(f"{cw_user.user_type}_availability-detail", kwargs={"pk": cw_user.pk})
            response = self.client.post(url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            self.assertEqual(len(result), 2)
            for idx, elt in enumerate(result):
                if isinstance(cw_user, Tutor):
                    availability = TutorAvailability.objects.get(pk=elt["pk"])
                    self.assertEqual(availability.tutor, self.tutor)
                else:
                    availability = CounselorAvailability.objects.get(pk=elt["pk"])
                    self.assertEqual(availability.counselor, self.counselor)
                self.assertEqual(
                    availability.start,
                    dateparse.parse_datetime(availability_objects[idx]["start"]).astimezone(pytz.timezone("UTC")),
                )
                self.assertEqual(
                    availability.end,
                    dateparse.parse_datetime(availability_objects[idx]["end"]).astimezone(pytz.timezone("UTC")),
                )

    def test_create_update(self):
        """ Test creating/updating availability as a tutor and as an administrator
            python manage.py test sncommon.tests.test_availability:TestAvailabilityViewset.test_create_update
        """
        for cw_user in (self.tutor, self.counselor):
            AvailabilityObject = TutorAvailability if isinstance(cw_user, Tutor) else CounselorAvailability
            AvailabilityObject.objects.all().delete()
            # Create a couple of availabilities
            eastern_timezone = pytz.FixedOffset(-1 * EASTERN_TIMEZONE_OFFSET)
            seed_date = datetime.now() + timedelta(days=12)
            seed_date = datetime(seed_date.year, seed_date.month, seed_date.day, tzinfo=eastern_timezone)
            # We pass dates in UTC ISO Format
            availability_objects = [
                {
                    "start": (seed_date + timedelta(hours=1)).astimezone(pytz.UTC).isoformat(),
                    "end": (seed_date + timedelta(hours=2)).astimezone(pytz.UTC).isoformat(),
                    "location": self.location.pk,
                },
                {
                    "start": (seed_date + timedelta(hours=23)).astimezone(pytz.UTC).isoformat(),
                    "end": (seed_date + timedelta(hours=24)).astimezone(pytz.UTC).isoformat(),
                },
            ]
            # Start with one availability so we're altering
            data = {
                "start": availability_objects[0]["start"],
                "end": availability_objects[0]["end"],
                cw_user.user_type: cw_user,
            }
            AvailabilityObject.objects.create(**data)

            availabilities = {seed_date.strftime("%Y-%m-%d"): availability_objects}
            data = {
                cw_user.user_type: cw_user.pk,
                "availability": availabilities,
                "timezone_offset": EASTERN_TIMEZONE_OFFSET,
            }
            url = reverse(f"{cw_user.user_type}_availability-detail", kwargs={"pk": cw_user.pk})
            # Login required
            self.client.logout()
            response = self.client.post(url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 401)
            # Success
            self.client.force_login(cw_user.user)
            self._test_post_availabilities(data, availability_objects)
            self.assertEqual(AvailabilityObject.objects.count(), 2)
            self.assertEqual(AvailabilityObject.objects.filter(location=self.location).count(), 1)
            # Admins are notified of altered availability
            if isinstance(cw_user, Tutor):
                self.assertEqual(
                    self.admin.user.notification_recipient.notifications.last().notification_type,
                    "tutor_altered_availability",
                )

            # Idempotence
            for idx in range(4):
                self._test_post_availabilities(data, availability_objects)
                self.assertEqual(AvailabilityObject.objects.count(), 2)

            AvailabilityObject.objects.all().delete()
            # Change them
            availability_objects = [
                {
                    "start": (seed_date + timedelta(hours=3)).astimezone(pytz.UTC).isoformat(),
                    "end": (seed_date + timedelta(hours=9)).astimezone(pytz.UTC).isoformat(),
                },
                {
                    "start": (seed_date + timedelta(hours=12)).astimezone(pytz.UTC).isoformat(),
                    "end": (seed_date + timedelta(hours=21)).astimezone(pytz.UTC).isoformat(),
                },
            ]
            availabilities = {seed_date.strftime("%Y-%m-%d"): availability_objects}
            data = {
                cw_user.user_type: cw_user.pk,
                "availability": availabilities,
                "timezone_offset": EASTERN_TIMEZONE_OFFSET,
            }
            self._test_post_availabilities(data, availability_objects)
            self.assertEqual(AvailabilityObject.objects.count(), 2)

            # No admin noti this time since we weren't altering existing availabilities
            # TODO: Are notifications here correct?
            # breakpoint()
            # self.assertEqual(
            #     self.admin.user.notification_recipient.notifications.count(), admin_noti_count,
            # )

            # Confirm validation success for individual session
            if isinstance(cw_user, Tutor):
                StudentTutoringSession.objects.create(
                    individual_session_tutor=self.tutor,
                    start=(seed_date + timedelta(hours=7)),
                    end=(seed_date + timedelta(hours=10, minutes=8)),
                )
            else:
                CounselorMeeting.objects.create(
                    student=self.student,
                    start=(seed_date + timedelta(hours=7)),
                    end=(seed_date + timedelta(hours=10, minutes=8)),
                )
            availability_objects = [
                {
                    "start": (seed_date + timedelta(hours=8)).astimezone(pytz.UTC).isoformat(),
                    "end": (seed_date + timedelta(hours=9)).astimezone(pytz.UTC).isoformat(),
                },
            ]
            availabilities = {seed_date.strftime("%Y-%m-%d"): availability_objects}
            data = {
                cw_user.user_type: cw_user.pk,
                "availability": availabilities,
                "timezone_offset": EASTERN_TIMEZONE_OFFSET,
            }
            self.client.force_login(cw_user.user)
            response = self.client.post(url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(AvailabilityObject.objects.count(), 1)

            # Confirm validation fail for group session
            if isinstance(cw_user, Tutor):
                GroupTutoringSession.objects.create(
                    primary_tutor=self.tutor,
                    start=(seed_date + timedelta(hours=12)),
                    end=(seed_date + timedelta(hours=14)),
                )
                availability_objects = [
                    {
                        "start": (seed_date + timedelta(hours=13)).astimezone(pytz.UTC).isoformat(),
                        "end": (seed_date + timedelta(hours=21)).astimezone(pytz.UTC).isoformat(),
                    },
                ]
                availabilities = {seed_date.strftime("%Y-%m-%d"): availability_objects}
                data = {
                    "tutor": self.tutor.pk,
                    "availability": availabilities,
                    "timezone_offset": EASTERN_TIMEZONE_OFFSET,
                }
                response = self.client.post(url, json.dumps(data), content_type="application/json")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(AvailabilityObject.objects.count(), 1)

            # Confirm validation fail for overlapping times
            availability_objects = [
                {
                    "start": (seed_date + timedelta(hours=0)).astimezone(pytz.UTC).isoformat(),
                    "end": (seed_date + timedelta(hours=2)).astimezone(pytz.UTC).isoformat(),
                },
                {
                    "start": (seed_date + timedelta(hours=1)).astimezone(pytz.UTC).isoformat(),
                    "end": (seed_date + timedelta(hours=24)).astimezone(pytz.UTC).isoformat(),
                },
            ]
            availabilities = {seed_date.strftime("%Y-%m-%d"): availability_objects}
            data = {
                cw_user.user_type: cw_user.pk,
                "availability": availabilities,
                "timezone_offset": EASTERN_TIMEZONE_OFFSET,
            }
            response = self.client.post(url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(AvailabilityObject.objects.count(), 1)

            # Confirm validation fail for times spanning days
            availability_objects = [
                {
                    "start": (seed_date + timedelta(hours=1)).astimezone(pytz.UTC).isoformat(),
                    "end": (seed_date + timedelta(hours=2)).astimezone(pytz.UTC).isoformat(),
                },
                {
                    "start": (seed_date + timedelta(hours=23)).astimezone(pytz.UTC).isoformat(),
                    "end": (seed_date + timedelta(hours=30)).astimezone(pytz.UTC).isoformat(),
                },
            ]
            availabilities = {seed_date.strftime("%Y-%m-%d"): availability_objects}
            data = {
                cw_user.user_type: cw_user.pk,
                "availability": availabilities,
                "timezone_offset": EASTERN_TIMEZONE_OFFSET,
            }
            response = self.client.post(url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(AvailabilityObject.objects.count(), 1)

    def test_timezone_offset(self):
        """ Timezone offset determines what the 24 hour period is used to clear and validate TutorAvailabilities
            when creating availabilities.
            We work with UTC strings to best simulate data we get from frontend
        """
        self.client.force_login(self.tutor.user)
        seed_date = dateparse.parse_datetime("2100-04-12T04:00:00.000Z")
        # Create an availability at 2am UTC
        two_am_availability = TutorAvailability.objects.create(
            tutor=self.tutor,
            start=dateparse.parse_datetime("2100-04-12T02:00:00.000Z"),
            end=dateparse.parse_datetime("2100-04-12T03:10:00.000Z"),
        )
        # Create a new availability using Eastern timezone. Should NOT delete our availability
        availability_objects = [
            {"start": str(seed_date + timedelta(hours=13)), "end": str(seed_date + timedelta(hours=21)),},
        ]
        availabilities = {seed_date.strftime("%Y-%m-%d"): availability_objects}
        data = {
            "tutor": self.tutor.pk,
            "availability": availabilities,
            "timezone_offset": EASTERN_TIMEZONE_OFFSET,
        }

        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TutorAvailability.objects.filter(pk=two_am_availability.pk).exists())
        # But if we use offset of 60, two_am_availability gets deleted
        data["timezone_offset"] = 60
        response = self.client.post(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TutorAvailability.objects.filter(pk=two_am_availability.pk).exists())

    def test_destroy(self):
        pass


class TestEmptyRecurringAvailability(TestCase):
    """
        python manage.py test sncommon.tests.test_availability_views:TestEmptyRecurringAvailability
        This class tests the difference between using recurring availability and having no availability
            (we use recurring availability for days with no availability, unless no availability is explicitly specified)
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.tutor = Tutor.objects.first()
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.tutor.students.add(self.student)
        self.url = reverse("tutor_availability-detail", kwargs={"pk": self.tutor.pk})
        self.admin = Administrator.objects.first()

        # Set it up so that tomorrow has availability, the next day hs empty availability
        now = timezone.now().astimezone(pytz.timezone("UTC"))
        tomorrow = now + timedelta(days=1)
        self.tomorrow = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, tzinfo=tomorrow.tzinfo)
        dbltomorrow = tomorrow + timedelta(days=1)
        self.availabilities = {
            "tutor": [
                # Availability tomorrow
                TutorAvailability.objects.create(
                    tutor=self.tutor,
                    start=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 11).astimezone(pytz.timezone("UTC")),
                    end=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 13).astimezone(pytz.timezone("UTC")),
                ),
                # Empty availability the following day
                TutorAvailability.objects.create(
                    tutor=self.tutor,
                    start=datetime(dbltomorrow.year, dbltomorrow.month, dbltomorrow.day, 11).astimezone(
                        pytz.timezone("UTC")
                    ),
                    end=datetime(dbltomorrow.year, dbltomorrow.month, dbltomorrow.day, 11).astimezone(
                        pytz.timezone("UTC")
                    ),
                ),
            ],
            "counselor": [
                # Availability tomorrow
                CounselorAvailability.objects.create(
                    counselor=self.counselor,
                    start=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 11).astimezone(pytz.timezone("UTC")),
                    end=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 13).astimezone(pytz.timezone("UTC")),
                ),
                # Empty availability the following day
                CounselorAvailability.objects.create(
                    counselor=self.counselor,
                    start=datetime(dbltomorrow.year, dbltomorrow.month, dbltomorrow.day, 11).astimezone(
                        pytz.timezone("UTC")
                    ),
                    end=datetime(dbltomorrow.year, dbltomorrow.month, dbltomorrow.day, 11).astimezone(
                        pytz.timezone("UTC")
                    ),
                ),
            ],
        }

    def test_create_empty_availability(self):
        for cw_user in (self.tutor, self.counselor):
            # Create an empty availability three days from now
            seed_date = self.tomorrow + timedelta(days=2)
            availabilities = {seed_date.strftime("%Y-%m-%d"): []}
            data = {
                cw_user.user_type: cw_user.pk,
                "availability": availabilities,
                "timezone_offset": EASTERN_TIMEZONE_OFFSET,
            }
            self.client.force_login(cw_user.user)
            url = reverse(f"{cw_user.user_type}_availability-detail", kwargs={"pk": cw_user.pk})
            response = self.client.post(url, json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)

            # Confirm we created an availability at noon with no duration
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["start"], result[0]["end"])
            AvailabilityObject = TutorAvailability if isinstance(cw_user, Tutor) else CounselorAvailability
            availability = AvailabilityObject.objects.order_by("pk").last()
            self.assertEqual(availability.start, availability.end)
            self.assertEqual(availability.start.day, seed_date.day)
            self.assertEqual(availability.start.month, seed_date.month)
            self.assertEqual(availability.start.year, seed_date.year)

    def test_use_recurring_availability(self):
        # Confirm that when getting availability (as needed to book a session), we use recurring availability if no
        # availability for a day
        for cw_user in (self.tutor, self.counselor):
            if isinstance(cw_user, Tutor):
                (recurring_availability, _) = RecurringTutorAvailability.objects.get_or_create(tutor=self.tutor)
            else:
                (recurring_availability, _) = RecurringCounselorAvailability.objects.get_or_create(
                    counselor=self.counselor
                )
            # We need to use all trimesters
            for trimester in (
                RecurringTutorAvailability.TRIMESTER_FALL,
                RecurringTutorAvailability.TRIMESTER_SPRING,
                RecurringTutorAvailability.TRIMESTER_SUMMER,
            ):
                for day in recurring_availability.availability[trimester]:
                    recurring_availability.availability[trimester][day] = [{"start": "12:00", "end": "15:00"}]
            recurring_availability.save()

            # Get availability over the following week (start tomorrow)
            self.client.force_login(cw_user.user)
            url_data = {
                "start": self.tomorrow.isoformat(),
                "end": (self.tomorrow + timedelta(days=7)).isoformat(),
            }
            url = reverse(f"{cw_user.user_type}_availability-detail", kwargs={"pk": cw_user.pk})
            url = f"{url}?{urlencode(url_data)}"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)

            # We expect 7 availabilities, starting with one tomorrow and then an empty one
            availabilities = self.availabilities[cw_user.user_type]
            for idx in range(2):
                self.assertEqual(
                    dateparse.parse_datetime(result[idx]["start"]), availabilities[idx].start,
                )
                self.assertEqual(
                    dateparse.parse_datetime(result[idx]["end"]), availabilities[idx].end,
                )
            # for idx in range(2, 7):
            #     day = self.tomorrow + timedelta(days=idx)
            #     start_hour = 12
            #     self.assertEqual(
            #         dateparse.parse_datetime(result[idx]["start"]),
            #         datetime(day.year, day.month, day.day, start_hour, tzinfo=pytz.UTC),
            #     )
            #     self.assertEqual(
            #         dateparse.parse_datetime(result[idx]["end"]),
            #         datetime(day.year, day.month, day.day, start_hour + 3, tzinfo=pytz.UTC),
            #     )

            # But not when getting availability for tutor availability view
            url_data["use_recurring_availability"] = False
            url = f"{self.url}?{urlencode(url_data)}"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.content)
            self.assertEqual(len(result), 2)


class TestRecurringAvailability(TestCase):
    """ Test to make sure recurring availability functions properly, especially around the edges
        of our trimesters
        python manage.py test sncommon.tests.test_availability:TestRecurringAvailability
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.tutor = Tutor.objects.first()
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.admin = Administrator.objects.first()
        self.location = Location.objects.first()

    def test_filter_recurring_availability_on_location(self):
        """ python manage.py test sncommon.tests.test_availability:TestRecurringAvailability.test_filter_recurring_availability_on_location """
        for cw_user in (self.tutor, self.counselor):
            availability_manager = AvailabilityManager(cw_user)
            (recurring_availability, _) = availability_manager.get_or_create_recurring_availability()
            now = timezone.now()

            # Setup some recurring availability
            availability = {x: [{"start": "9:00", "end": "11:00"}] for x in RecurringTutorAvailability.ORDERED_WEEKDAYS}
            recurring_availability.availability[RecurringTutorAvailability.TRIMESTER_SPRING] = availability.copy()
            recurring_availability.availability[RecurringTutorAvailability.TRIMESTER_SUMMER] = availability.copy()
            recurring_availability.availability[RecurringTutorAvailability.TRIMESTER_FALL] = availability.copy()

            # Setup to work in person every day
            locations = {x: self.location.pk for x in RecurringTutorAvailability.ORDERED_WEEKDAYS}
            recurring_availability.locations[RecurringTutorAvailability.TRIMESTER_SPRING] = locations.copy()
            recurring_availability.locations[RecurringTutorAvailability.TRIMESTER_SUMMER] = locations.copy()
            recurring_availability.locations[RecurringTutorAvailability.TRIMESTER_FALL] = locations.copy()
            recurring_availability.save()

            day_start = datetime(now.year, now.month, now.day)
            end = day_start + timedelta(days=7)

            # availability = availability_manager.get_availability(start=day_start, end=end)
            # self.assertEqual(len(availability), 7)  # One per day

            # Add some non-recurring availability just for fun. On our location

            AvailabilityObject = TutorAvailability if isinstance(cw_user, Tutor) else CounselorAvailability
            fields = {
                "start": day_start + timedelta(hours=14),
                "end": day_start + timedelta(hours=16),
                "location": self.location,
            }
            if isinstance(cw_user, Tutor):
                fields["tutor"] = self.tutor
            else:
                fields["counselor"] = self.counselor
            availability_object = AvailabilityObject.objects.create(**fields)

            # Get all dat availability for one week
            availability = availability_manager.get_availability(
                start=day_start, end=end, use_recurring_availability=True
            )
            self.assertEqual(
                len(availability), 7
            )  # One per day, (recurring avail not used for day with specific avail)
            self.assertEqual(
                len(
                    availability_manager.get_availability(
                        start=day_start, end=end, all_locations_and_remote=False, location=None
                    )
                ),
                0,
            )
            # Make our in person availability remote. Should be the only one returned
            availability_object.location = None
            availability_object.save()
            self.assertEqual(
                len(
                    availability_manager.get_availability(
                        start=day_start, end=end, all_locations_and_remote=False, location=None
                    )
                ),
                1,
            )
            location_availability = availability_manager.get_availability(
                start=day_start, end=end, all_locations_and_remote=False, location=self.location
            )
            self.assertEqual(
                len(location_availability), 7,
            )  # Still one per day

    def test_retrieve_availability(self):
        for cw_user in (self.tutor, self.counselor):
            self.availability_manager = AvailabilityManager(cw_user)
            (recurring_availability, _) = self.availability_manager.get_or_create_recurring_availability()
            self.recurring_availability = recurring_availability
            # Set different recurring availability for each trimester. Test that manager returns it
            spring_availability = {
                x: [{"start": "9:00", "end": "11:00"}] for x in RecurringTutorAvailability.ORDERED_WEEKDAYS
            }
            summer_availability = {
                x: [{"start": "14:00", "end": "15:00"}] for x in RecurringTutorAvailability.ORDERED_WEEKDAYS
            }
            fall_availability = {
                x: [{"start": "20:00", "end": "22:00"}] for x in RecurringTutorAvailability.ORDERED_WEEKDAYS
            }
            self.recurring_availability.availability[RecurringTutorAvailability.TRIMESTER_SPRING] = spring_availability
            self.recurring_availability.availability[RecurringTutorAvailability.TRIMESTER_SUMMER] = summer_availability
            self.recurring_availability.availability[RecurringTutorAvailability.TRIMESTER_FALL] = fall_availability
            self.recurring_availability.save()

            # Now we get availability. We use next year for everything to ensure it's in the future
            now = timezone.now()
            # Spring -> Summer
            start = datetime(now.year + 1, RECURRING_AVAILABILITY_SUMMER_START_MONTH - 1, 29)
            end = start + timedelta(days=7)
            availability = self.availability_manager.get_availability(start=start, end=end)
            for x in availability:
                self.assertEqual(x[cw_user.user_type], cw_user.pk)
                a_start = dateparse.parse_datetime(x["start"])
                a_end = dateparse.parse_datetime(x["end"])
                month = a_start.month
                if month < RECURRING_AVAILABILITY_SUMMER_START_MONTH:
                    self.assertEqual(a_start.hour, 9)
                    self.assertEqual(a_end.hour, 11)
                else:
                    self.assertEqual(a_start.hour, 14)
                    self.assertEqual(a_end.hour, 15)

            # Smmer -> Fall
            start = datetime(now.year + 1, RECURRING_AVAILABILITY_FALL_START_MONTH - 1, 29)
            end = start + timedelta(days=7)
            availability = self.availability_manager.get_availability(start=start, end=end)
            for x in availability:
                self.assertEqual(x[cw_user.user_type], cw_user.pk)
                a_start = dateparse.parse_datetime(x["start"])
                a_end = dateparse.parse_datetime(x["end"])
                month = a_start.month
                if month < RECURRING_AVAILABILITY_FALL_START_MONTH:
                    self.assertEqual(a_start.hour, 14)
                    self.assertEqual(a_end.hour, 15)
                else:
                    self.assertEqual(a_start.hour, 20)
                    self.assertEqual(a_end.hour, 22)

            # Test that view returns it. Fall -> Spring
            self.client.force_login(cw_user.user)
            url_data = {
                "start": datetime(now.year + 1, 12, 30).isoformat(),
                "end": datetime(now.year + 2, 1, 2).isoformat(),
            }
            url = reverse(f"{cw_user.user_type}_availability-detail", kwargs={"pk": cw_user.pk})
            url = f"{url}?{urlencode(url_data)}"
            result = self.client.get(url)
            self.assertEqual(result.status_code, 200)
            data = json.loads(result.content)
            for x in data:
                self.assertEqual(x[cw_user.user_type], cw_user.pk)
                a_start = dateparse.parse_datetime(x["start"])
                a_end = dateparse.parse_datetime(x["end"])
                month = a_start.month
                # TODO: This test is not going to do well when we switch over fall back or spring forward
                self.assertEqual(a_start.hour, 21 if month == 12 else 9)
                self.assertEqual(a_end.hour, 23 if month == 12 else 11)


class TestAvailability(TestCase):
    """ Simple tests for get_availability that don't do anything fancy with recurring
        availability

        python manage.py test sncommon.tests.test_availability:TestAvailability
    """

    fixtures = ("fixture.json",)

    def setUp(self):
        self.tutor = Tutor.objects.first()
        self.student = Student.objects.first()
        self.counselor = Counselor.objects.first()
        self.student.counselor = self.counselor
        self.student.save()
        self.admin = Administrator.objects.first()
        RecurringTutorAvailability.objects.get_or_create(tutor=self.tutor)
        RecurringCounselorAvailability.objects.get_or_create(counselor=self.counselor)
        now = timezone.now()

        # We isolate test to working within a single day
        self.day_start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo) + timedelta(days=2)
        self.day_end = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo) + timedelta(days=3)

    def _test_split_availability(self, cw_user, availability):
        availability = AvailabilityManager(cw_user).get_availability(
            start=timezone.now(), end=timezone.now() + timedelta(days=5)
        )
        self.assertEqual(len(availability), 2)
        self.assertEqual(dateparse.parse_datetime(availability[0]["start"]), self.day_start)
        self.assertEqual(dateparse.parse_datetime(availability[0]["end"]), self.day_start + timedelta(hours=1))
        self.assertEqual(dateparse.parse_datetime(availability[1]["start"]), self.day_start + timedelta(hours=4))
        self.assertEqual(dateparse.parse_datetime(availability[1]["end"]), self.day_end)

    def test_join_availability(self):
        """ Test that when two availabilities abutt, they get joined (when returned from get_availability)
            as long as they have the same location
        """
        location = Location.objects.create()
        start = timezone.now() - timedelta(hours=5)
        end = start + timedelta(days=3)
        availability_one = CounselorAvailability.objects.create(
            start=timezone.now(), end=timezone.now() + timedelta(hours=1), location=location, counselor=self.counselor
        )
        availability_two = CounselorAvailability.objects.create(
            start=availability_one.end,
            end=timezone.now() + timedelta(hours=2),
            location=location,
            counselor=self.counselor,
        )
        mgr = AvailabilityManager(self.counselor)
        self.assertEqual(len(mgr.get_availability(start=start, end=end)), 1)

        availability_two.location = None
        availability_two.save()
        self.assertEqual(
            len(mgr.get_availability(start=start, end=end, join_availabilities_at_different_location=False)), 2
        )

    def test_overlapping_sessions_tutor(self):
        """ When we get events from Outlook, they may overlap. These events are merged with existing sessions
            in UMS, so we can test that correct availability gets returned in this case by testing
            availability when there are overlapping sessions
        """
        availability = TutorAvailability.objects.create(tutor=self.tutor, start=self.day_start, end=self.day_end)
        availability_manager = AvailabilityManager(self.tutor)
        # First, ensure that we are available from start till end
        availability = availability_manager.get_availability(
            start=timezone.now(), end=timezone.now() + timedelta(days=5)
        )
        self.assertEqual(len(availability), 1)
        self.assertEqual(dateparse.parse_datetime(availability[0]["start"]), self.day_start)
        self.assertEqual(dateparse.parse_datetime(availability[0]["end"]), self.day_end)

        # Helper method that tests to ensure we have availability on our day for the first hour,
        # then no availability for 3 hours, then availability for the rest of the da

        # Create a session in the middle
        session = StudentTutoringSession.objects.create(
            student=self.student,
            individual_session_tutor=self.tutor,
            start=self.day_start + timedelta(hours=1),
            end=self.day_start + timedelta(hours=4),
        )
        self._test_split_availability(self.tutor, availability)

        # Make session into two abutting sessions
        session.end = session.end - timedelta(hours=2)
        session.save()
        session_two = StudentTutoringSession.objects.create(
            individual_session_tutor=self.tutor, start=session.end, end=self.day_start + timedelta(hours=4),
        )
        self._test_split_availability(self.tutor, availability)

        # Make sessions overlap just a teensy
        session_two.start = session_two.start - timedelta(minutes=38)
        session_two.save()
        self._test_split_availability(self.tutor, availability)

        # And make the sessions overlap completely
        session.start = session_two.start = self.day_start + timedelta(hours=1)
        session.end = session_two.end = self.day_start + timedelta(hours=4)
        session.save()
        session_two.save()
        self._test_split_availability(self.tutor, availability)

        # and now make session one entirely contain session two
        session_two.start += timedelta(minutes=45)
        session_two.end -= timedelta(minutes=45)
        session_two.save()
        self._test_split_availability(self.tutor, availability)

    def test_overlapping_sessions_counselor(self):
        """ When we get events from Outlook, they may overlap. These events are merged with existing sessions
            in UMS, so we can test that correct availability gets returned in this case by testing
            availability when there are overlapping sessions
        """
        availability = CounselorAvailability.objects.create(
            counselor=self.counselor, start=self.day_start, end=self.day_end
        )
        availability_manager = AvailabilityManager(self.counselor)
        # First, ensure that we are available from start till end
        availability = availability_manager.get_availability(
            start=timezone.now(), end=timezone.now() + timedelta(days=5)
        )
        self.assertEqual(len(availability), 1)
        self.assertEqual(dateparse.parse_datetime(availability[0]["start"]), self.day_start)
        self.assertEqual(dateparse.parse_datetime(availability[0]["end"]), self.day_end)

        # Helper method that tests to ensure we have availability on our day for the first hour,
        # then no availability for 3 hours, then availability for the rest of the da

        # Create a session in the middle
        session = CounselorMeeting.objects.create(
            student=self.student, start=self.day_start + timedelta(hours=1), end=self.day_start + timedelta(hours=4),
        )
        self._test_split_availability(self.counselor, availability)

        # Make session into two abutting sessions
        session.end = session.end - timedelta(hours=2)
        session.save()
        session_two = CounselorMeeting.objects.create(
            student=self.student, start=session.end, end=self.day_start + timedelta(hours=4),
        )
        self._test_split_availability(self.counselor, availability)

        # Make sessions overlap just a teensy
        session_two.start = session_two.start - timedelta(minutes=38)
        session_two.save()
        self._test_split_availability(self.counselor, availability)

        # And make the sessions overlap completely
        session.start = session_two.start = self.day_start + timedelta(hours=1)
        session.end = session_two.end = self.day_start + timedelta(hours=4)
        session.save()
        session_two.save()
        self._test_split_availability(self.counselor, availability)

        # and now make session one entirely contain session two
        session_two.start += timedelta(minutes=45)
        session_two.end -= timedelta(minutes=45)
        session_two.save()
        self._test_split_availability(self.counselor, availability)

    def test_availability_max_meetings(self):
        """ Confirm that Counselor.max_meetings_per_day constraint works
            python manage.py test sncommon.tests.test_availability:TestAvailability.test_availability_max_meetings
        """
        availability = CounselorAvailability.objects.create(
            start=timezone.now(), end=timezone.now() + timedelta(hours=1), counselor=self.counselor
        )
        CounselorAvailability.objects.create(
            start=availability.start + timedelta(days=1),
            end=availability.start + timedelta(hours=25),
            counselor=self.counselor,
        )

        cm = CounselorMeeting.objects.create(
            student=self.student,
            start=(availability.end + timedelta(minutes=5)),
            end=(availability.end + timedelta(minutes=15)),
        )
        mgr = AvailabilityManager(self.counselor)
        availabilities = mgr.get_availability(start=(cm.start - timedelta(days=5)), end=cm.end + timedelta(days=5))
        self.assertEqual(len(availabilities), 2)

        self.counselor.max_meetings_per_day = 2
        self.counselor.save()
        mgr = AvailabilityManager(self.counselor)
        availabilities = mgr.get_availability(start=(cm.start - timedelta(days=5)), end=cm.end + timedelta(days=5))
        self.assertEqual(len(availabilities), 2)

        self.counselor.max_meetings_per_day = 1
        self.counselor.save()
        mgr = AvailabilityManager(self.counselor)
        availabilities = mgr.get_availability(
            start=(cm.start - timedelta(days=5)), end=cm.end + timedelta(days=5), return_date_objects=True
        )
        self.assertEqual(len(availabilities), 1)
        # self.assertNotEqual(
        #     availabilities[0]["start"].astimezone(pytz.timezone(self.counselor.timezone)).day,
        #     cm.end.astimezone(pytz.timezone(self.counselor.timezone)).day,
        # )

    def test_buffer_between_meetings(self):
        """ python manage.py test sncommon.tests.test_availability:TestAvailability.test_buffer_between_meetings """
        now = timezone.now()
        start = datetime(now.year, now.month, now.day, now.hour, now.minute, tzinfo=now.tzinfo)
        availability = CounselorAvailability.objects.create(
            start=start, end=start + timedelta(hours=10), counselor=self.counselor
        )
        cm = CounselorMeeting.objects.create(
            student=self.student,
            start=(availability.start + timedelta(hours=1)),
            end=(availability.start + timedelta(hours=2)),
        )
        # Test with no buffer
        mgr = AvailabilityManager(self.counselor)
        availabilities = mgr.get_availability(
            start=(availability.start - timedelta(hours=1)),
            end=(availability.end + timedelta(hours=1)),
            return_date_objects=True,
        )
        self.assertEqual(len(availabilities), 2)
        self.assertEqual(availabilities[0]["end"], cm.start)
        self.assertEqual(availabilities[1]["start"], cm.end)

        # Test with buffer
        self.counselor.minutes_between_meetings = 16
        self.counselor.save()
        mgr = AvailabilityManager(self.counselor)
        availabilities = mgr.get_availability(
            start=(availability.start - timedelta(hours=1)),
            end=(availability.end + timedelta(hours=1)),
            return_date_objects=True,
        )
        self.assertEqual(len(availabilities), 2)
        self.assertEqual(availabilities[0]["end"], cm.start - timedelta(minutes=16))
        self.assertEqual(availabilities[1]["start"], cm.end + timedelta(minutes=16))
