from django.contrib import admin
from django.urls import include, path

from django_scim2_server.urls import get_urlpatterns
from tests.testapp.scim import MemberAdapter, organisation_token_auth

urlpatterns = [
    path("admin/", admin.site.urls),
    path("scim/v2/", include("django_scim2_server.urls")),
    path(
        "scim/v2/orgs/",
        include(
            (
                get_urlpatterns(
                    user_adapter=MemberAdapter,
                    auth_check=organisation_token_auth,
                ),
                "scim2",
            ),
            namespace="scim2-orgs",
        ),
    ),
]
