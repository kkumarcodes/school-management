from django.http import HttpResponse

from django.conf import settings



def health_check_version(request):
    """ View that returns a 200 with settings.VERSION. Used by devops infrastructure for health checks """
    return HttpResponse(settings.VERSION, content_type="text/plain")


def throw_exception(request):
    """ View that throws an exception intentionally.
        Why would we want to do this? Well, to ensure that our error tracking is working properly,
        of course :)
    """
    raise ValueError("Value error from throw_exception view")
