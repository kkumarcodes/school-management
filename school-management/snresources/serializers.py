from django.shortcuts import get_object_or_404
from django.core.files.base import ContentFile

from rest_framework import serializers
from rest_framework.serializers import ValidationError

from sncommon.models import FileUpload
from .models import Resource, ResourceGroup


class ResourceGroupSerializer(serializers.ModelSerializer):
    """ A category or grouping of resources (i.e. SAT Resources) """

    class Meta:
        model = ResourceGroup
        fields = ("pk", "slug", "title", "description", "is_stock", "created_by")


class ResourceSerializer(serializers.ModelSerializer):
    """ Everything a user needs to view a resource
        Note that .url should be used to expose a link to resource (via either link or resource_file)
    """

    resource_group = serializers.PrimaryKeyRelatedField(queryset=ResourceGroup.objects.all(), required=False)
    resource_group_title = serializers.CharField(source="resource_group.title", read_only=True)
    link = serializers.CharField(required=False)
    cap = serializers.SerializerMethodField()
    cas = serializers.SerializerMethodField()

    # Use this field to update the resource's resource_file field. This field is only
    # writeable (not readable), and expects the slug for a FileUpload object
    file_upload = serializers.CharField(write_only=True, allow_blank=True, required=False)

    resource_file = serializers.CharField(read_only=True)

    class Meta:
        model = Resource
        fields = (
            "pk",
            "slug",
            "title",
            "description",
            "resource_group",
            "resource_group_title",
            "file_upload",
            "resource_file",
            "link",
            "url",
            "is_stock",
            "view_count",
            "archived",
            "cap",
            "cas",
            "vimeo_id",
        )

    def get_cap(self, obj: Resource):
        return obj.resource_group.cap if obj.resource_group else False

    def get_cas(self, obj: Resource):
        return obj.resource_group.cas if obj.resource_group else False

    def _save_file_upload(self, instance, file_upload):
        """ This utility method copies the file from a file_upload object
            to instance.resource_file field
            Arguments:
                instance {Resource}
                file_upload {FileUpload} Must have file_resource set
            Returns:
                instance {Resource} with updated resource_file field
        """
        if not file_upload.file_resource:
            raise TypeError("FileUpload missing file_resource")
        instance.resource_file.save(
            name=file_upload.file_resource.name, content=ContentFile(file_upload.file_resource.read()),
        )
        return instance

    def create(self, validated_data):
        file_upload_slug = validated_data.pop("file_upload", None)
        instance = super(ResourceSerializer, self).create(validated_data)
        if file_upload_slug:
            instance = self._save_file_upload(instance, get_object_or_404(FileUpload, slug=file_upload_slug))
        return instance

    def update(self, instance, validated_data):
        file_upload_slug = validated_data.pop("file_upload", None)
        instance = super(ResourceSerializer, self).update(instance, validated_data)
        if file_upload_slug:
            instance = self._save_file_upload(instance, get_object_or_404(FileUpload, slug=file_upload_slug))
        elif file_upload_slug == "":
            instance.resource_file = ""
            instance.save()
        return instance

    def validate(self, attrs):
        if attrs.get("file_upload") and not FileUpload.objects.filter(slug=attrs["file_upload"]).exists():
            raise ValidationError("Invalid file upload object(s)")

        return attrs
