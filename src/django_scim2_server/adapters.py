"""SCIM 2.0 adapters mapping between SCIM JSON and Django models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from pydantic import ValidationError
from scim2_models import Email, GroupMember, Meta, Name
from scim2_models import Group as SCIMGroupModel
from scim2_models import User as SCIMUserModel

from django_scim2_server.exceptions import BadRequestError, ConflictError
from django_scim2_server.models import SCIMGroup, SCIMUser

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


class BaseUserAdapter:
    """Base adapter for mapping SCIM User resources to Django models."""

    filter_map: ClassVar[dict[str, str]] = {}

    def get_queryset(self) -> QuerySet[SCIMUser]:
        """Return the base queryset for SCIM users."""
        return SCIMUser.objects.select_related("user")

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
        raise NotImplementedError


class BaseGroupAdapter:
    """Base adapter for mapping SCIM Group resources to Django models."""

    filter_map: ClassVar[dict[str, str]] = {}

    def get_queryset(self) -> QuerySet[SCIMGroup]:
        """Return the base queryset for SCIM groups."""
        return SCIMGroup.objects.select_related("group")

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
        raise NotImplementedError


def _build_location(request: HttpRequest, endpoint: str, scim_id: str) -> str:
    """Build the full URL for a SCIM resource."""
    base = request.build_absolute_uri("/").rstrip("/")
    return f"{base}/scim/v2/{endpoint}/{scim_id}"


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

    def to_scim(self, scim_obj: SCIMUser, request: HttpRequest) -> SCIMUserModel:
        """Convert a SCIMUser to a SCIM User pydantic model."""
        user = scim_obj.user
        location = _build_location(request, "Users", str(scim_obj.id))
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
                location=location,
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

        if scim_obj is None:
            # Create
            if SCIMUser.objects.filter(scim_username=user_name).exists():
                raise ConflictError(f"User with userName '{user_name}' already exists")
            user = user_model.objects.create(
                username=user_name,
                first_name=name.given_name or "",
                last_name=name.family_name or "",
                email=email,
                is_active=active,
            )
            scim_obj = SCIMUser.objects.create(
                user=user,
                scim_username=user_name,
                external_id=external_id,
                active=active,
            )
        else:
            # Update
            if user_name != scim_obj.scim_username:
                if (
                    SCIMUser.objects.filter(scim_username=user_name)
                    .exclude(
                        pk=scim_obj.pk,
                    )
                    .exists()
                ):
                    raise ConflictError(
                        f"User with userName '{user_name}' already exists",
                    )
            user = scim_obj.user
            user.username = user_name
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

    def delete(self, scim_obj: SCIMUser) -> None:
        """Deactivate the user rather than deleting."""
        scim_obj.active = False
        scim_obj.save(update_fields=["active", "last_modified"])
        scim_obj.user.is_active = False
        scim_obj.user.save(update_fields=["is_active"])

    def patch(
        self,
        scim_obj: SCIMUser,
        operations: list[dict[str, Any]],
    ) -> SCIMUser:
        """Apply SCIM PATCH operations to a user."""
        from django_scim2_server.patch import apply_patch_operations

        return apply_patch_operations(scim_obj, operations, self)


class DefaultGroupAdapter(BaseGroupAdapter):
    """Default adapter mapping SCIM Groups to ``django.contrib.auth.Group``."""

    filter_map: ClassVar[dict[str, str]] = {
        "displayName": "display_name",
        "externalId": "external_id",
    }

    def to_scim(self, scim_obj: SCIMGroup, request: HttpRequest) -> SCIMGroupModel:
        """Convert a SCIMGroup to a SCIM Group pydantic model."""
        location = _build_location(request, "Groups", str(scim_obj.id))
        members = []
        for user in scim_obj.group.user_set.select_related("scim").all():
            scim_user = getattr(user, "scim", None)
            if scim_user:
                members.append(
                    GroupMember(
                        value=str(scim_user.id),
                        display=scim_user.scim_username,
                    ),
                )
        return SCIMGroupModel(
            id=str(scim_obj.id),
            external_id=scim_obj.external_id or None,
            display_name=scim_obj.display_name,
            members=members,
            meta=Meta(
                resource_type="Group",
                created=scim_obj.created,
                last_modified=scim_obj.last_modified,
                location=location,
            ),
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

        if scim_obj is None:
            # Create
            group = Group.objects.create(name=display_name)
            scim_obj = SCIMGroup.objects.create(
                group=group,
                display_name=display_name,
                external_id=external_id,
            )
        else:
            # Update
            scim_obj.group.name = display_name
            scim_obj.group.save()
            scim_obj.display_name = display_name
            scim_obj.external_id = external_id
            scim_obj.save()

        # Handle members
        self._sync_members(scim_obj, scim_group.members or [])

        return scim_obj

    def _sync_members(
        self,
        scim_obj: SCIMGroup,
        members: list[GroupMember],
    ) -> None:
        """Sync group membership from SCIM members list."""
        if not members:
            scim_obj.group.user_set.clear()
            return

        member_ids = [str(m.value) for m in members if m.value]
        scim_users = SCIMUser.objects.filter(id__in=member_ids).select_related("user")
        users = [su.user for su in scim_users]
        scim_obj.group.user_set.set(users)

    def delete(self, scim_obj: SCIMGroup) -> None:
        """Delete the group and its SCIM metadata."""
        group = scim_obj.group
        scim_obj.delete()
        group.delete()

    def patch(
        self,
        scim_obj: SCIMGroup,
        operations: list[dict[str, Any]],
    ) -> SCIMGroup:
        """Apply SCIM PATCH operations to a group."""
        from django_scim2_server.patch import apply_patch_operations

        return apply_patch_operations(scim_obj, operations, self)
