from django.core.exceptions import ValidationError


class ModelManagerBase:
    """ Base Model Manager class inherited by all Model Managers """

    def __init__(self, obj):
        """ Simple validation that can be inherited by child classes, if desired

			Child classes should `super().__init__(<object>)` to inherit
		"""
        if not isinstance(obj, self.Meta.model):
            raise ValidationError(
                f"Supplied object is an instance of '{type(obj).__name__}'. "
                f"This manager is for instances of '{self.Meta.model.__name__}'"
            )

    @classmethod
    def get_help_text(cls, field_name: str):
        """ Get the help text for any field on the managed model """
        return cls.Meta.model._meta.get_field(field_name).help_text

    @classmethod
    def _get_or_create(cls, **kwargs):
        """ Get or create an object for this model

			DO NOT DIRECTLY CALL THIS METHOD TO CREATE OBJECTS. This method should
			only be called by the `.create()` method of a ModelManager.
		"""
        return cls.Meta.model.objects.get_or_create(**kwargs)

