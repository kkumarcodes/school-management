from rest_framework.routers import DefaultRouter

from .views import (
    TaskViewset,
    TaskTemplateViewset,
    FormViewset,
    FormSubmissionViewset,
    FormFieldViewset,
    FormFieldEntryViewset,
)

# pylint: disable=invalid-name
router = DefaultRouter()
router.register("tasks", TaskViewset, basename="tasks")
router.register("task-templates", TaskTemplateViewset, basename="task_templates")
router.register("forms", FormViewset, basename="forms")
router.register("form-submissions", FormSubmissionViewset, basename="form_submissions")
router.register("form-fields", FormFieldViewset, basename="form_fields")
router.register("form-field-entries", FormFieldEntryViewset, basename="form_field_entries")

# all paths prefaced by /task/
# pylint: disable=invalid-name
urlpatterns = router.urls + []
