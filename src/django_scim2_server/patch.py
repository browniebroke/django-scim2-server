"""SCIM 2.0 PATCH operation handler (RFC 7644 Section 3.5.2)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction

from django_scim2_server.exceptions import BadRequestError
from django_scim2_server.models import SCIMGroup, SCIMUser

if TYPE_CHECKING:
    from django_scim2_server.adapters import (
        BaseGroupAdapter,
        BaseUserAdapter,
    )


def _apply_user_op(
    scim_obj: SCIMUser,
    op: str,
    path: str | None,
    value: Any,
) -> None:
    """Apply a single PATCH operation to a SCIMUser."""
    user = scim_obj.user

    if path is None and op in ("add", "replace") and isinstance(value, dict):
        # Bulk update: value is a dict of attributes
        _set_user_attrs(scim_obj, user, value)
        return

    if path is None:
        raise BadRequestError("path is required for this operation")

    if op in ("add", "replace"):
        _set_user_attr(scim_obj, user, path, value)
    elif op == "remove":
        _remove_user_attr(scim_obj, user, path)
    else:
        raise BadRequestError(f"Unsupported PATCH op: {op}")


def _set_user_attrs(scim_obj: SCIMUser, user: Any, attrs: dict[str, Any]) -> None:
    """Set multiple user attributes from a dict."""
    for key, val in attrs.items():
        _set_user_attr(scim_obj, user, key, val)


def _set_user_attr(scim_obj: SCIMUser, user: Any, path: str, value: Any) -> None:
    """Set a single user attribute by SCIM path."""
    if path == "userName":
        user.username = value
        scim_obj.scim_username = value
    elif path == "name.givenName":
        user.first_name = value
    elif path == "name.familyName":
        user.last_name = value
    elif path == "emails" and isinstance(value, list) and value:
        user.email = value[0].get("value", "")
    elif path == 'emails[type eq "work"].value' or path == "emails.value":
        user.email = value
    elif path == "active":
        scim_obj.active = value
        user.is_active = value
    elif path == "externalId":
        scim_obj.external_id = value or ""
    elif path == "name" and isinstance(value, dict):
        if "givenName" in value:
            user.first_name = value["givenName"]
        if "familyName" in value:
            user.last_name = value["familyName"]


def _remove_user_attr(scim_obj: SCIMUser, user: Any, path: str) -> None:
    """Remove (clear) a user attribute by SCIM path."""
    if path == "name.givenName":
        user.first_name = ""
    elif path == "name.familyName":
        user.last_name = ""
    elif path == "emails":
        user.email = ""
    elif path == "externalId":
        scim_obj.external_id = ""


def _apply_group_op(
    scim_obj: SCIMGroup,
    op: str,
    path: str | None,
    value: Any,
) -> None:
    """Apply a single PATCH operation to a SCIMGroup."""
    if path is None and op in ("add", "replace") and isinstance(value, dict):
        for key, val in value.items():
            _apply_group_op(scim_obj, op, key, val)
        return

    if path is None:
        raise BadRequestError("path is required for this operation")

    if path == "displayName" and op in ("add", "replace"):
        scim_obj.display_name = value
        scim_obj.group.name = value
    elif path == "externalId" and op in ("add", "replace"):
        scim_obj.external_id = value or ""
    elif path == "members" and op == "add":
        _add_group_members(scim_obj, value)
    elif path == "members" and op == "replace":
        _replace_group_members(scim_obj, value)
    elif path == "members" and op == "remove":
        _remove_group_members(scim_obj, value)
    elif path and path.startswith("members[") and op == "remove":
        _remove_group_member_by_filter(scim_obj, path)
    elif path == "externalId" and op == "remove":
        scim_obj.external_id = ""
    else:
        raise BadRequestError(f"Unsupported PATCH path: {path}")


def _add_group_members(scim_obj: SCIMGroup, value: Any) -> None:
    """Add members to a group."""
    if not isinstance(value, list):
        raise BadRequestError("members value must be a list")
    member_ids = [m["value"] for m in value if "value" in m]
    scim_users = SCIMUser.objects.filter(id__in=member_ids).select_related("user")
    for su in scim_users:
        scim_obj.group.user_set.add(su.user)


def _replace_group_members(scim_obj: SCIMGroup, value: Any) -> None:
    """Replace all group members."""
    if not isinstance(value, list):
        raise BadRequestError("members value must be a list")
    member_ids = [m["value"] for m in value if "value" in m]
    scim_users = SCIMUser.objects.filter(id__in=member_ids).select_related("user")
    users = [su.user for su in scim_users]
    scim_obj.group.user_set.set(users)


def _remove_group_members(scim_obj: SCIMGroup, value: Any) -> None:
    """Remove specified members from a group."""
    if not isinstance(value, list):
        raise BadRequestError("members value must be a list")
    member_ids = [m["value"] for m in value if "value" in m]
    scim_users = SCIMUser.objects.filter(id__in=member_ids).select_related("user")
    for su in scim_users:
        scim_obj.group.user_set.remove(su.user)


def _remove_group_member_by_filter(scim_obj: SCIMGroup, path: str) -> None:
    """Remove a group member by sub-filter like ``members[value eq "uuid"]``."""
    match = re.search(r'value\s+eq\s+"([^"]+)"', path)
    if not match:
        raise BadRequestError("Cannot parse member filter")
    member_id = match.group(1)

    try:
        member_uuid = UUID(member_id)
    except ValueError as exc:
        raise BadRequestError("Cannot parse member filter") from exc

    try:
        scim_user = SCIMUser.objects.select_related("user").get(id=member_uuid)
    except SCIMUser.DoesNotExist:
        return  # Silently ignore non-existent members
    scim_obj.group.user_set.remove(scim_user.user)


@transaction.atomic
def apply_patch_operations(
    scim_obj: SCIMUser | SCIMGroup,
    operations: list[dict[str, Any]],
    adapter: BaseUserAdapter | BaseGroupAdapter,
) -> SCIMUser | SCIMGroup:
    """Apply a list of SCIM PATCH operations to a resource."""
    for operation in operations:
        op = operation.get("op", "").lower()
        if op not in ("add", "remove", "replace"):
            raise BadRequestError(f"Unsupported PATCH op: {op}")

        path = operation.get("path")
        value = operation.get("value")

        if isinstance(scim_obj, SCIMUser):
            _apply_user_op(scim_obj, op, path, value)
        else:
            _apply_group_op(scim_obj, op, path, value)

    # Save all changes
    if isinstance(scim_obj, SCIMUser):
        scim_obj.user.save()
        scim_obj.save()
    else:
        scim_obj.group.save()
        scim_obj.save()

    return scim_obj
