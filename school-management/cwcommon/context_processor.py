from django.conf import settings
from django.utils import timezone
from cwusers.models import get_cw_user

# pylint: disable=unused-argument
def context_processor(request):
    """ Add settings.FRONTEND_URL to context always """
    cw_user = None
    if request.user.is_authenticated:
        cw_user = get_cw_user(request.user)

    # We attempt to activate a timezone if the user has one
    if cw_user and cw_user.timezone:
        timezone.activate(cw_user.timezone)

    return {
        # Settings
        "FRONTEND_URL": settings.FRONTEND_URL,
        "SITE_URL": settings.SITE_URL,
        "SITE_NAME": settings.SITE_NAME,
        "DEBUG": settings.DEBUG,
        "ENV": settings.ENV,
        "TIME_ZONE": cw_user.timezone if cw_user and cw_user.timezone else None,
        # Git hash - from version.txt
        "VERSION": settings.VERSION,
        # Other context
        "cw_user": cw_user,
    }
