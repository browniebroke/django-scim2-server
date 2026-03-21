"""SCIM 2.0 views: discovery endpoints and CRUD for Users and Groups."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.utils.module_loading import import_string
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from django_scim2_server.conf import app_settings
from django_scim2_server.constants import (
    RESOURCE_TYPE_GROUP,
    RESOURCE_TYPE_USER,
    SCHEMA_GROUP,
    SCHEMA_USER,
    SCIM_CONTENT_TYPE,
    SERVICE_PROVIDER_CONFIG,
    URN_LIST_RESPONSE,
    URN_PATCH_OP,
)
from django_scim2_server.exceptions import (
    BadRequestError,
    NotFoundError,
    SCIMError,
    scim_error_response,
)
from django_scim2_server.filters import parse_filter

logger = logging.getLogger(__name__)


def _get_adapter(dotted_path: str) -> Any:
    """Import and instantiate an adapter class from a dotted path."""
    cls = import_string(dotted_path)
    return cls()


@method_decorator(csrf_exempt, name="dispatch")
class SCIMView(View):
    """Base view for SCIM endpoints."""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Dispatch with SCIM error handling and content type."""
        if not self.check_auth(request):
            error = SCIMError(detail="Authentication required", status=401)
            return scim_error_response(error)
        try:
            response = super().dispatch(request, *args, **kwargs)
        except SCIMError as exc:
            return scim_error_response(exc)
        except json.JSONDecodeError:
            return scim_error_response(BadRequestError("Invalid JSON in request body"))
        return response

    def check_auth(self, request: HttpRequest) -> bool:
        """Check if the request is authenticated. Override for custom auth."""
        return bool(request.user and request.user.is_authenticated)

    def scim_response(
        self,
        data: dict[str, Any],
        status: int = 200,
    ) -> JsonResponse:
        """Return a JsonResponse with SCIM content type."""
        return JsonResponse(data, status=status, content_type=SCIM_CONTENT_TYPE)

    def parse_body(self, request: HttpRequest) -> dict[str, Any]:
        """Parse JSON body from request."""
        return json.loads(request.body)


# Discovery views


class ServiceProviderConfigView(SCIMView):
    """GET /ServiceProviderConfig - SCIM service provider configuration."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """Return the service provider configuration."""
        return self.scim_response(SERVICE_PROVIDER_CONFIG)


class ResourceTypesView(SCIMView):
    """GET /ResourceTypes - available SCIM resource types."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """Return the list of resource types."""
        return self.scim_response(
            {
                "schemas": [URN_LIST_RESPONSE],
                "totalResults": 2,
                "Resources": [RESOURCE_TYPE_USER, RESOURCE_TYPE_GROUP],
            },
        )


class SchemasView(SCIMView):
    """GET /Schemas - SCIM schema definitions."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """Return the list of schemas."""
        return self.scim_response(
            {
                "schemas": [URN_LIST_RESPONSE],
                "totalResults": 2,
                "Resources": [SCHEMA_USER, SCHEMA_GROUP],
            },
        )


# Resource views


class UserListView(SCIMView):
    """GET /Users (list+filter) and POST /Users (create)."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """List users with optional filtering and pagination."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_USER_ADAPTER)
        qs = adapter.get_queryset()

        # Filtering
        filter_expr = request.GET.get("filter")
        if filter_expr:
            q = parse_filter(filter_expr, adapter.filter_map)
            qs = qs.filter(q)

        # Pagination (SCIM uses 1-based startIndex)
        total = qs.count()
        start_index = max(1, int(request.GET.get("startIndex", 1)))
        count = int(request.GET.get("count", 100))
        offset = start_index - 1
        page = qs[offset : offset + count]

        resources = [adapter.to_scim(obj, request) for obj in page]
        return self.scim_response(
            {
                "schemas": [URN_LIST_RESPONSE],
                "totalResults": total,
                "startIndex": start_index,
                "itemsPerPage": len(resources),
                "Resources": resources,
            },
        )

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new user."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_USER_ADAPTER)
        data = self.parse_body(request)
        scim_obj = adapter.from_scim(data)
        return self.scim_response(adapter.to_scim(scim_obj, request), status=201)


