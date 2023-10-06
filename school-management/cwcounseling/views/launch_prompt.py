""" This module contains views for launching the Prompt platform
"""

from django.views import View
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.http import HttpResponseForbidden, HttpResponseRedirect, HttpResponseBadRequest
from django.contrib.auth.models import User
from cwusers.models import Student
from cwusers.utilities.prompt_api_manager import PromptAPIManager, PromptAPIManagerException

PROMPT_PLATFORM_URL = f"{settings.PROMPT_URL_BASE}/admissions/jwt/"  # JWT goes on the end here


class LaunchPromptPlatformView(View):
    """ View to launch the Prompt platform for a counselor, parent, or student
        Obtains JWT from Prompt for user first (which syncs school list for students)

        If user is a parent, then ?student parameter must exist indicating PK of student to launch  Prompt for
    """

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseForbidden("")

        user: User = request.user
        if hasattr(user, "counselor"):
            cwuser = user.counselor
        elif hasattr(user, "student"):
            cwuser = user.student
            if not cwuser.counseling_student_types_list:
                return HttpResponseForbidden("Must be counseling student")
        elif hasattr(user, "parent"):
            return HttpResponseForbidden("")
        else:
            return HttpResponseForbidden("")

        mgr = PromptAPIManager()
        try:
            jwt = mgr.obtain_jwt(cwuser)
            url = f"{PROMPT_PLATFORM_URL}?t={jwt}"
            return HttpResponseRedirect(url)
        except PromptAPIManagerException as exx:
            if settings.DEBUG or settings.TESTING:
                print(exx)
            return HttpResponseBadRequest("Unable to load platform")
