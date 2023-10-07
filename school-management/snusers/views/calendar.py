from django.conf import settings
from django.db.models import Q
from django.http import Http404
from django.contrib.auth.models import User
from django_ical.views import ICalFeed

from sntutoring.models import GroupTutoringSession, StudentTutoringSession
from snusers.models import get_cw_user, Student, Tutor
from sncounseling.models import CounselorMeeting


class CalendarException(Exception):
    pass


class EventFeed(ICalFeed):
    """ Calendar event feed for current user
        This is a view that allows GET. Expects URL param "slug" which identifies a cwuser
        object via slug UUID
    """

    product_id = "Collegewise Calendar"
    timezone = "UTC"
    file_name = "event.ics"
    cwuser = None

    def get_object(self, request, *args, **kwargs):
        slug = kwargs.get("slug")
        user = User.objects.filter(
            Q(student__slug=slug) | Q(parent__slug=slug) | Q(tutor__slug=slug) | Q(counselor__slug=slug)
        ).first()
        if not user:
            raise Http404("Invalid user")
        self.cwuser = get_cw_user(user)
        return self.cwuser

    def items(self, cwuser):
        """ For now items ONLY include StudentTutoringSessions
            Arguments:
              cwuser {CW User}
            TODO: Add other calendar items
        """

        if isinstance(cwuser, Student):
            return list(
                (
                    StudentTutoringSession.objects.filter(student=cwuser, is_tentative=False)
                    .exclude(Q(set_cancelled=True) | Q(group_tutoring_session__cancelled=True))
                    .distinct()
                ).order_by("-start")
            ) + list(
                CounselorMeeting.objects.filter(student=cwuser, cancelled=None).exclude(start=None).order_by("-start")
            )
        elif isinstance(cwuser, Tutor):
            return list(
                StudentTutoringSession.objects.filter(individual_session_tutor=cwuser)
                .exclude(set_cancelled=True)
                .distinct()
                .order_by("-start")
            ) + list(
                GroupTutoringSession.objects.filter(primary_tutor=cwuser)
                .exclude(cancelled=True)
                .distinct()
                .order_by("-start")
            )

        else:
            raise CalendarException("Invalid user type")

    """ All of the methods below get fields for calendar items.
        Arguments:
            item {StudentTutoringSession} Any item that can appear on calendar
    """

    def item_guid(self, item: StudentTutoringSession):
        return "{}{}".format(item.slug, "collegewise")

    def item_title(self, item: StudentTutoringSession):
        if isinstance(item, CounselorMeeting) or isinstance(item, GroupTutoringSession):
            return item.title
        if isinstance(item, StudentTutoringSession):
            title = item.title_for_tutor if isinstance(self.cwuser, Tutor) else item.title_for_student
            subject_name = item.tutoring_service.name if item.tutoring_service else ""
            non_tentative_title = f"{title} {subject_name}"
            return f"TENTATIVE {non_tentative_title}" if item.is_tentative else non_tentative_title
        return ""

    def item_location(self, item):
        """ Location of student tutoring session
        """
        if isinstance(item, CounselorMeeting):
            return ""
        if item.zoom_url:
            return item.zoom_url
        elif isinstance(item, GroupTutoringSession) and item.location:
            return item.location.full_address
        if item.individual_session_tutor and item.student.location:
            return item.student.location.full_address
        if item.group_tutoring_session and item.group_tutoring_session.location:
            return item.group_tutoring_session.location.full_address
        return ""

    def item_description(self, item):
        if isinstance(item, CounselorMeeting):
            return item.counselor_meeting_template.description if item.counselor_meeting_template else ""
        if isinstance(item, GroupTutoringSession):
            return item.description

        description = f"{self.item_title(item)}\n"
        if item.resources.exists():
            description += "Resources:\n"
            for resource in item.resources.all():
                description += f"- {resource.title} ({settings.SITE_URL}{resource.url()})"
        if not (item.missed or item.cancelled) and (
            item.tutoring_session_notes
            or (item.group_tutoring_session and hasattr(item.group_tutoring_session, "tutoring_session_notes"))
        ):
            description += "Notes (from tutor):\n"
            description += f"{settings.SITE_URL}{item.notes_url}\n"
        return description

    def item_start_datetime(self, item):
        return item.start

    def item_end_datetime(self, item):
        return item.end

    def item_link(self, item):
        """ Just link back to UMS for everything right now """
        return settings.SITE_URL
