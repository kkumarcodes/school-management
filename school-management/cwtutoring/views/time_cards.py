"""
    This module contains views for creating, updating, approving, and exporting time cards (TutorTimeCard)
"""
import csv
from decimal import Decimal
from datetime import timedelta
from itertools import groupby
from django.db.models import query
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django.views import View
from django.http import HttpResponse, HttpResponseForbidden
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError

from cwtutoring.models import TutorTimeCardLineItem, TutorTimeCard
from cwtutoring.serializers.time_cards import (
    TutorTimeCardSerializer,
    TutorTimeCardLineItemSerializer,
    TutorTimeCardAccountingSerializer,
)
from cwtutoring.utilities.time_card_manager import TutorTimeCardManager
from snusers.models import Tutor
from cwcommon.mixins import CSVMixin


class TutorTimeCardViewset(CSVMixin, ModelViewSet):
    """ Your run of the mill CRUD operations can be found here. Can LIST with the following query params:
        ?tutor {Tutor PK}
        ?start {Date} NOT DATETIME Only includes time cards that start on/after this datetime
        ?end {Date} NOT DATETIME Only includes time cards that start on/before this datetime
    """

    permission_classes = (IsAuthenticated,)
    queryset = TutorTimeCard.objects.all().order_by("tutor__user__last_name")
    serializer_class = TutorTimeCardSerializer
    serializer_acct_class = TutorTimeCardAccountingSerializer

    def get_serializer_class(self):
        if self.request.query_params.get("acct_report"):
            return self.serializer_acct_class

        return self.serializer_class

    def check_object_permissions(self, request, obj):
        super(TutorTimeCardViewset, self).check_object_permissions(request, obj)
        if not (hasattr(request.user, "administrator") or obj.tutor.user == request.user):
            self.permission_denied(request)

    def check_permissions(self, request):
        super(TutorTimeCardViewset, self).check_permissions(request)
        if request.query_params.get("tutor") and not hasattr(request.user, "administrator"):
            tutor = get_object_or_404(Tutor, pk=request.query_params["tutor"])
            if tutor.user != request.user:
                self.permission_denied(request)

    def get_serializer_context(self):
        """ Serializer is AdminModelSerializer, so we need to pass admin in context, where applicable """
        context = super().get_serializer_context()
        if hasattr(self.request.user, "administrator"):
            context["admin"] = self.request.user.administrator
        return context

    def filter_queryset(self, queryset):
        """ Filter on tutor, start, and end params """
        if self.request.query_params.get("acct_report"):
            queryset = queryset.filter(admin_approval_time__isnull=False)
        if self.kwargs.get("pk"):
            return queryset
        query_params = self.request.query_params
        if query_params.get("tutor"):
            tutor = get_object_or_404(Tutor, pk=query_params["tutor"])
            queryset = queryset.filter(tutor=tutor)
        for start_end in ("start", "end"):
            if query_params.get(start_end):
                key = "end__gte" if start_end == "start" else "end__lte"
                try:
                    queryset = queryset.filter(**{key: parse_date(query_params[start_end])})
                except ValueError:
                    raise ValidationError(detail=f"Invalid {start_end} query param")
        return queryset.order_by("tutor__user__last_name")

    def create(self, request, *args, **kwargs):
        """ Arguments:
                start {date}
                end {date}
                tutors: {List of TutorPKs}
        """
        # Validate the data all at once
        data = [
            {"start": request.data.get("start"), "end": request.data.get("end"), "tutor": x,}
            for x in request.data.get("tutors")
        ]
        serializer = self.get_serializer(data=data, many=True)
        serializer.is_valid(raise_exception=True)
        # Create time cards
        time_cards, skipped_tutors = TutorTimeCardManager.create_many_time_cards(
            Tutor.objects.filter(pk__in=request.data.get("tutors")),
            parse_datetime(request.data.get("start")),
            parse_datetime(request.data.get("end")),
        )
        return Response(self.get_serializer(time_cards, many=True).data, status=201)

    @action(
        methods=["POST"], detail=True, url_path="admin-approve", url_name="admin_approve",
    )
    def admin_approve(self, request, *args, **kwargs):
        if not hasattr(request.user, "administrator"):
            self.permission_denied(request)
        time_card = self.get_object()
        time_card.admin_approver = request.user.administrator
        time_card.admin_approval_time = timezone.now()
        time_card.save()
        return Response(self.get_serializer(time_card).data)

    @action(
        methods=["POST"], detail=True, url_path="tutor-approve", url_name="tutor_approve",
    )
    def tutor_approve(self, request, *args, **kwargs):
        time_card = self.get_object()
        time_card.tutor_approval_time = timezone.now()
        time_card.save()
        return Response(self.get_serializer(time_card).data)

    def perform_update(self, serializer):
        """ Re-Calculate total when we update time card """
        time_card: TutorTimeCard = serializer.save()
        mgr = TutorTimeCardManager(time_card.tutor)
        mgr.calculate_total(time_card)


