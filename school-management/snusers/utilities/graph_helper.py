from snusers.constants.outlook_integration import NUM_OF_DAYS_TO_RETRIEVE_CW_EVENTS
import os
from datetime import timedelta

from sncounseling.models import CounselorMeeting
from sntutoring.models import GroupTutoringSession, StudentTutoringSession

from snusers.models import Counselor, Tutor

# from django.urls.base import reverse
from django.conf import settings
from django.utils import timezone
from O365 import Account
from O365.utils import BaseTokenBackend
from sentry_sdk import capture_exception, configure_scope


class GraphHelperException(Exception):
    pass


# This is necessary for testing with non-HTTPS localhost
# Remove this if deploying to production
if settings.ENV != "production":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# This is necessary because Azure does not guarantee
# to return scopes in the same case and order as requested
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
os.environ["OAUTHLIB_IGNORE_SCOPE_CHANGE"] = "1"

BUSY = "EventShowAs.Busy"


class TokenBackend(BaseTokenBackend):
    """ Required as part of O365 SDK to retrieve and store token(s) from and to
        our database
    """

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.cwuser = kwargs["user"]

    def load_token(self):
        # return json format of token data
        return self.token_constructor(
            {"refresh_token": self.cwuser.microsoft_refresh, "access_token": self.cwuser.microsoft_token}
        )

    def save_token(self):
        # update user token after is_authenticated call
        self.cwuser.microsoft_refresh = self.token["refresh_token"]
        self.cwuser.microsoft_token = self.token["access_token"]
        self.cwuser.save()


def get_schedule_instance(session):
    """ Helper method to gain access to CWUser outlook calendar (or raise exception
        if refresh token is no longer valid).
        Input: session can be either StudentTutoringSession, GroupTutoringSession, or CounselorMeeting
        Returns: Tuple: Instance of schedule for the tutor connected to session and tutor
    """
    if hasattr(session, "individual_session_tutor") and session.individual_session_tutor is not None:
        user = session.individual_session_tutor
    elif hasattr(session, "primary_tutor_id") and session.primary_tutor_id is not None:
        user = GroupTutoringSession.objects.get(pk=session.pk).primary_tutor
    elif isinstance(session, CounselorMeeting):
        user = session.student.counselor
    else:
        raise GraphHelperException("Input is invalid for creating an outlook calendar event")

    credentials = (settings.MS_APP_ID, settings.MS_APP_SECRET)

    token_backend = TokenBackend(user=user)
    account = Account(
        credentials,
        token_backend=token_backend,
        scopes=[
            "https://graph.microsoft.com/Calendar.ReadWrite.Shared",
            "https://graph.microsoft.com/Calendar.ReadWrite",
            "https://graph.microsoft.com/offline_access",
            "https://graph.microsoft.com/User.Read",
        ],
        auth_flow_type="authorization",
    )
    account.con.refresh_token()
    if not account.is_authenticated:
        user.microsoft_token = None
        user.microsoft_refresh = None
        user.save()
        raise GraphHelperException("User has expired token and needs to reauthenticate")
    # not sure why token will not refresh itself, but hitting CompactToken validation failed 80049228 error consistently without this
    schedule = account.schedule()
    return schedule, user


def outlook_create(session, schedule=None):
    """ Add tutoring session event to cwuser outlook calendar. Raise execption
        if CWuser token is expired and cannot be refreshed
        Input: session can be either StudentTutoringSession, GroupTutoringSession, or CounselorMeeting
        RETURN: graph_api id for the event instance stored on the event object
        in Microsoft Calendar.
        Takes optional schedule parameter for sync_outlook. We don't want to
        reconnect to tutor/counselor schedule for every session we are scheduling
    """
    if not schedule:
        try:
            schedule, user = get_schedule_instance(session)
        except Exception as e:
            raise GraphHelperException(e)
    # counselor_meeting does not have a location
    location = session.location.name if session.location else ""
    # STS
    if hasattr(session, "note"):
        note = session.note
    # GTS
    elif hasattr(session, "description"):
        note = session.description
    # counselor_meeting
    else:
        note = ""

    try:
        calendar = schedule.get_default_calendar()
        event = calendar.new_event()
        # GTS does noth have title_for_tutor, only title
        event.subject = session.title_for_tutor if hasattr(session, "title_for_tutor") else session.title
        if hasattr(session, "student") and session.student:
            event.subject = f"{session.student.name} {event.subject}"
        event.location = location
        event.start = session.start
        event.end = session.end
        # if STS, note, if GTS, description
        event.body = note
        event.save()
        return event.object_id
    # except GraphHelperException as e:
    except Exception as e:
        print(e)
        raise GraphHelperException("Something went wrong. Could not add event to calendar", e)


