"""
    This module contains views for interacting with TutoringPackage and TutoringPackagePurchase
    objects.
    Find views here for purchasing tutoring packages.
"""
from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from django.http import HttpResponseBadRequest
from rest_framework import status
from rest_framework.viewsets import ModelViewSet
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError, MethodNotAllowed

from cwtutoring.models import TutoringPackage, TutoringPackagePurchase
from cwtutoring.utilities.tutoring_package_manager import (
    StudentTutoringPackagePurchaseManager,
    TutoringPackageManagerException,
)
from cwtutoring.serializers.tutoring_packages import (
    TutoringPackageSerializer,
    TutoringPackagePurchaseSerializer,
)
from snusers.mixins import AccessStudentPermission
from snusers.models import Student
from cwcommon.mixins import CSVMixin


class TutoringPackagePurchaseViewset(ModelViewSet, AccessStudentPermission):
    """ View for managing TutoringPackagePurchase objects.
        Create, update, delete, and list views are only available to admin.
        DELETE not supported (see reverse)
        Retrieval view available to anyone who has access to student
        Purchase view is available to students and parents.

        PERMISSIONS: Only admins can list purchases. When working with individual objects,
            must have access to student package purchase is for.

        LIST: Allows filtering by sutdent
            ?student {Student PK}
            If not included, then must be admin

        REVERSE: Special (detail) action to reverse a purchse. Cannot un-reverse a purchase
            Only admins allowed
    """

    serializer_class = TutoringPackagePurchaseSerializer
    queryset = TutoringPackagePurchase.objects.all()
    permission_classes = (IsAuthenticated,)

    def check_permissions(self, request):
        super(TutoringPackagePurchaseViewset, self).check_permissions(request)
        # If getting individual purchase, need access to student
        if request.method.lower() == "get" and self.kwargs.get("pk"):
            # This case gets handled by object_permissions;
            pass
        elif request.query_params.get("student"):
            student = get_object_or_404(Student, pk=request.query_params.get("student"))
            if not self.has_access_to_student(student):
                self.permission_denied(request)
        elif request.data.get("student"):
            student = get_object_or_404(Student, pk=request.data.get("student"))
            if not self.has_access_to_student(student):
                self.permission_denied(request)
        elif not hasattr(request.user, "administrator"):
            self.permission_denied(request)

    def filter_queryset(self, queryset):
        if self.request.query_params.get("student"):
            student = get_object_or_404(Student, pk=self.request.query_params.get("student"))
            return queryset.filter(student=student)
        return queryset

    def check_object_permissions(self, request, obj):
        super(TutoringPackagePurchaseViewset, self).check_object_permissions(request, obj)
        if not self.has_access_to_student(obj.student):
            self.permission_denied(request)

    def get_serializer_context(self):
        """ Serializer is AdminModelSerializer, so we need to pass admin in context, where applicable """
        context = super(TutoringPackagePurchaseViewset, self).get_serializer_context()
        if hasattr(self.request.user, "administrator"):
            context["admin"] = self.request.user.administrator
        return context

    @action(methods=["POST"], detail=True)
    def reverse(self, request, *args, **kwargs):
        obj = self.get_object()
        if not hasattr(request.user, "administrator"):
            self.permission_denied(request)

        if obj.purchase_reversed:
            return HttpResponseBadRequest("Purchase already reversed")
        obj.purchase_reversed = timezone.now()
        obj.purchase_reversed_by = request.user
        obj.save()
        return Response(self.get_serializer_class()(obj, context=self.get_serializer_context()).data)

    def create(self, request, *args, **kwargs):
        """ Create a purchase with the following data
            Purchase will be performed unless execute_purchase is False AND USER IS ADMIN
            Arguments:
                student {Student PK}
                tutoring_package {TutoringPackage PK}
                execute_charge {Boolean} Whether or not purchase should be executed against our Magento API
                price_paid {Decimal; Optional}
                hours {Int} If purchasing a paygo package, can specify how many hours are being purchased
                admin_note {String} Optional note to be added to package purchase
            Returns: LIST OF TutoringPackagePurchases (is just one for singular purchase, but
                may be multiple for paygo purchase with multiple hours)
        """
        student: Student = get_object_or_404(Student, pk=request.data.get("student"))
        package: TutoringPackage = get_object_or_404(TutoringPackage, pk=request.data.get("tutoring_package"))
        mgr = StudentTutoringPackagePurchaseManager(student)
        execute_charge = request.data.get("execute_charge")

        if execute_charge and not student.last_paygo_purchase_id:
            return Response({"detail": "No payment information on file"}, status=status.HTTP_400_BAD_REQUEST)
        elif not execute_charge and not hasattr(request.user, "administrator"):
            self.permission_denied(request)
        try:
            paid = None
            if request.data.get("price_paid"):
                paid = Decimal(request.data.get("price_paid"))
            purchases = mgr.purchase_package(
                package,
                paid=paid,
                purchaser=request.user,
                execute_charge=execute_charge,
                hours=request.data.get("hours"),
                admin_note=request.data.get("admin_note", ""),
            )
        except TutoringPackageManagerException as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            self.serializer_class(purchases, many=True, context=self.get_serializer_context()).data, status=201,
        )

    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed("PUT/PATCH")

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE. Use Reverse action instead.")


