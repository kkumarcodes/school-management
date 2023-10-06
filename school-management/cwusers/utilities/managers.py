from typing import Tuple
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from cwmessages.models import ConversationParticipant
from cwmessages.utilities.conversation_manager import ConversationManager
from cwnotifications.constants.notification_types import CAP_MAGENTO_STUDENT_CREATED, CAS_MAGENTO_STUDENT_CREATED
from cwnotifications.generator import create_notification
from cwnotifications.models import Notification, NotificationRecipient
from cwnotifications.utilities.bulletin_manager import BulletinManager
from cwusers.models import Administrator, Student, Parent, Counselor, Tutor
from cwcommon.utilities.manager_base import ModelManagerBase


class UserManagerBase(ModelManagerBase):
    """ Some common logic for creating and updating users """

    @classmethod
    def create_user(cls, invite=True, **kwargs):
        cw_user, created = cls._get_or_create(**kwargs)
        if invite:
            create_notification(cw_user.user, notification_type="invite")
            cw_user.last_invited = timezone.now()
            cw_user.save()
        NotificationRecipient.objects.get_or_create(user=cw_user.user)
        return (cw_user, created)


class TutorManager(UserManagerBase):
    """ Manager for Tutor. """

    class Meta:
        model = Tutor

    def __init__(self, tutor: Tutor):
        super().__init__(tutor)
        self.tutor = tutor

    @classmethod
    def create(cls, invite=True, **kwargs) -> Tuple[Tutor, bool]:
        return cls.create_user(invite=invite, **kwargs)


class CounselorManager(UserManagerBase):
    """ Manager for Counselor. """

    class Meta:
        model = Counselor

    def __init__(self, counselor: Counselor):
        super().__init__(counselor)
        self.counselor = counselor

    @classmethod
    def create(cls, invite=True, **kwargs) -> Tuple[Counselor, bool]:
        return cls.create_user(invite=invite, **kwargs)


class StudentManager(UserManagerBase):
    """ Manager for Student. """

    class Meta:
        model = Student

    def __init__(self, student: Student):
        super().__init__(student)
        self.student = student

    @classmethod
    def create(cls, invite=True, **kwargs) -> Tuple[Student, bool]:
        student, created = cls.create_user(invite=invite, **kwargs)
        # We set visible bulletins on student
        if created:
            student.user.notification_recipient.bulletins.add(
                *list(BulletinManager.get_evergreen_bulletins_for_new_student(student))
            )
            # If we created student with a parent, we need to set bulletins on that parent
            if student.parent:
                StudentManager(student).set_parent(student.parent)
            StudentManager(student).save_counseling_student_types()

        return (student, created)

    def save_counseling_student_types(self) -> Student:
        """ Business logic that takes place after changes to a student's counseling student types
            The crux here is that paygo students need their is_paygo flag set to True
        """
        if "paygo" in [x.lower() for x in self.student.counseling_student_types_list]:
            self.student.is_paygo = True
            self.student.save()
        return self.student

    def set_parent(self, parent: Parent) -> Student:
        """ Set the parent on our student, and make proper evergreen bulletins visible to that parent
        """
        self.student.parent = parent
        self.student.save()
        parent_manager = ParentManager(parent)
        parent_manager.set_evergreen_bulletins()
        return self.student

    def set_counselor(self, counselor: Counselor = None) -> Student:
        """ Helper method to update a student's counselor. In addition to setting counselor prop, we:
            1) Unsubscribe old counselor from conversations with student. Subscribe new counselor
            2) Update tasks created by old counselor to instead be created by new counselor
            New counselor can be None, in which case old counselor (if there is one) is just removed
                from all conversations with student or their parent
        """
        if self.student.counselor and self.student.counselor != counselor:
            old_counselor: Counselor = self.student.counselor
            participants = ConversationParticipant.objects.filter(
                notification_recipient__user__counselor=old_counselor, conversation__student=self.student
            )
            if self.student.parent:
                participants &= ConversationParticipant.objects.filter(
                    notification_recipient__user__counselor=old_counselor, conversation__parent=self.student.parent
                )
            mgr = ConversationManager()
            for participant in participants:
                if counselor:
                    mgr.get_or_create_chat_participant(
                        participant.conversation,
                        counselor.invitation_name,
                        notification_recipient=counselor.user.notification_recipient,
                    )
                mgr.delete_conversation_participant(participant)

        if counselor:
            if self.student.counselor:
                self.student.user.tasks.filter(created_by=old_counselor.user).update(created_by=counselor.user)
            self.student.counselor = counselor
            self.student.save()
        return self.student

    def send_new_cap_student_notification(self) -> None:
        """ Assumes self.student is a new user, and sends notifications to counselor that new
            CAP student was created
        """

        if self.student.counselor:
            notification_data = {
                "related_object_content_type": ContentType.objects.get_for_model(Student),
                "related_object_pk": self.student.pk,
                "notification_type": CAP_MAGENTO_STUDENT_CREATED,
            }
            if (
                Notification.objects.filter(recipient__user=self.student.counselor.user)
                .filter(**notification_data)
                .exists()
            ):
                return False
            create_notification(self.student.counselor.user, **notification_data)

    def send_new_cas_student_notification(self) -> None:
        """ Assumes self.student is new student (or newly a CAS student) and sends noti to counselor
            and ops team of new CAS student
        """
        notification_data = {
            "related_object_content_type": ContentType.objects.get_for_model(Student),
            "related_object_pk": self.student.pk,
            "notification_type": CAS_MAGENTO_STUDENT_CREATED,
        }
        # If this notification type already exists for ANY user then we don't resend
        if Notification.objects.filter(**notification_data).exists():
            return False

        [create_notification(a.user, **notification_data) for a in Administrator.objects.all()]

        # Counselor gets notification if student is not new and has a counselor
        if self.student.counselor:
            create_notification(self.student.counselor.user, **notification_data)


class ParentManager(UserManagerBase):
    """ Manager for Parent. """

    class Meta:
        model = Parent

    def __init__(self, parent: Parent):
        super().__init__(parent)
        self.parent = parent

    @classmethod
    def create(cls, invite=True, **kwargs) -> Tuple[Parent, bool]:
        return cls.create_user(invite=invite, **kwargs)

    def set_evergreen_bulletins(self) -> Parent:
        """ Set evergreen bulletins on a parent. Ideally after their students have been assigned ;) """
        self.parent.user.notification_recipient.bulletins.add(
            *list(BulletinManager.get_evergreen_bulletins_for_new_parent(self.parent))
        )
        return self.parent


USER_MANAGERS_BY_USER_CLASS = {
    Counselor: CounselorManager,
    Student: StudentManager,
    Tutor: TutorManager,
    Parent: ParentManager,
}
