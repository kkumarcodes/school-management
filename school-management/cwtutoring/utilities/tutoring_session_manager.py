""" Utility for managing tutoring sessions, including signing students up for tutoring sessions,
  verifying students have enough hours for session, and sending communications regarding sessions
"""
from typing import List
from datetime import timedelta, datetime, date
from django.conf import settings
from django.utils import timezone, dateparse
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.contrib.auth.models import User

from cwtutoring.models import (
    StudentTutoringSession,
    Course,
    GroupTutoringSession,
)
from cwtutoring.utilities.tutoring_package_manager import StudentTutoringPackagePurchaseManager
from cwusers.models import Student, Tutor, Administrator
from cwusers.utilities.graph_helper import (
    outlook_delete,
    outlook_update,
    outlook_create,
    GraphHelperException,
)
from cwnotifications.generator import create_notification
from cwresources.models import ResourceGroup
from cwtasks.models import Task

BUFFER = 0
DIAGNOSTIC_REGISTRATION_NOTI = "student_diagnostic_registration"
STS_CONFIRMATION_NOTI = "student_tutoring_session_confirmation"
OPS_DIAGNOSTIC_REGISTRATION_NOTI = "ops_student_diagnostic_registration"
DIAGNOSTIC_RESOURCE_GROUP_TITLE = "Diagnostic"


class TutoringSessionManagerException(Exception):
    pass


