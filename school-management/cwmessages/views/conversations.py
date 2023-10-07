from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import (
    HttpResponseNotAllowed,
    HttpResponseNotFound,
    HttpResponseForbidden,
    HttpResponse,
    HttpResponseBadRequest,
)
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action

from cwnotifications.models import NotificationRecipient
from snusers.mixins import AccessStudentPermission
from snusers.models import Counselor, Parent, Student, Tutor
from cwmessages.models import Conversation, ConversationParticipant
from cwmessages.utilities.conversation_manager import (
    ConversationManager,
    TwilioException,
)
from cwmessages.serializers import (
    ConversationSerializer,
    ConversationParticipantSerializer,
)
from cwmessages.utilities.vcard import get_vcard


class ConversationView(APIView, AccessStudentPermission):
    """ Attempt to retrieve a conversation
        To filter, we use the combination of the following details which can be included as query params:
            student {Student PK} either student or parent or counselor must be provided
            parent {Parent PK} either student or parent or counselor must be provided
            counselor {Counselor PK} either student or parent or counselor must be provided
            conversation_type {optional; CONVERSATION_TYPES} conversation of this type cannot already exist for user
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request, *args, **kwargs):
        """ DO perms checks and attempt to retrieve relevant Conversation all in one go
        """
        query_params = request.query_params
        filter_data = {"conversation_type": query_params["conversation_type"]}
        for key in ["student", "counselor", "parent"]:
            if query_params.get(key):
                filter_data[key] = query_params[key]
        conversation = Conversation.objects.filter(**filter_data).first()
        if not conversation:
            return HttpResponseNotFound()
        if not ConversationManager.user_can_view_conversation(request.user, conversation):
            self.permission_denied(request)

        return Response(ConversationSerializer(conversation).data)

    def post(self, request, *args, **kwargs):
        """ Create a conversation. Expects data defined in ConversationSpecification type on frontend
            Note that we do NOT use serializer to create, we use ConversationManager
        """
        if not (
            self.request.data.get("conversation_type")
            and any([self.request.data.get(x) for x in ("student", "parent", "counselor", "tutor")])
        ):
            raise ValidationError(detail="Invalid query params")

        manager = ConversationManager()
        create_data = {"conversation_type": request.data["conversation_type"]}
        if self.request.data.get("student"):
            create_data["student"] = get_object_or_404(Student, pk=self.request.data["student"])
        if self.request.data.get("counselor"):
            create_data["counselor"] = get_object_or_404(Counselor, pk=self.request.data["counselor"])
        if self.request.data.get("parent"):
            create_data["parent"] = get_object_or_404(Parent, pk=self.request.data["parent"])
        if self.request.data.get("tutor"):
            create_data["tutor"] = get_object_or_404(Tutor, pk=self.request.data["tutor"])

        if create_data.get("student"):
            if not self.has_access_to_student(create_data["student"]):
                self.permission_denied(request)
        elif create_data.get("parent"):
            if not (
                (self.request.user == create_data["parent"].user)
                or hasattr(request.user, "counselor")
                or hasattr(request.user, "administrator")
            ):
                self.permission_denied(request)
        elif create_data["conversation_type"] == Conversation.CONVERSATION_TYPE_COUNSELOR_TUTOR:
            if not (
                (create_data.get("tutor") and create_data["tutor"].user == request.user)
                or (create_data.get("counselor") and create_data["counselor"].user == request.user)
            ):
                self.permission_denied(request)
        else:
            return HttpResponseBadRequest("Student or parent required")

        conversation = manager.get_or_create_conversation(**create_data)
        return Response(ConversationSerializer(conversation).data, status=200)

    def patch(self, request, *args, **kwargs):
        raise NotImplementedError("")


class ChatConversationTokenView(APIView):
    """ This view is used to obtain a chat access token for a conversation
        Note that token will be obtained for currently logged in user, and identity
        will be set for currently logged in user UNLESS user is admin and they specify an identity.
        This is a POST because a ConversationParticipant may get created
        Data:
            conversation {Conversation PK}
            identity {string} Only allowed for admins
        Returns:
            {
                token: Chat Token
                participant_id: ConversationParticipant.participant_id
            }
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        conversation = get_object_or_404(Conversation, pk=request.data.get("conversation"))

        # Confirm permissions
        if not ConversationManager.user_can_view_conversation(request.user, conversation):
            self.permission_denied(request)

        # Get or create participant
        mgr = ConversationManager()
        query_identifier = request.data.get("identifier")
        identifier = (
            query_identifier
            if (query_identifier and hasattr(request.user, "administrator"))
            else request.user.get_full_name()
        )
        notification_recipient, _ = NotificationRecipient.objects.get_or_create(user=request.user)
        chat_participant = mgr.get_or_create_chat_participant(
            conversation, identifier, notification_recipient=notification_recipient
        )
        token = mgr.get_chat_access_token(chat_participant)
        chat_participant.last_read = timezone.now()
        chat_participant.save()

        return Response({"token": token, "participant_id": chat_participant.participant_id})