class TutoringPackageViewset(CSVMixin, ModelViewSet, AccessStudentPermission):
    """ View for working with TutoringPackage objects.
        List allows filtering based on the following query parameters.
        Admin can leave off location/student to get all packages. IF NOT ADMIN, THEN EITHER
        LOCATION OR STUDENT MUST BE PROVIDED!
            ?location {Location PK}
            ?student {Student PK} - returns packages purchased by student
            ?include_inactive {bool} - MUST BE ADMIN

        Other supported options (ADMIN ONLY):
            Update (see TutoringPackageSerializer for fields)
            Create (see TutoringPackageSerializer for fields)
    """

    serializer_class = TutoringPackageSerializer
    queryset = TutoringPackage.objects.all()
    permission_classes = (IsAuthenticated,)

    def filter_queryset(self, queryset):
        """ See docstring for filter options """
        params = self.request.query_params
        if (
            self.request.method.lower() == "get"
            and not hasattr(self.request.user, "administrator")
            and not any([params.get("location"), params.get("student"), params.get("all")])
        ):
            raise ValidationError(detail="Location, student, or all param required")
        if (params.get("include_inactive")) and not hasattr(self.request.user, "administrator"):
            self.permission_denied(self.request)

        if params.get("location"):
            queryset = queryset.filter(Q(locations=params["location"]) | Q(all_locations=True))
        elif params.get("student"):
            student = get_object_or_404(Student, pk=params["student"])
            if not self.has_access_to_student(student):
                self.permission_denied(self.request)
            queryset = queryset.filter(tutoring_package_purchases__student=params["student"])
        elif not hasattr(self.request.user, "administrator"):
            self.permission_denied(self.request, message="Location or student required")

        if not params.get("include_inactive"):
            queryset = queryset.filter(active=True)

        return queryset.distinct()

    def get_serializer_context(self):
        context = super(TutoringPackageViewset, self).get_serializer_context()
        if hasattr(self.request.user, "administrator"):
            context["admin"] = self.request.user.administrator
        return context

    def check_permissions(self, request):
        """ Only admin can update or delete or retrieve a specific object
        """
        super(TutoringPackageViewset, self).check_permissions(request)
        # If not an administrator, then must be attempting to list
        if not hasattr(request.user, "administrator"):
            if not (request.method.lower() == "get" and not self.kwargs.get("pk")):
                self.permission_denied(request)

    def perform_destroy(self, instance):
        """ Destroy not supported. Update to inactive instead. """
        raise MethodNotAllowed("DELETE", detail="Destroy not supported. Update to inactive instead.")


class PurchaseableTutoringPackageView(ListAPIView, AccessStudentPermission):
    """ View that returns the purchase-able tutoring packages for a specific student
        We separate from TutoringPackageViewset because the filtering logic is fundamentally
        different

        Expects: ?student Query Param with student PK
        Returns: List of TutoringPackage objects that student can purchase, including paygo iff student
            is paygo
    """

    serializer_class = TutoringPackageSerializer
    queryset = TutoringPackage.objects.exclude(magento_purchase_link=None)
    permission_classes = (IsAuthenticated,)

    def filter_queryset(self, queryset):
        """ Perform filter and perms check """
        student: Student = get_object_or_404(Student, pk=self.request.query_params.get("student"))
        if not self.has_access_to_student(student):
            self.permission_denied(self.request)
        return (
            queryset.filter(allow_self_enroll=True)
            .filter(
                Q(Q(available__gte=timezone.now()) | Q(available=None)),
                Q(Q(expires__lte=timezone.now()) | Q(expires=None)),
                # Doesn't have to be at student's location to be restricted tutor link
                Q(Q(all_locations=True) | Q(locations=student.location) | Q(restricted_tutor__students=student)),
            )
            .filter(Q(Q(restricted_tutor=None) | Q(restricted_tutor__students=student)))
            .distinct()
        )
