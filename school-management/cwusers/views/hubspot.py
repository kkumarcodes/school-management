""" This module contains views (mostly API views) used by the CW Hubspot App
"""

from django.http import HttpResponseBadRequest, HttpResponse, HttpResponseNotFound
from django.contrib.auth.models import User

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from cwusers.models import Student, Parent
from cwusers.serializers.hubspot import HubspotExtensionSerializer
from cwusers.utilities.hubspot_manager import HubspotManager


class HubspotUserCardView(APIView):
    """ This view returns details that appear on contact cards in the Hubspot CRM, through a custom Hubspot
      Extension.
    """

    permissions_classes = (AllowAny,)

    def get(self, request, *args, **kwargs):
        """ Retrieve user data to display on contact card in Hubspot
        """
        # TODO: Security!
        query_params = request.query_params
        if not query_params.get("email"):
            return HttpResponseBadRequest("Email required to identify user")
        # We attempt to find first a student and then a parent via email
        student = Student.objects.filter(user__email=query_params.get("email")).first()
        if student:
            return Response(HubspotExtensionSerializer(student).data)

        parent = Parent.objects.filter(user__email=query_params.get("email")).first()
        if parent:
            return Response(HubspotExtensionSerializer(parent).data)

        return HttpResponseNotFound()


class HubspotOAuthRedirect(APIView):
    """ View called upon successful OAuth connection to Hubspot. We need to generate access/refresh
        tokens with code from redirect URL
    """

    permission_classes = (AllowAny,)

    def get(self, request, *args, **kwargs):
        """ Redirect from Oauth workflow.
            Query Params: code
            Returns: Success or failure message
        """
        code = request.query_params.get("code")
        if not code:
            return HttpResponseBadRequest("Invalid code")
        mgr = HubspotManager()
        # Allow HubspotManagerException to bubble up as 500
        mgr.obtain_jwt(access_code=code)
        return HttpResponse("JWT Obtained")
