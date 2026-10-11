"""SCIM 2.0 views: discovery endpoints and CRUD for Users and Groups."""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, ClassVar, cast

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.utils.module_loading import import_string
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from pydantic import BaseModel

from django_scim2_server.conf import app_settings
from django_scim2_server.constants import (
    SCIM_CONTENT_TYPE,
    SERVICE_PROVIDER_CONFIG,
    URN_LIST_RESPONSE,
    URN_PATCH_OP,
)
from django_scim2_server.exceptions import (
    BadRequestError,
    SCIMError,
    scim_error_response,
)
from django_scim2_server.filters import parse_filter

logger = logging.getLogger(__name__)

# Bound page size to mitigate resource-exhaustion requests while remaining generous.
MAX_PAGE_SIZE = 1000
# Bound offset to avoid pathological deep-offset scans on large tables.
# One million keeps compatibility for large tenants while still rejecting extreme abuse.
MAX_START_INDEX = 1000000


def _resolve(spec: Any, default: str) -> Any:
    """Turn a dotted path, an object, or None (use the setting) into an object."""
    if spec is None:
        spec = default
    if isinstance(spec, str):
        return import_string(spec)
    return spec


def _parse_pagination(request: HttpRequest) -> tuple[int, int]:
    """Parse and validate SCIM pagination query parameters."""
    try:
        start_index = int(request.GET.get("startIndex", 1))
        count = int(request.GET.get("count", 100))
    except (TypeError, ValueError) as exc:
        raise BadRequestError("startIndex and count must be integers") from exc

    if start_index < 1:
        raise BadRequestError("startIndex must be >= 1")
    if start_index > MAX_START_INDEX:
        raise BadRequestError(f"startIndex must be <= {MAX_START_INDEX}")
    if count < 0:
        raise BadRequestError("count must be >= 0")
    if count > MAX_PAGE_SIZE:
        raise BadRequestError(f"count must be <= {MAX_PAGE_SIZE}")
    return start_index, count


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


@method_decorator(csrf_exempt, name="dispatch")
class SCIMView(View):
    """
    Base view for SCIM endpoints.

    ``user_adapter``, ``group_adapter`` and ``auth_check`` default to the
    ``SCIM2_SERVER_*`` settings and can be overridden per mount through
    ``as_view()`` or :func:`django_scim2_server.urls.get_urlpatterns`.
    """

    user_adapter: ClassVar[Any] = None
    group_adapter: ClassVar[Any] = None
    auth_check: ClassVar[Any] = None

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Dispatch with SCIM error handling and content type."""
        auth_check = self.auth_check
        if inspect.ismethod(auth_check) and auth_check.__self__ is self:
            # A plain function set on a subclass body is bound like a method.
            auth_check = auth_check.__func__
        auth_check = _resolve(auth_check, app_settings.SCIM2_SERVER_AUTH_CHECK)
        if not auth_check(request):
            error = SCIMError(detail="Authentication required", status=401)
            return scim_error_response(error)
        try:
            response = super().dispatch(request, *args, **kwargs)
        except SCIMError as exc:
            return scim_error_response(exc)
        except json.JSONDecodeError:
            return scim_error_response(BadRequestError("Invalid JSON in request body"))
        return cast(HttpResponse, response)

    def get_user_adapter(self) -> Any:
        """Instantiate the user adapter for the current request."""
        cls = _resolve(self.user_adapter, app_settings.SCIM2_SERVER_USER_ADAPTER)
        return cls(self.request)

    def get_group_adapter(self) -> Any:
        """Instantiate the group adapter for the current request."""
        cls = _resolve(self.group_adapter, app_settings.SCIM2_SERVER_GROUP_ADAPTER)
        return cls(self.request)

    def scim_response(
        self,
        data: BaseModel | dict[str, Any],
        status: int = 200,
    ) -> JsonResponse:
        """Return a JsonResponse with SCIM content type."""
        json_data = _dump(data) if isinstance(data, BaseModel) else data
        return JsonResponse(json_data, status=status, content_type=SCIM_CONTENT_TYPE)

    def list_response(
        self,
        resources: list[dict[str, Any]],
        total: int,
        start_index: int = 1,
    ) -> JsonResponse:
        """
        Return a ListResponse.

        Built from already-dumped resources: a typed ``ListResponse[User[Any]]``
        would drop extension attributes such as the Enterprise User ones.
        """
        return self.scim_response(
            {
                "schemas": [URN_LIST_RESPONSE],
                "totalResults": total,
                "startIndex": start_index,
                "itemsPerPage": len(resources),
                "Resources": resources,
            },
        )

    def parse_body(self, request: HttpRequest) -> dict[str, Any]:
        """Parse JSON body from request."""
        body = json.loads(request.body)
        if not isinstance(body, dict):
            raise BadRequestError("Request body must be a JSON object")
        return body


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
        resources = [
            _dump(adapter.resource_type)
            for adapter in (self.get_user_adapter(), self.get_group_adapter())
        ]
        return self.list_response(resources, total=len(resources))


class SchemasView(SCIMView):
    """GET /Schemas - SCIM schema definitions."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """Return the list of schemas."""
        schemas: dict[str, dict[str, Any]] = {}
        for adapter in (self.get_user_adapter(), self.get_group_adapter()):
            for schema in adapter.schemas:
                schemas.setdefault(str(schema.id), _dump(schema))
        resources = list(schemas.values())
        return self.list_response(resources, total=len(resources))


# Resource views


class _ResourceListView(SCIMView):
    """GET (list+filter) and POST (create) for one resource type."""

    def get_adapter(self) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def get(self, request: HttpRequest) -> JsonResponse:
        """List resources with optional filtering and pagination."""
        adapter = self.get_adapter()
        qs = adapter.get_queryset()

        filter_expr = request.GET.get("filter")
        if filter_expr:
            qs = qs.filter(parse_filter(filter_expr, adapter.filter_map))

        # SCIM uses a 1-based startIndex.
        total = qs.count()
        start_index, count = _parse_pagination(request)
        offset = start_index - 1
        page = qs[offset : offset + count]

        resources = [_dump(adapter.to_scim(obj, request)) for obj in page]
        return self.list_response(resources, total=total, start_index=start_index)

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new resource."""
        adapter = self.get_adapter()
        scim_obj = adapter.from_scim(self.parse_body(request))
        return self.scim_response(adapter.to_scim(scim_obj, request), status=201)


