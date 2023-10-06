"""
    This module contains views that return Django html templates (which in turn probably
    load frontend apps).
"""
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.contrib.auth import login
from django.shortcuts import render, reverse
from django.http import HttpResponseBadRequest, HttpResponseRedirect, HttpResponseForbidden, HttpResponseNotFound
from django.views import View
from django.conf import settings

from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

from cwusers.models import Student, Counselor, Parent, Tutor, Administrator, get_cw_user
from cwusers.constants.user_types import USER_TYPES
from cwusers.authentication import JWTSpecifyTokenAuthentication

# Dictionary of user model managers based on user type
USER_MODELS = {
    "student": Student,
    "counselor": Counselor,
    "administrator": Administrator,
    "tutor": Tutor,
    "parent": Parent,
}


class PlatformView(View):
    """This view returns the "platform" - the primary application - for all users. All users use the same
        Django template (application.html) but load different frontend apps.
        Note that this view allows for JWT auth. If a valid JWT is provided, then we actually log the
        user in and create a session for them.
    """

    template_name = "cwusers/application.html"

    def get(self, request, platform_type, student_uuid=None):
        """Arguments
            platform_type: URL Parameter that MUST match a cwuser user_type
            student_uuid: Only used for parents; used to specify which student they are loading platform for
        """
        if request.GET.get("t"):
            # We have a JWT. Figure out if it's for a user that we can login as
            # Attempt to authenticate via JWT
            auth = JWTSpecifyTokenAuthentication()
            try:
                user, _ = auth.authenticate(request)
                if user:
                    # We make sure that token is valid for at least 1 more day
                    token = AccessToken(token=request.GET.get("t"))
                    try:
                        token.check_exp(current_time=timezone.now() + timedelta(days=1))
                    except TokenError:
                        token.set_exp(lifetime=timedelta(days=1))
                    login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
            except (AuthenticationFailed, InvalidToken, TokenError):
                # Authentication failed.... oh no!!!
                return HttpResponseForbidden()

        if not request.user.is_authenticated:
            redirect_url = reverse("cw_login")
            if request.META.get("QUERY_STRING"):
                redirect_url += f"?{request.META['QUERY_STRING']}"
            return HttpResponseRedirect(redirect_url)
        if platform_type not in USER_TYPES:
            return HttpResponseBadRequest("Invalid platform type")

        manager_class = USER_MODELS[platform_type]
        cwuser = manager_class.objects.filter(user=request.user).first()
        if not cwuser:
            actual_cwuser = get_cw_user(request.user)
            if actual_cwuser:
                return HttpResponseRedirect(f"{settings.SITE_URL}{reverse('logout')}")
            return HttpResponseBadRequest("You do not have access to this platform. You are not logged in.")

        context = {"cwuser": cwuser, "STATIC_URL": settings.STATIC_URL}

        # We need to set an active student for parent (or one may have been specified via student_uuid)
        # This is necessary because which frontend app gets loaded (counseling vs tutoring) depends on which student
        # parent is viewing
        if hasattr(request.user, "parent"):
            if student_uuid:
                context["student"] = get_object_or_404(Student, slug=student_uuid, parent=request.user.parent)
            elif request.user.parent.students.exists():
                context["student"] = request.user.parent.students.first()
            else:
                return HttpResponseNotFound("Parent account has no associated students")

        return render(request, self.template_name, context=context)
