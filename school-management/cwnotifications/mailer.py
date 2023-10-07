"""
    This module sends emails for Notification objects.
    Pretty straightforward.
    We use python-mailsnake to interface with Mandrill to send emails
    https://github.com/michaelhelmick/python-mailsnake
"""
from datetime import timedelta
from typing import Tuple

from django.conf import settings
from django.core import mail
from django.db.models import Q
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import dateparse, timezone
from cwcounseling.models import CounselorMeeting
from cwmessages.models import Conversation, ConversationParticipant
from cwnotifications.constants import notification_types
from cwnotifications.constants.constants import NOTIFICATIONS_FOR_PENDING_USERS, get_notification_config
from cwnotifications.models import Notification
from cwtasks.models import Task
from cwtutoring.models import GroupTutoringSession, StudentTutoringSession, TutoringPackage
from cwtutoring.utilities.tutoring_session_notes_generator import generate_pdf
from snusers.models import Parent, Student, Tutor, get_cw_user

CAP_INVITE = "cap_invite"


# Functions to generate additional context to pass to email templates. Each returns a dictionary
def get_tutoring_hours(notification):
    from cwtutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager

    hours = StudentTutoringPackagePurchaseManager(notification.related_object).get_available_hours()
    return {"hours": hours}


def get_student_low_hours_context(notification):
    """ Get context for email to student/parent about hours remaining """
    hours = get_tutoring_hours(notification)["hours"]
    return {
        "max_hours": max(*list(hours.values())),
        "individual_curriculum": max(0, hours["individual_curriculum"]),
        "individual_test_prep": max(0, hours["individual_test_prep"]),
        "group_test_prep": max(0, hours["group_test_prep"]),
    }


def last_meeting_context(notification: Notification):
    """ Turn student PKs in notification.additional_args into queryset of students """
    return {
        "date": notification.additional_args["date"],
        "students": Student.objects.filter(pk__in=notification.additional_args["students"]),
        "paygo_sessions": StudentTutoringSession.objects.filter(
            pk__in=notification.additional_args["sessions"], student__is_paygo=True
        ).order_by("start"),
        "non_paygo_sessions": StudentTutoringSession.objects.filter(
            pk__in=notification.additional_args["sessions"], student__is_paygo=False
        ).order_by("start"),
    }


def counselor_task_digest_context(notification: Notification) -> dict:
    """ Returns a list of objects like this: {
        student: StudentProfile
        counselor_meeting: Student's next CounselorMeeting with counselor
        tasks: All tasks for student relevant to this digest
    }
    """
    tasks = Task.objects.filter(pk__in=notification.additional_args)
    students = Student.objects.filter(user__tasks__in=tasks).distinct()
    data = [
        {
            "student": s,
            "counselor_meeting": s.counselor_meetings.filter(start__gt=timezone.now(), cancelled=None)
            .order_by("start")
            .first(),
            "tasks": tasks.filter(for_user__student=s).order_by("due"),
        }
        for s in students
    ]
    data.sort(key=lambda d: d["counselor_meeting"].start.isoformat())
    return {"data": data}


def counselor_completed_tasks_context(notification: Notification) -> dict:
    """ Returns a list of tasks sorted by student
    """
    tasks = Task.objects.filter(pk__in=notification.additional_args).order_by("for_user", "completed")
    return {"tasks": tasks}


def get_paygo_magento_url(notification):
    from cwtutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager

    session: StudentTutoringSession = notification.related_object
    hours = StudentTutoringPackagePurchaseManager(session.student).get_available_hours()
    if not (session.student.is_paygo and not session.student.last_paygo_purchase_id):
        # Can't send paygo purchase link
        return {}

    if (
        (session.session_type == StudentTutoringSession.SESSION_TYPE_CURRICULUM and hours["individual_curriculum"]) < 0
        or session.session_type == StudentTutoringSession.SESSION_TYPE_TEST_PREP
        and hours["individual_test_prep"] < 0
    ):
        mgr = StudentTutoringPackagePurchaseManager(session.student)
        package: TutoringPackage = mgr.get_paygo_tutoring_package(session)
        if package and package.magento_purchase_link:
            return {"paygo_magento_url": package.magento_purchase_link}
    return {}


