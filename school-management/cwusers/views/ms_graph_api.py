"""
    This module contains views to facilitate authentication process with Microsoft
    Graph API to obtain read/write permission to CW Counselor and Tutor Outlook
    calendars
"""
import sentry_sdk
from django.http.response import HttpResponseBadRequest
from django.shortcuts import reverse
from django.http import HttpResponseRedirect
from django.conf import settings
from rest_framework.viewsets import ViewSet
from rest_framework.decorators import action
from cwusers.models import get_cw_user
from cwusers.utilities.auth_helper import get_sign_in_url, get_token_from_code


class MSOutlookAPIView(ViewSet):
    """ Handles Microsoft authentication for CWUsers (tutors and counselors)
        Returns an access and refresh token, which is then stored on the user
        for future use
    """

    @action(
        detail=False, methods=["GET"], url_path="signin", url_name="signin",
    )
    def signin(self, request):
        # Get the sign-in URL
        sign_in_url, state = get_sign_in_url()
        # Save the expected state so we can validate in the callback
        request.session["auth_state"] = state
        request.session["user_pk"] = self.request.user.pk
        if not settings.TESTING:
            sentry_sdk.capture_message(
                f"Outlook Signin set user PK {self.request.user.pk} {self.request.user.email} on URL {request.build_absolute_uri()}"
            )
        # Redirect to the Azure sign-in page
        return HttpResponseRedirect(sign_in_url)

    @action(
        detail=False, methods=["GET"], url_path="callback", url_name="callback",
    )
    def callback(self, request):
        # Get the state saved in session
        expected_state = request.session.pop("auth_state", "")
        # Make the token request
        token = get_token_from_code(request.get_full_path(), expected_state)
        # get the logged in user and save tokens on user object
        pk = request.session.get("user_pk")
        if (not pk) and request.user.is_authenticated:
            pk = request.user.pk
        if not pk:
            if not settings.TESTING:
                with sentry_sdk.configure_scope() as scope:
                    scope.set_context(
                        "outlook_callback",
                        {"Is Auth'd": request.user.is_authenticated, "URL": request.build_absolute_uri()},
                    )

                    sentry_sdk.capture_exception(ValueError("Missing user PK in session"))
            return HttpResponseBadRequest("Unexpected response from Microsoft API. Please try again.")
        user = get_cw_user(pk)
        user.microsoft_token = token["access_token"]
        user.microsoft_refresh = token["refresh_token"]
        user.save()
        return HttpResponseRedirect(reverse("cw_login"))
