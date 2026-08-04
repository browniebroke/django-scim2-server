"""SCIM 2.0 views: discovery endpoints and CRUD for Users and Groups."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from pydantic import BaseModel
from scim2_models import Group as SCIMGroupModel
from scim2_models import ListResponse, ResourceType, Schema
from scim2_models import User as SCIMUserModel

from django_scim2_server.conf import get_config
from django_scim2_server.constants import (
    RESOURCE_TYPE_GROUP,
    RESOURCE_TYPE_USER,
    SCHEMA_GROUP,
    SCHEMA_USER,
    SCIM_CONTENT_TYPE,
    URN_PATCH_OP,
)
from django_scim2_server.context import REQUEST_ATTR, SCIMContext
from django_scim2_server.exceptions import (
    BadRequestError,
    NotFoundError,
    SCIMError,
    scim_error_response,
)
from django_scim2_server.filters import parse_filter

if TYPE_CHECKING:
    from django_scim2_server.adapters import BaseGroupAdapter, BaseUserAdapter

logger = logging.getLogger(__name__)

# Bound page size to mitigate resource-exhaustion requests while remaining generous.
MAX_PAGE_SIZE = 1000
# Bound offset to avoid pathological deep-offset scans on large tables.
# One million keeps compatibility for large tenants while still rejecting extreme abuse.
MAX_START_INDEX = 1000000


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


@method_decorator(csrf_exempt, name="dispatch")
class SCIMView(View):
    """Base view for SCIM endpoints."""

    config_name: str = "default"
    """Name of the SCIM configuration this view serves, bound by ``scim2_urls()``."""

    scim_context: SCIMContext

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Resolve the configuration, then dispatch with SCIM error handling."""
        config = get_config(self.config_name)
        scope = ""
        if config.scope_url_kwarg is not None:
            if config.scope_url_kwarg not in kwargs:
                raise ImproperlyConfigured(
                    f"SCIM configuration '{config.name}' declares "
                    f"SCOPE_URL_KWARG = '{config.scope_url_kwarg}', but the URL "
                    f"pattern it is mounted under does not capture it."
                )
            scope = str(kwargs.pop(config.scope_url_kwarg))

        self.scim_context = SCIMContext(config=config, scope=scope)
        setattr(request, REQUEST_ATTR, self.scim_context)

        if not config.auth_check(request):
            error = SCIMError(detail="Authentication required", status=401)
            return scim_error_response(error)
        try:
            response = super().dispatch(request, *args, **kwargs)
        except SCIMError as exc:
            return scim_error_response(exc)
        except json.JSONDecodeError:
            return scim_error_response(BadRequestError("Invalid JSON in request body"))
        return response

    def build_url(self, url_name: str, **kwargs: str) -> str:
        """Build an absolute URL on the mount serving the current request."""
        scope_kwarg = self.scim_context.config.scope_url_kwarg
        if scope_kwarg is not None:
            kwargs[scope_kwarg] = self.scim_context.scope
        path = reverse(f"{self.config_name}:{url_name}", kwargs=kwargs)
        return self.request.build_absolute_uri(path)

    def scim_response(
        self,
        data: BaseModel | dict[str, Any],
        status: int = 200,
    ) -> JsonResponse:
        """Return a JsonResponse with SCIM content type."""
        if isinstance(data, BaseModel):
            json_data = data.model_dump(mode="json", by_alias=True, exclude_none=True)
        else:
            json_data = data
        return JsonResponse(json_data, status=status, content_type=SCIM_CONTENT_TYPE)

    def parse_body(self, request: HttpRequest) -> dict[str, Any]:
        """Parse JSON body from request."""
        return json.loads(request.body)


# Discovery views


