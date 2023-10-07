""" Serializers that created data that conforms to the structure of data Prompt expects
"""
from rest_framework import serializers
from cwcommon.serializers.base import ReadOnlySerializer
from snusers.models import Student, Counselor
from cwuniversities.models import StudentUniversityDecision

# All organizations have the same name
ORGANIZATION_NAME = "Collegewise"
TEST_SCHOOLS = ["123961", "110662", "164988", "170976", "110705", "236948", "110635", "126614", "193900", "110680"]


class PromptStudentSerializer(ReadOnlySerializer):
    name = serializers.CharField(source="invitation_name")
    email = serializers.CharField(source="invitation_email")
    counselor_id = serializers.CharField(source="counselor.slug")
    schools = serializers.SerializerMethodField()
    partner_id = serializers.CharField(source="slug")
    application_year = serializers.IntegerField(source="graduation_year")

    class Meta:
        model = Student
        fields = ("name", "email", "counselor_id", "schools", "partner_id", "application_year")

    def get_schools(self, obj: Student):
        # List of IPEDs for all universities student has decision objects for
        return list(
            obj.student_university_decisions.filter(is_applying=StudentUniversityDecision.YES).values_list(
                "university__iped", flat=True
            )
        )


class PromptCounselorSerializer(ReadOnlySerializer):
    name = serializers.CharField(source="invitation_name")
    email = serializers.CharField(source="invitation_email")
    organization_id = serializers.CharField(source="slug")
    partner_id = serializers.CharField(source="slug")
    is_admin = serializers.SerializerMethodField()

    class Meta:
        model = Counselor
        fields = ("name", "email", "organization_id", "partner_id", "is_admin")

    def get_is_admin(self, obj: Counselor):
        # From Prompt's perspective, all counselors are admins of their own org
        return True


class PromptOrganizationSerializer(ReadOnlySerializer):
    """ Prompt request that all counselors belong to an organization
        In UMS, we consider each counselor their own organization
    """

    # Fake organization name. Always "Collegewise"
    name = serializers.SerializerMethodField()
    # Org ID same as Counselor ID
    partner_id = serializers.CharField(source="slug")
    students = serializers.SerializerMethodField()
    counselors = serializers.SerializerMethodField()

    class Meta:
        model = Counselor
        fields = ("name", "partner_id", "students", "counselors")

    def get_name(self, obj: Counselor):
        return ORGANIZATION_NAME

    def get_students(self, obj: Counselor):
        return PromptStudentSerializer(
            obj.students.filter(is_prompt_active=True, counselor__prompt=True), many=True
        ).data

    def get_counselors(self, obj: Counselor):
        return PromptCounselorSerializer([obj], many=True).data
