"""URL configuration for SCIM 2.0 endpoints."""

from __future__ import annotations

from django.urls import path

from django_scim2_server import views

app_name = "scim2"

urlpatterns = [
    path(
        "ServiceProviderConfig",
        views.ServiceProviderConfigView.as_view(),
        name="service-provider-config",
    ),
    path(
        "ResourceTypes",
        views.ResourceTypesView.as_view(),
        name="resource-types",
    ),
    path(
        "Schemas",
        views.SchemasView.as_view(),
        name="schemas",
    ),
    path(
        "Users",
        views.UserListView.as_view(),
        name="users-list",
    ),
    path(
        "Users/<uuid:scim_id>",
        views.UserDetailView.as_view(),
        name="users-detail",
    ),
    path(
        "Groups",
        views.GroupListView.as_view(),
        name="groups-list",
    ),
    path(
        "Groups/<uuid:scim_id>",
        views.GroupDetailView.as_view(),
        name="groups-detail",
    ),
]
