from django.contrib import admin
from .models import Resource, ResourceGroup


class ResourceAdmin(admin.ModelAdmin):
    search_fields = ("title", "description")


admin.site.register(Resource, ResourceAdmin)
admin.site.register(ResourceGroup)
