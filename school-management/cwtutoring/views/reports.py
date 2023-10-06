from django.utils.dateparse import parse_date
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAdminUser
from rest_framework.exceptions import ValidationError
from cwcommon.mixins import CSVMixin
from cwtutoring.serializers.reports import ReportTutoringPackagePurchaseSerializer, ReportTutorSerializer
from cwtutoring.models import TutoringPackagePurchase
from cwusers.models import Tutor


class ReportTutoringPackagePurchaseView(CSVMixin, ListAPIView):
    permission_classes = (IsAdminUser,)
    serializer_class = ReportTutoringPackagePurchaseSerializer
    queryset = TutoringPackagePurchase.objects.all().select_related("tutoring_package", "student__user")

    def filter_queryset(self, queryset):
        """ This view supports the following query parameters:
            start
            end
        """
        start = end = None
        if parse_date(self.request.query_params.get("start", "")):
            start = parse_date(self.request.query_params.get("start"))
            queryset = queryset.filter(created__gte=start)
        if parse_date(self.request.query_params.get("end", "")):
            end = parse_date(self.request.query_params.get("end"))
            queryset = queryset.filter(created__gte=end)
        return queryset


class ReportTutorView(CSVMixin, ListAPIView):
    permission_classes = (IsAdminUser,)
    serializer_class = ReportTutorSerializer
    queryset = Tutor.objects.all()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        # We request start and end in query_params
        ctx["start"] = parse_date(self.request.query_params.get("start"))
        ctx["end"] = parse_date(self.request.query_params.get("end"))
        if not (ctx["start"] and ctx["end"]):
            raise ValidationError("Invalid start/end")
        return ctx
