from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from cwresources.models import Resource
from cwresources.serializers import ResourceSerializer
from cwtutoring.models import (
    TutoringSessionNotes,
    StudentTutoringSession,
    GroupTutoringSession,
)
from cwusers.models import Tutor
from cwcommon.serializers.file_upload import UpdateFileUploadsSerializer


class TutoringSessionNotesSerializer(UpdateFileUploadsSerializer, serializers.ModelSerializer):
    """ Serializer for working with TutoringSessionNotes
        Note that there are separate fields to UPDATE resources and file_uploads than to READ the same
        Also note that "notes" field is HTML!
        Oh and "author" field is PK of a Tutor!

        Also to CREATE, set either group_tutoring_session or individual_tutoring_session
        When reading, student_tutoring_sessions field is added for convenience; when reading notes created for a
        group session, this field will contain all of the individual StudentTutoringSession PKs
        associated with the GroupTutoringSession
    """

    related_name_field = "tutoring_session_notes"
    resources = ResourceSerializer(many=True, required=False)

    # Use this field to set resources when creating/updating. The set of resources
    # on GroupTutoringSession will be OVERWRITTEN (replaced) by set of resources identified
    # by SLUGS supplied in this field.
    update_resources = serializers.ListField(child=serializers.CharField(), write_only=True, required=False)

    group_tutoring_session = serializers.PrimaryKeyRelatedField(
        queryset=GroupTutoringSession.objects.all(), required=False
    )

    individual_tutoring_session = serializers.PrimaryKeyRelatedField(
        queryset=StudentTutoringSession.objects.all(), write_only=True, required=False
    )

    student_tutoring_sessions = serializers.PrimaryKeyRelatedField(
        many=True, queryset=StudentTutoringSession.objects.all(), required=False
    )
    author = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.all())

    class Meta:
        model = TutoringSessionNotes
        fields = (
            "pk",
            "slug",
            "author",
            "notes",
            "resources",
            "update_resources",
            "file_uploads",
            "update_file_uploads",
            "student_tutoring_sessions",
            "group_tutoring_session",
            "individual_tutoring_session",
            "visible_to_student",
            "visible_to_parent",
        )

    def validate(self, attrs):
        if not self.instance and not (attrs.get("individual_tutoring_session") or attrs.get("group_tutoring_session")):
            raise ValidationError("Must set individual_tutoring_session or group_tutoring_session")
        elif self.instance:
            if (
                attrs.get("group_tutoring_session")
                and attrs["group_tutoring_session"].pk != self.instance.group_tutoring_session.pk
            ):
                raise ValidationError("Cannot change group tutoring session")
        return attrs

    def create(self, validated_data):

        individual_session = validated_data.pop("individual_tutoring_session", None)
        if individual_session:
            validated_data["student_tutoring_sessions"] = [individual_session]
        update_resources = validated_data.pop("update_resources", None)
        # If there was a group session, associate all individual sessions
        instance = super(TutoringSessionNotesSerializer, self).create(validated_data)
        if instance.group_tutoring_session:
            instance.student_tutoring_sessions.set(
                list(instance.group_tutoring_session.student_tutoring_sessions.all())
            )
        if update_resources is not None:
            instance.resources.set(list(Resource.objects.filter(slug__in=update_resources)))
        return instance

    def update(self, instance, validated_data):
        update_resources = validated_data.pop("update_resources", None)
        instance = super(TutoringSessionNotesSerializer, self).update(instance, validated_data)
        if update_resources is not None:
            instance.resources.set(list(Resource.objects.filter(slug__in=update_resources)))
        return instance
