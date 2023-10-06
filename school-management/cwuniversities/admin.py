from django.contrib import admin
from .models import Deadline, DeadlineCategory, DeadlineType, University


class UniversityModelAdmin(admin.ModelAdmin):
    search_fields = ("name",)


class DeadlineModelAdmin(admin.ModelAdmin):
    search_fields = ("university__name",)


admin.site.register(University, UniversityModelAdmin)
admin.site.register(Deadline, DeadlineModelAdmin)
admin.site.register(DeadlineType)
admin.site.register(DeadlineCategory)
