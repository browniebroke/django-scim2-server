"""Tests for SCIM views."""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth.models import Group, User
from django.test import TestCase

from django_scim2_server.constants import URN_PATCH_OP, URN_USER
from django_scim2_server.models import SCIMGroup, SCIMUser

SCIM_CONTENT_TYPE = "application/scim+json"


class AuthenticatedTestCase(TestCase):
    """Base test case with an authenticated admin user."""

    def setUp(self) -> None:
        self.admin = User.objects.create_superuser(
            username="admin",
            password="admin123",  # noqa: S106
            email="admin@example.com",
        )
        self.client.force_login(self.admin)


class ServiceProviderConfigViewTest(AuthenticatedTestCase):
    """Tests for GET /ServiceProviderConfig."""

    def test_get(self) -> None:
        resp = self.client.get("/scim/v2/ServiceProviderConfig")
        assert resp.status_code == 200
        data = resp.json()
        assert "patch" in data
        assert data["patch"]["supported"] is True

    def test_unauthenticated(self) -> None:
        self.client.logout()
        resp = self.client.get("/scim/v2/ServiceProviderConfig")
        assert resp.status_code == 401


class ResourceTypesViewTest(AuthenticatedTestCase):
    """Tests for GET /ResourceTypes."""

    def test_get(self) -> None:
        resp = self.client.get("/scim/v2/ResourceTypes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalResults"] == 2


class SchemasViewTest(AuthenticatedTestCase):
    """Tests for GET /Schemas."""

    def test_get(self) -> None:
        resp = self.client.get("/scim/v2/Schemas")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalResults"] == 2


class UserListViewTest(AuthenticatedTestCase):
    """Tests for GET/POST /Users."""

    def test_list_empty(self) -> None:
        resp = self.client.get("/scim/v2/Users")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalResults"] == 0
        assert data["Resources"] == []

    def test_create_user(self) -> None:
        payload = {
            "schemas": [URN_USER],
            "userName": "newuser",
            "name": {"givenName": "New", "familyName": "User"},
            "emails": [{"value": "new@example.com", "primary": True}],
            "active": True,
        }
        resp = self.client.post(
            "/scim/v2/Users",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["userName"] == "newuser"
        assert data["name"]["givenName"] == "New"
        assert User.objects.filter(username="newuser").exists()

    def test_create_user_missing_username(self) -> None:
        payload = {"schemas": [URN_USER], "name": {"givenName": "No"}}
        resp = self.client.post(
            "/scim/v2/Users",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400

    def test_create_duplicate_user(self) -> None:
        user = User.objects.create_user(username="dup")
        SCIMUser.objects.create(user=user, scim_username="dup")
        payload = {"schemas": [URN_USER], "userName": "dup"}
        resp = self.client.post(
            "/scim/v2/Users",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 409

    def test_list_with_filter(self) -> None:
        user = User.objects.create_user(username="filtered")
        SCIMUser.objects.create(user=user, scim_username="filtered")
        resp = self.client.get('/scim/v2/Users?filter=userName eq "filtered"')
        data = resp.json()
        assert data["totalResults"] == 1
        assert data["Resources"][0]["userName"] == "filtered"

    def test_list_pagination(self) -> None:
        for i in range(5):
            u = User.objects.create_user(username=f"page{i}")
            SCIMUser.objects.create(user=u, scim_username=f"page{i}")
        resp = self.client.get("/scim/v2/Users?startIndex=2&count=2")
        data = resp.json()
        assert data["totalResults"] == 5
        assert data["itemsPerPage"] == 2
        assert data["startIndex"] == 2


class UserDetailViewTest(AuthenticatedTestCase):
    """Tests for GET/PUT/PATCH/DELETE /Users/<id>."""

    def _create_scim_user(self, username: str = "detail") -> SCIMUser:
        user = User.objects.create_user(username=username, email="d@ex.com")
        return SCIMUser.objects.create(user=user, scim_username=username)

    def test_get_user(self) -> None:
        scim_user = self._create_scim_user()
        resp = self.client.get(f"/scim/v2/Users/{scim_user.id}")
        assert resp.status_code == 200
        assert resp.json()["userName"] == "detail"

    def test_get_user_not_found(self) -> None:
        import uuid

        resp = self.client.get(f"/scim/v2/Users/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_put_user(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_USER],
            "userName": "updated",
            "name": {"givenName": "Up", "familyName": "Dated"},
            "active": True,
        }
        resp = self.client.put(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["userName"] == "updated"

    def test_patch_user(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "replace", "path": "active", "value": False},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    def test_delete_user(self) -> None:
        scim_user = self._create_scim_user()
        resp = self.client.delete(f"/scim/v2/Users/{scim_user.id}")
        assert resp.status_code == 204
        scim_user.refresh_from_db()
        assert scim_user.active is False
        assert scim_user.user.is_active is False

    def test_invalid_json(self) -> None:
        scim_user = self._create_scim_user()
        resp = self.client.put(
            f"/scim/v2/Users/{scim_user.id}",
            data="not json",
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400


class GroupListViewTest(AuthenticatedTestCase):
    """Tests for GET/POST /Groups."""

    def test_list_empty(self) -> None:
        resp = self.client.get("/scim/v2/Groups")
        assert resp.status_code == 200
        assert resp.json()["totalResults"] == 0

    def test_create_group(self) -> None:
        payload = {"displayName": "Engineering"}
        resp = self.client.post(
            "/scim/v2/Groups",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["displayName"] == "Engineering"
        assert Group.objects.filter(name="Engineering").exists()

    def test_create_group_missing_name(self) -> None:
        payload: dict[str, Any] = {}
        resp = self.client.post(
            "/scim/v2/Groups",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400


class GroupDetailViewTest(AuthenticatedTestCase):
    """Tests for GET/PUT/PATCH/DELETE /Groups/<id>."""

    def _create_scim_group(self, name: str = "testgrp") -> SCIMGroup:
        group = Group.objects.create(name=name)
        return SCIMGroup.objects.create(group=group, display_name=name)

    def test_get_group(self) -> None:
        scim_group = self._create_scim_group()
        resp = self.client.get(f"/scim/v2/Groups/{scim_group.id}")
        assert resp.status_code == 200
        assert resp.json()["displayName"] == "testgrp"

    def test_put_group(self) -> None:
        scim_group = self._create_scim_group()
        payload = {"displayName": "Renamed"}
        resp = self.client.put(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["displayName"] == "Renamed"

    def test_patch_group_add_members(self) -> None:
        scim_group = self._create_scim_group()
        user = User.objects.create_user(username="member1")
        scim_user = SCIMUser.objects.create(user=user, scim_username="member1")
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {
                    "op": "add",
                    "path": "members",
                    "value": [{"value": str(scim_user.id)}],
                },
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["members"]) == 1

    def test_delete_group(self) -> None:
        scim_group = self._create_scim_group()
        group_id = scim_group.group.id
        resp = self.client.delete(f"/scim/v2/Groups/{scim_group.id}")
        assert resp.status_code == 204
        assert not Group.objects.filter(id=group_id).exists()
        assert not SCIMGroup.objects.filter(id=scim_group.id).exists()
