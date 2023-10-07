""" This module has mixins for other classes - namely views - used throughout this Django project
"""
from django.utils import timezone
from django.http import HttpResponseForbidden
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as CSVRenderers


class AdminContextMixin(GenericAPIView):
    """ Mixin for DRF views that adds 'admin' key to serializer context if current
        user is an admin.
        Use this in conjunction with AdminModelSerializer
    """

    def get_serializer_context(self):
        context = super(AdminContextMixin, self).get_serializer_context()
        if hasattr(self.request.user, "administrator"):
            context["admin"] = self.request.user.administrator
        return context


class CSVMixin:
    """ This mixin adds CSVRenderer as a rendering class to a view, and overrides finalize_response
        to name the resulting csv after the type of data being downloaded.
        This mixin must appear to the LEFT of DRF views in inheritance order
    """

    # Syntax here is funky because renderer_classes needs to be a tuple, but DEFAULT_RENDERER_CLASSES is a list
    # so we tuple-ify it and then tack on our csv renderer
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (CSVRenderers.CSVRenderer,)

    def finalize_response(self, request, response, *args, **kwargs):
        """
        Return the response with the proper content disposition and the customized
        filename instead of the browser default (or lack thereof).
        """
        response = super(CSVMixin, self).finalize_response(request, response, *args, **kwargs)

        if isinstance(response, Response) and response.accepted_renderer.format == "csv":
            # Last-ditch effort not to allow CSV access
            if not hasattr(request.user, "administrator"):
                return HttpResponseForbidden()
            # pylint: disable=protected-access
            timestamp = timezone.now().strftime("%m-%d-%Y %H%M")
            filename = f'"{self.get_serializer_class().Meta.model._meta.verbose_name}s - {timestamp}.csv"'
            response["content-disposition"] = f"attachment; filename={filename}"
        return response