class _ResourceDetailView(SCIMView):
    """GET/PUT/PATCH/DELETE for a single resource."""

    def get_adapter(self) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def get(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Return a single resource."""
        adapter = self.get_adapter()
        scim_obj = adapter.get_object(str(scim_id))
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def put(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Replace a resource."""
        adapter = self.get_adapter()
        scim_obj = adapter.get_object(str(scim_id))
        scim_obj = adapter.from_scim(self.parse_body(request), scim_obj)
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def patch(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Partially update a resource via SCIM PatchOp."""
        adapter = self.get_adapter()
        scim_obj = adapter.get_object(str(scim_id))
        data = self.parse_body(request)
        self._validate_patch(data)
        scim_obj = adapter.patch(scim_obj, data["Operations"])
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def delete(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> HttpResponse:
        """Delete (or deactivate, depending on the adapter) a resource."""
        adapter = self.get_adapter()
        adapter.delete(adapter.get_object(str(scim_id)))
        return HttpResponse(status=204)

    def _validate_patch(self, data: dict[str, Any]) -> None:
        schemas = data.get("schemas", [])
        if URN_PATCH_OP not in schemas:
            raise BadRequestError("PatchOp schema required")
        if "Operations" not in data:
            raise BadRequestError("Operations is required")


class UserListView(_ResourceListView):
    """GET /Users (list+filter) and POST /Users (create)."""

    def get_adapter(self) -> Any:
        """Return the user adapter."""
        return self.get_user_adapter()


class UserDetailView(_ResourceDetailView):
    """GET/PUT/PATCH/DELETE /Users/<scim_id>."""

    def get_adapter(self) -> Any:
        """Return the user adapter."""
        return self.get_user_adapter()


class GroupListView(_ResourceListView):
    """GET /Groups (list+filter) and POST /Groups (create)."""

    def get_adapter(self) -> Any:
        """Return the group adapter."""
        return self.get_group_adapter()


class GroupDetailView(_ResourceDetailView):
    """GET/PUT/PATCH/DELETE /Groups/<scim_id>."""

    def get_adapter(self) -> Any:
        """Return the group adapter."""
        return self.get_group_adapter()