class ServiceProviderConfigView(SCIMView):
    """GET /ServiceProviderConfig - SCIM service provider configuration."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """Return the service provider configuration."""
        return self.scim_response(self.scim_context.config.service_provider_config)


class ResourceTypesView(SCIMView):
    """GET /ResourceTypes - available SCIM resource types."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """Return the list of resource types."""
        resources = [
            self._localise(RESOURCE_TYPE_USER, "users-list"),
            self._localise(RESOURCE_TYPE_GROUP, "groups-list"),
        ]
        response = ListResponse[ResourceType](
            total_results=len(resources),
            resources=resources,
        )
        return self.scim_response(response)

    def _localise(self, resource_type: ResourceType, url_name: str) -> ResourceType:
        """Copy a resource type with a location pointing at the current mount."""
        localised = resource_type.model_copy(deep=True)
        if localised.meta is not None:
            localised.meta.location = self.build_url(url_name)
        return localised


class SchemasView(SCIMView):
    """GET /Schemas - SCIM schema definitions."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """Return the list of schemas."""
        base = self.build_url("schemas")
        resources = [
            self._localise(schema, base) for schema in (SCHEMA_USER, SCHEMA_GROUP)
        ]
        response = ListResponse[Schema](
            total_results=len(resources),
            resources=resources,
        )
        return self.scim_response(response)

    def _localise(self, schema: Schema, base: str) -> Schema:
        """Copy a schema with a location pointing at the current mount."""
        localised = schema.model_copy(deep=True)
        if localised.meta is not None:
            localised.meta.location = f"{base}/{schema.id}"
        return localised


# Resource views


class SCIMResourceView(SCIMView):
    """Base for the Users and Groups endpoints."""

    resource_name: ClassVar[str] = ""
    """Human-readable resource name, used in error messages."""

    adapter_attr: ClassVar[str] = ""
    """Name of the :class:`~django_scim2_server.conf.SCIMConfig` adapter field."""

    list_response_model: ClassVar[type[ListResponse[Any]]]
    """Parametrised ``ListResponse`` used to serialise list results."""

    def get_adapter(self) -> BaseUserAdapter | BaseGroupAdapter:
        """Instantiate the adapter for this resource, bound to the request context."""
        adapter_class = getattr(self.scim_context.config, self.adapter_attr)
        adapter: BaseUserAdapter | BaseGroupAdapter = adapter_class(self.scim_context)
        return adapter


class SCIMListView(SCIMResourceView):
    """GET (list+filter) and POST (create) for a SCIM resource collection."""

    def get(self, request: HttpRequest) -> JsonResponse:
        """List resources with optional filtering and pagination."""
        adapter = self.get_adapter()
        qs = adapter.get_queryset()

        # Filtering
        filter_expr = request.GET.get("filter")
        if filter_expr:
            q = parse_filter(filter_expr, adapter.filter_map)
            qs = qs.filter(q)

        # Pagination (SCIM uses 1-based startIndex)
        total = qs.count()
        start_index, count = _parse_pagination(request)
        offset = start_index - 1
        page = qs[offset : offset + count]

        resources = [adapter.to_scim(obj, request) for obj in page]
        response = self.list_response_model(
            total_results=total,
            start_index=start_index,
            items_per_page=len(resources),
            resources=resources,
        )
        return self.scim_response(response)

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new resource."""
        adapter = self.get_adapter()
        data = self.parse_body(request)
        scim_obj = adapter.from_scim(data)
        return self.scim_response(adapter.to_scim(scim_obj, request), status=201)


class SCIMDetailView(SCIMResourceView):
    """GET/PUT/PATCH/DELETE for a single SCIM resource."""

    def get(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Return a single resource."""
        adapter = self.get_adapter()
        scim_obj = self._get_object(adapter, scim_id)
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def put(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Replace a resource."""
        adapter = self.get_adapter()
        scim_obj = self._get_object(adapter, scim_id)
        data = self.parse_body(request)
        scim_obj = adapter.from_scim(data, scim_obj)
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def patch(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> JsonResponse:
        """Partially update a resource via SCIM PatchOp."""
        adapter = self.get_adapter()
        scim_obj = self._get_object(adapter, scim_id)
        data = self.parse_body(request)
        self._validate_patch(data)
        scim_obj = adapter.patch(scim_obj, data["Operations"])
        return self.scim_response(adapter.to_scim(scim_obj, request))

    def delete(self, request: HttpRequest, scim_id: str, **kwargs: Any) -> HttpResponse:
        """Delete a resource."""
        adapter = self.get_adapter()
        scim_obj = self._get_object(adapter, scim_id)
        adapter.delete(scim_obj)
        return HttpResponse(status=204)

    def _get_object(
        self,
        adapter: BaseUserAdapter | BaseGroupAdapter,
        scim_id: str,
    ) -> Any:
        queryset = adapter.get_queryset()
        try:
            return queryset.get(id=scim_id)
        except queryset.model.DoesNotExist:
            raise NotFoundError(f"{self.resource_name} {scim_id} not found") from None

    def _validate_patch(self, data: dict[str, Any]) -> None:
        schemas = data.get("schemas", [])
        if URN_PATCH_OP not in schemas:
            raise BadRequestError("PatchOp schema required")
        if "Operations" not in data:
            raise BadRequestError("Operations is required")


class UserListView(SCIMListView):
    """GET /Users (list+filter) and POST /Users (create)."""

    resource_name = "User"
    adapter_attr = "user_adapter"
    list_response_model = ListResponse[SCIMUserModel]


class UserDetailView(SCIMDetailView):
    """GET/PUT/PATCH/DELETE /Users/<scim_id>."""

    resource_name = "User"
    adapter_attr = "user_adapter"


class GroupListView(SCIMListView):
    """GET /Groups (list+filter) and POST /Groups (create)."""

    resource_name = "Group"
    adapter_attr = "group_adapter"
    list_response_model = ListResponse[SCIMGroupModel]


class GroupDetailView(SCIMDetailView):
    """GET/PUT/PATCH/DELETE /Groups/<scim_id>."""

    resource_name = "Group"
    adapter_attr = "group_adapter"
