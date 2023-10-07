""" Serializers for Student Activity model
"""

from rest_framework import serializers
from sncounseling.models import StudentActivity


class StudentActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentActivity
        fields = (
            "category",
            "student",
            "years_active",
            "hours_per_week",
            "weeks_per_year",
            "awards",
            "name",
            "description",
            "pk",
            "slug",
            "intend_to_participate_college",
            "during_school_year",
            "during_school_break",
            "all_year",
            "position",
            "common_app_category",
            "post_graduate",
            "recognition",
            "order",
        )
