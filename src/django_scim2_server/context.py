"""Per-request SCIM context: which configuration, and which tenant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.http import HttpRequest

    from django_scim2_server.conf import SCIMConfig

#: Attribute under which the context is attached to the request.
REQUEST_ATTR = "scim2_context"


@dataclass(frozen=True)
class SCIMContext:
    """
    The configuration and tenant a SCIM request is being served under.

    Attached to the request as ``request.scim2_context`` before the access-control
    callable runs, and passed to the adapters handling the request.
    """

    config: SCIMConfig
    """The configuration this request was routed to."""

    scope: str = ""
    """
    Tenant key for this request, or ``""`` for an unscoped configuration.

    Read from the URL keyword argument named by the configuration's
    ``SCOPE_URL_KWARG``.
    """


def get_context(request: HttpRequest) -> SCIMContext | None:
    """
    Return the SCIM context attached to ``request``, if any.

    Useful from an access-control callable, which receives only the request:

    .. code-block:: python

        from django_scim2_server.context import get_context


        def tenant_token_check(request):
            context = get_context(request)
            if context is None:  # not a SCIM request
                return False
            header = request.META.get("HTTP_AUTHORIZATION", "")
            return header == f"Bearer {token_for(context.scope)}"
    """
    context: SCIMContext | None = getattr(request, REQUEST_ATTR, None)
    return context
