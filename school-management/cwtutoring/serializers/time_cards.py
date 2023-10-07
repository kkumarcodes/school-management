from decimal import Decimal

from django.db import models
from rest_framework import serializers

from cwcommon.serializers.base import AdminModelSerializer
from cwtutoring.models import GroupTutoringSession, StudentTutoringSession, TutorTimeCard, TutorTimeCardLineItem
from snusers.models import Tutor
from cwtutoring.constants import (
    TIME_CARD_CATEGORY_CHECK_IN,
    TIME_CARD_CATEGORY_SESSION_NOTES_ADMIN,
    TIME_CARD_CATEGORY_TRAINING_PD,
    TIME_CARD_CATEGORY_TUTORING,
    TIME_CARD_CATEGORY_DIAG_REPORT,
    TIME_CARD_CATEGORY_EVAL_CONSULTS,
)


class TutorTimeCardLineItemSerializer(serializers.ModelSerializer):
    group_tutoring_session = serializers.PrimaryKeyRelatedField(
        queryset=GroupTutoringSession.objects.all(), required=False
    )
    individual_tutoring_session = serializers.PrimaryKeyRelatedField(
        queryset=StudentTutoringSession.objects.filter(individual_session_tutor__isnull=False), required=False,
    )
    time_card = serializers.PrimaryKeyRelatedField(queryset=TutorTimeCard.objects.all())
    hourly_rate = serializers.DecimalField(decimal_places=2, max_digits=5, required=False, allow_null=True)

    class Meta:
        model = TutorTimeCardLineItem
        fields = (
            "pk",
            "slug",
            "title",
            "group_tutoring_session",
            "individual_tutoring_session",
            "time_card",
            "date",
            "hours",
            "created_by",
            "hourly_rate",
            "category",
        )


class TutorTimeCardSerializer(AdminModelSerializer):
    line_items = TutorTimeCardLineItemSerializer(many=True, read_only=True)

    # Approval stuff is updated in dedicated viewset actions, not via serializer
    admin_approval_time = serializers.DateTimeField(read_only=True)
    tutor_approval_time = serializers.DateTimeField(read_only=True)
    admin_approver = serializers.PrimaryKeyRelatedField(read_only=True)

    tutor = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.all())
    hourly_rate = serializers.DecimalField(decimal_places=2, max_digits=5, required=False)

    tutor_name = serializers.SerializerMethodField()
    admin_has_approved = serializers.SerializerMethodField()

    class Meta:
        model = TutorTimeCard
        admin_fields = ("admin_approval_time", "admin_approver", "admin_note")
        fields = (
            "pk",
            "slug",
            "line_items",
            "tutor",
            "start",
            "end",
            "tutor_approval_time",
            "tutor_note",
            "hourly_rate",
            "total",
            "total_hours",
            "tutor_name",
            "admin_has_approved",
        ) + admin_fields

    def get_tutor_name(self, obj):
        return obj.tutor.name

    def get_admin_has_approved(self, obj):
        return bool(obj.admin_approval_time)


class TutorTimeCardAccountingSerializer(AdminModelSerializer):
    tutor_name = serializers.CharField(source="tutor.name")
    tutor_email = serializers.CharField(source="tutor.invitation_email")

    hours_check_in = serializers.SerializerMethodField()
    hours_session_notes_admin = serializers.SerializerMethodField()
    hours_training_pd = serializers.SerializerMethodField()
    hours_tutoring = serializers.SerializerMethodField()
    hours_diag_report = serializers.SerializerMethodField()
    hours_eval_consults = serializers.SerializerMethodField()

    class Meta:
        model = TutorTimeCard
        fields = (
            "pk",
            "slug",
            "tutor_name",
            "tutor_email",
            "total_hours",
            "hours_check_in",
            "hours_session_notes_admin",
            "hours_training_pd",
            "hours_tutoring",
            "hours_diag_report",
            "hours_eval_consults",
            "total",
        )

    def get_tutor_name(self, obj):
        return obj.tutor.name

    def get_tutor_email(self, obj):
        return obj.tutor.invitation_email

    def get_hours_check_in(self, obj: TutorTimeCard):
        return Decimal(
            obj.line_items.filter(category=TIME_CARD_CATEGORY_CHECK_IN).aggregate(s=models.Sum("hours"))["s"] or 0
        )

    def get_hours_session_notes_admin(self, obj: TutorTimeCard):
        return Decimal(
            obj.line_items.filter(category=TIME_CARD_CATEGORY_SESSION_NOTES_ADMIN).aggregate(s=models.Sum("hours"))["s"]
            or 0
        )

    def get_hours_training_pd(self, obj: TutorTimeCard):
        return Decimal(
            obj.line_items.filter(category=TIME_CARD_CATEGORY_TRAINING_PD).aggregate(s=models.Sum("hours"))["s"] or 0
        )

    def get_hours_tutoring(self, obj: TutorTimeCard):
        return Decimal(
            obj.line_items.filter(models.Q(category=TIME_CARD_CATEGORY_TUTORING) | models.Q(category="")).aggregate(
                s=models.Sum("hours")
            )["s"]
            or 0
        )

    def get_hours_diag_report(self, obj: TutorTimeCard):
        return Decimal(
            obj.line_items.filter(category=TIME_CARD_CATEGORY_DIAG_REPORT).aggregate(s=models.Sum("hours"))["s"] or 0
        )

    def get_hours_eval_consults(self, obj: TutorTimeCard):
        return Decimal(
            obj.line_items.filter(category=TIME_CARD_CATEGORY_EVAL_CONSULTS).aggregate(s=models.Sum("hours"))["s"] or 0
        )

