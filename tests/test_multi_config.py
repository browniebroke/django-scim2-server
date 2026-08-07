"""Tests for running several SCIM configurations alongside each other."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from django.contrib.auth.models import Group, User
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from django_scim2_server.constants import URN_PATCH_OP
from django_scim2_server.models import SCIMGroup, SCIMUser

SCIM_CONTENT_TYPE = "application/scim+json"


class MultiConfigTestCase(TestCase):
    """Base case with an authenticated superuser, accepted by both configurations."""

    def setUp(self) -> None:
        self.admin = User.objects.create_superuser(
            username="admin",
            password="admin123",  # noqa: S106
            email="admin@example.com",
        )
        self.client.force_login(self.admin)

    def tenant_url(self, tenant: str, suffix: str = "") -> str:
        return f"/t/{tenant}/scim/v2/{suffix}"

    def post_user(self, url: str, user_name: str, **extra: Any) -> dict[str, Any]:
        resp = self.client.post(
            url,
            data=json.dumps({"userName": user_name, **extra}),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 201, resp.content
        data: dict[str, Any] = resp.json()
        return data

    def post_group(self, url: str, display_name: str, **extra: Any) -> dict[str, Any]:
        resp = self.client.post(
            url,
            data=json.dumps({"displayName": display_name, **extra}),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 201, resp.content
        data: dict[str, Any] = resp.json()
        return data


class TenantIsolationTest(MultiConfigTestCase):
    """The same scoped configuration keeps each tenant's resources apart."""

    def test_same_username_in_two_tenants(self) -> None:
        acme = self.post_user(self.tenant_url("acme", "Users"), "alice")
        globex = self.post_user(self.tenant_url("globex", "Users"), "alice")

        assert acme["userName"] == "alice"
        assert globex["userName"] == "alice"
        assert acme["id"] != globex["id"]

        # Two distinct SCIM records, partitioned by scope.
        assert SCIMUser.objects.filter(scim_username="alice").count() == 2
        assert set(
            SCIMUser.objects.filter(scim_username="alice").values_list(
                "config", "scope"
            )
        ) == {("tenants", "acme"), ("tenants", "globex")}

        # The underlying Django usernames are namespaced, since auth.User.username
        # is unique across the whole table.
        assert set(
            User.objects.exclude(username="admin").values_list("username", flat=True)
        ) == {"acme:alice", "globex:alice"}

    def test_same_display_name_in_two_tenants(self) -> None:
        acme = self.post_group(self.tenant_url("acme", "Groups"), "Admins")
        globex = self.post_group(self.tenant_url("globex", "Groups"), "Admins")

        assert acme["displayName"] == "Admins"
        assert globex["displayName"] == "Admins"
        assert acme["id"] != globex["id"]
        assert set(Group.objects.values_list("name", flat=True)) == {
            "acme:Admins",
            "globex:Admins",
        }

    def test_list_only_returns_own_tenant(self) -> None:
        self.post_user(self.tenant_url("acme", "Users"), "alice")
        self.post_user(self.tenant_url("globex", "Users"), "bob")

        resp = self.client.get(self.tenant_url("acme", "Users"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalResults"] == 1
        assert [r["userName"] for r in data["Resources"]] == ["alice"]

    def test_filter_only_matches_own_tenant(self) -> None:
        self.post_user(self.tenant_url("globex", "Users"), "alice")

        resp = self.client.get(
            self.tenant_url("acme", "Users"), {"filter": 'userName eq "alice"'}
        )
        assert resp.status_code == 200
        assert resp.json()["totalResults"] == 0

    def test_detail_of_other_tenant_is_not_found(self) -> None:
        globex = self.post_user(self.tenant_url("globex", "Users"), "alice")

        resp = self.client.get(self.tenant_url("acme", f"Users/{globex['id']}"))
        assert resp.status_code == 404

    def test_write_to_other_tenant_is_not_found(self) -> None:
        globex = self.post_user(self.tenant_url("globex", "Users"), "alice")
        url = self.tenant_url("acme", f"Users/{globex['id']}")

        put = self.client.put(
            url,
            data=json.dumps({"userName": "hijacked"}),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert put.status_code == 404

        delete = self.client.delete(url)
        assert delete.status_code == 404

        # The record is untouched.
        assert SCIMUser.objects.get(id=globex["id"]).scim_username == "alice"

    def test_group_membership_cannot_cross_tenants(self) -> None:
        foreign = self.post_user(self.tenant_url("globex", "Users"), "bob")
        group = self.post_group(
            self.tenant_url("acme", "Groups"),
            "Admins",
            members=[{"value": foreign["id"]}],
        )

        assert group["members"] == []
        assert Group.objects.get(name="acme:Admins").user_set.count() == 0

    def test_patch_cannot_add_a_foreign_member(self) -> None:
        foreign = self.post_user(self.tenant_url("globex", "Users"), "bob")
        group = self.post_group(self.tenant_url("acme", "Groups"), "Admins")

        resp = self.client.patch(
            self.tenant_url("acme", f"Groups/{group['id']}"),
            data=json.dumps(
                {
                    "schemas": [URN_PATCH_OP],
                    "Operations": [
                        {
                            "op": "add",
                            "path": "members",
                            "value": [{"value": foreign["id"]}],
                        }
                    ],
                }
            ),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["members"] == []
        assert Group.objects.get(name="acme:Admins").user_set.count() == 0

    def test_member_list_never_shows_another_tenants_record(self) -> None:
        # Same Django user provisioned in both tenants, and added to acme's group.
        acme_user = self.post_user(self.tenant_url("acme", "Users"), "carol")
        acme_group = self.post_group(
            self.tenant_url("acme", "Groups"),
            "Team",
            members=[{"value": acme_user["id"]}],
        )
        django_user = SCIMUser.objects.get(id=acme_user["id"]).user
        globex_record = SCIMUser.objects.create(
            config="tenants",
            scope="globex",
            user=django_user,
            scim_username="carol",
        )

        resp = self.client.get(self.tenant_url("acme", f"Groups/{acme_group['id']}"))
        assert resp.status_code == 200
        member_ids = [m["value"] for m in resp.json()["members"]]
        assert member_ids == [acme_user["id"]]
        assert str(globex_record.id) not in member_ids

    def test_uniqueness_is_still_enforced_within_a_tenant(self) -> None:
        self.post_user(self.tenant_url("acme", "Users"), "alice")
        resp = self.client.post(
            self.tenant_url("acme", "Users"),
            data=json.dumps({"userName": "alice"}),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 409


class ConfigurationIsolationTest(MultiConfigTestCase):
    """Two different configurations do not see each other's resources."""

    def test_unscoped_config_does_not_see_tenant_resources(self) -> None:
        tenant_user = self.post_user(self.tenant_url("acme", "Users"), "alice")

        listing = self.client.get("/scim/v2/Users")
        assert listing.status_code == 200
        assert listing.json()["totalResults"] == 0

        detail = self.client.get(f"/scim/v2/Users/{tenant_user['id']}")
        assert detail.status_code == 404

    def test_tenant_config_does_not_see_unscoped_resources(self) -> None:
        staff_user = self.post_user("/scim/v2/Users", "alice")

        listing = self.client.get(self.tenant_url("acme", "Users"))
        assert listing.status_code == 200
        assert listing.json()["totalResults"] == 0

        detail = self.client.get(self.tenant_url("acme", f"Users/{staff_user['id']}"))
        assert detail.status_code == 404

    def test_unscoped_config_keeps_plain_django_names(self) -> None:
        self.post_user("/scim/v2/Users", "alice")
        self.post_group("/scim/v2/Groups", "Admins")

        assert User.objects.filter(username="alice").exists()
        assert Group.objects.filter(name="Admins").exists()

    def test_records_are_tagged_with_their_configuration(self) -> None:
        self.post_user("/scim/v2/Users", "alice")
        self.post_user(self.tenant_url("acme", "Users"), "alice")

        assert SCIMUser.objects.get(config="default").scope == ""
        assert SCIMUser.objects.get(config="tenants").scope == "acme"


class LocationTest(MultiConfigTestCase):
    """``meta.location`` points back at the mount that served the request."""

    def test_user_location_per_mount(self) -> None:
        staff = self.post_user("/scim/v2/Users", "alice")
        tenant = self.post_user(self.tenant_url("acme", "Users"), "alice")

        assert staff["meta"]["location"] == (
            f"http://testserver/scim/v2/Users/{staff['id']}"
        )
        assert tenant["meta"]["location"] == (
            f"http://testserver/t/acme/scim/v2/Users/{tenant['id']}"
        )

    def test_group_location_per_mount(self) -> None:
        tenant = self.post_group(self.tenant_url("globex", "Groups"), "Admins")
        assert tenant["meta"]["location"] == (
            f"http://testserver/t/globex/scim/v2/Groups/{tenant['id']}"
        )

    def test_resource_types_location_per_mount(self) -> None:
        resp = self.client.get(self.tenant_url("acme", "ResourceTypes"))
        assert resp.status_code == 200
        locations = {r["id"]: r["meta"]["location"] for r in resp.json()["Resources"]}
        assert locations == {
            "User": "http://testserver/t/acme/scim/v2/Users",
            "Group": "http://testserver/t/acme/scim/v2/Groups",
        }

    def test_schemas_location_per_mount(self) -> None:
        resp = self.client.get(self.tenant_url("acme", "Schemas"))
        assert resp.status_code == 200
        for resource in resp.json()["Resources"]:
            assert resource["meta"]["location"] == (
                f"http://testserver/t/acme/scim/v2/Schemas/{resource['id']}"
            )


class PerConfigAuthTest(TestCase):
    """Each configuration runs its own access-control callable."""

    configs: ClassVar[dict[str, dict[str, str]]] = {
        "default": {"AUTH_CHECK": "django_scim2_server.auth.is_superuser"},
        "tenants": {
            "AUTH_CHECK": "tests.utils.tenant_token_check",
            "SCOPE_URL_KWARG": "tenant",
        },
    }

    def test_tenant_token_is_accepted_for_its_own_tenant(self) -> None:
        with self.settings(SCIM2_SERVER_CONFIGS=self.configs):
            resp = self.client.get(
                "/t/acme/scim/v2/Users",
                headers={"authorization": "Bearer acme-secret"},
            )
        assert resp.status_code == 200

    def test_tenant_token_is_rejected_for_another_tenant(self) -> None:
        with self.settings(SCIM2_SERVER_CONFIGS=self.configs):
            resp = self.client.get(
                "/t/globex/scim/v2/Users",
                headers={"authorization": "Bearer acme-secret"},
            )
        assert resp.status_code == 401

    def test_unknown_tenant_is_rejected(self) -> None:
        with self.settings(SCIM2_SERVER_CONFIGS=self.configs):
            resp = self.client.get(
                "/t/nope/scim/v2/Users",
                headers={"authorization": "Bearer acme-secret"},
            )
        assert resp.status_code == 401

    def test_staff_mount_is_unaffected_by_the_tenant_check(self) -> None:
        admin = User.objects.create_superuser(
            username="admin2",
            password="admin123",  # noqa: S106
            email="admin2@example.com",
        )
        self.client.force_login(admin)
        with self.settings(SCIM2_SERVER_CONFIGS=self.configs):
            resp = self.client.get("/scim/v2/Users")
        assert resp.status_code == 200

    def test_session_auth_does_not_open_the_tenant_mount(self) -> None:
        admin = User.objects.create_superuser(
            username="admin3",
            password="admin123",  # noqa: S106
            email="admin3@example.com",
        )
        self.client.force_login(admin)
        with self.settings(SCIM2_SERVER_CONFIGS=self.configs):
            resp = self.client.get("/t/acme/scim/v2/Users")
        assert resp.status_code == 401


class MisconfiguredMountTest(TestCase):
    """A scoped configuration mounted without its URL kwarg fails loudly."""

    def setUp(self) -> None:
        self.admin = User.objects.create_superuser(
            username="admin",
            password="admin123",  # noqa: S106
            email="admin@example.com",
        )
        self.client.force_login(self.admin)

    def test_scope_kwarg_missing_from_the_mount(self) -> None:
        # The "default" mount does not capture a tenant, so declaring
        # SCOPE_URL_KWARG for it is a configuration error.
        configs = {
            "default": {"SCOPE_URL_KWARG": "tenant"},
            "tenants": {"SCOPE_URL_KWARG": "tenant"},
        }
        with self.settings(SCIM2_SERVER_CONFIGS=configs):
            with self.assertRaises(ImproperlyConfigured):
                self.client.get("/scim/v2/Users")


class ScopedGroupPatchTest(MultiConfigTestCase):
    """Scoped group PATCH keeps the namespaced Django group name in sync."""

    def test_replace_display_name_keeps_the_namespace(self) -> None:
        group = self.post_group(self.tenant_url("acme", "Groups"), "Admins")

        resp = self.client.patch(
            self.tenant_url("acme", f"Groups/{group['id']}"),
            data=json.dumps(
                {
                    "schemas": [URN_PATCH_OP],
                    "Operations": [
                        {"op": "replace", "path": "displayName", "value": "Owners"}
                    ],
                }
            ),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["displayName"] == "Owners"
        assert SCIMGroup.objects.get(id=group["id"]).group.name == "acme:Owners"

    def test_replace_username_keeps_the_namespace(self) -> None:
        user = self.post_user(self.tenant_url("acme", "Users"), "alice")

        resp = self.client.patch(
            self.tenant_url("acme", f"Users/{user['id']}"),
            data=json.dumps(
                {
                    "schemas": [URN_PATCH_OP],
                    "Operations": [
                        {"op": "replace", "path": "userName", "value": "alice2"}
                    ],
                }
            ),
            content_type=SCIM_CONTENT_TYPE,
        )
        assert resp.status_code == 200
        assert resp.json()["userName"] == "alice2"
        assert SCIMUser.objects.get(id=user["id"]).user.username == "acme:alice2"


class SharedDjangoObjectTest(MultiConfigTestCase):
    """Deprovisioning in one tenant leaves shared Django objects alone."""

    def test_deprovisioning_keeps_a_user_active_elsewhere(self) -> None:
        acme = self.post_user(self.tenant_url("acme", "Users"), "carol")
        django_user = SCIMUser.objects.get(id=acme["id"]).user
        SCIMUser.objects.create(
            config="tenants",
            scope="globex",
            user=django_user,
            scim_username="carol",
        )

        resp = self.client.delete(self.tenant_url("acme", f"Users/{acme['id']}"))
        assert resp.status_code == 204

        assert SCIMUser.objects.get(id=acme["id"]).active is False
        django_user.refresh_from_db()
        assert django_user.is_active is True

    def test_deprovisioning_the_last_record_deactivates_the_user(self) -> None:
        acme = self.post_user(self.tenant_url("acme", "Users"), "carol")
        django_user = SCIMUser.objects.get(id=acme["id"]).user

        resp = self.client.delete(self.tenant_url("acme", f"Users/{acme['id']}"))
        assert resp.status_code == 204

        django_user.refresh_from_db()
        assert django_user.is_active is False

    def test_deleting_a_group_keeps_a_shared_django_group(self) -> None:
        acme = self.post_group(self.tenant_url("acme", "Groups"), "Admins")
        django_group = SCIMGroup.objects.get(id=acme["id"]).group
        SCIMGroup.objects.create(
            config="tenants",
            scope="globex",
            group=django_group,
            display_name="Admins",
        )

        resp = self.client.delete(self.tenant_url("acme", f"Groups/{acme['id']}"))
        assert resp.status_code == 204

        assert not SCIMGroup.objects.filter(id=acme["id"]).exists()
        assert Group.objects.filter(pk=django_group.pk).exists()

    def test_deleting_the_last_record_deletes_the_django_group(self) -> None:
        acme = self.post_group(self.tenant_url("acme", "Groups"), "Admins")
        django_group = SCIMGroup.objects.get(id=acme["id"]).group

        resp = self.client.delete(self.tenant_url("acme", f"Groups/{acme['id']}"))
        assert resp.status_code == 204

        assert not Group.objects.filter(pk=django_group.pk).exists()
