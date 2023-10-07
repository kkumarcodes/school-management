""" This module contains serializers for reporting. They differ from other serializers in that they are:
    1) Read only
    2) Only used by admins, so it's safe not to specify every field
    3) No nested fields
"""
from datetime import datetime, date
from rest_framework import serializers
from django.db.models import Q, Sum
from cwcommon.serializers.base import ReadOnlySerializer

from cwtutoring.models import TutoringPackagePurchase, StudentTutoringSession, GroupTutoringSession, TutoringService
from snusers.models import Tutor, Student


class ReportTutorSerializer(ReadOnlySerializer):
    """ Serializes a tutor and their sessions over a time period
        Expects 'start' and 'end' in serializer
    """

    first_name = serializers.CharField(source="user.first_name")
    last_name = serializers.CharField(source="user.last_name")
    email = serializers.CharField(source="invitation_email")

    # For date period provided in context
    individual_student_count = serializers.SerializerMethodField()
    individual_curriculum_sessions = serializers.SerializerMethodField()
    individual_test_prep_sessions = serializers.SerializerMethodField()
    group_test_prep_sessions = serializers.SerializerMethodField()
    individual_curriculum_hours = serializers.SerializerMethodField()
    individual_test_prep_hours = serializers.SerializerMethodField()
    group_test_prep_hours = serializers.SerializerMethodField()

    # List of all services provided
    tutoring_services = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not (isinstance(self.context.get("start"), date) and isinstance(self.context.get("end"), date)):
            raise ValueError("Invalid start/end for ReportTutorSerializer")
        # We set thsi queryset now as a convenience for all of our serializer method fields later
        self.sts_queryset = StudentTutoringSession.objects.filter(
            set_cancelled=False, start__gte=self.context["start"], start__lte=self.context["end"], missed=False,
        )

    class Meta:
        model = Tutor
        fields = (
            "pk",
            "first_name",
            "last_name",
            "email",
            "individual_student_count",
            "individual_curriculum_sessions",
            "individual_test_prep_sessions",
            "group_test_prep_sessions",
            "individual_curriculum_hours",
            "individual_test_prep_hours",
            "group_test_prep_hours",
            "tutoring_services",
        )

    def get_individual_student_count(self, obj: Tutor):
        return (
            Student.objects.filter(tutoring_sessions__in=self.sts_queryset.filter(individual_session_tutor=obj))
            .distinct()
            .count()
        )

    def get_individual_curriculum_sessions(self, obj: Tutor):
        return self.sts_queryset.filter(
            individual_session_tutor=obj, session_type=StudentTutoringSession.SESSION_TYPE_CURRICULUM
        ).count()

    def get_individual_test_prep_sessions(self, obj: Tutor):
        return self.sts_queryset.filter(
            individual_session_tutor=obj, session_type=StudentTutoringSession.SESSION_TYPE_TEST_PREP
        ).count()

    def get_group_test_prep_sessions(self, obj: Tutor):
        return GroupTutoringSession.objects.filter(
            primary_tutor=obj, cancelled=False, start__gte=self.context["start"], start__lte=self.context["end"],
        ).count()

    def get_individual_curriculum_hours(self, obj: Tutor):
        return round(
            (
                self.sts_queryset.filter(
                    individual_session_tutor=obj, session_type=StudentTutoringSession.SESSION_TYPE_CURRICULUM
                ).aggregate(s=Sum("duration_minutes"))["s"]
                or 0
            )
            / 60.0,
            2,
        )

    def get_individual_test_prep_hours(self, obj: Tutor):
        return round(
            (
                self.sts_queryset.filter(
                    individual_session_tutor=obj, session_type=StudentTutoringSession.SESSION_TYPE_TEST_PREP
                ).aggregate(s=Sum("duration_minutes"))["s"]
                or 0
            )
            / 60.0,
            2,
        )

    def get_group_test_prep_hours(self, obj: Tutor):
        # We can't use set_pay_tutor_duration here, because it could be set to 0
        group_sessions = GroupTutoringSession.objects.filter(
            primary_tutor=obj, cancelled=False, start__gte=self.context["start"], start__lte=self.context["end"],
        )
        return round(sum([x.pay_tutor_duration / 60.0 for x in group_sessions]), 2)

    def get_tutoring_services(self, obj: Tutor):
        # List of tutoring sesssions for individual sessions tutor was involved in
        return ", ".join(
            TutoringService.objects.filter(
                student_tutoring_sessions__in=self.sts_queryset.filter(individual_session_tutor=obj)
            )
            .distinct()
            .values_list("name", flat=True)
        )


class ReportTutoringPackagePurchaseSerializer(ReadOnlySerializer):
    individual_curriculum_hours = serializers.DecimalField(
        max_digits=8, decimal_places=2, source="tutoring_package.individual_curriculum_hours"
    )
    individual_test_prep_hours = serializers.DecimalField(
        max_digits=8, decimal_places=2, source="tutoring_package.individual_test_prep_hours"
    )
    group_test_prep_hours = serializers.DecimalField(
        max_digits=8, decimal_places=2, source="tutoring_package.group_test_prep_hours"
    )
    magento_order_id = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    student_name = serializers.CharField(source="student.name")
    package_name = serializers.CharField(source="tutoring_package.title")
    location = serializers.CharField(source="student.location.name")
    package_type = serializers.SerializerMethodField()

    class Meta:
        model = TutoringPackagePurchase
        exclude = (
            "slug",
            "magento_payload",
            "sku",
            "magento_response",
        )

    def get_magento_order_id(self, obj):
        try:
            return obj.magento_payload.get("items", [])[0]["order_id"]
        except (KeyError, IndexError):
            return ""

    def get_created_by_name(self, obj: TutoringPackagePurchase):
        return obj.purchased_by.get_full_name() if obj.purchased_by else ""

    def get_package_type(self, obj: TutoringPackagePurchase):
        if obj.tutoring_package.group_test_prep_hours > 0:
            return "Class"
        elif obj.tutoring_package.individual_curriculum_hours > 0:
            return "Private Curriculum"
        elif obj.tutoring_package.individual_test_prep_hours > 0:
            return "Private Tutoring"
        return ""