class TutorTimeCardLineItemViewset(ModelViewSet):
    """ CRUD views for a time card line item. LISTing is not supported. """

    permission_classes = (IsAuthenticated,)
    serializer_class = TutorTimeCardLineItemSerializer
    queryset = TutorTimeCardLineItem.objects.all()

    def check_object_permissions(self, request, obj):
        super(TutorTimeCardLineItemViewset, self).check_object_permissions(request, obj)
        if not (hasattr(request.user, "administrator") or obj.time_card.tutor.user == request.user):
            self.permission_denied(request)

    def check_permissions(self, request):
        """ Confirm that when creating a line item, user has access to the time card line item is for
        """
        super(TutorTimeCardLineItemViewset, self).check_permissions(request)
        if hasattr(request.user, "administrator"):
            return True
        if request.method.lower() == "post":
            time_card = get_object_or_404(TutorTimeCard, pk=request.data.get("time_card"))
            if time_card.tutor.user != request.user:
                self.permission_denied(request)

    def perform_update(self, serializer):
        """ Re-Calculate total when we update time card """
        line_item: TutorTimeCardLineItem = serializer.save()
        mgr = TutorTimeCardManager(line_item.time_card.tutor)
        mgr.calculate_total(line_item.time_card)

    def perform_create(self, serializer):
        super().perform_create(serializer)
        time_card = serializer.validated_data["time_card"]
        time_card.refresh_from_db()
        mgr = TutorTimeCardManager(time_card.tutor)
        mgr.calculate_total(time_card)

    def perform_destroy(self, instance: TutorTimeCardLineItem):
        time_card = instance.time_card
        super().perform_destroy(instance)
        time_card.refresh_from_db()
        mgr = TutorTimeCardManager(time_card.tutor)
        mgr.calculate_total(time_card)


class TutorTimeCardLineItemAccountingView(View):
    """ View that returns a CSV that matches CW specification from this story:
        https://app.clubhouse.io/promptfeedback/story/2328/add-categories-for-each-different-hour-type-in-accounting-export
    """

    def get(self, request, *args, **kwargs):
        """ We require start and end to filter TutorTimeCards """
        if not (request.user.is_authenticated and hasattr(request.user, "administrator")):
            return HttpResponseForbidden("")
        time_cards = TutorTimeCard.objects.filter(admin_approval_time__isnull=False)
        for start_end in ("start", "end"):
            if request.GET.get(start_end):
                key = "end__gte" if start_end == "start" else "end__lte"
                date = parse_date(request.GET[start_end])
                if start_end == "end":
                    date += timedelta(hours=24)
                try:
                    time_cards = time_cards.filter(**{key: date})
                except ValueError:
                    raise ValidationError(detail=f"Invalid {start_end} query param")
            else:
                raise ValidationError(detail="Start and end dates (query params) required")

        line_items = TutorTimeCardLineItem.objects.filter(time_card__in=time_cards)

        def get_group_key(li: TutorTimeCardLineItem):
            rate = li.hourly_rate or li.time_card.tutor.hourly_rate
            return f"{li.time_card.tutor.pk}__{rate}"

        grouped_line_items = groupby(sorted(line_items, key=get_group_key), key=get_group_key)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="TimeCardLineItemAccounting.csv"'
        writer = csv.writer(response)
        writer.writerow(["First", "Last", "Total", "Hours", "Rate", "Rate Description"])
        for k, g in grouped_line_items:
            items = list(g)
            hours = sum([x.hours for x in items])
            tutor = items[0].time_card.tutor
            rate = items[0].hourly_rate if items[0].hourly_rate is not None else tutor.hourly_rate
            writer.writerow(
                [
                    tutor.user.first_name,
                    tutor.user.last_name,
                    round(Decimal(hours) * Decimal(rate), 2),
                    hours,
                    rate,
                    items[0].category or "Tutoring",
                ]
            )
        return response

