"""URL configuration for SCIM 2.0 endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.urls import path

from django_scim2_server import views

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.urls import URLPattern

app_name = "scim2"


def get_urlpatterns(
    *,
    user_adapter: str | type | None = None,
    group_adapter: str | type | None = None,
    auth_check: str | Callable[[HttpRequest], bool] | None = None,
) -> list[URLPattern]:
    """
    Build the SCIM URL patterns, optionally with their own adapters and auth.

    Arguments left as ``None`` fall back to the ``SCIM2_SERVER_*`` settings.
    Mount each set under its own namespace to serve several SCIM endpoints::

        path(
            "scim/v2/staff/",
            include(
                (get_urlpatterns(user_adapter=StaffAdapter), "scim2"),
                namespace="scim2-staff",
            ),
        )
    """
    config: dict[str, Any] = {
        "user_adapter": user_adapter,
        "group_adapter": group_adapter,
        "auth_check": auth_check,
    }
    return [
        path(
            "ServiceProviderConfig",
            views.ServiceProviderConfigView.as_view(**config),
            name="service-provider-config",
        ),
        path(
            "ResourceTypes",
            views.ResourceTypesView.as_view(**config),
            name="resource-types",
        ),
        path(
            "Schemas",
            views.SchemasView.as_view(**config),
            name="schemas",
        ),
        path(
            "Users",
            views.UserListView.as_view(**config),
            name="users-list",
        ),
        path(
            "Users/<str:scim_id>",
            views.UserDetailView.as_view(**config),
            name="users-detail",
        ),
        path(
            "Groups",
            views.GroupListView.as_view(**config),
            name="groups-list",
        ),
        path(
            "Groups/<str:scim_id>",
            views.GroupDetailView.as_view(**config),
            name="groups-detail",
        ),
    ]


urlpatterns = get_urlpatterns()
