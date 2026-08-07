from __future__ import annotations

from django.http import HttpRequest

from django_scim2_server.conf import get_config
from django_scim2_server.context import SCIMContext, get_context

#: Bearer token per tenant, standing in for a lookup against a real credential store.
TENANT_TOKENS = {
    "acme": "acme-secret",
    "globex": "globex-secret",
}


def make_context(config_name: str = "default", scope: str = "") -> SCIMContext:
    """Build a SCIM context the way a view would, for testing adapters directly."""
    return SCIMContext(config=get_config(config_name), scope=scope)


def tenant_token_check(request: HttpRequest) -> bool:
    """Accept the bearer token belonging to the tenant being addressed."""
    context = get_context(request)
    if context is None:
        return False
    expected = TENANT_TOKENS.get(context.scope)
    if expected is None:
        return False
    return request.META.get("HTTP_AUTHORIZATION") == f"Bearer {expected}"


def deny_all(request: HttpRequest) -> bool:
    """Reject every request."""
    return False
