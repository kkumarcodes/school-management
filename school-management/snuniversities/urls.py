from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    DeadlineViewset,
    StudentUniversityDecisionViewset,
    UniversityViewset,
    UniversityListViewset,
    SNUniversityDataView,
)

# pylint: disable=invalid-name
router = DefaultRouter()
router.register("deadlines", DeadlineViewset, basename="deadlines")
router.register(
    "student-university-decisions", StudentUniversityDecisionViewset, basename="student_university_decisions"
)
router.register("universities", UniversityViewset, basename="universities")
router.register("university-lists", UniversityListViewset, basename="university_lists")

# all paths prefaced by /university/
# pylint: disable=invalid-name
urlpatterns = router.urls + [path("cw-data/<int:pk>/", SNUniversityDataView.as_view(), name="cw_university_data")]
