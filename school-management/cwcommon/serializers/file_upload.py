from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from cwcommon.models import FileUpload
from cwusers.models import Student


class FileUploadSerializer(serializers.ModelSerializer):
    counseling_student = serializers.PrimaryKeyRelatedField(write_only=True, queryset=Student.objects.all())

    class Meta:
        model = FileUpload
        fields = ("slug", "name", "tags", "url", "title", "link", "counseling_student", "created")


class UpdateFileUploadsSerializer(serializers.Serializer):
    """Inheritable serializer that adds functionality for uploading a set of file uploads
    related to model (Meta.model)
    Adds:
        file_uploads_field (default: file_uploads) Field on Meta.model that represents many
            relationship to FileUpload model.
        update_file_uploads: Writeable field; list of FileUpload slugs
        file_uploads: Serializer method field; list of FileUpload objects
        ^^ YOU MUST ADD BOTH OF THESE SERIALIZER FIELDS TO META.FIELDS!
    """

    file_uploads_field = "file_uploads"
    related_name_field = ""

    update_file_uploads = serializers.ListField(child=serializers.CharField(), write_only=True, required=False)
    file_uploads = serializers.SerializerMethodField()

    def get_file_uploads(self, obj):
        return FileUploadSerializer(getattr(obj, self.file_uploads_field).filter(active=True), many=True).data

    # Override update and create to update FileUpload objects accordingly
    def update(self, instance, validated_data):
        update_file_uploads = validated_data.pop("update_file_uploads", [])
        FileUpload.objects.filter(slug__in=update_file_uploads).update(**{self.related_name_field: instance})
        getattr(instance, self.file_uploads_field).exclude(slug__in=update_file_uploads).update(
            **{self.related_name_field: None}
        )
        return super(UpdateFileUploadsSerializer, self).update(instance, validated_data)

    def create(self, validated_data):
        update_file_uploads = validated_data.pop("update_file_uploads", [])
        instance = super(UpdateFileUploadsSerializer, self).create(validated_data)
        FileUpload.objects.filter(slug__in=update_file_uploads).update(**{self.related_name_field: instance})
        return instance

    def validate(self, attrs):
        """Make sure file uploads don't belong to another object"""
        bad_file_uploads = FileUpload.objects.filter(
            **{
                f"{self.related_name_field}__isnull": False,
                "slug__in": attrs.get("update_file_uploads", []),
            }
        )
        if self.instance:
            bad_file_uploads = bad_file_uploads.exclude(**{self.related_name_field: self.instance})
        if bad_file_uploads.exists():
            raise ValidationError("Invalid file upload object(s)")

        return super(UpdateFileUploadsSerializer, self).validate(attrs)
