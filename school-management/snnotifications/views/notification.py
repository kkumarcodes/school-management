from django.http import HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from rest_framework.viewsets import GenericViewSet
from rest_framework.mixins import UpdateModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from rest_framework import status

from snmessages.models import ConversationParticipant
from snmessages.utilities.conversation_manager import ConversationManager
from snnotifications.models import NotificationRecipient, Notification
from snnotifications.serializers import NotificationRecipientSerializer, NotificationSerializer
from snnotifications.generator import create_notification
from snnotifications.constants.constants import SYSTEM_NOTIFICATIONS
from sncommon.utilities.twilio import TwilioManager
from snusers.mixins import AccessStudentPermission
from snusers.models import Student


class CreateNotificationView(AccessStudentPermission, APIView):
    permission_classes = (IsAuthenticated,)

    def _send_diagnostic_invite(self, recipient: NotificationRecipient):
        create_notification(recipient.user, notification_type="diagnostic_invite")
        if not hasattr(recipient.user, "student"):
            raise ValidationError("Recipient does not have a student profile")
        if not self.has_access_to_student(recipient.user.student):
            self.permission_denied(self.request)
        return Response()

    def post(self, request, notification_type, *args, **kwargs):
        """ There are a few notifications that can be created from the frontend and aren't tied to system
            events. Rather than create a separate view for each one, this view  support all of them.
            Private methods exist on this view for each type of notification. Private methods are responsible
                for perms checks
            Kwargs:
                notification_type: Key identifying notification type
            Data:
                recipient: PK of NotificationRecipient who will get notification.
                ... Each notificaiton type can have it's own additional data
        """
        recipient = get_object_or_404(NotificationRecipient, pk=request.data.get("recipient"))
        if notification_type == "diagnostic_invite":
            return self._send_diagnostic_invite(recipient)
        return Response(
            {"detail": f"Invalid notification type: {notification_type}"}, status=status.HTTP_400_BAD_REQUEST
        )


class ActivityLogView(AccessStudentPermission, APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, user_pk=None, *args, **kwargs):
        """ Get notifications that comprise activity log for a user
            If no user_pk is provided (via URL), then system notifications (notifications with no recipient)
            are returned. MUST BE ADMIN TO GET SYSTEM NOTIFICATIONS

            Returns most recent 1000 notifications
        """
        if not user_pk:
            if not hasattr(request.user, "administrator"):
                self.permission_denied(request)
            # System notifications!
            notifications = Notification.objects.filter(
                recipient=None, notification_type__in=SYSTEM_NOTIFICATIONS
            ).exclude(activity_log_title="")
        else:
            user = get_object_or_404(User, pk=user_pk, notification_recipient__isnull=False)
            student = Student.objects.filter(user=user).first()
            # Must be admin or user or have access to student
            if not (
                hasattr(request.user, "administrator")
                or user == request.user
                or (student and self.has_access_to_student(student))
            ):
                self.permission_denied(request)
            notifications = Notification.objects.filter(recipient=user.notification_recipient).exclude(
                activity_log_title=""
            )
        return Response(NotificationSerializer(notifications.order_by("-created")[:500], many=True).data)


class NotificationRecipientViewset(GenericViewSet, UpdateModelMixin, RetrieveModelMixin, AccessStudentPermission):
    """ This viewset allows for:
        - Updating NotificationRecipient
        - Sending text verification code to NotificationRecipient
        - Attempting to verify phone number using verification code
        Arguments/return for each endpoint are described below
    """

    queryset = NotificationRecipient.objects.all()
    serializer_class = NotificationRecipientSerializer
    permission_classes = (IsAuthenticated,)

    def check_object_permissions(self, request, obj):
        super(NotificationRecipientViewset, self).check_object_permissions(request, obj)
        if obj.user != request.user and not hasattr(request.user, "administrator"):
            # Check if notification rec is for student user has access to
            access_student = hasattr(obj.user, "student") and self.has_access_to_student(obj.user.student)
            access_parent = hasattr(obj.user, "parent") and any(
                [self.has_access_to_student(x) for x in obj.user.parent.students.all()]
            )
            if not (access_student or access_parent):
                self.permission_denied(request)

    def perform_update(self, serializer):
        """ Override update to send verification if new phone number
            Arguments:
                All non-read-only fields on NotificationRecipientSerializer.
                Query params:
                - dont_send_verification: If included and true, then a new verification code
                    WONT be sent if phone number is updated. By default a verification code
                    is sent.
                    NOTE THAT THIS IS A QUERY PARAM AND IS NOT MEANT TO BE INCLUDED IN REQUEST BODY
        """
        og_obj = self.get_object()
        obj = serializer.save()
        if obj.phone_number != og_obj.phone_number:
            obj.phone_number_verification_code = ""
            obj.save()
            # Deacitvate ConversationParticipants for old phone number
            if og_obj.phone_number:
                participants = ConversationParticipant.objects.filter(
                    active=True, phone_number__contains=og_obj.phone_number
                )
                if participants.exists():
                    conversation_manager = ConversationManager()
                    for participant in participants:
                        conversation_manager.delete_conversation_participant(participant)
            if obj.phone_number and not self.request.query_params.get("dont_send_verification", False):
                twilio_manager = TwilioManager()
                twilio_manager.send_verification(obj)
        return obj

    @action(
        detail=True, methods=["POST"], url_path="send-verification", url_name="send_verification",
    )
    def send_verification(self, request, pk=None):
        """ Use this view to send a NEW verification code to a recipient
            No arguments.
            Returns 200 upon success. No content in response
        """
        # Runs get_object_permissions
        twilio_manager = TwilioManager()
        twilio_manager.send_verification(self.get_object())
        return HttpResponse()

    @action(
        detail=True, methods=["POST"], url_path="attempt-verify", url_name="attempt_verify",
    )
    def attempt_verify(self, request, pk=None):
        """ Use this view to submit a verification code and see if it matches NotificationRecipient's
            phone_number_verification_code.
            Arguments:
                code {string} Verification code (if you want to do frontend validation, this
                    must be a 5 digit number)
            Success Returns:
                NotificationRecipient object with updated phone_numberis_confirmed field.
                Status code 200

            Failure returns:
                400, with content {"detail": "Invalid verification code"}
        """
        notification_recipient = self.get_object()
        if not (
            notification_recipient.phone_number_verification_code
            and notification_recipient.phone_number_verification_code == request.data.get("code")
        ):
            return Response({"detail": "Invalid verification code"}, status=400)
        else:
            # Success!
            notification_recipient.phone_number_confirmed = timezone.now()
            notification_recipient.save()
            return Response(NotificationRecipientSerializer(notification_recipient).data)