def get_tutor_daily_digest_details(notification):
    digest_details = {
        "unread_messages": 0,
        "sessions_needing_notes": [],
        "sessions_upcoming_individual": [],
        "sessions_upcoming_group": [],
    }
    tutor: Tutor = notification.related_object

    # Conversations with unread messages
    tutor_participations = ConversationParticipant.objects.filter(notification_recipient__user_id=tutor.user_id)
    for participation in tutor_participations:
        if (participation.last_read and participation.conversation.last_message) and (
            participation.last_read < participation.conversation.last_message
        ):
            digest_details["unread_messages"] += 1

    # Tutoring sessions needing notes
    sessions = StudentTutoringSession.objects.filter(
        Q(individual_session_tutor=tutor) & Q(tutoring_session_notes=None) & Q(end__lt=timezone.now())
    ).order_by("start")
    for session in sessions:
        session_description = {"name": session.student.name, "start": session.start}
        digest_details["sessions_needing_notes"].append(session_description)

    # Individual tutoring sessions in the next 24hrs
    sessions = StudentTutoringSession.objects.filter(
        Q(individual_session_tutor=tutor)
        & Q(start__gt=timezone.now())
        & Q(start__lt=(timezone.now() + timedelta(days=1)))
    ).order_by("start")
    for session in sessions:
        session_description = {
            "name": session.student.name,
            "start": session.start,
            "zoom_url": session.zoom_url,
        }
        digest_details["sessions_upcoming_individual"].append(session_description)

    # Group tutoring sessions in the next 24hrs
    sessions = GroupTutoringSession.objects.filter(
        (Q(primary_tutor=tutor) | Q(support_tutors__id=tutor.id))
        & Q(start__gt=timezone.now())
        & Q(start__lt=(timezone.now() + timedelta(days=1)))
    ).order_by("start")
    for session in sessions:
        session_description = {
            "title": session.title,
            "start": session.start,
            "zoom_url": session.zoom_url,
        }
        digest_details["sessions_upcoming_group"].append(session_description)

    return digest_details


def get_first_individual_tutoring_session_digest_details(notification):
    """
    Returns all individual tutoring sessions that meet the following conditions:
        - Individual tutoring session took place within the last 24 hours
        - The session was a student's first individual tutoring session
    """
    from cwtutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager

    digest_details = {"recent_first_individual_sessions": []}
    # Retrieve all individual tutoring sessions in the last 24 hours
    sessions = StudentTutoringSession.objects.filter(
        individual_session_tutor__isnull=False,
        start__gte=timezone.now() - timedelta(days=1),
        start__lte=timezone.now(),
        set_cancelled=False,
        missed=False,
        is_tentative=False,
    ).order_by("start")
    for session in sessions:
        # If student has no sessions prior to found session, found session must be first session
        if not StudentTutoringSession.objects.filter(
            student=session.student,
            start__lt=session.start,
            individual_session_tutor__isnull=False,
            set_cancelled=False,
            missed=False,
        ).exists():
            hours = StudentTutoringPackagePurchaseManager(session.student).get_available_hours()
            session_description = {
                "student": session.student.name,
                "tutor": session.individual_session_tutor.name,
                "start": session.start,
                "individual_curriculum": max(0, hours["individual_curriculum"]),
                "individual_test_prep": max(0, hours["individual_test_prep"]),
                "group_test_prep": max(0, hours["group_test_prep"]),
            }
            digest_details["recent_first_individual_sessions"].append(session_description)
    return digest_details


def get_invite_context(x: Notification):
    return {
        "url": reverse_lazy("register_get", kwargs={"uuid": str(get_cw_user(x.recipient.user).slug)}),
        "accepted_invite": bool(get_cw_user(x.recipient.user).accepted_invite),
    }


def student_task_reminder_context(noti: Notification):
    return {
        "overdue_tasks": Task.objects.filter(pk__in=noti.additional_args.get("overdue", [])),
        "coming_due_tasks": Task.objects.filter(pk__in=noti.additional_args.get("coming_due", [])),
    }


def get_unread_messages_context(x: Notification):
    cwuser = get_cw_user(x.recipient.user)
    url = f"{ settings.SITE_URL }{ reverse_lazy('platform', args=[cwuser.user_type]) }"
    # Counselors have different URLs to direct them to conversation in platform
    if (
        hasattr(x.recipient.user, "counselor")
        and x.related_object.conversation.conversation_type == Conversation.CONVERSATION_TYPE_COUNSELOR
        and x.related_object.conversation.student
    ):
        url += f"#/profile/student/{x.related_object.conversation.student.pk}/"
    else:
        url += "#/message"
    return {"url": url}


