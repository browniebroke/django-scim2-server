from django.contrib import admin
from django.urls import include, path

from django_scim2_server.urls import scim2_urls

urlpatterns = [
    path("admin/", admin.site.urls),
    path("scim/v2/", include(scim2_urls("default"))),
    path("t/<slug:tenant>/scim/v2/", include(scim2_urls("tenants"))),
]
