from django.contrib.contenttypes.models import ContentType

from cwnotifications.generator import create_notification
from cwtutoring.models import StudentTutoringSession


class TutoringSessionNotesManager:
    tutoring_session_notes = None

    def __init__(self, tutoring_session_notes=None):
        self.tutoring_session_notes = tutoring_session_notes

    def send_notification(self, student_tutoring_session, cc_email=None):
        """ Send these notes to student associated with student_tutoring_session
            SESSION WILL BE ADDED TO self.tutoring_session_notes.student_tutoring_sessions!!
            (to ensure student has access to notes)
            Arguments:
                student_tutoring_session {StudentTutoringSession}
            Returns: None
        """
        if not self.tutoring_session_notes:
            raise ValueError("No notes to send")

        if student_tutoring_session.tutoring_session_notes != self.tutoring_session_notes:
            student_tutoring_session.tutoring_session_notes = self.tutoring_session_notes
            student_tutoring_session.save()

        noti_data = {
            "notification_type": "tutoring_session_notes",
            "actor": self.tutoring_session_notes.author.user,
            "related_object_content_type": ContentType.objects.get_for_model(StudentTutoringSession),
            "related_object_pk": student_tutoring_session.pk,
            "cc_email": cc_email,
        }

        if self.tutoring_session_notes.visible_to_student:
            create_notification(student_tutoring_session.student.user, **noti_data)
        if self.tutoring_session_notes.visible_to_parent and student_tutoring_session.student.parent:
            create_notification(student_tutoring_session.student.parent.user, **noti_data)