def get_counselor_meeting_context(counselor_meetings: CounselorMeeting):
    meetings = {}
    for x in counselor_meetings.additional_args:
        mtg = CounselorMeeting.objects.get(pk=x)
        if meetings.get(mtg.student.name):
            meetings[mtg.student.name].append(mtg)
        else:
            meetings[mtg.student.name] = [mtg]
    for student, meeting_list in meetings.items():
        meetings[student] = sorted(meeting_list, key=lambda i: i.start, reverse=False)
    return {"meetings": meetings}


def get_counselor_meeting_message_context(notification: Notification):
    meeting: CounselorMeeting = notification.related_object
    data = {
        "sorted_completed_tasks": meeting.notes_message_completed_tasks.order_by("-completed"),
        "sorted_upcoming_tasks": meeting.notes_message_upcoming_tasks.order_by("due"),
    }
    # Next scheduled meeting for student
    if meeting.start and not meeting.link_schedule_meeting_pk:
        data["next_counselor_meeting"] = (
            CounselorMeeting.objects.filter(student=meeting.student, cancelled__isnull=True, start__gt=meeting.start)
            .order_by("start")
            .first()
        )
    return data


CONTEXT_GENERATORS = {
    "invite": get_invite_context,
    "invite_reminder": get_invite_context,
    "student_student_low_on_hours": get_student_low_hours_context,
    "cas_magento_student_created": get_tutoring_hours,
    "user_accepted_invite": lambda x: {"cw_user": get_cw_user(x.related_object)},
    "student_tutoring_session_reminder": get_paygo_magento_url,
    "tutor_daily_digest": get_tutor_daily_digest_details,
    "ops_upcoming_course": lambda x: {
        "first_gts": x.related_object.group_tutoring_sessions.filter(cancelled=False).order_by("start").first()
    },
    "first_individual_tutoring_session_daily_digest": get_first_individual_tutoring_session_digest_details,
    "last_meeting": last_meeting_context,
    "unread_messages": get_unread_messages_context,
    "overdue_task_reminder": lambda x: {"tasks": Task.objects.filter(pk__in=x.additional_args)},
    "task_digest": lambda x: {"tasks": Task.objects.filter(pk__in=x.additional_args)},
    "coming_due_task_reminder": lambda x: {"tasks": Task.objects.filter(pk__in=x.additional_args)},
    # Used both for scheduling and rescheduling
    "counselor_meeting_scheduled": lambda x: {"old_time": dateparse.parse_datetime(x.additional_args.get("old_time"))},
    "counselor_weekly_digest": get_counselor_meeting_context,
    "course_enrollment_confirmation": lambda x: {
        "sessions": x.related_object.group_tutoring_sessions.order_by("start")
    },
    "counselor_meeting_message": get_counselor_meeting_message_context,
    notification_types.COUNSELOR_TASK_DIGEST: counselor_task_digest_context,
    notification_types.STUDENT_TASK_REMINDER: student_task_reminder_context,
    notification_types.COUNSELOR_COMPLETED_TASKS: counselor_completed_tasks_context,
    notification_types.INDIVIDUAL_TASK_REMINDER: lambda x: {
        "overdue": x.related_object.due and x.related_object.due <= timezone.now()
    },
}

# Helper function to determine whether we send standard invite or CAP invite (cap_invite.html)
def get_invite_email_template_name(notification: Notification):
    if (
        hasattr(notification.recipient.user, "student")
        and notification.recipient.user.student.counseling_student_types_list
    ):
        return CAP_INVITE
    if (
        hasattr(notification.recipient.user, "parent")
        and Student.objects.filter(parent__user=notification.recipient.user)
        .exclude(counseling_student_types_list=[])
        .exists()
    ):
        return CAP_INVITE
    return notification.notification_type


TEMPLATE_NAME_GETTERS = {"invite": get_invite_email_template_name}


def get_tutoring_session_notes(notification):
    """ Return tutoring session notes attachment, but only if user has usable password """
    if notification.recipient.user.has_usable_password():
        return (
            generate_pdf(notification.related_object),
            "application/json",
        )
    return (None, None)


# Functions to generate attachments
# Return (contentFile, mimetype)
ATTACHMENT_GENERATORS = {"tutoring_session_notes": get_tutoring_session_notes}

# Notifications where parent is directly cc'd instead of creating a separate notification object for them
CC_PARENT_ON_STUDENT_NOTIFICATIONS = ["task_diagnostic"]


