""" Manager for creating, filtering, and sending (as Notification) Bulletins
"""
import itertools
from django.utils import timezone
from django.db.models.query import QuerySet
from django.db.models.query_utils import Q
from django.contrib.contenttypes.models import ContentType
from snnotifications.models import Bulletin, NotificationRecipient
from snnotifications.generator import create_notification
from snnotifications.constants import notification_types
from snusers.models import Parent, Student


class BulletinManager:
    bulletin: Bulletin = None

    def __init__(self, bulletin=None):
        if bulletin:
            if not isinstance(bulletin, Bulletin):
                raise ValueError("Invalid bulletin for BulletinManager")
            self.bulletin = bulletin

    # @shared_task
    def send_bulletin(self, notification_recipients=None):
        """Send self.bulletin to everyone in it's visible_to_notification_recipients
            Note this is an async method that can be called with .delay() to be executed
            by Celery.
            Arguments:
                notification_recipients: Optional list of notification recipients to send
                    bulletin to. Must be a subset of self.bulletin.visible_to_notification_recipients

        """
        data = {
            "notification_type": notification_types.BULLETIN,
            "related_object_content_type": ContentType.objects.get_for_model(Bulletin),
            "related_object_pk": self.bulletin.pk,
        }
        send_to_recipients = (
            self.bulletin.visible_to_notification_recipients.filter(pk__in=[x.pk for x in notification_recipients])
            if notification_recipients
            else self.bulletin.visible_to_notification_recipients.all()
        )
        for recipient in send_to_recipients:
            create_notification(recipient.user, **data)

    def set_visible_to_notification_recipients(self) -> Bulletin:
        """ Sets self.bulletin.visible_to_notification_recipients based off the value of filtering
            fields on self.bulletin. Meant to be called when first creating a bulletin.

            For students/parents, we only search for students and parents visible to self.bulletin.created_by.
            So if the bulletin is created by a counselor/tutor, only their students (and their students parents)
            will get added to visible_to_notification_recipients.
            IF THE BULLETIN IS CREATED BY AN ADMIN THEN ALL STUDENTS/PARENTS/TUTORS/COUNSELORS CAN BE ADDED

            Overwrites existing visible_to_notification_recipients
            Returns updated Bulletin
        """
        self.bulletin.visible_to_notification_recipients.clear()
        if self.bulletin.students or self.bulletin.parents:
            filter_kwargs = {}
            if self.bulletin.class_years and not self.bulletin.all_class_years:
                filter_kwargs["graduation_year__in"] = self.bulletin.class_years
            if self.bulletin.tags:
                filter_kwargs["tags__overlap"] = self.bulletin.tags
            if not self.bulletin.cap:
                filter_kwargs["counseling_student_types_list"] = []
            elif self.bulletin.counseling_student_types and not self.bulletin.all_counseling_student_types:
                filter_kwargs["counseling_student_types_list__overlap"] = self.bulletin.counseling_student_types

            students = parents = []

            # Setup filtering based on who created the bulletin
            if hasattr(self.bulletin.created_by, "administrator"):
                base_students = Student.objects.all()
                base_parents = Parent.objects.all()
            else:
                base_students = Student.objects.filter(
                    Q(counselor__user=self.bulletin.created_by) | Q(tutors__user=self.bulletin.created_by)
                )
                base_parents = Parent.objects.filter(students__in=base_students)

            cap_students = base_students.exclude(counseling_student_types_list=[])

            if self.bulletin.students:
                students = (
                    base_students.filter(**filter_kwargs) if self.bulletin.cas else cap_students.filter(**filter_kwargs)
                ).distinct()
            if self.bulletin.parents:
                parent_filter_kwargs = {}
                for k, v in filter_kwargs.items():
                    parent_filter_kwargs[f"students__{k}"] = v
                parents = base_parents.filter(**parent_filter_kwargs)
                if not self.bulletin.cas:
                    parents = parents.filter(students__in=cap_students).distinct()

            self.bulletin.visible_to_notification_recipients.add(
                *NotificationRecipient.objects.filter(Q(user__student__in=students) | Q(user__parent__in=parents))
            )
        if self.bulletin.tutors and hasattr(self.bulletin.created_by, "administrator"):
            self.bulletin.visible_to_notification_recipients.add(
                *NotificationRecipient.objects.filter(user__tutor__isnull=False)
            )
        if self.bulletin.counselors and hasattr(self.bulletin.created_by, "administrator"):
            self.bulletin.visible_to_notification_recipients.add(
                *NotificationRecipient.objects.filter(user__counselor__isnull=False)
            )
        return self.bulletin

    @staticmethod
    def get_bulletins_for_notification_recipient(notification_recipient: NotificationRecipient):
        """ Get all of the bulletins that are visible to a notification_recipient
        """
        if hasattr(notification_recipient.user, "administrator"):
            return Bulletin.objects.all()
        return Bulletin.objects.filter(
            Q(created_by=notification_recipient.user) | Q(visible_to_notification_recipients=notification_recipient)
        ).distinct()

    @staticmethod
    def get_evergreen_bulletins_for_new_student(student: Student) -> QuerySet:
        """ Get evergreen bulletins that should be visible to a new student or parent
            Currently only considers bulletins created by the student's counselor
        """
        if not (isinstance(student, Student)):
            raise ValueError("Attempting to get evergreen bulletins for non-student")
        return (
            Bulletin.objects.filter(evergreen=True, created_by__counselor__students=student, students=True)
            .filter(Q(evergreen_expiration=None) | Q(evergreen_expiration__gt=timezone.now()))
            .filter(Q(class_years__overlap=[student.graduation_year]) | Q(all_class_years=True))
            .filter(
                Q(counseling_student_types__overlap=student.counseling_student_types_list)
                | Q(all_counseling_student_types=True)
            )
            .distinct()
        )

    @staticmethod
    def get_evergreen_bulletins_for_new_parent(parent: Parent) -> QuerySet:
        if not (isinstance(parent, Parent)):
            raise ValueError("Attempting to get evergreen bulletins for non-parent")
        grad_years = list(parent.students.values_list("graduation_year", flat=True))
        counseling_student_types_list = list(
            itertools.chain(parent.students.values_list("counseling_student_types_list", flat=True))
        )
        counseling_student_types = [item for sublist in counseling_student_types_list for item in sublist]
        return (
            Bulletin.objects.filter(evergreen=True, created_by__counselor__students__parent=parent, parents=True)
            .filter(Q(evergreen_expiration=None) | Q(evergreen_expiration__gt=timezone.now()))
            .filter(Q(class_years__overlap=grad_years) | Q(all_class_years=True))
            .filter(
                Q(counseling_student_types__overlap=counseling_student_types) | Q(all_counseling_student_types=True)
            )
            .distinct()
        )
