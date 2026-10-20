"""An organisation-scoped SCIM mount, exercising the per-mount configuration."""

from __future__ import annotations

from typing import Any, ClassVar

from django.http import HttpRequest
from pydantic import ValidationError
from scim2_models import Email, EnterpriseUser, Meta, Name, Schema
from scim2_models import User as SCIMUserModel

from django_scim2_server.adapters import BaseUserAdapter, build_location
from django_scim2_server.auth import get_bearer_token
from django_scim2_server.constants import (
    RESOURCE_TYPE_USER_WITH_ENTERPRISE,
    SCHEMA_ENTERPRISE_USER,
    SCHEMA_USER,
)
from django_scim2_server.exceptions import BadRequestError, ConflictError
from tests.testapp.models import Member, Organisation


def organisation_token_auth(request: HttpRequest) -> bool:
    token = get_bearer_token(request)
    organisation = (
        Organisation.objects.filter(scim_token=token).first() if token else None
    )
    request.scim_organisation = organisation  # type: ignore[attr-defined]
    return organisation is not None


class MemberAdapter(BaseUserAdapter):
    resource_type = RESOURCE_TYPE_USER_WITH_ENTERPRISE
    schemas: ClassVar[list[Schema]] = [SCHEMA_USER, SCHEMA_ENTERPRISE_USER]
    filter_map: ClassVar[dict[str, str]] = {"userName": "email"}
    lookup_field = "uuid"

    @property
    def organisation(self) -> Organisation:
        return self.request.scim_organisation  # type: ignore[union-attr]

    def get_queryset(self) -> Any:
        return Member.objects.filter(organisation=self.organisation)

    def to_scim(self, member: Member, request: HttpRequest) -> SCIMUserModel[Any]:
        resource = SCIMUserModel[EnterpriseUser](
            id=str(member.uuid),
            user_name=member.email,
            name=Name(given_name=member.given_name, family_name=member.family_name),
            emails=[Email(value=member.email, type="work", primary=True)],
            active=member.active,
            meta=Meta(
                resource_type="User",
                location=build_location(request, "Users", str(member.uuid)),
            ),
        )
        resource[EnterpriseUser] = EnterpriseUser(department=member.department or None)
        return resource

    def from_scim(self, data: dict[str, Any], member: Member | None = None) -> Member:
        try:
            resource = SCIMUserModel[EnterpriseUser].model_validate(data)
        except ValidationError as exc:
            raise BadRequestError(str(exc)) from exc
        if not resource.user_name:
            raise BadRequestError("userName is required")
        duplicates = self.get_queryset().filter(email__iexact=resource.user_name)
        if member is not None:
            duplicates = duplicates.exclude(pk=member.pk)
        if duplicates.exists():
            raise ConflictError(
                f"User with userName '{resource.user_name}' already exists"
            )

        member = member or Member(organisation=self.organisation)
        name = resource.name or Name()
        enterprise = resource[EnterpriseUser] or EnterpriseUser()
        member.email = resource.user_name
        member.given_name = name.given_name or ""
        member.family_name = name.family_name or ""
        member.department = enterprise.department or ""
        member.active = resource.active if resource.active is not None else True
        member.save()
        return member

    def delete(self, member: Member) -> None:
        member.active = False
        member.save(update_fields=["active"])
