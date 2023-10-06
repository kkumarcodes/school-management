# pylint: disable=invalid-name

from rest_framework.routers import DefaultRouter
from django.urls import path
from cwresources.views import get_resource, ResourceViewset, ResourceGroupViewset

# Prefaced by /resource/

router = DefaultRouter()
router.register("resources", ResourceViewset, basename="resources")
router.register("resource-groups", ResourceGroupViewset, basename="resource_groups")
# pylint: disable=invalid-name
urlpatterns = router.urls + [
    path("get/<str:resource_slug>/", get_resource, name="get_resource"),
]
