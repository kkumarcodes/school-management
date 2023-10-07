from django.contrib.auth.models import User
from django.db.models import Q

from rest_framework import serializers

from snuniversities.managers.student_university_decision_manager import StudentUniversityDecisionManager

from .models import Deadline, StudentUniversityDecision, University, UniversityList


class DeadlineSerializer(serializers.ModelSerializer):
    """A Deadline for a University"""

    category_name = serializers.CharField(source="category.name", read_only=True)
    category_abbreviation = serializers.CharField(source="category.abbreviation", read_only=True)
    type_of_name = serializers.CharField(source="type_of.name", read_only=True)
    type_of_abbreviation = serializers.CharField(source="type_of.abbreviation", read_only=True)
    enddate = serializers.DateTimeField(format="%Y-%m-%d", required=False)
    startdate = serializers.DateTimeField(format="%Y-%m-%d", required=False)

    class Meta:
        model = Deadline
        fields = (
            "id",
            "slug",
            "updated",
            "university",
            "category",
            "type_of",
            "startdate",
            "enddate",
            "pk",
            "category_name",
            "category_abbreviation",
            "type_of_name",
            "type_of_abbreviation",
        )


class StudentUniversityDecisionSerializer(serializers.ModelSerializer):
    """A Student's decision about a University"""

    deadline_date = serializers.SerializerMethodField()
    university_name = serializers.SerializerMethodField(read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        context_request = self.context.get("request")
        user = context_request.user if context_request else self.context.get("user")
        if not (hasattr(user, "administrator") or hasattr(user, "counselor")):
            [self.fields.pop(field_name) for field_name in self.Meta.counselor_fields]

    class Meta:
        model = StudentUniversityDecision
        counselor_fields = (
            "note_counselor_private",
            "application_status_note",
            "short_answer_note",
            "transcript_note",
            "recommendation_two_note",
            "test_scores_note",
            "recommendation_one_note",
            "acceptance_status",
        )
        fields = (
            "slug",
            "created",
            "updated",
            "student",
            "university",
            "deadline",
            "is_applying",
            "note",
            "target_reach_safety",
            "goal_date",
            "deadline_date",
            "pk",
            "university_name",
            # These fields are used for counselor tracker and student app plan
            "submitted",
            "major",
            "application",
            "application_status",
            "transcript_status",
            "test_scores_status",
            "recommendation_one_status",
            "recommendation_two_status",
            "recommendation_three_status",
            "recommendation_four_status",
            "standardized_testing",
            "custom_deadline",
            "custom_deadline_description",
            "scholarship",
            "twin",
            "legacy",
            "honors_college",
            "additional_requirement_deadline",
            "additional_requirement_deadline_note",
            "short_answer_completion",
            "send_test_scores",
        ) + counselor_fields

    def get_university_name(self, obj):
        return obj.university.name

    def get_deadline_date(self, obj):
        if obj.custom_deadline:
            return obj.custom_deadline
        if obj.deadline:
            return obj.deadline.enddate
        return None

    def create(self, validated_data):
        obj, created = StudentUniversityDecisionManager.create(**validated_data)
        return obj


class UniversitySerializer(serializers.ModelSerializer):
    """A University to which a Student may apply"""

    class Meta:
        model = University
        fields = (
            "id",
            "slug",
            "created",
            "updated",
            "name",
            "long_name",
            "abbreviations",
            "logo",
            "url",
            "city",
            "state",
            "rank",
            "scid",
            "iped",
            "pk",
            "unigo_url",
            "college_board_url",
            "niche_url",
            "tpr_url",
            "scorecard_data",
            "facebook_url",
            "youtube_url",
            "instagram_url",
            "twitter_url",
            "linkedin_url",
            "common_app_personal_statement_required",
            "transcript_requirements",
            "courses_and_grades",
            "common_app_portfolio",
            "testing_requirements",
            "common_app_test_policy",
            "counselor_recommendation_required",
            "mid_year_report",
            "international_tests",
            "required_teacher_recommendations",
            "optional_teacher_recommendations",
            "optional_other_recommendations",
            "interview_requirements",
            "need_status",
            "demonstrated_interest",
            "international_sat_act_subject_test_required",
            "resume_required",
            "accepted_applications",
        )
        # To optimize the queryset performance
        # https://hakibenita.com/django-rest-framework-slow
        read_only_fields = fields


class UniversityListSerializer(serializers.ModelSerializer):
    """A curated collection of `University` objects"""

    owned_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(Q(student__isnull=False) | Q(counselor__isnull=False))
    )

    class Meta:
        model = UniversityList
        fields = (
            "pk",
            "slug",
            "name",
            "description",
            "slug",
            "created",
            "created_by",
            "updated",
            "owned_by",
            "universities",
            "assigned_to",
        )