class ConversationParticipantViewset(ModelViewSet):
    """ View for managing listing/retrieving/deleting ConversationParticipant objects, or
        creating SMS CONVERSATION PARTIICPANTS
        Use ChatConversationTokenView to get/create chat conversation participants. This view
        will not help you if you need a ConversationParticipant for web chat.
    """

    queryset = ConversationParticipant.objects.all()
    serializer_class = ConversationParticipantSerializer
    permission_classes = (IsAuthenticated,)

    def filter_queryset(self, queryset):
        user = self.request.user
        if self.request.query_params.get("user"):
            user = get_object_or_404(User, pk=self.request.query_params["user"])
            if not (user == self.request.user or hasattr(self.request.user, "administrator")):
                self.permission_denied(self.request)
        return queryset.filter(notification_recipient__user=user)

    def check_object_permissions(self, request, obj):
        super(ConversationParticipantViewset, self).check_object_permissions(request, obj)
        if obj.notification_recipient.user != request.user:
            self.permission_denied(request)

    @action(detail=True, methods=["get"], url_path="vcard", url_name="vcard")
    def get_vcard(self, request, *args, **kwargs):
        """ Obtain a vcard file that user can add to their address book
        """
        obj = self.queryset.get(pk=kwargs.get("pk"))
        if not obj:
            return HttpResponseNotFound()
        if not ConversationManager.user_can_view_conversation(request.user, obj.conversation):
            self.permission_denied(request)
        vcard, filename = get_vcard(obj)
        response = HttpResponse(vcard, content_type="text/x-vCard")
        response["Content-Disposition"] = "attachment; filename=%s" % filename
        return response

    def create(self, request, *args, **kwargs):
        """ We do NOT use serializer for create.
            Assumes we're adding participant for current user.
            Will return matching participant if they already exist!
            Arguments (data):
                - conversation (Conversation must already exist. Make it first if not) 
                - user Optional PK of user we're creating ConversationParticipant for.
                    Must be logged in user or logged in user must be admin
        """
        conversation = get_object_or_404(Conversation, pk=request.data.get("conversation"))
        if not ConversationManager.user_can_view_conversation(request.user, conversation):
            return HttpResponseForbidden()

        # Only students and tutors can subscribe to text notifications
        user = request.user
        if request.data.get("user"):
            user = get_object_or_404(User, pk=request.data["user"])
        if not (user == request.user or hasattr(request.user, "administrator")):
            return HttpResponseForbidden()

        recipient, _ = NotificationRecipient.objects.get_or_create(user=user)
        if not (hasattr(recipient.user, "student") or hasattr(recipient.user, "counselor")):
            return HttpResponseForbidden()

        # Create our participant!
        manager = ConversationManager()
        participant = (
            conversation.participants.filter(notification_recipient=recipient).exclude(phone_number="").first()
        )
        if not participant:
            try:
                participant = manager.add_sms_participant_to_conversation(conversation, recipient)
            except TwilioException:
                return HttpResponseBadRequest("Participant cannot join conversation")
        elif not participant.active:
            participant.active = True
            participant.save()
        return Response(self.serializer_class(participant).data)

    @action(methods=["POST"], detail=True, url_path="update-last-read", url_name="update_last_read")
    def update_last_read(self, request, *args, **kwargs):
        """ Simple little action, just updates last_read since this viewset does not otherwise support
            updates
        """
        obj: ConversationParticipant = self.get_object()
        obj.last_read = timezone.now()
        obj.save()
        return Response(self.serializer_class(obj).data)

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def perform_destroy(self, instance):
        """ ConversationManager takes care of deletion """
        manager = ConversationManager()
        manager.delete_conversation_participant(instance)
