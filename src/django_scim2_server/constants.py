"""SCIM 2.0 constants: schema URNs, content types, and discovery payloads."""

from __future__ import annotations

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

SERVICE_PROVIDER_CONFIG: dict[str, object] = {
    "schemas": [URN_SERVICE_PROVIDER_CONFIG],
    "documentationUri": "https://tools.ietf.org/html/rfc7644",
    "patch": {"supported": True},
    "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
    "filter": {"supported": True, "maxResults": 200},
    "changePassword": {"supported": False},
    "sort": {"supported": False},
    "etag": {"supported": False},
    "authenticationSchemes": [
        {
            "type": "oauthbearertoken",
            "name": "OAuth Bearer Token",
            "description": (
                "Authentication scheme using the OAuth Bearer Token Standard"
            ),
            "specUri": "https://tools.ietf.org/html/rfc6750",
        },
    ],
}

RESOURCE_TYPE_USER: dict[str, object] = {
    "schemas": [URN_RESOURCE_TYPE],
    "id": "User",
    "name": "User",
    "endpoint": "/Users",
    "description": "User Account",
    "schema": URN_USER,
}

RESOURCE_TYPE_GROUP: dict[str, object] = {
    "schemas": [URN_RESOURCE_TYPE],
    "id": "Group",
    "name": "Group",
    "endpoint": "/Groups",
    "description": "Group",
    "schema": URN_GROUP,
}

SCHEMA_USER: dict[str, object] = {
    "id": URN_USER,
    "name": "User",
    "description": "User Account",
    "attributes": [
        {
            "name": "userName",
            "type": "string",
            "multiValued": False,
            "required": True,
            "caseExact": False,
            "mutability": "readWrite",
            "returned": "default",
            "uniqueness": "server",
        },
        {
            "name": "name",
            "type": "complex",
            "multiValued": False,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
            "subAttributes": [
                {
                    "name": "givenName",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                },
                {
                    "name": "familyName",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                },
            ],
        },
        {
            "name": "emails",
            "type": "complex",
            "multiValued": True,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
            "subAttributes": [
                {
                    "name": "value",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                },
                {
                    "name": "primary",
                    "type": "boolean",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                },
            ],
        },
        {
            "name": "active",
            "type": "boolean",
            "multiValued": False,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
        },
        {
            "name": "externalId",
            "type": "string",
            "multiValued": False,
            "required": False,
            "caseExact": True,
            "mutability": "readWrite",
            "returned": "default",
        },
    ],
    "meta": {
        "resourceType": "Schema",
        "location": "/Schemas/" + URN_USER,
    },
}

SCHEMA_GROUP: dict[str, object] = {
    "id": URN_GROUP,
    "name": "Group",
    "description": "Group",
    "attributes": [
        {
            "name": "displayName",
            "type": "string",
            "multiValued": False,
            "required": True,
            "mutability": "readWrite",
            "returned": "default",
        },
        {
            "name": "members",
            "type": "complex",
            "multiValued": True,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
            "subAttributes": [
                {
                    "name": "value",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "immutable",
                    "returned": "default",
                },
                {
                    "name": "display",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "immutable",
                    "returned": "default",
                },
            ],
        },
        {
            "name": "externalId",
            "type": "string",
            "multiValued": False,
            "required": False,
            "caseExact": True,
            "mutability": "readWrite",
            "returned": "default",
        },
    ],
    "meta": {
        "resourceType": "Schema",
        "location": "/Schemas/" + URN_GROUP,
    },
}
