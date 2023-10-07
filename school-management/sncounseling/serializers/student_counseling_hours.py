""" Serializers for Student Counseling Hours
"""

from rest_framework import serializers
from snusers.models import Student
from django.db.models import Sum


class StudentCounselingHoursSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="name")
    student_email = serializers.CharField(source="email")
    counselor_name = serializers.SerializerMethodField()
    counselor_email = serializers.SerializerMethodField()
    is_counselor_part_time = serializers.SerializerMethodField()
    total_hours = serializers.SerializerMethodField()
    spent_hours = serializers.SerializerMethodField()

    class Meta:

        model = Student
        fields = (
            "student_name",
            "student_email",
            "counselor_name",
            "counselor_email",
            "is_counselor_part_time",
            "is_paygo",
            "total_hours",
            "spent_hours",
        )

    def get_counselor_name(self, obj):
        return obj.counselor.name if obj.counselor else None

    def get_counselor_email(self, obj):
        return obj.counselor.email if obj.counselor else None

    def get_is_counselor_part_time(self, obj):
        return obj.counselor.part_time if obj.counselor else None

    def get_total_hours(self, obj):
        return (
            obj.counseling_hours_grants.filter(include_in_hours_bank=True).aggregate(
                total_hours=Sum("number_of_hours")
            )["total_hours"]
            or 0
        )

    def get_spent_hours(self, obj):
        return (
            obj.counseling_time_entries.filter(include_in_hours_bank=True).aggregate(spent_hours=Sum("hours"))[
                "spent_hours"
            ]
            or 0
        )
