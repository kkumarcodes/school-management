from django.shortcuts import get_object_or_404
from rest_framework.decorators import action

from rest_framework.viewsets import ModelViewSet
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from snnotifications.models import Bulletin, NotificationRecipient
from snnotifications.serializers import BulletinSerializer
from snnotifications.utilities.bulletin_manager import BulletinManager
from snusers.mixins import AccessStudentPermission


class BulletinViewset(AccessStudentPermission, ModelViewSet):
    """ Viewset with basic CRUD operations for a bulletin.
        List:
            Returns bulletins visible to current user or user specific by query params. Possible Query Params:
            ?student, ?parent, ?tutor, or ?counselor
    """

    serializer_class = BulletinSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        """ Filter queryset based on user-type query parameters listed in class docstring
            Also checks permissions to access user if specified
        """
        query_params = self.request.query_params
        notification_recipient = None
        if query_params.get("student"):
            notification_recipient = get_object_or_404(NotificationRecipient, user__student=query_params["student"])
            if not self.has_access_to_student(notification_recipient.user.student):
                self.permission_denied(self.request)
            return BulletinManager.get_bulletins_for_notification_recipient(
                notification_recipient.user.student.user.notification_recipient
            )
        if any([x in query_params for x in ("tutor", "counselor", "parent")]):
            # Only admins can get bulletins for other users who aren't students
            if not hasattr(self.request.user, "administrator"):
                self.permission_denied(self.request)
            if query_params.get("tutor"):
                notification_recipient = get_object_or_404(NotificationRecipient, user__tutor=query_params["tutor"])
            elif query_params.get("counselor"):
                notification_recipient = get_object_or_404(
                    NotificationRecipient, user__counselor=query_params["counselor"]
                )
            elif query_params.get("parent"):
                notification_recipient = get_object_or_404(NotificationRecipient, user__parent=query_params["parent"])
            return (
                BulletinManager.get_bulletins_for_notification_recipient(notification_recipient)
                if notification_recipient
                else Bulletin.objects.none()
            )
        return BulletinManager.get_bulletins_for_notification_recipient(self.request.user.notification_recipient)

    def check_permissions(self, request):
        super().check_permissions(request)
        # Filtering perms are checked in get_queryset
        # So here we check perms for create
        create_or_update = (
            request.method.lower() == "post" and not self.kwargs.get("pk")
        ) or request.method.lower() not in ("post", "get")

        if create_or_update and not (hasattr(request.user, "counselor") or hasattr(request.user, "administrator")):
            self.permission_denied(request)

    def check_object_permissions(self, request, obj):
        # Must be bulletin's creator, an admin, or have tbe bulletin be visible to request.user
        # If not creator/admin, then can only retrieve (GET)
        super().check_object_permissions(request, obj)
        if hasattr(request.user, "administrator") or obj.created_by == request.user:
            return True
        if not obj.visible_to_notification_recipients.filter(user=request.user).exists():
            self.permission_denied(request)
        if request.method.lower() == "post" and not self.kwargs.get("pk"):
            self.permission_denied(request)

    def create(self, request, *args, **kwargs):
        """ A couple of special things about this method
            1) We set notification recipients using BulletinManager.set_visible_to_notification_recipients IF
                (and only if) visible_to_notification_recipients is NOT in request.data
            2) If send_notification (prop that is set on created Bulletin) is True, then notifications
                will be sent to visible_to_notification_recipients
        """
        data = request.data
        data["created_by"] = request.user.pk
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        bulletin = serializer.save()

        # If the visible_to_notification_recipients field is included in data, then we don't need
        # to calculate which notification recipients this bulletin is visible to
        if "visible_to_notification_recipients" not in data:
            mgr = BulletinManager(bulletin)
            bulletin = mgr.set_visible_to_notification_recipients()
        if bulletin.send_notification:
            mgr = BulletinManager(bulletin)
            mgr.send_bulletin()
        serializer = self.get_serializer(instance=bulletin)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=["POST"])
    def read(self, request, *args, **kwargs):
        """ Mark a bulletin as being read by the current user
        """
        bulletin: Bulletin = self.get_object()
        bulletin.read_notification_recipients.add(request.user.notification_recipient)
        return Response(BulletinSerializer(bulletin).data)
