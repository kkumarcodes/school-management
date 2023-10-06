""" Serializers for Roadmap-related models
"""

from rest_framework import serializers
from cwcounseling.models import CounselorMeetingTemplate, Roadmap
from cwcounseling.serializers.counselor_meeting import CounselorMeetingTemplateSerializer


class RoadmapSerializer(serializers.ModelSerializer):
    counselor_meeting_templates = CounselorMeetingTemplateSerializer(many=True, read_only=True)
    update_counselor_meeting_templates = serializers.PrimaryKeyRelatedField(
        write_only=True,
        source="counselor_meeting_templates",
        many=True,
        required=False,
        queryset=CounselorMeetingTemplate.objects.all(),
    )

    class Meta:
        model = Roadmap
        fields = (
            "pk",
            "slug",
            "title",
            "repeatable",
            "description",
            "category",
            "counselor_meeting_templates",
            "update_counselor_meeting_templates",
            "active",
        )
