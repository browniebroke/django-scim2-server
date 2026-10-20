"""SCIM 2.0 adapters mapping between SCIM JSON and Django models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.urls import NoReverseMatch, reverse
from pydantic import ValidationError
from scim2_models import (
    Email,
    EnterpriseUser,
    GroupMember,
    Meta,
    Name,
    Resource,
    ResourceType,
    Schema,
)
from scim2_models import Group as SCIMGroupModel
from scim2_models import User as SCIMUserModel

from django_scim2_server.constants import (
    RESOURCE_TYPE_GROUP,
    RESOURCE_TYPE_USER,
    SCHEMA_GROUP,
    SCHEMA_USER,
)
from django_scim2_server.exceptions import BadRequestError, ConflictError, NotFoundError
from django_scim2_server.models import SCIMGroup, SCIMUser
from django_scim2_server.resource_patch import apply_patch_to_resource

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


class BaseAdapter:
    """
    Common behaviour for SCIM resource adapters.

    An adapter is instantiated once per request, so ``self.request`` (and
    anything an auth check attached to it) can be used to scope queries.
    """

    filter_map: ClassVar[dict[str, str]] = {}
    lookup_field: ClassVar[str] = "id"
    """Model field holding the SCIM ``id``."""
    resource_type: ClassVar[ResourceType]
    schemas: ClassVar[list[Schema]]

    def __init__(self, request: HttpRequest | None = None) -> None:
        self.request = request

    def get_queryset(self) -> QuerySet[Any]:
        """Return the base queryset, scoped to what this request may see."""
        raise NotImplementedError

    def get_object(self, scim_id: str) -> Any:
        """Return the object with SCIM ``id`` ``scim_id`` or raise NotFoundError."""
        try:
            return self.get_queryset().get(**{self.lookup_field: scim_id})
        except (ObjectDoesNotExist, ValueError, DjangoValidationError):
            raise NotFoundError(
                f"{self.resource_type.name} {scim_id} not found"
            ) from None

    def to_scim(self, scim_obj: Any, request: HttpRequest) -> Resource[Any]:
        """Convert an object to a SCIM resource model."""
        raise NotImplementedError

    def from_scim(self, data: dict[str, Any], scim_obj: Any | None = None) -> Any:
        """Create (``scim_obj`` is None) or fully replace an object from SCIM JSON."""
        raise NotImplementedError

    def delete(self, scim_obj: Any) -> None:
        """Handle SCIM DELETE."""
        raise NotImplementedError

    def patch(self, scim_obj: Any, operations: list[dict[str, Any]]) -> Any:
        """
        Apply SCIM PATCH operations.

        The resource is rendered with ``to_scim``, patched as JSON, then
        written back through ``from_scim``, so an adapter only has to
        implement the mapping once.
        """
        request = cast("HttpRequest", self.request)
        current = self.to_scim(scim_obj, request).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        patched = apply_patch_to_resource(current, operations)
        return self.from_scim(patched, scim_obj)


class BaseUserAdapter(BaseAdapter):
    """Base adapter for mapping SCIM User resources to Django models."""

    resource_type = RESOURCE_TYPE_USER
    schemas: ClassVar[list[Schema]] = [SCHEMA_USER]

    def get_queryset(self) -> QuerySet[Any]:
        """Return the base queryset for SCIM users."""
        return SCIMUser.objects.select_related("user")


class BaseGroupAdapter(BaseAdapter):
    """Base adapter for mapping SCIM Group resources to Django models."""

    resource_type = RESOURCE_TYPE_GROUP
    schemas: ClassVar[list[Schema]] = [SCHEMA_GROUP]

    def get_queryset(self) -> QuerySet[Any]:
        """Return the base queryset for SCIM groups."""
        return SCIMGroup.objects.select_related("group")


def build_location(request: HttpRequest, endpoint: str, scim_id: str) -> str:
    """
    Build the absolute URL of a SCIM resource.

    Resolves against the URL namespace the request came through, so the
    same views can be mounted more than once.
    """
    match = getattr(request, "resolver_match", None)
    if match is not None:
        prefix = f"{match.namespace}:" if match.namespace else ""
        url_name = f"{prefix}{endpoint.lower()}-detail"
        try:
            return request.build_absolute_uri(
                reverse(url_name, kwargs={"scim_id": scim_id})
            )
        except NoReverseMatch:
            pass
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

    def to_scim(self, scim_obj: SCIMUser, request: HttpRequest) -> SCIMUserModel[Any]:
        """Convert a SCIMUser to a SCIM User pydantic model."""
        user = scim_obj.user
        location = build_location(request, "Users", str(scim_obj.id))
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
            scim_user = SCIMUserModel[EnterpriseUser].model_validate(data)
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
        location = build_location(request, "Groups", str(scim_obj.id))
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