class UserDetailView(SCIMView):
    """GET/PUT/PATCH/DELETE /Users/<scim_id>."""

    def get(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Return a single user."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_USER_ADAPTER)
        scim_obj = self._get_object(adapter, scim_id)
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def put(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Replace a user."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_USER_ADAPTER)
        scim_obj = self._get_object(adapter, scim_id)
        data = self.parse_body(request)
        scim_obj = adapter.from_scim(data, scim_obj)
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def patch(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Partially update a user via SCIM PatchOp."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_USER_ADAPTER)
        scim_obj = self._get_object(adapter, scim_id)
        data = self.parse_body(request)
        self._validate_patch(data)
        scim_obj = adapter.patch(scim_obj, data["Operations"])
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def delete(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> HttpResponse:
        """Delete (deactivate) a user."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_USER_ADAPTER)
        scim_obj = self._get_object(adapter, scim_id)
        adapter.delete(scim_obj)
        return HttpResponse(status=204)

    def _get_object(self, adapter: Any, scim_id: str) -> Any:
        try:
            return adapter.get_queryset().get(id=scim_id)
        except adapter.get_queryset().model.DoesNotExist:
            raise NotFoundError(f"User {scim_id} not found") from None

    def _validate_patch(self, data: dict[str, Any]) -> None:
        schemas = data.get("schemas", [])
        if URN_PATCH_OP not in schemas:
            raise BadRequestError("PatchOp schema required")
        if "Operations" not in data:
            raise BadRequestError("Operations is required")


class GroupListView(SCIMView):
    """GET /Groups (list+filter) and POST /Groups (create)."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """List groups with optional filtering and pagination."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_GROUP_ADAPTER)
        qs = adapter.get_queryset()

        # Filtering
        filter_expr = request.GET.get("filter")
        if filter_expr:
            q = parse_filter(filter_expr, adapter.filter_map)
            qs = qs.filter(q)

        # Pagination
        total = qs.count()
        start_index = max(1, int(request.GET.get("startIndex", 1)))
        count = int(request.GET.get("count", 100))
        offset = start_index - 1
        page = qs[offset : offset + count]

        resources = [adapter.to_scim(obj, request) for obj in page]
        return self.scim_response(
            {
                "schemas": [URN_LIST_RESPONSE],
                "totalResults": total,
                "startIndex": start_index,
                "itemsPerPage": len(resources),
                "Resources": resources,
            },
        )

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new group."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_GROUP_ADAPTER)
        data = self.parse_body(request)
        scim_obj = adapter.from_scim(data)
        return self.scim_response(adapter.to_scim(scim_obj, request), status=201)


class GroupDetailView(SCIMView):
    """GET/PUT/PATCH/DELETE /Groups/<scim_id>."""

    def get(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Return a single group."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_GROUP_ADAPTER)
        scim_obj = self._get_object(adapter, scim_id)
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def put(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Replace a group."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_GROUP_ADAPTER)
        scim_obj = self._get_object(adapter, scim_id)
        data = self.parse_body(request)
        scim_obj = adapter.from_scim(data, scim_obj)
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def patch(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Partially update a group via SCIM PatchOp."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_GROUP_ADAPTER)
        scim_obj = self._get_object(adapter, scim_id)
        data = self.parse_body(request)
        self._validate_patch(data)
        scim_obj = adapter.patch(scim_obj, data["Operations"])
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def delete(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> HttpResponse:
        """Delete a group."""
        adapter = _get_adapter(app_settings.SCIM2_SERVER_GROUP_ADAPTER)
        scim_obj = self._get_object(adapter, scim_id)
        adapter.delete(scim_obj)
        return HttpResponse(status=204)

    def _get_object(self, adapter: Any, scim_id: str) -> Any:
        try:
            return adapter.get_queryset().get(id=scim_id)
        except adapter.get_queryset().model.DoesNotExist:
            raise NotFoundError(f"Group {scim_id} not found") from None

    def _validate_patch(self, data: dict[str, Any]) -> None:
        schemas = data.get("schemas", [])
        if URN_PATCH_OP not in schemas:
            raise BadRequestError("PatchOp schema required")
        if "Operations" not in data:
            raise BadRequestError("Operations is required")
