from django.contrib import admin
from .models import Task, TaskTemplate, Form, FormSubmission, FormField, FormFieldEntry


class TaskTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "roadmap_key", "task_type", "roadmap", "description")


admin.site.register(Task)
admin.site.register(TaskTemplate, TaskTemplateAdmin)
admin.site.register(Form)
admin.site.register(FormSubmission)
admin.site.register(FormField)
admin.site.register(FormFieldEntry)