def outlook_retrieve(user, start, end):
    """ Retrieve tutor events from outlook. Default to next 2 weeks if no start/end
        dates provided
    """
    credentials = (settings.MS_APP_ID, settings.MS_APP_SECRET)
    token_backend = TokenBackend(user=user)
    account = Account(
        credentials,
        token_backend=token_backend,
        scopes=["https://graph.microsoft.com/Calendar.ReadWrite"],
        auth_flow_type="authorization",
    )
    account.con.refresh_token()
    if not account.is_authenticated:
        user.microsoft_token = None
        user.microsoft_refresh = None
        user.save()
        raise GraphHelperException("User has expired token and needs to reauthenticate")
    # not sure why token will not refresh itself, but hitting CompactToken validation failed 80049228 error consistently without this
    schedule = account.schedule()
    try:
        calendar = schedule.get_default_calendar()
        query = calendar.new_query("start").greater_equal(start)
        query.chain("and").on_attribute("end").less_equal(end)
        events = calendar.get_events(limit=999, query=query, include_recurring=True)

        # We filter out events where the user is not busy
        events = list(events)
        return list([e for e in events if (not hasattr(e, "show_as") or str(e.show_as) == BUSY)])
    except Exception as e:
        print(e)
        raise GraphHelperException("Something went wrong. Could not retreive calendar events", e)


def outlook_delete(event):
    """ Remove specific event from CWUser outlook calendar.
        INPUT: StudentTutoringSession
    """
    try:
        schedule, user = get_schedule_instance(event)
    except Exception as e:
        raise GraphHelperException(e)

    try:
        calendar = schedule.get_default_calendar()
        e = calendar.get_event(event.outlook_event_id)
        if e:
            e.delete()
            return True

    except Exception as e:
        print(e)
        raise GraphHelperException("Something went wrong. Could not delete event calendar", e)


def outlook_update(event):
    """ Update tutoring event event
    """
    try:
        schedule, user = get_schedule_instance(event)
    except Exception as e:
        raise GraphHelperException(e)
    # counselor_meeting does not have a location
    location = event.location.name if hasattr(event, "location") and event.location else ""
    # STS
    if hasattr(event, "note"):
        note = event.note
    # GTS
    elif hasattr(event, "description"):
        note = event.description
    # counselor_meeting
    else:
        note = ""
    try:
        calendar = schedule.get_default_calendar()
        e = calendar.get_event(event.outlook_event_id)

        # GTS does noth ave title_for_tutor, only title
        e.subject = event.title_for_tutor if hasattr(event, "title_for_tutor") else event.title
        if hasattr(event, "student") and event.student:
            e.subject = f"{event.student.name} {e.subject}"
        e.location = location
        e.start = event.start
        e.end = event.end
        # if STS, note, if GTS, description
        e.body = note
        e.save()
        return True
    except Exception as e:
        print(e)
        raise GraphHelperException("Something went wrong. Could not update calendar", e)


def sync_outlook(cw_user):
    """ For all STS/GTS or CounselorMeetings that do not currently have an
    outlook_object_id, create an outlook event.
    """

    # connect to user ms account
    credentials = (settings.MS_APP_ID, settings.MS_APP_SECRET)

    token_backend = TokenBackend(user=cw_user)
    account = Account(
        credentials,
        token_backend=token_backend,
        scopes=[
            "https://graph.microsoft.com/Calendar.ReadWrite.Shared",
            "https://graph.microsoft.com/Calendar.ReadWrite",
            "https://graph.microsoft.com/offline_access",
            "https://graph.microsoft.com/User.Read",
        ],
        auth_flow_type="authorization",
    )
    account.con.refresh_token()
    if not account.is_authenticated:
        cw_user.microsoft_token = None
        cw_user.microsoft_refresh = None
        cw_user.save()
        raise GraphHelperException("User has expired token and needs to reauthenticate")

    schedule = account.schedule()

    # create list of cw events
    end = timezone.now() + timedelta(days=NUM_OF_DAYS_TO_RETRIEVE_CW_EVENTS)
    start = timezone.now()

    if isinstance(cw_user, Tutor):
        sts = StudentTutoringSession.objects.filter(individual_session_tutor=cw_user, outlook_event_id=None).filter(
            end__gte=start, end__lte=end
        )
        event_list = list(sts)
        gts = GroupTutoringSession.objects.filter(primary_tutor=cw_user, outlook_event_id=None).filter(
            end__gte=start, end__lte=end
        )
        event_list.extend(list(gts))
    elif isinstance(cw_user, Counselor):
        event_list = list(
            CounselorMeeting.objects.filter(student__counselor=cw_user, outlook_event_id=None).filter(
                end__gte=start, end__lte=end
            )
        )
    else:
        raise GraphHelperException("User type is invalid")
    for x in event_list:
        try:
            object_id = outlook_create(x, schedule)
            x.outlook_event_id = object_id
            x.save()
        except Exception as e:
            if not (settings.TESTING or settings.DEBUG):
                with configure_scope() as scope:
                    scope.set_context("outlook_create", {"cwuser": cw_user, "cw_event": x})
                capture_exception(e)
    return cw_user
