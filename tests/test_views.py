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

    def test_non_superuser_rejected(self) -> None:
        regular = User.objects.create_user(
            username="regular",
            password="regular123",  # noqa: S106
        )
        self.client.force_login(regular)
        resp = self.client.get("/scim/v2/ServiceProviderConfig")
        assert resp.status_code == 401

    def test_custom_auth_check(self) -> None:
        regular = User.objects.create_user(
            username="regular2",
            password="regular123",  # noqa: S106
        )
        self.client.force_login(regular)
        with self.settings(
            SCIM2_SERVER_AUTH_CHECK="django_scim2_server.auth.is_authenticated",
        ):
            resp = self.client.get("/scim/v2/ServiceProviderConfig")
        assert resp.status_code == 200


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

    def test_list_pagination_invalid_start_index_type(self) -> None:
        resp = self.client.get("/scim/v2/Users?startIndex=not-an-int")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "startIndex and count must be integers"

    def test_list_pagination_invalid_start_index_lower_bound(self) -> None:
        resp = self.client.get("/scim/v2/Users?startIndex=0")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "startIndex must be >= 1"

    def test_list_pagination_invalid_count_lower_bound(self) -> None:
        resp = self.client.get("/scim/v2/Users?count=-1")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "count must be >= 0"

    def test_list_pagination_invalid_count_upper_bound(self) -> None:
        resp = self.client.get("/scim/v2/Users?count=1001")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "count must be <= 1000"


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

    def test_patch_user_replace_username(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "replace", "path": "userName", "value": "renamed"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["userName"] == "renamed"
        scim_user.refresh_from_db()
        assert scim_user.user.username == "renamed"

    def test_patch_user_replace_name_fields(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "replace", "path": "name.givenName", "value": "First"},
                {"op": "replace", "path": "name.familyName", "value": "Last"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"]["givenName"] == "First"
        assert data["name"]["familyName"] == "Last"

    def test_patch_user_replace_emails_list(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {
                    "op": "replace",
                    "path": "emails",
                    "value": [{"value": "new@example.com"}],
                },
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["emails"][0]["value"] == "new@example.com"

    def test_patch_user_replace_emails_value_path(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "replace", "path": "emails.value", "value": "alt@example.com"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["emails"][0]["value"] == "alt@example.com"

    def test_patch_user_replace_external_id(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "replace", "path": "externalId", "value": "ext-999"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["externalId"] == "ext-999"

    def test_patch_user_replace_name_dict(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {
                    "op": "replace",
                    "path": "name",
                    "value": {"givenName": "G", "familyName": "F"},
                },
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"]["givenName"] == "G"
        assert data["name"]["familyName"] == "F"

    def test_patch_user_bulk_replace_without_path(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {
                    "op": "replace",
                    "value": {"userName": "bulk", "active": False},
                },
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["userName"] == "bulk"
        assert data["active"] is False

    def test_patch_user_remove_given_name(self) -> None:
        user = User.objects.create_user(
            username="rm", first_name="First", last_name="Last"
        )
        scim_user = SCIMUser.objects.create(user=user, scim_username="rm")
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "remove", "path": "name.givenName"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["name"]["givenName"] == ""

    def test_patch_user_remove_family_name(self) -> None:
        user = User.objects.create_user(username="rm2", first_name="F", last_name="L")
        scim_user = SCIMUser.objects.create(user=user, scim_username="rm2")
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "remove", "path": "name.familyName"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["name"]["familyName"] == ""

    def test_patch_user_remove_emails(self) -> None:
        user = User.objects.create_user(username="rm3", email="old@ex.com")
        scim_user = SCIMUser.objects.create(user=user, scim_username="rm3")
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "remove", "path": "emails"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert "emails" not in resp.json()

    def test_patch_user_remove_external_id(self) -> None:
        user = User.objects.create_user(username="rm4")
        scim_user = SCIMUser.objects.create(
            user=user, scim_username="rm4", external_id="ext-old"
        )
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "remove", "path": "externalId"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert "externalId" not in resp.json()

    def test_patch_user_replace_name_dict_partial(self) -> None:
        user = User.objects.create_user(
            username="partial", first_name="Old", last_name="Name"
        )
        scim_user = SCIMUser.objects.create(user=user, scim_username="partial")
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "replace", "path": "name", "value": {"givenName": "Only"}},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"]["givenName"] == "Only"
        assert data["name"]["familyName"] == "Name"

    def test_patch_user_unsupported_op(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "invalid", "path": "active", "value": True},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400

    def test_patch_user_remove_without_path(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "remove"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400

    def test_patch_user_missing_schema(self) -> None:
        scim_user = self._create_scim_user()
        payload = {
            "schemas": [],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        }
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400
        assert "PatchOp schema required" in resp.json()["detail"]

    def test_patch_user_missing_operations_key(self) -> None:
        scim_user = self._create_scim_user()
        payload = {"schemas": [URN_PATCH_OP]}
        resp = self.client.patch(
            f"/scim/v2/Users/{scim_user.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400
        assert "Operations is required" in resp.json()["detail"]

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

    def test_list_with_filter(self) -> None:
        group = Group.objects.create(name="Filtered")
        SCIMGroup.objects.create(group=group, display_name="Filtered")
        resp = self.client.get('/scim/v2/Groups?filter=displayName eq "Filtered"')
        data = resp.json()
        assert data["totalResults"] == 1
        assert data["Resources"][0]["displayName"] == "Filtered"

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

    def test_patch_group_replace_display_name(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "replace", "path": "displayName", "value": "Renamed"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["displayName"] == "Renamed"

    def test_patch_group_replace_external_id(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "replace", "path": "externalId", "value": "ext-g1"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["externalId"] == "ext-g1"

    def test_patch_group_replace_members(self) -> None:
        scim_group = self._create_scim_group()
        user1 = User.objects.create_user(username="rep1")
        SCIMUser.objects.create(user=user1, scim_username="rep1")
        user2 = User.objects.create_user(username="rep2")
        su2 = SCIMUser.objects.create(user=user2, scim_username="rep2")
        # Add user1 first
        scim_group.group.user_set.add(user1)
        # Replace with user2 only
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {
                    "op": "replace",
                    "path": "members",
                    "value": [{"value": str(su2.id)}],
                },
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        members = resp.json()["members"]
        assert len(members) == 1
        assert members[0]["value"] == str(su2.id)

    def test_patch_group_remove_members(self) -> None:
        scim_group = self._create_scim_group()
        user = User.objects.create_user(username="rem1")
        su = SCIMUser.objects.create(user=user, scim_username="rem1")
        scim_group.group.user_set.add(user)
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {
                    "op": "remove",
                    "path": "members",
                    "value": [{"value": str(su.id)}],
                },
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["members"] == []

    def test_patch_group_remove_member_by_filter(self) -> None:
        scim_group = self._create_scim_group()
        user = User.objects.create_user(username="filt1")
        su = SCIMUser.objects.create(user=user, scim_username="filt1")
        scim_group.group.user_set.add(user)
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {
                    "op": "remove",
                    "path": f'members[value eq "{su.id}"]',
                },
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["members"] == []

    def test_patch_group_bulk_replace_without_path(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {
                    "op": "replace",
                    "value": {"displayName": "Bulk", "externalId": "ext-b"},
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
        assert data["displayName"] == "Bulk"
        assert data["externalId"] == "ext-b"

    def test_patch_group_remove_member_by_filter_nonexistent(self) -> None:
        scim_group = self._create_scim_group()
        import uuid

        fake_id = uuid.uuid4()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {
                    "op": "remove",
                    "path": f'members[value eq "{fake_id}"]',
                },
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200

    def test_patch_group_members_not_a_list(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "add", "path": "members", "value": "not-a-list"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400

    def test_patch_group_replace_members_not_a_list(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "replace", "path": "members", "value": "not-a-list"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400

    def test_patch_group_remove_members_not_a_list(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "remove", "path": "members", "value": "not-a-list"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400

    def test_patch_group_remove_member_bad_filter(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "remove", "path": "members[bad filter]"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot parse member filter"

    def test_patch_group_remove_member_invalid_uuid_filter(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "remove", "path": 'members[value eq "not-a-uuid"]'},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot parse member filter"

    def test_patch_group_remove_external_id(self) -> None:
        group = Group.objects.create(name="extgrp")
        scim_group = SCIMGroup.objects.create(
            group=group, display_name="extgrp", external_id="ext-old"
        )
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "remove", "path": "externalId"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert "externalId" not in resp.json()

    def test_patch_group_unsupported_path(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "replace", "path": "nonsense", "value": "x"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400

    def test_patch_group_remove_without_path(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [URN_PATCH_OP],
            "Operations": [
                {"op": "remove"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400

    def test_get_group_not_found(self) -> None:
        import uuid

        resp = self.client.get(f"/scim/v2/Groups/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_patch_group_missing_schema(self) -> None:
        scim_group = self._create_scim_group()
        payload = {
            "schemas": [],
            "Operations": [
                {"op": "replace", "path": "displayName", "value": "X"},
            ],
        }
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400
        assert "PatchOp schema required" in resp.json()["detail"]

    def test_patch_group_missing_operations_key(self) -> None:
        scim_group = self._create_scim_group()
        payload = {"schemas": [URN_PATCH_OP]}
        resp = self.client.patch(
            f"/scim/v2/Groups/{scim_group.id}",
            data=json.dumps(payload),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 400
        assert "Operations is required" in resp.json()["detail"]

    def test_delete_group(self) -> None:
        scim_group = self._create_scim_group()
        group_id = scim_group.group.id
        resp = self.client.delete(f"/scim/v2/Groups/{scim_group.id}")
        assert resp.status_code == 204
        assert not Group.objects.filter(id=group_id).exists()
        assert not SCIMGroup.objects.filter(id=scim_group.id).exists()
