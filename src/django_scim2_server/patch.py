"""SCIM 2.0 PATCH operation handler (RFC 7644 Section 3.5.2)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from django.db import transaction

from django_scim2_server.exceptions import BadRequestError

if TYPE_CHECKING:
    from django_scim2_server.adapters import (
        BaseGroupAdapter,
        BaseUserAdapter,
    )
    from django_scim2_server.models import SCIMGroup, SCIMUser

MEMBER_FILTER_VALUE_EQ_RE = re.compile(r'value\s+eq\s+"([^"]+)"')

SUPPORTED_OPS = ("add", "remove", "replace")

_Resource = TypeVar("_Resource", "SCIMUser", "SCIMGroup")


def parse_member_filter(path: str) -> UUID:
    """Extract the member id from a sub-filter like ``members[value eq "uuid"]``."""
    match = MEMBER_FILTER_VALUE_EQ_RE.search(path)
    if not match:
        raise BadRequestError("Cannot parse member filter")
    try:
        return UUID(match.group(1))
    except ValueError as exc:
        raise BadRequestError("Cannot parse member filter") from exc


@transaction.atomic
def apply_patch_operations(
    scim_obj: _Resource,
    operations: list[dict[str, Any]],
    adapter: BaseUserAdapter | BaseGroupAdapter,
) -> _Resource:
    """
    Apply a list of SCIM PATCH operations to a resource.

    Each operation is delegated to the adapter, so an adapter can support additional
    SCIM paths by overriding ``apply_patch_operation``.
    """
    for operation in operations:
        op = operation.get("op", "").lower()
        if op not in SUPPORTED_OPS:
            raise BadRequestError(f"Unsupported PATCH op: {op}")

        adapter.apply_patch_operation(
            scim_obj,
            op,
            operation.get("path"),
            operation.get("value"),
        )

    adapter.save_patched(scim_obj)
    return scim_obj
