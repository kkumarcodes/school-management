from rest_framework import serializers


class ReadOnlySerializer(serializers.ModelSerializer):
    """ Like a regular serializer except all fields are read-only
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in list(self.fields.keys()):
            self.fields[field].read_only = True


class AdminModelSerializer(serializers.ModelSerializer):
    """ Base class for other ModelSerializers that have some fields
        they only expose to admin. To use:
        1) include admin_fields in Meta
        2) Pass {'admin'} in context iff admin fields should be included in serialization

        Tip: Use in conjunction with AdminContextMixin
    """

    def __init__(self, *args, **kwargs):
        super(AdminModelSerializer, self).__init__(*args, **kwargs)
        admin = self.context.get("admin", False)
        if not admin and self.context.get("request") and hasattr(self.context["request"].user, "administrator"):
            admin = True

        if not admin:
            for field_name in self.Meta.admin_fields:
                self.fields.pop(field_name)

    class Meta:
        admin_fields = ()
        fields = ()


class AdminCounselorModelSerializer(serializers.ModelSerializer):
    """ Base class for other ModelSerializers that have some fields
        they only expose to admins or counselors. To use:
        1) include admin_counselor_fields in Meta
        2) Pass {'admin' or 'counselor'} in context iff admin_counselor fields should be included in serialization

        Tip: Use in conjunction with AdminContextMixin
    """

    def __init__(self, *args, **kwargs):
        super(AdminCounselorModelSerializer, self).__init__(*args, **kwargs)
        admin = self.context.get("admin", False)
        if not admin and self.context.get("request") and hasattr(self.context["request"].user, "administrator"):
            admin = True
        counselor = self.context.get("counselor", False)
        if not counselor and self.context.get("request") and hasattr(self.context["request"].user, "counselor"):
            counselor = True

        self.admin_counselor = admin or counselor
        if not self.admin_counselor:
            for field_name in self.Meta.admin_counselor_fields:
                self.fields.pop(field_name)

    class Meta:
        admin_counselor_fields = ()
        fields = ()


class AdminCounselorModelSerializer(serializers.ModelSerializer):
    """ Base class for other ModelSerializers that have some fields
        they only expose to admins or counselors. To use:
        1) include admin_counselor_fields in Meta
        2) Pass {'admin' or 'counselor'} in context iff admin_counselor fields should be included in serialization

        Tip: Use in conjunction with AdminContextMixin
    """

    def __init__(self, *args, **kwargs):
        super(AdminCounselorModelSerializer, self).__init__(*args, **kwargs)
        admin = self.context.get("admin", False)
        if not admin and self.context.get("request") and hasattr(self.context["request"].user, "administrator"):
            admin = True
        counselor = self.context.get("counselor", False)
        if not counselor and self.context.get("request") and hasattr(self.context["request"].user, "counselor"):
            counselor = True

        self.admin_counselor = admin or counselor
        if not self.admin_counselor:
            for field_name in self.Meta.admin_counselor_fields:
                self.fields.pop(field_name)

    class Meta:
        admin_counselor_fields = ()
        fields = ()


class DiferentiatedUserSerializer(serializers.ModelSerializer):
    """ Base class for ther ModelSerializers that expose different fields to admins, counselors, tutors, students,
        and/or parents.
        WORK IN PROGRESS!
        To use, take the following actions in inheriting serializer class:
        1) add fields to admin_fields, counselor_fields, tutor_fields, student_fields, and parent_fields
            for those that should ONLY be exposed to the specific user (types). To expose a field to multiple
            user types, include it in multiple *_fields
        2) Use the serializer in a DRF View/Viewset (as request is automatically passed in serializer context)
            OR pass a Django auth.user as 'user' in serializer context.
    """

    def __init__(self, *args, **kwargs):
        super(AdminModelSerializer, self).__init__(*args, **kwargs)
        if not self.context.get("admin", False):
            for field_name in self.Meta.admin_fields:
                self.fields.pop(field_name)

    class Meta:
        admin_fields = ()
        counselor_fields = ()
        tutor_fields = ()
        student_fields = ()
        parent_fields = ()
        fields = ()
