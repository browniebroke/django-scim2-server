"""Tests for a second, separately configured SCIM mount (see ``tests/urls.py``)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.test import Client

from django_scim2_server.constants import URN_ENTERPRISE_USER, URN_PATCH_OP, URN_USER
from tests.testapp.models import Member, Organisation

SCIM_CONTENT_TYPE = "application/scim+json"
BASE = "/scim/v2/orgs"

pytestmark = pytest.mark.django_db


@pytest.fixture
def acme() -> Organisation:
    return Organisation.objects.create(name="Acme", scim_token="acme-token")  # noqa: S106


@pytest.fixture
def globex() -> Organisation:
    return Organisation.objects.create(name="Globex", scim_token="globex-token")  # noqa: S106


def _client(organisation: Organisation) -> Client:
    return Client(headers={"Authorization": f"Bearer {organisation.scim_token}"})


def _send(client: Client, method: str, url: str, payload: dict[str, Any]) -> Any:
    return getattr(client, method)(
        url, data=json.dumps(payload), content_type=SCIM_CONTENT_TYPE
    )


def _entra_create_payload(user_name: str) -> dict[str, Any]:
    return {
        "schemas": [URN_USER, URN_ENTERPRISE_USER],
        "userName": user_name,
        "active": True,
        "name": {"givenName": "Jane", "familyName": "Doe"},
        "emails": [{"primary": True, "type": "work", "value": user_name}],
        "externalId": "00aa00aa-bb11-cc22-dd33-44ee44ee44ee",
        URN_ENTERPRISE_USER: {"department": "Tax", "employeeNumber": "123"},
    }


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-header"),
        pytest.param({"Authorization": "Bearer wrong"}, id="unknown-token"),
        pytest.param({"Authorization": "Basic acme-token"}, id="wrong-scheme"),
    ],
)
def test_rejects_requests_without_a_valid_token(
    acme: Organisation, headers: dict[str, str]
) -> None:
    response = Client(headers=headers).get(f"{BASE}/Users")

    assert response.status_code == 401


def test_superuser_session_does_not_open_the_token_mount(acme: Organisation) -> None:
    client = Client()
    client.force_login(User.objects.create_superuser("admin", "a@x.io", "pw"))

    assert client.get(f"{BASE}/Users").status_code == 401


def test_creates_user_with_enterprise_extension_and_location_on_its_mount(
    acme: Organisation,
) -> None:
    response = _send(
        _client(acme), "post", f"{BASE}/Users", _entra_create_payload("j@acme.io")
    )

    assert response.status_code == 201
    body = response.json()
    member = Member.objects.get(organisation=acme)
    assert body["id"] == str(member.uuid)
    assert body[URN_ENTERPRISE_USER] == {"department": "Tax"}
    assert body["meta"]["location"] == f"http://testserver{BASE}/Users/{member.uuid}"


def test_list_is_scoped_to_the_token_and_keeps_extension_attributes(
    acme: Organisation, globex: Organisation
) -> None:
    Member.objects.create(organisation=acme, email="a@acme.io", department="Tax")
    Member.objects.create(organisation=globex, email="g@globex.io")

    response = _client(acme).get(f"{BASE}/Users", {"filter": 'userName eq "A@ACME.IO"'})

    body = response.json()
    assert body["totalResults"] == 1
    assert body["Resources"][0]["userName"] == "a@acme.io"
    assert body["Resources"][0][URN_ENTERPRISE_USER] == {"department": "Tax"}


@pytest.mark.parametrize("method", ["get", "delete"])
def test_cannot_reach_another_organisations_user(
    acme: Organisation, globex: Organisation, method: str
) -> None:
    other = Member.objects.create(organisation=globex, email="g@globex.io")

    response = getattr(_client(acme), method)(f"{BASE}/Users/{other.uuid}")

    assert response.status_code == 404
    other.refresh_from_db()
    assert other.active is True


def test_unknown_id_format_is_not_found(acme: Organisation) -> None:
    assert _client(acme).get(f"{BASE}/Users/not-a-uuid").status_code == 404


def test_entra_patch_is_applied_through_the_adapter_mapping(acme: Organisation) -> None:
    member = Member.objects.create(
        organisation=acme, email="j@acme.io", given_name="Jane", department="Tax"
    )
    payload = {
        "schemas": [URN_PATCH_OP],
        "Operations": [
            {"op": "Replace", "path": "active", "value": "False"},
            {
                "op": "Replace",
                "path": 'emails[type eq "work"].value',
                "value": "jd@acme.io",
            },
            {
                "op": "Add",
                "path": f"{URN_ENTERPRISE_USER}:department",
                "value": "Probate",
            },
            {"op": "Replace", "value": {"name.familyName": "Doe"}},
        ],
    }

    response = _send(_client(acme), "patch", f"{BASE}/Users/{member.uuid}", payload)

    assert response.status_code == 200
    member.refresh_from_db()
    assert (
        member.active,
        member.department,
        member.family_name,
        member.given_name,
    ) == (
        False,
        "Probate",
        "Doe",
        "Jane",
    )


def test_discovery_advertises_the_mount_adapters_schemas(acme: Organisation) -> None:
    client = _client(acme)

    schemas = client.get(f"{BASE}/Schemas").json()
    resource_types = client.get(f"{BASE}/ResourceTypes").json()

    assert [s["id"] for s in schemas["Resources"]] == [
        URN_USER,
        URN_ENTERPRISE_USER,
        "urn:ietf:params:scim:schemas:core:2.0:Group",
    ]
    assert resource_types["Resources"][0]["schemaExtensions"] == [
        {"schema": URN_ENTERPRISE_USER, "required": False}
    ]


def test_default_mount_accepts_entra_payload_with_enterprise_extension() -> None:
    client = Client()
    client.force_login(User.objects.create_superuser("admin", "a@x.io", "pw"))

    response = _send(client, "post", "/scim/v2/Users", _entra_create_payload("j@x.io"))

    assert response.status_code == 201


def test_rejects_a_body_that_is_not_an_object(acme: Organisation) -> None:
    response = _send(_client(acme), "post", f"{BASE}/Users", [])  # type: ignore[arg-type]

    assert response.status_code == 400
