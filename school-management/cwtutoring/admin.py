from django.contrib import admin
from .models import (
    Location,
    TestResult,
    Diagnostic,
    DiagnosticResult,
    TutorAvailability,
    GroupTutoringSession,
    StudentTutoringSession,
    TutoringSessionNotes,
    TutoringPackage,
    TutoringPackagePurchase,
    TutorTimeCard,
    TutorTimeCardLineItem,
    Course,
    TutoringService,
)


class StudentTutoringSessionModelAdmin(admin.ModelAdmin):
    search_fields = (
        "student__invitation_name",
        "individual_session_tutor__invitation_name",
        "group_tutoring_session__title",
        "group_tutoring_session__primary_tutor__invitation_name",
    )
    exclude = (
        "student",
        "group_tutoring_session",
        "created_by",
        "tutoring_session_notes",
    )


class TutoringPackagePurchaseAdmin(admin.ModelAdmin):
    search_fields = ("student__invitation_name", "tutoring_package__title")


class TutoringPackageAdmin(admin.ModelAdmin):
    def tutor_name(x):
        return x.restricted_tutor.invitation_name if x.restricted_tutor else ""

    def locations(x: TutoringPackage):
        return "All" if x.all_locations else ", ".join(x.locations.values_list("name", flat=True))

    list_display = (
        "title",
        "active",
        "allow_self_enroll",
        "is_paygo_package",
        "product_id",
        tutor_name,
        locations,
        "individual_test_prep_hours",
        "group_test_prep_hours",
        "individual_curriculum_hours",
        "price",
    )
    search_fields = ("title", "locations__name")
    list_filter = ("active", "is_paygo_package", "product_id", "all_locations", "is_paygo_package")


admin.site.register(Location)
admin.site.register(TestResult)
admin.site.register(Diagnostic)
admin.site.register(DiagnosticResult)
admin.site.register(TutorAvailability)
admin.site.register(GroupTutoringSession)
admin.site.register(StudentTutoringSession, StudentTutoringSessionModelAdmin)
admin.site.register(TutoringSessionNotes)
admin.site.register(TutoringPackage, TutoringPackageAdmin)
admin.site.register(TutoringPackagePurchase, TutoringPackagePurchaseAdmin)
admin.site.register(TutorTimeCard)
admin.site.register(TutorTimeCardLineItem)
admin.site.register(Course)
admin.site.register(TutoringService)
