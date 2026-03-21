from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("scim/v2/", include("django_scim2_server.urls")),
]
