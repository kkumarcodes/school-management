"""
URL configuration for schoolnet project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static
from django.conf import settings

from snusers.views.register_login import LoginView
from cwtutoring.views.courses import CourseLandingPageView
from cwtutoring.views.diagnostic import DiagnosticLandingPageView

from rest_framework_simplejwt import views as jwt_views

# pylint: disable=invalid-name
app_patterns = [
    path("user/", include("snusers.urls")),
    path("tutoring/", include("cwtutoring.urls")),
    path("task/", include("cwtasks.urls")),
    path("cw/", include("cwcommon.urls")),
    path("resource/", include("cwresources.urls")),
    path("notification/", include("cwnotifications.urls")),
    path("message/", include("cwmessages.urls")),
    path("university/", include("cwuniversities.urls")),
    path("counseling/", include("cwcounseling.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
]
urlpatterns = [
    path("", LoginView.as_view()),
    path("admin/", admin.site.urls),
    path("grappelli/", include("grappelli.urls")),
    path("hijack/", include("hijack.urls", namespace="hijack")),
    path('token/', 
          jwt_views.TokenObtainPairView.as_view(), 
          name ='token_obtain_pair'),
     path('token/refresh/', 
          jwt_views.TokenRefreshView.as_view(), 
          name ='token_refresh')
]

landing_pages = [
    path("courses/", CourseLandingPageView.as_view(), name="course_landing_page"),
    path("diagnostics/", DiagnosticLandingPageView.as_view(), name="diagnostic_landing_page"),
]
urlpatterns += app_patterns + landing_pages
if settings.STATIC_ROOT and settings.ENV == "dev":
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
if settings.MEDIA_ROOT:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
