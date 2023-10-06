import re

from django.core.exceptions import ValidationError


class ModelManagerBase:
    """ Base Model Manager class inherited by all Model Managers """

    def __init__(self, obj):
        # Simple object validation
        if not isinstance(obj, self.Meta.model):
            raise ValidationError(
                f"Supplied object is an instance of '{type(obj).__name__}'. "
                f"This manager is for instances of '{self.Meta.model.__name__}'"
            )

        # The object is provided on the Manager via both its explicit model
        # name, and also abstractly, as "obj". The abstraction is not intended
        # to be used in model-specific logic. Rather, it allows us to write
        # inheritable instance methods here in the base class
        snake_cased_model_name = re.sub("(?!^)([A-Z]+)", r"_\1", self.Meta.model.__name__).lower()
        setattr(self, snake_cased_model_name, obj)
        setattr(self, "obj", obj)

    @classmethod
    def get_help_text(cls, field_name: str):
        """ Get the help text for any field on the managed model """
        return cls.Meta.model._meta.get_field(field_name).help_text

    @classmethod
    def get_field_names(cls):
        """ Get a list of the field names on the managed model """
        field_names = [field.name for field in cls.Meta.model._meta.fields]
        field_names.sort()
        return field_names

    @classmethod
    def get_field_lookups(cls, field_name: str):
        """ Get the field lookups for any field on the managed model """
        field_lookups = [k for k, v in cls.Meta.model._meta.get_field(field_name).get_lookups().items()]
        field_lookups.sort()
        return field_lookups

    @classmethod
    def _get_or_create(cls, **kwargs):
        """ Get or create an object for this model

          DO NOT DIRECTLY CALL THIS METHOD TO CREATE OBJECTS. This method should
          only be called by the `.create()` method of a ModelManager.
        """
        return cls.Meta.model.objects.get_or_create(**kwargs)

    def update(self, **kwargs):
        """ Update fields on this model instance

            This method exists to be overridden, allowing the ModelManager to
            handle any side effects triggered by updating a field -- such as
            the sending of Notifications, or the creation of secondary objects.
        """
        for attr, value in kwargs.items():
            setattr(self.obj, attr, value)
        self.obj.save()
