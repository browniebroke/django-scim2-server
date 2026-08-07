"""URL configuration for SCIM 2.0 endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.urls import path

from django_scim2_server import views

if TYPE_CHECKING:
    from django.urls import URLPattern


def scim2_urls(config_name: str = "default") -> tuple[list[URLPattern], str]:
    """
    Build the SCIM URL patterns for a named configuration.

    The return value is ready to hand to ``include()``, and uses the configuration
    name as the URL namespace, so the same endpoints can be mounted several times:

    .. code-block:: python

        from django.urls import include, path
        from django_scim2_server.urls import scim2_urls

        urlpatterns = [
            path("scim/v2/", include(scim2_urls("staff"))),
            path("t/<slug:tenant>/scim/v2/", include(scim2_urls("tenants"))),
        ]

    Resources are then reversed as ``staff:users-detail``, ``tenants:users-detail``,
    and so on. A configuration declaring ``SCOPE_URL_KWARG`` must be mounted under a
    pattern capturing that keyword — ``tenant`` in the example above.
    """
    urlpatterns = [
        path(
            "ServiceProviderConfig",
            views.ServiceProviderConfigView.as_view(config_name=config_name),
            name="service-provider-config",
        ),
        path(
            "ResourceTypes",
            views.ResourceTypesView.as_view(config_name=config_name),
            name="resource-types",
        ),
        path(
            "Schemas",
            views.SchemasView.as_view(config_name=config_name),
            name="schemas",
        ),
        path(
            "Users",
            views.UserListView.as_view(config_name=config_name),
            name="users-list",
        ),
        path(
            "Users/<uuid:scim_id>",
            views.UserDetailView.as_view(config_name=config_name),
            name="users-detail",
        ),
        path(
            "Groups",
            views.GroupListView.as_view(config_name=config_name),
            name="groups-list",
        ),
        path(
            "Groups/<uuid:scim_id>",
            views.GroupDetailView.as_view(config_name=config_name),
            name="groups-detail",
        ),
    ]
    return urlpatterns, config_name
