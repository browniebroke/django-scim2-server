"""Tests for the generic, JSON-level SCIM PATCH engine."""

from __future__ import annotations

from typing import Any

import pytest

from django_scim2_server.exceptions import BadRequestError, SCIMError
from django_scim2_server.resource_patch import apply_patch_to_resource

URN_CORE = "urn:ietf:params:scim:schemas:core:2.0:User"
URN_ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"


def _user(**extra: Any) -> dict[str, Any]:
    return {
        "schemas": [URN_CORE],
        "id": "42",
        "userName": "jane@firm.example",
        "name": {"givenName": "Jane", "familyName": "Doe"},
        "emails": [{"value": "jane@firm.example", "type": "work", "primary": True}],
        "active": True,
        **extra,
    }


@pytest.mark.parametrize(
    ("operations", "expected"),
    [
        pytest.param(
            [{"op": "Replace", "path": "active", "value": "False"}],
            {"active": False},
            id="entra-capitalised-op-and-string-boolean",
        ),
        pytest.param(
            [{"op": "replace", "value": {"active": False}}],
            {"active": False},
            id="okta-deactivate-without-path",
        ),
        pytest.param(
            [{"op": "Replace", "value": {"name.givenName": "Janet", "active": "true"}}],
            {"name": {"givenName": "Janet", "familyName": "Doe"}, "active": True},
            id="entra-dotted-keys-in-pathless-value",
        ),
        pytest.param(
            [{"op": "replace", "path": "name", "value": {"familyName": "Smith"}}],
            {"name": {"givenName": "Jane", "familyName": "Smith"}},
            id="complex-replace-merges-sub-attributes",
        ),
        pytest.param(
            [
                {
                    "op": "replace",
                    "path": 'emails[type eq "work"].value',
                    "value": "j@x.io",
                }
            ],
            {"emails": [{"value": "j@x.io", "type": "work", "primary": True}]},
            id="filtered-sub-attribute-replace",
        ),
        pytest.param(
            [{"op": "replace", "path": "USERNAME", "value": "renamed"}],
            {"userName": "renamed"},
            id="attribute-names-are-case-insensitive",
        ),
        pytest.param(
            [{"op": "replace", "path": f"{URN_CORE}:userName", "value": "renamed"}],
            {"userName": "renamed"},
            id="core-urn-prefixed-path",
        ),
        pytest.param(
            [{"op": "remove", "path": "name.givenName"}],
            {"name": {"familyName": "Doe"}},
            id="remove-sub-attribute",
        ),
    ],
)
def test_applies_operations_to_user(
    operations: list[dict[str, Any]], expected: dict[str, Any]
) -> None:
    result = apply_patch_to_resource(_user(), operations)

    assert result == {**_user(), **expected}


def test_does_not_mutate_the_input_resource() -> None:
    resource = _user()

    apply_patch_to_resource(
        resource, [{"op": "replace", "path": "name.givenName", "value": "X"}]
    )

    assert resource == _user()


def test_filtered_path_without_a_match_appends_a_value() -> None:
    resource = _user(emails=[{"value": "old@x.io"}])

    result = apply_patch_to_resource(
        resource,
        [{"op": "add", "path": 'emails[type eq "work"].value', "value": "new@x.io"}],
    )

    assert result["emails"] == [
        {"value": "old@x.io"},
        {"type": "work", "value": "new@x.io"},
    ]


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(
            {"op": "Add", "path": f"{URN_ENTERPRISE}:department", "value": "Tax"},
            id="entra-urn-prefixed-path",
        ),
        pytest.param(
            {"op": "Add", "value": {f"{URN_ENTERPRISE}:department": "Tax"}},
            id="entra-urn-prefixed-key-without-path",
        ),
        pytest.param(
            {"op": "add", "path": URN_ENTERPRISE, "value": {"department": "Tax"}},
            id="okta-whole-extension-object",
        ),
    ],
)
def test_sets_enterprise_extension_attribute(operation: dict[str, Any]) -> None:
    resource = _user(schemas=[URN_CORE, URN_ENTERPRISE])

    result = apply_patch_to_resource(resource, [operation])

    assert result[URN_ENTERPRISE] == {"department": "Tax"}
    assert result["schemas"] == [URN_CORE, URN_ENTERPRISE]


def test_entra_manager_id_becomes_a_complex_value() -> None:
    result = apply_patch_to_resource(
        _user(schemas=[URN_CORE, URN_ENTERPRISE]),
        [{"op": "Add", "path": f"{URN_ENTERPRISE}:manager", "value": "m-1"}],
    )

    assert result[URN_ENTERPRISE] == {"manager": {"value": "m-1"}}


def test_registers_extension_schema_when_first_set() -> None:
    result = apply_patch_to_resource(
        _user(), [{"op": "add", "path": f"{URN_ENTERPRISE}:department", "value": "Tax"}]
    )

    assert result["schemas"] == [URN_CORE, URN_ENTERPRISE]
    assert result[URN_ENTERPRISE] == {"department": "Tax"}


@pytest.mark.parametrize(
    ("operation", "expected_members"),
    [
        pytest.param(
            {"op": "add", "path": "members", "value": [{"value": "2"}, {"value": "1"}]},
            [{"value": "1"}, {"value": "2"}],
            id="add-skips-existing-members",
        ),
        pytest.param(
            {"op": "Remove", "path": "members", "value": [{"value": "1"}]},
            [],
            id="entra-remove-with-value-list",
        ),
        pytest.param(
            {"op": "remove", "path": 'members[value eq "1"]'},
            [],
            id="okta-remove-with-filter",
        ),
        pytest.param(
            {"op": "replace", "path": "members", "value": [{"value": "3"}]},
            [{"value": "3"}],
            id="replace-members",
        ),
        pytest.param(
            {"op": "add", "value": {"members": [{"value": "2"}]}},
            [{"value": "1"}, {"value": "2"}],
            id="add-members-without-path",
        ),
    ],
)
def test_applies_member_operations_to_group(
    operation: dict[str, Any], expected_members: list[dict[str, Any]]
) -> None:
    group = {"displayName": "Tax", "members": [{"value": "1"}]}

    result = apply_patch_to_resource(group, [operation])

    assert result["members"] == expected_members


@pytest.mark.parametrize(
    ("operations", "scim_type"),
    [
        pytest.param([{"op": "move", "path": "active"}], "", id="unknown-op"),
        pytest.param([{"op": "remove"}], "noTarget", id="remove-without-path"),
        pytest.param([{"op": "replace", "value": "x"}], "", id="pathless-non-object"),
        pytest.param(
            [{"op": "replace", "path": "a..b", "value": 1}],
            "invalidPath",
            id="bad-path",
        ),
        pytest.param(
            [{"op": "remove", "path": 'emails[type co "w"]'}],
            "invalidPath",
            id="unsupported-filter-operator",
        ),
        pytest.param("not-a-list", "", id="operations-not-a-list"),
    ],
)
def test_rejects_invalid_operations(operations: Any, scim_type: str) -> None:
    with pytest.raises(SCIMError) as exc_info:
        apply_patch_to_resource(_user(), operations)

    assert exc_info.value.status == 400
    assert exc_info.value.scim_type == scim_type


def test_bad_request_error_is_raised_for_unknown_op() -> None:
    with pytest.raises(BadRequestError):
        apply_patch_to_resource(_user(), [{"op": "copy", "path": "active"}])
