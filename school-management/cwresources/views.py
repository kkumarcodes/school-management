from django.http import (
    HttpResponseRedirect,
    HttpResponseForbidden,
    HttpResponseBadRequest,
)
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from snusers.models import Student
from snusers.mixins import AccessStudentPermission
from cwresources.serializers import ResourceSerializer, ResourceGroupSerializer
from cwresources.utilities.resource_permission_manager import get_resources_for_user
from cwresources.models import Resource, ResourceGroup
from cwcommon.mixins import CSVMixin


def get_resource(request, resource_slug):
    """ View that returns resource. File resources are downloaded. Link
        resources result in HttpResponseRedirect.
        User must have access to resource, or resource must be public.
    """
    if not request.user.is_authenticated:
        return HttpResponseRedirect(
            f"{reverse('cw_login')}?next={reverse('get_resource', kwargs={'resource_slug': resource_slug})}"
        )
    resource = get_object_or_404(Resource, slug=resource_slug)

    resources_available_to_user = get_resources_for_user(request.user)
    if not resources_available_to_user.filter(pk=resource.pk).exists():
        return HttpResponseForbidden("")

    # Alright, after all that authentication fun, we finally get to return our resource
    resource.view_count += 1
    resource.save()
    if resource.resource_file:
        return HttpResponseRedirect(resource.resource_file.url)
    if resource.link:
        return HttpResponseRedirect(resource.link)
    return HttpResponseBadRequest("Resource has no file or link")


class ResourceGroupViewset(CSVMixin, ModelViewSet):
    """ Here ye find yer basic CRUD tasks for working with ResourceGroups
        Pretty straightforward.
        Counselors, Tutors, and Admins can retrieve all resource groups
        Only admins can create resource groups (for now)
    """

    serializer_class = ResourceGroupSerializer
    permission_classes = (IsAuthenticated,)
    queryset = ResourceGroup.objects.all()

    def filter_queryset(self, queryset):
        """ Can filter resource groups for a particular student
        """
        user = self.request.user
        # TODO: Counselors and tutors get their own resource groups
        if hasattr(user, "administrator") or hasattr(user, "tutor") or hasattr(user, "counselor"):
            return queryset
        if hasattr(user, "student"):
            return queryset.filter(visible_students=user.student)
        if hasattr(user, "parent"):
            return queryset.filter(visible_students__parent=user.parent)
        raise ValidationError("Invalid user type")

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method.lower() != "get" and not hasattr(request.user, "administrator"):
            self.permission_denied(request)


class ResourceViewset(CSVMixin, ModelViewSet, AccessStudentPermission):
    """
        Create, update, and archive (instead of deleting) resources
        LIST:
            Returns resources visible to the current user, unless one of the following
            query params is specific:
            student: PK of student we're getting resources for. Returns all resources visible
                to this student, as long as current user has access to student.
                Note that this DOES include all stock resources but does NOT include all public resources
            all: If included AND CURRENT USER IS AN ADMINISTRATOR then all resources are returned

            We use resource_permission_manager.get_resources_for_user to determine the resources
            a user has access to.

        CREATE:
            Tutors and counselors can create non-stock resources (and then make those resources visible
                to their students)
            Admins can create and update stock resources
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = ResourceSerializer
    queryset = Resource.objects.all()

    def filter_queryset(self, queryset):
        """ See LIST details in viewset docstring """
        if self.request.query_params.get("student"):
            student = get_object_or_404(Student, pk=self.request.query_params["student"])
            return get_resources_for_user(student.user)
        elif hasattr(self.request.user, "administrator") and self.kwargs.get("pk"):
            return Resource.objects.all()
        elif self.request.query_params.get("all"):
            return Resource.objects.all()

        return get_resources_for_user(self.request.user)

    def perform_create(self, serializer):
        """ Override create to set created_by """

        instance = serializer.save()
        instance.created_by = self.request.user
        instance.save()
        return instance

    def check_object_permissions(self, request, obj):
        """ Ensure user has access to resource they're trying to manipulate.
            A bit redundant as they should 404 if trying to manipulate a resource they
            don't have access to. But this will ensure strict permissions should we change
            filter_queryset
        """
        super(ResourceViewset, self).check_object_permissions(request, obj)
        if hasattr(self.request.user, "administrator"):
            return
        if not get_resources_for_user(request.user).filter(pk=obj.pk).exists():
            self.permission_denied(request)

    def check_permissions(self, request):
        super(ResourceViewset, self).check_permissions(request)
        is_admin = hasattr(self.request.user, "administrator")
        if request.method.lower() == "get":
            if self.request.query_params.get("student"):
                student = get_object_or_404(Student, pk=self.request.query_params["student"])
                if not self.has_access_to_student(student):
                    self.permission_denied(request, message="No access to student")
            if self.request.query_params.get("all") and not is_admin:
                self.permission_denied(request)
        elif hasattr(request.user, "student"):
            self.permission_denied(request)
        if request.data.get("is_stock") and not is_admin:
            self.permission_denied(request, message="Only admins can create stock resources")
