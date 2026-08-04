"""Tests for the SCIM configuration registry and its system checks."""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from django_scim2_server.adapters import DefaultGroupAdapter, DefaultUserAdapter
from django_scim2_server.auth import is_authenticated, is_superuser
from django_scim2_server.checks import INVALID_CONFIG, NO_CONFIGS, check_configs
from django_scim2_server.conf import (
    clear_config_cache,
    get_config,
    get_config_names,
    get_setting,
)
from django_scim2_server.constants import SERVICE_PROVIDER_CONFIG


class GetConfigTest(SimpleTestCase):
    """Tests for resolving a named configuration."""

    def test_defaults(self) -> None:
        config = get_config("default")
        assert config.name == "default"
        assert config.user_adapter is DefaultUserAdapter
        assert config.group_adapter is DefaultGroupAdapter
        assert config.auth_check is is_superuser
        assert config.service_provider_config is SERVICE_PROVIDER_CONFIG
        assert config.scope_url_kwarg is None
        assert config.is_scoped is False

    def test_scoped_config(self) -> None:
        config = get_config("tenants")
        assert config.scope_url_kwarg == "tenant"
        assert config.is_scoped is True

    def test_config_names(self) -> None:
        assert get_config_names() == ["default", "tenants"]

    def test_unknown_name(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="No SCIM configuration named"):
            get_config("nope")

    def test_result_is_cached(self) -> None:
        assert get_config("default") is get_config("default")

    def test_override_rebuilds_the_config(self) -> None:
        before = get_config("default")
        with self.settings(
            SCIM2_SERVER_CONFIGS={
                "default": {"AUTH_CHECK": "django_scim2_server.auth.is_authenticated"},
            },
        ):
            during = get_config("default")
            assert during is not before
            assert during.auth_check is is_authenticated
        assert get_config("default").auth_check is is_superuser

    def test_missing_setting(self) -> None:
        with self.settings(SCIM2_SERVER_CONFIGS=None):
            assert get_setting() == {}
            with pytest.raises(ImproperlyConfigured, match="declared: none"):
                get_config("default")

    def test_unknown_key(self) -> None:
        with self.settings(
            SCIM2_SERVER_CONFIGS={"default": {"USER_MODEL": "auth.User"}}
        ):
            with pytest.raises(ImproperlyConfigured, match="Unknown key"):
                get_config("default")

    def test_config_must_be_a_dict(self) -> None:
        with self.settings(SCIM2_SERVER_CONFIGS={"default": ["nope"]}):
            with pytest.raises(ImproperlyConfigured, match="must be a dict"):
                get_config("default")

    def test_scope_url_kwarg_must_be_an_identifier(self) -> None:
        with self.settings(
            SCIM2_SERVER_CONFIGS={"default": {"SCOPE_URL_KWARG": "not an identifier"}},
        ):
            with pytest.raises(ImproperlyConfigured, match="valid Python identifier"):
                get_config("default")

    def test_unimportable_dotted_path(self) -> None:
        with self.settings(
            SCIM2_SERVER_CONFIGS={"default": {"AUTH_CHECK": "nope.does.not.Exist"}},
        ):
            with pytest.raises(ImportError):
                get_config("default")

    def test_auth_check_must_be_callable(self) -> None:
        with self.settings(
            SCIM2_SERVER_CONFIGS={
                "default": {"AUTH_CHECK": "django_scim2_server.conf.SETTING_NAME"},
            },
        ):
            with pytest.raises(ImproperlyConfigured, match="must be a callable"):
                get_config("default")

    def test_adapter_must_subclass_the_base(self) -> None:
        with self.settings(
            SCIM2_SERVER_CONFIGS={
                "default": {"USER_ADAPTER": "django_scim2_server.auth.is_superuser"},
            },
        ):
            with pytest.raises(ImproperlyConfigured, match="must be a subclass of"):
                get_config("default")

    def test_clear_cache(self) -> None:
        get_config("default")
        clear_config_cache()
        assert get_config("default").name == "default"


class ChecksTest(SimpleTestCase):
    """Tests for the ``SCIM2_SERVER_CONFIGS`` system checks."""

    def test_valid_configs_produce_no_messages(self) -> None:
        assert check_configs() == []

    def test_empty_setting_warns(self) -> None:
        with self.settings(SCIM2_SERVER_CONFIGS={}):
            messages = check_configs()
        assert [m.id for m in messages] == [NO_CONFIGS]

    def test_invalid_config_is_reported(self) -> None:
        with self.settings(SCIM2_SERVER_CONFIGS={"default": {"BOGUS": 1}}):
            messages = check_configs()
        assert [m.id for m in messages] == [INVALID_CONFIG]

    def test_unimportable_path_is_reported(self) -> None:
        with self.settings(
            SCIM2_SERVER_CONFIGS={"default": {"AUTH_CHECK": "nope.does.not.Exist"}},
        ):
            messages = check_configs()
        assert [m.id for m in messages] == [INVALID_CONFIG]

    def test_adapter_of_the_wrong_type_is_reported(self) -> None:
        with self.settings(
            SCIM2_SERVER_CONFIGS={
                "default": {"USER_ADAPTER": "django_scim2_server.auth.is_superuser"},
            },
        ):
            messages = check_configs()
        assert [m.id for m in messages] == [INVALID_CONFIG]

    def test_every_config_is_checked(self) -> None:
        with self.settings(
            SCIM2_SERVER_CONFIGS={
                "a": {"BOGUS": 1},
                "b": {"ALSO_BOGUS": 1},
            },
        ):
            messages = check_configs()
        assert [m.id for m in messages] == [INVALID_CONFIG, INVALID_CONFIG]
