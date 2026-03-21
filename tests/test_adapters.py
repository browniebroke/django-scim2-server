"""Tests for SCIM adapters."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import RequestFactory, TestCase

from django_scim2_server.adapters import DefaultGroupAdapter, DefaultUserAdapter
from django_scim2_server.exceptions import BadRequestError, ConflictError
from django_scim2_server.models import SCIMGroup, SCIMUser


class DefaultUserAdapterTest(TestCase):
    """Tests for the DefaultUserAdapter."""

    def setUp(self) -> None:
        self.adapter = DefaultUserAdapter()
        self.factory = RequestFactory()

    def _make_request(self) -> object:
        request = self.factory.get("/scim/v2/Users")
        request.resolver_match = None
        return request

    def test_from_scim_create(self) -> None:
        data = {
            "userName": "newuser",
            "name": {"givenName": "New", "familyName": "User"},
            "emails": [{"value": "new@example.com"}],
            "externalId": "ext123",
            "active": True,
        }
        scim_user = self.adapter.from_scim(data)
        assert scim_user.scim_username == "newuser"
        assert scim_user.user.first_name == "New"
        assert scim_user.user.last_name == "User"
        assert scim_user.user.email == "new@example.com"
        assert scim_user.external_id == "ext123"

    def test_from_scim_update(self) -> None:
        user = User.objects.create_user(username="old")
        scim_user = SCIMUser.objects.create(user=user, scim_username="old")
        data = {
            "userName": "updated",
            "name": {"givenName": "Up", "familyName": "Dated"},
            "active": True,
        }
        result = self.adapter.from_scim(data, scim_user)
        assert result.scim_username == "updated"
        result.user.refresh_from_db()
        assert result.user.username == "updated"

    def test_from_scim_missing_username(self) -> None:
        with pytest.raises(BadRequestError):
            self.adapter.from_scim({"name": {"givenName": "No"}})

    def test_from_scim_duplicate_username(self) -> None:
        user = User.objects.create_user(username="existing")
        SCIMUser.objects.create(user=user, scim_username="existing")
        with pytest.raises(ConflictError):
            self.adapter.from_scim({"userName": "existing"})

    def test_to_scim(self) -> None:
        user = User.objects.create_user(
            username="test", first_name="Test", last_name="User", email="t@ex.com"
        )
        scim_user = SCIMUser.objects.create(
            user=user, scim_username="test", external_id="ext1"
        )
        request = self._make_request()
        result = self.adapter.to_scim(scim_user, request)
        assert result["userName"] == "test"
        assert result["name"]["givenName"] == "Test"
        assert result["emails"][0]["value"] == "t@ex.com"
        assert result["externalId"] == "ext1"
        assert "meta" in result

    def test_delete_deactivates(self) -> None:
        user = User.objects.create_user(username="todel")
        scim_user = SCIMUser.objects.create(user=user, scim_username="todel")
        self.adapter.delete(scim_user)
        scim_user.refresh_from_db()
        assert scim_user.active is False
        user.refresh_from_db()
        assert user.is_active is False

    def test_get_queryset(self) -> None:
        qs = self.adapter.get_queryset()
        assert qs.model is SCIMUser


class DefaultGroupAdapterTest(TestCase):
    """Tests for the DefaultGroupAdapter."""

    def setUp(self) -> None:
        self.adapter = DefaultGroupAdapter()
        self.factory = RequestFactory()

    def _make_request(self) -> object:
        request = self.factory.get("/scim/v2/Groups")
        request.resolver_match = None
        return request

    def test_from_scim_create(self) -> None:
        data = {"displayName": "Engineering", "externalId": "ext-eng"}
        scim_group = self.adapter.from_scim(data)
        assert scim_group.display_name == "Engineering"
        assert scim_group.group.name == "Engineering"
        assert scim_group.external_id == "ext-eng"

    def test_from_scim_update(self) -> None:
        group = Group.objects.create(name="Old")
        scim_group = SCIMGroup.objects.create(group=group, display_name="Old")
        data = {"displayName": "New"}
        result = self.adapter.from_scim(data, scim_group)
        assert result.display_name == "New"
        result.group.refresh_from_db()
        assert result.group.name == "New"

    def test_from_scim_missing_name(self) -> None:
        with pytest.raises(BadRequestError):
            self.adapter.from_scim({})

    def test_to_scim_with_members(self) -> None:
        group = Group.objects.create(name="Team")
        scim_group = SCIMGroup.objects.create(group=group, display_name="Team")
        user = User.objects.create_user(username="member")
        scim_user = SCIMUser.objects.create(user=user, scim_username="member")
        group.user_set.add(user)

        request = self._make_request()
        result = self.adapter.to_scim(scim_group, request)
        assert result["displayName"] == "Team"
        assert len(result["members"]) == 1
        assert result["members"][0]["value"] == str(scim_user.id)

    def test_delete_removes_group(self) -> None:
        group = Group.objects.create(name="Del")
        scim_group = SCIMGroup.objects.create(group=group, display_name="Del")
        group_id = group.id
        self.adapter.delete(scim_group)
        assert not Group.objects.filter(id=group_id).exists()
        assert not SCIMGroup.objects.filter(id=scim_group.id).exists()

    def test_sync_members(self) -> None:
        group = Group.objects.create(name="Sync")
        scim_group = SCIMGroup.objects.create(group=group, display_name="Sync")
        user = User.objects.create_user(username="syncuser")
        scim_user = SCIMUser.objects.create(user=user, scim_username="syncuser")

        data = {
            "displayName": "Sync",
            "members": [{"value": str(scim_user.id)}],
        }
        self.adapter.from_scim(data, scim_group)
        assert user in scim_group.group.user_set.all()
