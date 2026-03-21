"""Tests for SCIM models."""

from __future__ import annotations

from django.contrib.auth.models import Group, User
from django.test import TestCase

from django_scim2_server.models import SCIMGroup, SCIMUser


class SCIMUserModelTest(TestCase):
    """Tests for the SCIMUser model."""

    def test_create_scim_user(self) -> None:
        user = User.objects.create_user(username="testuser")
        scim_user = SCIMUser.objects.create(user=user, scim_username="testuser")
        assert scim_user.pk is not None
        assert scim_user.active is True
        assert scim_user.external_id == ""
        assert str(scim_user) == "testuser"

    def test_scim_user_linked_to_django_user(self) -> None:
        user = User.objects.create_user(username="linked")
        scim_user = SCIMUser.objects.create(user=user, scim_username="linked")
        assert user.scim == scim_user

    def test_scim_username_unique(self) -> None:
        user1 = User.objects.create_user(username="u1")
        user2 = User.objects.create_user(username="u2")
        SCIMUser.objects.create(user=user1, scim_username="unique_name")
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            SCIMUser.objects.create(user=user2, scim_username="unique_name")

    def test_cascade_delete(self) -> None:
        user = User.objects.create_user(username="del")
        SCIMUser.objects.create(user=user, scim_username="del")
        user.delete()
        assert SCIMUser.objects.count() == 0


class SCIMGroupModelTest(TestCase):
    """Tests for the SCIMGroup model."""

    def test_create_scim_group(self) -> None:
        group = Group.objects.create(name="testgroup")
        scim_group = SCIMGroup.objects.create(group=group, display_name="Test Group")
        assert scim_group.pk is not None
        assert scim_group.external_id == ""
        assert str(scim_group) == "Test Group"

    def test_scim_group_linked_to_django_group(self) -> None:
        group = Group.objects.create(name="linked")
        scim_group = SCIMGroup.objects.create(group=group, display_name="Linked")
        assert group.scim == scim_group

    def test_cascade_delete(self) -> None:
        group = Group.objects.create(name="del")
        SCIMGroup.objects.create(group=group, display_name="del")
        group.delete()
        assert SCIMGroup.objects.count() == 0
