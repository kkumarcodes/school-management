import uuid
from django.db import models


class SNModel(models.Model):
    """ We add some default fields to every model (all models derive from this class) """

    slug = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SNAbbreviation(SNModel):
    """
    Abstract base class for abbreviation models.

    Abbreviations (including acronyms and initialisms) are commonly used as
    codes, as labels, in table-headings, etc., but may lose their meaning out
    of context or may be inscrutable to users without domain expertise.
    Abbreviation models allow us to associate abbreviations, full terms, and
    their definitions in a consistent way.
    """

    abbreviation = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    definition = models.TextField(blank=True)

    def __str__(self):
        return self.name

    class Meta:
        abstract = True
