""" Webhook that receives events from Zoom
"""
import logging
from django.http import HttpResponseBadRequest, HttpResponse

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from snusers.models import Tutor, Counselor
from snusers.utilities.zoom_manager import ZoomManager

# All of these zoom events have the same payload.
EVENTS = ["user.activated", "user.created", "user.invitation_accepted", "user.updated"]


class ZoomWebhookView(APIView):
    permission_classes = (AllowAny,)

    def _handle_user_created(self, request_data):
        """ Handle user created
            https://marketplace.zoom.us/docs/api-reference/webhook-reference/user-events/user-created
            Arugments:
                request_data {Payload of zoom webhook}
            Returns:
                Updated cwuser object (Tutor/Counselor) if cwuser with same email as user was found. Otherwise, None
        """
        # We need to to try to find tutor/counselor via email or ID in payload['object']
        cwuser = None
        for klass in (Tutor, Counselor):
            cwuser = klass.objects.filter(
                user__email=request_data["object"].get("email")
            ).first()
            if cwuser:
                break
            cwuser = klass.objects.filter(
                zoom_user_id=request_data["object"]["id"]
            ).first()
            if cwuser:
                break
        if cwuser:
            mgr = ZoomManager()
            cwuser = mgr.get_zoom_user(cwuser)
        return cwuser

    def post(self, request, *args, **kwargs):
        """ We recieve webhook from Zoom. Figure out how to route it.
        """
        logger = logging.getLogger("watchtower")
        logger.info(f"Zoom Webhook: \n\n {str(request.data)}")

        event = request.data.get("event")
        if event in EVENTS:
            updated_user = self._handle_user_created(request.data.get("payload"))
            return (
                HttpResponse(str(updated_user.slug)) if updated_user else HttpResponse()
            )
        return HttpResponseBadRequest("Invalid Event Type")
