from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.shortcuts import render

from coreapp.auth_views import RateLimitedLoginView


def permission_denied_view(request, exception=None):
    return render(request, "403.html", status=403)


handler403 = permission_denied_view

urlpatterns = [
    path("admin/", admin.site.urls),

    path(
        "login/",
        RateLimitedLoginView.as_view(),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    path("", include("coreapp.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
