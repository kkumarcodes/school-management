"""
    This module contains views for CRUD operations on TutoringSessionNotes, and a view for
    retrieving a PDF of TutoringSessionNotes
"""
from django.shortcuts import get_object_or_404
from django.db.models import Q

from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework.response import Response

from snusers.models import Student, Parent, Tutor
from snusers.mixins import AccessStudentPermission
from cwtutoring.serializers.tutoring_session_notes import TutoringSessionNotesSerializer
from cwtutoring.models import TutoringSessionNotes, StudentTutoringSession
from cwtutoring.utilities.tutoring_session_notes_manager import TutoringSessionNotesManager


class TutoringSessionNotesViewset(ModelViewSet, AccessStudentPermission):
    """ LIST: Must include one of the following query args:
            ?student
            ?tutor
            ?all (ADMIN ONLY)
        CREATE: See TutoringSessionNotesSerializer. Worth noting that group_tutoring_session or
            (write-only) individual_tutoring_session field must be included. Must be author or Admin.

        RETRIEVE (specific obj by PK) is NOT SUPPORTED
        UPDATE: See TutoringSessionNotesSerializer. Must be author or Admin.
        DELETE: Must be author or Admin
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = TutoringSessionNotesSerializer
    queryset = TutoringSessionNotes.objects.all()

    def check_object_permissions(self, request, obj):
        """ Confirm user is admin, tutor, or has access to one of the students notes are for
        """
        super(TutoringSessionNotesViewset, self).check_object_permissions(request, obj)
        method = request.method.lower()
        if hasattr(request.user, "administrator"):
            return True
        # Counselors can read only
        elif hasattr(request.user, "counselor") and method == "get":
            return True
        # Tutors have full access to their notes, and can read all other notes
        elif hasattr(request.user, "tutor") and (method == "get" or obj.author.user == request.user):
            return True
        elif (
            Student.objects.filter(tutoring_sessions__tutoring_session_notes=obj, user=request.user).exists()
            or Parent.objects.filter(
                students__tutoring_sessions__tutoring_session_notes=obj, user=request.user,
            ).exists()
            and method == "get"
        ):
            return True

        self.permission_denied(request)

    def check_permissions(self, request):
        """ Ensure that create only done by administrator or author.
            Ensure that tutors can only create for their own sessions
        """
        super(TutoringSessionNotesViewset, self).check_permissions(request)
        if hasattr(self.request.user, "administrator"):
            return True
        if request.method.lower() == "post" and request.data.get("author"):
            author = get_object_or_404(Tutor, pk=request.data.get("author"))
            if author.user != request.user:
                self.permission_denied(request)
        if self.kwargs.get("pk"):
            obj = self.get_object()
            if obj.author.user != request.user:
                self.permission_denied(request)

    def filter_queryset(self, queryset):
        """ Combination of filtering queryset and some authentication
        """
        query_params = self.request.query_params
        if query_params.get("student"):
            student = get_object_or_404(Student, pk=query_params["student"])
            if not self.has_access_to_student(student):
                self.permission_denied(self.request)
            return queryset.filter(student_tutoring_sessions__student=student).distinct()
        elif query_params.get("tutor"):
            tutor = get_object_or_404(Tutor, pk=query_params["tutor"])
            if not (hasattr(self.request.user, "administrator") or tutor.user == self.request.user):
                self.permission_denied(self.request)
            return queryset.filter(
                Q(author=tutor)
                | Q(group_tutoring_session__primary_tutor=tutor)
                | Q(group_tutoring_session__support_tutors=tutor)
                | Q(student_tutoring_sessions__individual_session_tutor=tutor)
            ).distinct()
        elif query_params.get("all"):
            if not hasattr(self.request.user, "administrator"):
                self.permission_denied(self.request)
            return queryset
        if self.request.method.lower() == "get" and not self.kwargs.get("pk"):
            raise ValidationError("Invalid query parameters")
        return queryset

    @action(methods=["POST"], detail=True, url_path="send")
    def send(self, request, *args, **kwargs):
        """ Send notes to a student, by referencing StudentTutoringSession.
            If StudentTutoringSession is related to notes' group session, but is not
            in notes.student_tutoring_sessions, then will be added to notes.student_tutoring_sessions
            Arguments:
                student_tutoring_session {StudentTutoringSession PK}
            Returns:
                204 No Content
        """
        notes = self.get_object()
        mgr = TutoringSessionNotesManager(notes)

        if request.data.get("student_tutoring_session"):
            student_tutoring_session = get_object_or_404(
                StudentTutoringSession, pk=request.data.get("student_tutoring_session")
            )
            # Ensure session can be associated with notes
            if not notes.student_tutoring_sessions.filter(pk=student_tutoring_session.pk).exists():
                if not (
                    student_tutoring_session.group_tutoring_session
                    and student_tutoring_session.group_tutoring_session == notes.group_tutoring_session
                ):
                    raise ValidationError("StudentTutoringSession cannot be associated with TutoringSessionNotes")
            mgr.send_notification(student_tutoring_session)
        else:
            # We send note to all students
            for student_tutoring_session in notes.student_tutoring_sessions.filter(
                missed=False, set_cancelled=False
            ).exclude(group_tutoring_session__cancelled=True):
                mgr.send_notification(student_tutoring_session)
        return Response(status=204)

    def perform_create(self, serializer):
        """ Override create to send notifications """
        # Note that after notes are created, notes.student_tutoring_sessions will include StudentTutoringSession
        # objects related to group session, as appropriate
        notes = serializer.save()
        cc_email = self.request.data.get("cc_email")
        mgr = TutoringSessionNotesManager(notes)
        for student_tutoring_session in notes.student_tutoring_sessions.filter(
            missed=False, set_cancelled=False
        ).exclude(group_tutoring_session__cancelled=True):
            mgr.send_notification(student_tutoring_session, cc_email=cc_email)
        return notes