def send_email_for_notification(notification: Notification, resend=True, force_test=False):
    """
        Send an email for a Notification object.
    Arguments:
            notification {Notification}
            resend {Boolean} Will resend notifications that have already been sent (default)
                unless this is set to False
            force_test {Bolean} If True we will send email to test address, even if env is prod
        Returns:
            Boolean indicating whether or not email was sent
    """
    if not notification.recipient:
        raise ValueError(f"Cannot send notification without recipient (noti {notification.slug})")

    template_name = notification.notification_type
    if notification.notification_type in TEMPLATE_NAME_GETTERS:
        template_name = TEMPLATE_NAME_GETTERS[notification.notification_type](notification)
    template_file = f"cwnotifications/email_templates/{template_name}.html"
    if notification.emailed and not resend:
        return False
    if not notification.recipient.receive_emails:
        return False
    if (
        not notification.recipient.user.has_usable_password()
        and notification.notification_type not in NOTIFICATIONS_FOR_PENDING_USERS
    ):
        return False
    # We attempt to get copy for email
    try:
        cw_user = get_cw_user(notification.recipient.user)
        context = {
            "notification": notification,
            "SITE_NAME": settings.SITE_NAME,
            "SITE_URL": settings.SITE_URL,
            "DEBUG": settings.DEBUG,
            "TIME_ZONE": cw_user.timezone,  # Could very well be None
            "cas_student": False,
            "cap_reply_to": None,
        }
        # We figure out if email is for CAS student. Note that individual noti context methods can override this!
        if hasattr(notification.recipient.user, "student"):
            context["cas_student"] = not notification.recipient.user.student.counseling_student_types_list
            if "counselor_meeting" in notification.notification_type and notification.recipient.user.student.counselor:
                context["cap_reply_to"] = notification.recipient.user.student.counselor.invitation_email
        elif hasattr(notification.recipient.user, "parent"):
            if "counselor_meeting_message" in notification.notification_type:
                context["cas_student"] = False
                context["cap_reply_to"] = notification.related_object.student.counselor.invitation_email
            else:
                context["cas_student"] = notification.recipient.user.parent.students.filter(
                    counseling_student_types_list=[]
                ).exists()
        # Generate additional context to pass to email template
        if notification.notification_type in CONTEXT_GENERATORS:
            context.update(CONTEXT_GENERATORS[notification.notification_type](notification))
        carbon_copy = None
        # If recipient is student and notification is not a cc, we check whether or not parent is to be cc'd on
        # this notification. If they are, then we recursively call ourself to create another notification
        if (
            hasattr(notification.recipient.user, "student")
            and not notification.is_cc
            and notification.recipient.user.student.parent
            and get_notification_config(notification.notification_type).get("cc_parent")
        ):
            carbon_copy = list(
                Parent.objects.filter(students=notification.recipient.user.student).values_list(
                    "user__email", flat=True
                )
            )
            # if parent object has cc_email field, cc that email as well
            parent_cc = notification.recipient.user.student.parent.cc_email
            if parent_cc:
                carbon_copy.append(parent_cc)
        elif (
            hasattr(notification.recipient.user, "parent")
            and Parent.objects.filter(user_id=notification.recipient.user_id).first().cc_email
        ):
            carbon_copy = [Parent.objects.filter(user_id=notification.recipient.user_id).first().cc_email]

        if notification.cc_email and carbon_copy is None:
            carbon_copy = [notification.cc_email]
        elif notification.cc_email and carbon_copy is not None:
            carbon_copy.append(notification.cc_email)

        subject = notification.title

        # When DEBUG=True, all go to settings.TEST_EMAILS_TO with a note indicating who the
        # email would have gone to
        send_test_email = force_test or (settings.ENV != "production" and not settings.TESTING)
        if send_test_email:
            subject = f"[CW Platform Sandbox - {settings.ENV}] {subject}"
            context["test_email_recipient"] = notification.recipient.user.email

        msg = mail.EmailMultiAlternatives(
            subject=subject,
            from_email=settings.EMAIL_FROM,
            to=[notification.recipient.user.email if not send_test_email else settings.TEST_EMAILS_TO],
            cc=carbon_copy if not send_test_email else None,
        )
        msg.attach_alternative(render_to_string(template_file, context=context), "text/html")
        if notification.notification_type in ATTACHMENT_GENERATORS:
            attachment_content_file, mime = ATTACHMENT_GENERATORS[notification.notification_type](notification)
            if attachment_content_file:
                msg.attach(
                    filename=attachment_content_file.name, content=attachment_content_file.read(), mimetype=mime,
                )

        if settings.ENV == "production":
            msg.send(fail_silently=True)
        else:
            msg.send(fail_silently=False)

        notification.emailed = timezone.now()
        notification.save()
        return True
    except TemplateDoesNotExist as exc:
        print(f"Email template does not exist: {template_name}", exc)
        return False
