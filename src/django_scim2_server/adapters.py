"""SCIM 2.0 adapters mapping between SCIM JSON and Django models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.urls import reverse
from pydantic import ValidationError
from scim2_models import Email, GroupMember, Meta, Name
from scim2_models import Group as SCIMGroupModel
from scim2_models import User as SCIMUserModel

from django_scim2_server.exceptions import BadRequestError, ConflictError
from django_scim2_server.models import SCIMGroup, SCIMUser

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet
    from django.http import HttpRequest

    from django_scim2_server.context import SCIMContext


def _uuids(values: Iterable[Any]) -> list[UUID]:
    """Keep only the values that are well-formed UUIDs."""
    parsed = []
    for value in values:
        try:
            parsed.append(UUID(str(value)))
        except (AttributeError, TypeError, ValueError):
            continue
    return parsed


class BaseAdapter:
    """Behaviour shared by the user and group adapters."""

    filter_map: ClassVar[dict[str, str]] = {}
    """Maps SCIM filter attribute names to ORM lookup paths."""

    detail_url_name: ClassVar[str] = ""
    """Name of the detail URL pattern, used to build ``meta.location``."""

    def __init__(self, context: SCIMContext) -> None:
        self.context = context

    @property
    def config_name(self) -> str:
        """Name of the configuration serving the current request."""
        return self.context.config.name

    @property
    def scope(self) -> str:
        """Tenant key for the current request, empty when unscoped."""
        return self.context.scope

    def context_filters(self) -> dict[str, str]:
        """ORM filters partitioning resources by configuration and tenant."""
        return {"config": self.config_name, "scope": self.scope}

    def build_location(self, request: HttpRequest, scim_id: str) -> str:
        """Build the absolute URL of a resource, on the mount serving the request."""
        kwargs: dict[str, str] = {"scim_id": scim_id}
        scope_kwarg = self.context.config.scope_url_kwarg
        if scope_kwarg is not None:
            kwargs[scope_kwarg] = self.scope
        path = reverse(f"{self.config_name}:{self.detail_url_name}", kwargs=kwargs)
        return request.build_absolute_uri(path)


class BaseUserAdapter(BaseAdapter):
    """Base adapter for mapping SCIM User resources to Django models."""

    detail_url_name: ClassVar[str] = "users-detail"

    def get_queryset(self) -> QuerySet[SCIMUser]:
        """Return the base queryset for SCIM users, scoped to the request."""
        return SCIMUser.objects.filter(**self.context_filters()).select_related("user")

    def to_scim(self, scim_obj: SCIMUser, request: HttpRequest) -> SCIMUserModel:
        """Convert a SCIMUser instance to a SCIM User model."""
        raise NotImplementedError

    def from_scim(
        self,
        data: dict[str, Any],
        scim_obj: SCIMUser | None = None,
    ) -> SCIMUser:
        """Create or update a SCIMUser from SCIM JSON data."""
        raise NotImplementedError

    def delete(self, scim_obj: SCIMUser) -> None:
        """Handle SCIM DELETE for a user (deactivate by default)."""
        raise NotImplementedError

    def patch(
        self,
        scim_obj: SCIMUser,
        operations: list[dict[str, Any]],
    ) -> SCIMUser:
        """Apply SCIM PATCH operations to a user."""
        from django_scim2_server.patch import apply_patch_operations

        return apply_patch_operations(scim_obj, operations, self)

    def apply_patch_operation(
        self,
        scim_obj: SCIMUser,
        op: str,
        path: str | None,
        value: Any,
    ) -> None:
        """Apply a single SCIM PATCH operation to a user, without saving."""
        raise NotImplementedError

    def save_patched(self, scim_obj: SCIMUser) -> None:
        """Persist a user after a run of PATCH operations."""
        raise NotImplementedError


class BaseGroupAdapter(BaseAdapter):
    """Base adapter for mapping SCIM Group resources to Django models."""

    detail_url_name: ClassVar[str] = "groups-detail"

    def get_queryset(self) -> QuerySet[SCIMGroup]:
        """Return the base queryset for SCIM groups, scoped to the request."""
        return SCIMGroup.objects.filter(**self.context_filters()).select_related(
            "group"
        )

    def get_user_queryset(self) -> QuerySet[SCIMUser]:
        """
        Return the SCIM users that may be referenced as members.

        Delegates to the configuration's user adapter so that a project overriding
        user scoping only has to do it in one place.
        """
        return self.context.config.user_adapter(self.context).get_queryset()

    def to_scim(self, scim_obj: SCIMGroup, request: HttpRequest) -> SCIMGroupModel:
        """Convert a SCIMGroup instance to a SCIM Group model."""
        raise NotImplementedError

    def from_scim(
        self,
        data: dict[str, Any],
        scim_obj: SCIMGroup | None = None,
    ) -> SCIMGroup:
        """Create or update a SCIMGroup from SCIM JSON data."""
        raise NotImplementedError

    def delete(self, scim_obj: SCIMGroup) -> None:
        """Handle SCIM DELETE for a group."""
        raise NotImplementedError

    def patch(
        self,
        scim_obj: SCIMGroup,
        operations: list[dict[str, Any]],
    ) -> SCIMGroup:
        """Apply SCIM PATCH operations to a group."""
        from django_scim2_server.patch import apply_patch_operations

        return apply_patch_operations(scim_obj, operations, self)

    def apply_patch_operation(
        self,
        scim_obj: SCIMGroup,
        op: str,
        path: str | None,
        value: Any,
    ) -> None:
        """Apply a single SCIM PATCH operation to a group, without saving."""
        raise NotImplementedError

    def save_patched(self, scim_obj: SCIMGroup) -> None:
        """Persist a group after a run of PATCH operations."""
        raise NotImplementedError


class DefaultUserAdapter(BaseUserAdapter):
    """Default adapter mapping SCIM Users to ``django.contrib.auth.User``."""

    filter_map: ClassVar[dict[str, str]] = {
        "userName": "scim_username",
        "name.givenName": "user__first_name",
        "name.familyName": "user__last_name",
        "emails.value": "user__email",
        "active": "active",
        "externalId": "external_id",
    }

    def get_django_username(self, scim_username: str) -> str:
        """
        Derive the Django ``username`` from the SCIM ``userName``.

        ``auth.User.username`` is unique across the whole table, so two tenants
        provisioning the same ``userName`` would collide. Namespacing by tenant keeps
        them apart. Unscoped configurations are left untouched.

        Override this to choose a different mapping, for instance if your user model
        drops the global uniqueness constraint.
        """
        if self.scope:
            return f"{self.scope}:{scim_username}"
        return scim_username

    def to_scim(self, scim_obj: SCIMUser, request: HttpRequest) -> SCIMUserModel:
        """Convert a SCIMUser to a SCIM User pydantic model."""
        user = scim_obj.user
        return SCIMUserModel(
            id=str(scim_obj.id),
            external_id=scim_obj.external_id or None,
            user_name=scim_obj.scim_username,
            name=Name(
                given_name=user.first_name,
                family_name=user.last_name,
            ),
            emails=[Email(value=user.email, primary=True)] if user.email else None,
            active=scim_obj.active,
            meta=Meta(
                resource_type="User",
                created=scim_obj.created,
                last_modified=scim_obj.last_modified,
                location=self.build_location(request, str(scim_obj.id)),
            ),
        )

    @transaction.atomic
    def from_scim(
        self,
        data: dict[str, Any],
        scim_obj: SCIMUser | None = None,
    ) -> SCIMUser:
        """Create or update a SCIMUser from SCIM JSON data."""
        try:
            scim_user = SCIMUserModel.model_validate(data)
        except ValidationError as exc:
            raise BadRequestError(str(exc)) from exc

        user_name = scim_user.user_name
        if not user_name:
            raise BadRequestError("userName is required")

        name = scim_user.name or Name()
        emails = scim_user.emails or []
        email = str(emails[0].value) if emails and emails[0].value else ""
        external_id = scim_user.external_id or ""
        active = scim_user.active if scim_user.active is not None else True

        user_model = get_user_model()
        django_username = self.get_django_username(user_name)

        if scim_obj is None:
            # Create
            if self.get_queryset().filter(scim_username=user_name).exists():
                raise ConflictError(f"User with userName '{user_name}' already exists")
            try:
                user = user_model.objects.create(
                    username=django_username,
                    first_name=name.given_name or "",
                    last_name=name.family_name or "",
                    email=email,
                    is_active=active,
                )
                scim_obj = SCIMUser.objects.create(
                    **self.context_filters(),
                    user=user,
                    scim_username=user_name,
                    external_id=external_id,
                    active=active,
                )
            except IntegrityError as exc:
                raise ConflictError(
                    f"User with userName '{user_name}' already exists"
                ) from exc
        else:
            # Update
            if (
                user_name != scim_obj.scim_username
                and self.get_queryset()
                .filter(scim_username=user_name)
                .exclude(pk=scim_obj.pk)
                .exists()
            ):
                raise ConflictError(
                    f"User with userName '{user_name}' already exists",
                )
            user = scim_obj.user
            user.username = django_username
            user.first_name = name.given_name or ""
            user.last_name = name.family_name or ""
            user.email = email
            user.is_active = active
            user.save()

            scim_obj.scim_username = user_name
            scim_obj.external_id = external_id
            scim_obj.active = active
            scim_obj.save()

        return scim_obj

    @transaction.atomic
    def delete(self, scim_obj: SCIMUser) -> None:
        """
        Deactivate the user rather than deleting.

        The Django user is only deactivated once no other configuration or tenant
        still has an active SCIM record for them, so one tenant deprovisioning a
        person cannot lock them out of another.
        """
        scim_obj.active = False
        scim_obj.save(update_fields=["active", "last_modified"])
        active_elsewhere = (
            SCIMUser.objects.filter(user=scim_obj.user, active=True)
            .exclude(pk=scim_obj.pk)
            .exists()
        )
        if not active_elsewhere:
            scim_obj.user.is_active = False
            scim_obj.user.save(update_fields=["is_active"])

    def apply_patch_operation(
        self,
        scim_obj: SCIMUser,
        op: str,
        path: str | None,
        value: Any,
    ) -> None:
        """Apply a single SCIM PATCH operation to a user, without saving."""
        user = scim_obj.user

        if path is None and op in ("add", "replace") and isinstance(value, dict):
            # Bulk update: value is a dict of attributes
            for key, val in value.items():
                self._set_attr(scim_obj, user, key, val)
            return

        if path is None:
            raise BadRequestError("path is required for this operation")

        if op in ("add", "replace"):
            self._set_attr(scim_obj, user, path, value)
        elif op == "remove":
            self._remove_attr(scim_obj, user, path)
        else:
            raise BadRequestError(f"Unsupported PATCH op: {op}")

    def _set_attr(
        self,
        scim_obj: SCIMUser,
        user: Any,
        path: str,
        value: Any,
    ) -> None:
        """Set a single user attribute by SCIM path."""
        if path == "userName":
            user.username = self.get_django_username(value)
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

    def _remove_attr(self, scim_obj: SCIMUser, user: Any, path: str) -> None:
        """Remove (clear) a user attribute by SCIM path."""
        if path == "name.givenName":
            user.first_name = ""
        elif path == "name.familyName":
            user.last_name = ""
        elif path == "emails":
            user.email = ""
        elif path == "externalId":
            scim_obj.external_id = ""

    def save_patched(self, scim_obj: SCIMUser) -> None:
        """Persist a user after a run of PATCH operations."""
        scim_obj.user.save()
        scim_obj.save()


class DefaultGroupAdapter(BaseGroupAdapter):
    """Default adapter mapping SCIM Groups to ``django.contrib.auth.Group``."""

    filter_map: ClassVar[dict[str, str]] = {
        "displayName": "display_name",
        "externalId": "external_id",
    }

    def get_django_group_name(self, display_name: str) -> str:
        """
        Derive the Django ``Group.name`` from the SCIM ``displayName``.

        ``auth.Group.name`` is unique across the whole table, so two tenants
        provisioning the same ``displayName`` would collide. Namespacing by tenant
        keeps them apart. Unscoped configurations are left untouched.
        """
        if self.scope:
            return f"{self.scope}:{display_name}"
        return display_name

    def to_scim(self, scim_obj: SCIMGroup, request: HttpRequest) -> SCIMGroupModel:
        """Convert a SCIMGroup to a SCIM Group pydantic model."""
        members = [
            GroupMember(value=str(scim_user.id), display=scim_user.scim_username)
            for scim_user in self.get_member_queryset(scim_obj)
        ]
        return SCIMGroupModel(
            id=str(scim_obj.id),
            external_id=scim_obj.external_id or None,
            display_name=scim_obj.display_name,
            members=members,
            meta=Meta(
                resource_type="Group",
                created=scim_obj.created,
                last_modified=scim_obj.last_modified,
                location=self.build_location(request, str(scim_obj.id)),
            ),
        )

    def get_member_queryset(self, scim_obj: SCIMGroup) -> QuerySet[SCIMUser]:
        """Return the SCIM users that are members of ``scim_obj``."""
        return self.get_user_queryset().filter(
            user__in=scim_obj.group.user_set.all(),
        )

    @transaction.atomic
    def from_scim(
        self,
        data: dict[str, Any],
        scim_obj: SCIMGroup | None = None,
    ) -> SCIMGroup:
        """Create or update a SCIMGroup from SCIM JSON data."""
        try:
            scim_group = SCIMGroupModel.model_validate(data)
        except ValidationError as exc:
            raise BadRequestError(str(exc)) from exc

        display_name = scim_group.display_name
        if not display_name:
            raise BadRequestError("displayName is required")

        external_id = scim_group.external_id or ""
        django_group_name = self.get_django_group_name(display_name)

        if scim_obj is None:
            # Create
            try:
                group = Group.objects.create(name=django_group_name)
                scim_obj = SCIMGroup.objects.create(
                    **self.context_filters(),
                    group=group,
                    display_name=display_name,
                    external_id=external_id,
                )
            except IntegrityError as exc:
                raise ConflictError(
                    f"Group with displayName '{display_name}' already exists"
                ) from exc
        else:
            # Update
            scim_obj.group.name = django_group_name
            scim_obj.group.save()
            scim_obj.display_name = display_name
            scim_obj.external_id = external_id
            scim_obj.save()

        # Handle members
        self._sync_members(scim_obj, scim_group.members or [])

        return scim_obj

    def resolve_members(self, member_ids: Iterable[Any]) -> list[Any]:
        """
        Resolve SCIM member references to Django users.

        References that are malformed, or that do not exist within the current
        configuration and tenant, are ignored — so a member list can never reach
        across tenants.
        """
        parsed = _uuids(member_ids)
        if not parsed:
            return []
        return [
            scim_user.user
            for scim_user in self.get_user_queryset().filter(id__in=parsed)
        ]

    def _sync_members(
        self,
        scim_obj: SCIMGroup,
        members: list[GroupMember],
    ) -> None:
        """Sync group membership from SCIM members list."""
        if not members:
            scim_obj.group.user_set.clear()
            return

        scim_obj.group.user_set.set(
            self.resolve_members(member.value for member in members)
        )

    @transaction.atomic
    def delete(self, scim_obj: SCIMGroup) -> None:
        """
        Delete the group and its SCIM metadata.

        The Django group is only deleted once no other configuration or tenant still
        references it.
        """
        group = scim_obj.group
        scim_obj.delete()
        if not SCIMGroup.objects.filter(group=group).exists():
            group.delete()

    def apply_patch_operation(
        self,
        scim_obj: SCIMGroup,
        op: str,
        path: str | None,
        value: Any,
    ) -> None:
        """Apply a single SCIM PATCH operation to a group, without saving."""
        from django_scim2_server.patch import parse_member_filter

        if path is None and op in ("add", "replace") and isinstance(value, dict):
            for key, val in value.items():
                self.apply_patch_operation(scim_obj, op, key, val)
            return

        if path is None:
            raise BadRequestError("path is required for this operation")

        if path == "displayName" and op in ("add", "replace"):
            scim_obj.display_name = value
            scim_obj.group.name = self.get_django_group_name(value)
        elif path == "externalId" and op in ("add", "replace"):
            scim_obj.external_id = value or ""
        elif path == "members" and op == "add":
            scim_obj.group.user_set.add(*self._member_users(value))
        elif path == "members" and op == "replace":
            scim_obj.group.user_set.set(self._member_users(value))
        elif path == "members" and op == "remove":
            scim_obj.group.user_set.remove(*self._member_users(value))
        elif path.startswith("members[") and op == "remove":
            member_id = parse_member_filter(path)
            users = [
                scim_user.user
                for scim_user in self.get_user_queryset().filter(id=member_id)
            ]
            scim_obj.group.user_set.remove(*users)
        elif path == "externalId" and op == "remove":
            scim_obj.external_id = ""
        else:
            raise BadRequestError(f"Unsupported PATCH path: {path}")

    def _member_users(self, value: Any) -> list[Any]:
        """Resolve a raw PATCH ``members`` value to Django users."""
        if not isinstance(value, list):
            raise BadRequestError("members value must be a list")
        return self.resolve_members(
            item["value"]
            for item in value
            if isinstance(item, dict) and "value" in item
        )

    def save_patched(self, scim_obj: SCIMGroup) -> None:
        """Persist a group after a run of PATCH operations."""
        scim_obj.group.save()
        scim_obj.save()