class TutoringSessionManager:
    student_tutoring_session = None

    def __init__(self, session=None):
        self.student_tutoring_session = session

    def _get_notification_data(self):
        """ Utility method to get data used to create a notification or self.student_tutoring_session
        """
        return {
            "related_object_content_type": ContentType.objects.get_for_model(StudentTutoringSession),
            "related_object_pk": self.student_tutoring_session.pk,
            "is_cc": False,
        }

    @staticmethod
    def cancel_group_tutoring_session(gts: GroupTutoringSession, actor: User = None) -> GroupTutoringSession:
        """ Cancel a group tutoring session, which notifies students that have associated
            StudentTutoringSession
            Arguments:
                gts {GroupTutoringSession} to delete
                actor optional {User} who is deleting the session
        """
        if gts.diagnostic:
            list_of_tasks_to_cancel = Task.objects.filter(
                diagnostic=gts.diagnostic, for_user__student__tutoring_sessions__group_tutoring_session=gts
            ).distinct()
            list_of_tasks_to_cancel.update(archived=timezone.now())

        gts.cancelled = True
        gts.save()

        # if this is on tutor's outlook calendar, delete from calendar
        try:
            if gts.outlook_event_id and gts.primary_tutor.microsoft_token:
                outlook_delete(gts)
        except GraphHelperException as e:
            if settings.TESTING:
                print(e)

        # Create notifications for tutors and students
        noti_kwargs = {
            "actor": actor or gts.primary_tutor.user,
            "related_object_content_type": ContentType.objects.get_for_model(GroupTutoringSession),
            "related_object_pk": gts.pk,
            "is_cc": False,
            "notification_type": "group_tutoring_session_cancelled",
        }
        for tutor in Tutor.objects.filter(
            Q(primary_group_tutoring_sessions=gts) | Q(support_group_tutoring_sessions=gts)
        ):
            create_notification(tutor.user, **noti_kwargs)

        for sts in StudentTutoringSession.objects.filter(group_tutoring_session=gts, set_cancelled=False,):
            create_notification(sts.student.user, **noti_kwargs)
        return gts

    def cancel(self, actor=None):
        """ Cancels a student tutoring session. Sends notification to student and - where applicable - individual
            session tutor IF SESSION WAS NOT TENTATIVE
            Arguments:
                actor {User} optional actor for notification(s)
            Returns updated StudentTutoringSession
        """
        if self.student_tutoring_session.cancelled:
            return self.student_tutoring_session
        self.student_tutoring_session.set_cancelled = True
        self.student_tutoring_session.save()

        # if event is on CWuser outlook calendar, remove event from tutor outlook calendar
        try:
            if (
                self.student_tutoring_session.outlook_event_id
                and self.student_tutoring_session.individual_session_tutor.microsoft_token
            ):
                outlook_delete(self.student_tutoring_session)
        except GraphHelperException as e:
            if settings.TESTING:
                print(e)

        # No notifications for tentative sessions. That would be so silly!
        if self.student_tutoring_session.is_tentative:
            return self.student_tutoring_session

        create_notification(
            self.student_tutoring_session.student.user,
            actor=actor,
            notification_type="student_tutoring_session_cancelled",
            **self._get_notification_data(),
        )
        if self.student_tutoring_session.individual_session_tutor:
            create_notification(
                self.student_tutoring_session.individual_session_tutor.user,
                actor=actor,
                notification_type="tutor_tutoring_session_cancelled",
                **self._get_notification_data(),
            )
        return self.student_tutoring_session

    def uncancel(self, actor=None):
        """ Uncancels an individual student session (only if request made by administrator).
            Returns updated StudentTutoringSession
        """
        if not self.student_tutoring_session.cancelled:
            return self.student_tutoring_session
        self.student_tutoring_session.set_cancelled = False
        self.student_tutoring_session.late_cancel = False
        self.student_tutoring_session.save()

        # create an outlook calendar event for this session on the tutor's calendar
        if (
            self.student_tutoring_session.outlook_event_id
            and self.student_tutoring_session.individual_session_tutor.microsoft_token
        ):
            try:
                outlook_create(self.student_tutoring_session)
            except GraphHelperException as e:
                if settings.TESTING:
                    print(e)

        return self.student_tutoring_session

    def reschedule(self, start, end, actor=None):
        """ Reschedules self.student_tutoring_session to new start and end time.
            ALSO UPDATES DURATION_MINUTES
            Can't reschedule group session.
            Arguments:
                start {Datetime}
                end {Datetime}
            Returns updated StudentTutoringSession
        """
        if not self.student_tutoring_session.individual_session_tutor:
            raise TutoringSessionManagerException("Cannot reschedule group session")
        if start >= end:
            raise TutoringSessionManagerException("Invalid start/end times for reschedule")
        self.student_tutoring_session.start = start
        self.student_tutoring_session.end = end
        self.student_tutoring_session.duration_minutes = (end - start).total_seconds() / 60.0
        self.student_tutoring_session.save()

        # update event in CWUser outlook calendar
        try:
            if (
                self.student_tutoring_session.outlook_event_id
                and self.student_tutoring_session.individual_session_tutor.microsoft_token
            ):
                outlook_update(self.student_tutoring_session)
        except GraphHelperException as e:
            if settings.TESTING:
                print(e)

        create_notification(
            self.student_tutoring_session.student.user,
            actor=actor,
            notification_type="student_tutoring_session_rescheduled",
            **self._get_notification_data(),
        )
        create_notification(
            self.student_tutoring_session.individual_session_tutor.user,
            actor=actor,
            notification_type="tutor_tutoring_session_rescheduled",
            **self._get_notification_data(),
        )
        return self.student_tutoring_session

    def reschedule_individual_sessions(self, start, end, duration, actor=None):
        """ Reschedules an individual group tutoring session that is part of a course
            to new start and end time. Actor must be a tutor or admin.
            ALSO UPDATES DURATION_MINUTES

            Arguments:
                start {Datetime}
                end {Datetime}
                actor {User}
                duration { }
            Returns updated StudentTutoringSession
        """
        if not hasattr(actor, "administrator"):
            raise TutoringSessionManagerException("You are not authorized.")
        if start >= end:
            raise TutoringSessionManagerException("Invalid start/end times for reschedule")
        self.student_tutoring_session.start = start
        self.student_tutoring_session.end = end
        self.student_tutoring_session.duration_minutes = duration
        self.student_tutoring_session.save()

        return self.student_tutoring_session

    @staticmethod
    def student_can_join_group_session(student, group_tutoring_session):
        """ Check whether or not student can join group tutoring session, considering
            student's hours and capacity constraints

            Arguments:
              student {Student}
              group_tutoring_session {GroupTutoringSession}
        """
        # TODO: Check student's hours
        # Ensure student doesn't already have a session at this time
        return (
            group_tutoring_session.student_tutoring_sessions.exclude(set_cancelled=True).count()
            < group_tutoring_session.capacity
        )

    @staticmethod
    def enroll_student_in_course(student, course, purchase=False):
        """ Enroll a student in a course, creating necessary GroupTutoringSessions,
            sending confirmations, and removing pending_enrollment_course from student
            Additionally - assigns enrolled student to the primary tutor of each session
            Arguments:
                student {Student}
                course {Course} course to enroll in
                purchase {Boolean} If True we will execute a payment for student and add the
                    course's related tutoring package
            Returns updated Student object
        """
        if student.courses.filter(pk=course.pk).exists():
            raise TutoringSessionManagerException(f"Student {student} already enrolled in course {course}")

        # Attempt the purchase if needed
        if purchase:
            if not course.package:
                raise TutoringSessionManagerException(f"Package {course.name} cannot be purchased")
            mgr = StudentTutoringPackagePurchaseManager(student)
            # Exception will be raised if charge fails or what have you
            mgr.purchase_package(course.package, execute_charge=True, send_noti=False, purchaser=student.user)

        for gts in course.group_tutoring_sessions.filter(start__gte=timezone.now()):
            # Assign student to session primary tutor
            gts.primary_tutor.students.add(student)
            # Enroll student in course but do NOT send notification for each session
            TutoringSessionManager.enroll_student_in_gts(student, gts, send_notification=False)

        create_notification(
            student.user,
            notification_type="course_enrollment_confirmation",
            related_object_content_type=ContentType.objects.get_for_model(Course),
            related_object_pk=course.pk,
            secondary_related_object_content_type=ContentType.objects.get_for_model(Student),
            secondary_related_object_pk=student.pk,
        )
        student.courses.add(course)
        if student.pending_enrollment_course == course:
            student.pending_enrollment_course = None
            student.save()
        return student

    @staticmethod
    def unenroll_student_from_course(student, course):
        """ Unenroll a student from a course they are already enrolled in.
            WIll cancel upcoming group tutoring sessions for the course
            Arguments:
                student {Student}
                course {Course} course to unenroll from
            Returns updated Student object
        """
        if not student.courses.filter(pk=course.pk).exists():
            raise TutoringSessionManagerException(f"Student {student} is not enrolled in course {course}")
        # Cancel upcoming student tutoring sessions
        student.tutoring_sessions.filter(
            set_cancelled=False, missed=False, start__gt=timezone.now(), group_tutoring_session__courses=course,
        ).update(set_cancelled=True)
        create_notification(
            student.user,
            notification_type="course_unenrollment_confirmation",
            related_object_content_type=ContentType.objects.get_for_model(Course),
            related_object_pk=course.pk,
            secondary_related_object_content_type=ContentType.objects.get_for_model(Student),
            secondary_related_object_pk=student.pk,
        )
        student.courses.remove(course)
        return student

    @staticmethod
    def enroll_student_in_gts(
        student: Student, group_tutoring_session: GroupTutoringSession, send_notification=True,
    ) -> StudentTutoringSession:
        """ Enroll student in GTS (creates STS)
            Arguments:
                student {Student} stud to enroll
                group_tutoring_session {GroupTutoringSession} GTS they're enrolling in
                send_notification {bool; default True} whether or not to send noti for enrollment
        """
        if not TutoringSessionManager.student_can_join_group_session(student, group_tutoring_session):
            raise TutoringSessionManagerException("Cannot join group session")
        # Create STS
        sts = StudentTutoringSession.objects.create(
            group_tutoring_session=group_tutoring_session,
            start=group_tutoring_session.start,
            end=group_tutoring_session.end,
            student=student,
            duration_minutes=group_tutoring_session.charge_student_duration,
        )
        # Give student access to resources
        for resource in group_tutoring_session.resources.all():
            student.visible_resources.add(resource)

        # There's a special diangostic resource group that we give student access to if enrolling in diagnostic
        if (
            group_tutoring_session.charge_student_duration == 0
            and DIAGNOSTIC_RESOURCE_GROUP_TITLE in group_tutoring_session.title
        ):
            diag_resource_group = ResourceGroup.objects.filter(title=DIAGNOSTIC_RESOURCE_GROUP_TITLE).first()
            if diag_resource_group:
                student.visible_resource_groups.add(diag_resource_group)

        # If it's a diagnostic, we ened to create a diag task for student
        if group_tutoring_session.diagnostic:
            task: Task = Task.objects.create(
                diagnostic=group_tutoring_session.diagnostic,
                for_user=student.user,
                due=group_tutoring_session.end,
                require_file_submission=True,
                title=f"{group_tutoring_session.title} Diagnostic",
            )
            resources = list(group_tutoring_session.diagnostic.resources.all())
            task.resources.add(*resources)
            # Student gets access to diagnostic materials
            student.visible_resources.add(*resources)
            # No need for a task notification here

        if send_notification and sts.start > timezone.now():
            # Diagnostics have their own notification type
            notification_type = (
                DIAGNOSTIC_REGISTRATION_NOTI
                # TODO: We don't need to filter on diagnostic in title once we have diag objects associated
                # with all diag GTS
                if group_tutoring_session.diagnostic or "diagnostic" in group_tutoring_session.title.lower()
                else STS_CONFIRMATION_NOTI
            )
            create_notification(
                sts.student.user,
                notification_type=notification_type,
                related_object_content_type=ContentType.objects.get_for_model(StudentTutoringSession),
                related_object_pk=sts.pk,
            )
            if notification_type == DIAGNOSTIC_REGISTRATION_NOTI:
                for admin in Administrator.objects.filter(is_diagnostic_scorer=True):
                    create_notification(
                        admin.user,
                        notification_type=OPS_DIAGNOSTIC_REGISTRATION_NOTI,
                        related_object_content_type=ContentType.objects.get_for_model(StudentTutoringSession),
                        related_object_pk=sts.pk,
                    )
        return sts

    @staticmethod
    def mark_paygo_sessions_paid(session_type: str, student: Student, hours: float) -> List[StudentTutoringSession]:
        """ Use purchased hours to mark future paygo sessions as paid.
            Will mark as many sessions paid as package has hours to cover
        """
        if not (student.is_paygo):
            raise TutoringSessionManagerException("Cannot mark paygo sessions paid for non-paygo student")
        updated_sessions = []
        unpaid_sessions = (
            student.tutoring_sessions.filter(
                set_cancelled=False,
                individual_session_tutor__isnull=False,
                session_type=session_type,
                missed=False,
                paygo_transaction_id="",
            )
            .exclude(duration_minutes=0)
            .order_by("start")
        )

        while unpaid_sessions.exists() and unpaid_sessions.first().duration_minutes / 60.0 <= hours and hours > 0:
            session = unpaid_sessions.first()
            session.paygo_transaction_id = "From Magento Purchase"
            session.save()
            updated_sessions.append(session)
            hours -= session.duration_minutes / 60.0

        return updated_sessions
