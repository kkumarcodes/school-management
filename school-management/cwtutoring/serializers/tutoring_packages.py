from rest_framework import serializers

from cwcommon.serializers.base import AdminModelSerializer
from cwtutoring.models import (
    TutoringPackage,
    TutoringPackagePurchase,
    Location,
    GroupTutoringSession,
)
from cwresources.models import ResourceGroup


class TutoringPackageSerializer(AdminModelSerializer):
    """ Pretty straightforward. All related fields represented by primary keys
    """

    locations = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), many=True, allow_null=True, required=False
    )
    group_tutoring_sessions = serializers.PrimaryKeyRelatedField(
        queryset=GroupTutoringSession.objects.all(), many=True, allow_null=True, required=False,
    )
    resource_groups = serializers.PrimaryKeyRelatedField(
        queryset=ResourceGroup.objects.all(), many=True, allow_null=True, required=False
    )

    number_of_students = serializers.SerializerMethodField()

    class Meta:
        model = TutoringPackage
        admin_fields = ("number_of_students",)
        fields = (
            "pk",
            "slug",
            "title",
            "description",
            "locations",
            "all_locations",
            "price",
            "available",
            "expires",
            "individual_test_prep_hours",
            "group_test_prep_hours",
            "individual_curriculum_hours",
            "group_tutoring_sessions",
            "resource_groups",
            "active",
            "sku",
            "magento_purchase_link",
            "restricted_tutor",
            "allow_self_enroll",
            "product_id",
            "is_paygo_package",
        ) + admin_fields

    def get_number_of_students(self, obj):
        return obj.tutoring_package_purchases.exclude(purchase_reversed__isnull=False).distinct("student").count()


class TutoringPackagePurchaseSerializer(AdminModelSerializer):
    """ Serializer for TutoringPackagePurchase """

    purchase_reversed_by = serializers.CharField(read_only=True, source="purchase_reversed_by.get_full_name")
    # Read only - update via reverse action on viewset
    purchase_reversed = serializers.DateTimeField(read_only=True)
    purchased_by = serializers.CharField(read_only=True, source="purchased_by.get_full_name")
    tutoring_package = serializers.PrimaryKeyRelatedField(queryset=TutoringPackage.objects.all())
    tutoring_package_name = serializers.CharField(read_only=True, source="tutoring_package.title")
    individual_test_prep_hours = serializers.DecimalField(
        source="tutoring_package.individual_test_prep_hours", max_digits=6, decimal_places=2,
    )
    group_test_prep_hours = serializers.DecimalField(
        source="tutoring_package.group_test_prep_hours", max_digits=6, decimal_places=2
    )
    individual_curriculum_hours = serializers.DecimalField(
        source="tutoring_package.individual_curriculum_hours", max_digits=6, decimal_places=2,
    )

    class Meta:
        model = TutoringPackagePurchase
        admin_fields = (
            "purchased_by",
            "purchase_reversed",
            "purchase_reversed_by",
            "payment_completed",
            "payment_confirmation",
            "admin_note",
        )
        fields = (
            "pk",
            "slug",
            "student",
            "created",
            "tutoring_package",
            "payment_required",
            "individual_test_prep_hours",
            "group_test_prep_hours",
            "individual_curriculum_hours",
            "payment_link",
            "price_paid",
            "tutoring_package_name",
        ) + admin_fields
