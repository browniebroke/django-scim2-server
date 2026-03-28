"""SCIM 2.0 constants: schema URNs, content types, and discovery payloads."""

from __future__ import annotations

from scim2_models import (
    Attribute,
    AuthenticationScheme,
    Bulk,
    ChangePassword,
    ETag,
    Filter,
    Meta,
    Patch,
    ResourceType,
    Schema,
    ServiceProviderConfig,
    Sort,
)

SCIM_CONTENT_TYPE = "application/scim+json"

# Schema URNs
URN_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
URN_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
URN_LIST_RESPONSE = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
URN_PATCH_OP = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
URN_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
URN_SERVICE_PROVIDER_CONFIG = (
    "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
)
URN_RESOURCE_TYPE = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
URN_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"

SERVICE_PROVIDER_CONFIG = ServiceProviderConfig(
    documentation_uri="https://tools.ietf.org/html/rfc7644",
    patch=Patch(supported=True),
    bulk=Bulk(supported=False, max_operations=0, max_payload_size=0),
    filter=Filter(supported=True, max_results=200),
    change_password=ChangePassword(supported=False),
    sort=Sort(supported=False),
    etag=ETag(supported=False),
    authentication_schemes=[
        AuthenticationScheme(
            type="oauthbearertoken",
            name="OAuth Bearer Token",
            description=("Authentication scheme using the OAuth Bearer Token Standard"),
            spec_uri="https://tools.ietf.org/html/rfc6750",
        ),
    ],
)

RESOURCE_TYPE_USER = ResourceType(
    id="User",
    name="User",
    endpoint="/Users",
    description="User Account",
    schema_=URN_USER,
)

RESOURCE_TYPE_GROUP = ResourceType(
    id="Group",
    name="Group",
    endpoint="/Groups",
    description="Group",
    schema_=URN_GROUP,
)

SCHEMA_USER = Schema(
    id=URN_USER,
    name="User",
    description="User Account",
    attributes=[
        Attribute(
            name="userName",
            type="string",
            multi_valued=False,
            required=True,
            case_exact=False,
            mutability="readWrite",
            returned="default",
            uniqueness="server",
        ),
        Attribute(
            name="name",
            type="complex",
            multi_valued=False,
            required=False,
            mutability="readWrite",
            returned="default",
            sub_attributes=[
                Attribute(
                    name="givenName",
                    type="string",
                    multi_valued=False,
                    required=False,
                    mutability="readWrite",
                    returned="default",
                ),
                Attribute(
                    name="familyName",
                    type="string",
                    multi_valued=False,
                    required=False,
                    mutability="readWrite",
                    returned="default",
                ),
            ],
        ),
        Attribute(
            name="emails",
            type="complex",
            multi_valued=True,
            required=False,
            mutability="readWrite",
            returned="default",
            sub_attributes=[
                Attribute(
                    name="value",
                    type="string",
                    multi_valued=False,
                    required=False,
                    mutability="readWrite",
                    returned="default",
                ),
                Attribute(
                    name="primary",
                    type="boolean",
                    multi_valued=False,
                    required=False,
                    mutability="readWrite",
                    returned="default",
                ),
            ],
        ),
        Attribute(
            name="active",
            type="boolean",
            multi_valued=False,
            required=False,
            mutability="readWrite",
            returned="default",
        ),
        Attribute(
            name="externalId",
            type="string",
            multi_valued=False,
            required=False,
            case_exact=True,
            mutability="readWrite",
            returned="default",
        ),
    ],
    meta=Meta(
        resource_type="Schema",
        location="/Schemas/" + URN_USER,
    ),
)

SCHEMA_GROUP = Schema(
    id=URN_GROUP,
    name="Group",
    description="Group",
    attributes=[
        Attribute(
            name="displayName",
            type="string",
            multi_valued=False,
            required=True,
            mutability="readWrite",
            returned="default",
        ),
        Attribute(
            name="members",
            type="complex",
            multi_valued=True,
            required=False,
            mutability="readWrite",
            returned="default",
            sub_attributes=[
                Attribute(
                    name="value",
                    type="string",
                    multi_valued=False,
                    required=False,
                    mutability="immutable",
                    returned="default",
                ),
                Attribute(
                    name="display",
                    type="string",
                    multi_valued=False,
                    required=False,
                    mutability="immutable",
                    returned="default",
                ),
            ],
        ),
        Attribute(
            name="externalId",
            type="string",
            multi_valued=False,
            required=False,
            case_exact=True,
            mutability="readWrite",
            returned="default",
        ),
    ],
    meta=Meta(
        resource_type="Schema",
        location="/Schemas/" + URN_GROUP,
    ),
)
