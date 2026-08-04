"""
Named SCIM configurations.

A project declares one or more *configurations* in the ``SCIM2_SERVER_CONFIGS``
setting. Each configuration is a deployment profile — which adapters to use, which
access-control callable to run — and is mounted at its own URL prefix.

A configuration may additionally be *scoped*, meaning a tenant key is captured from
the URL on every request. A scoped configuration serves many tenants from the same
profile, with the data of each tenant isolated from the others.

.. code-block:: python

    SCIM2_SERVER_CONFIGS = {
        "staff": {
            "AUTH_CHECK": "django_scim2_server.auth.is_superuser",
        },
        "tenants": {
            "USER_ADAPTER": "myproject.scim.TenantUserAdapter",
            "AUTH_CHECK": "myproject.scim.tenant_token_check",
            "SCOPE_URL_KWARG": "tenant",
        },
    }

The available keys for each configuration are:

``USER_ADAPTER``
    Dotted path to the user adapter class. Defaults to
    ``django_scim2_server.adapters.DefaultUserAdapter``.

``GROUP_ADAPTER``
    Dotted path to the group adapter class. Defaults to
    ``django_scim2_server.adapters.DefaultGroupAdapter``.

``AUTH_CHECK``
    Dotted path to a callable ``(HttpRequest) -> bool`` for access control. Defaults
    to ``django_scim2_server.auth.is_superuser``.

``SCOPE_URL_KWARG``
    Name of the URL keyword argument carrying the tenant key. When set, the
    configuration is scoped and the URL pattern it is mounted under must capture that
    keyword. Defaults to ``None`` (a single, unscoped configuration).

``SERVICE_PROVIDER_CONFIG``
    Dotted path to a :class:`scim2_models.ServiceProviderConfig` instance served by
    the ``/ServiceProviderConfig`` endpoint. Defaults to the built-in one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.module_loading import import_string

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from scim2_models import ServiceProviderConfig

    from django_scim2_server.adapters import BaseGroupAdapter, BaseUserAdapter

#: Name of the Django setting holding the configurations.
SETTING_NAME = "SCIM2_SERVER_CONFIGS"

DEFAULT_USER_ADAPTER = "django_scim2_server.adapters.DefaultUserAdapter"
DEFAULT_GROUP_ADAPTER = "django_scim2_server.adapters.DefaultGroupAdapter"
DEFAULT_AUTH_CHECK = "django_scim2_server.auth.is_superuser"
DEFAULT_SERVICE_PROVIDER_CONFIG = (
    "django_scim2_server.constants.SERVICE_PROVIDER_CONFIG"
)

#: Keys accepted inside a single configuration.
CONFIG_KEYS = frozenset(
    {
        "USER_ADAPTER",
        "GROUP_ADAPTER",
        "AUTH_CHECK",
        "SCOPE_URL_KWARG",
        "SERVICE_PROVIDER_CONFIG",
    }
)


@dataclass(frozen=True)
class SCIMConfig:
    """A resolved SCIM configuration, with all dotted paths imported."""

    name: str
    """The name this configuration is registered under."""

    user_adapter: type[BaseUserAdapter]
    """Adapter class handling ``/Users``."""

    group_adapter: type[BaseGroupAdapter]
    """Adapter class handling ``/Groups``."""

    auth_check: Callable[[HttpRequest], bool]
    """Access-control callable run before every request."""

    service_provider_config: ServiceProviderConfig
    """Document served by ``/ServiceProviderConfig``."""

    scope_url_kwarg: str | None = None
    """URL keyword argument carrying the tenant key, if this config is scoped."""

    @property
    def is_scoped(self) -> bool:
        """Whether this configuration serves multiple tenants."""
        return self.scope_url_kwarg is not None


def get_setting() -> dict[str, Any]:
    """Return the raw ``SCIM2_SERVER_CONFIGS`` setting."""
    from django.conf import settings

    return getattr(settings, SETTING_NAME, None) or {}


def get_config_names() -> list[str]:
    """Return the names of all declared configurations."""
    return sorted(get_setting())


def _build_config(name: str) -> SCIMConfig:
    """Resolve a single configuration from the setting, importing dotted paths."""
    setting = get_setting()
    if name not in setting:
        declared = ", ".join(sorted(setting)) or "none"
        raise ImproperlyConfigured(
            f"No SCIM configuration named '{name}'. "
            f"Add it to {SETTING_NAME} (declared: {declared})."
        )

    options = setting[name] or {}
    if not isinstance(options, dict):
        raise ImproperlyConfigured(
            f"{SETTING_NAME}['{name}'] must be a dict, got {type(options).__name__}."
        )

    unknown = set(options) - CONFIG_KEYS
    if unknown:
        raise ImproperlyConfigured(
            f"Unknown key(s) in {SETTING_NAME}['{name}']: "
            f"{', '.join(sorted(unknown))}. "
            f"Valid keys: {', '.join(sorted(CONFIG_KEYS))}."
        )

    scope_url_kwarg = options.get("SCOPE_URL_KWARG")
    if scope_url_kwarg is not None and not str(scope_url_kwarg).isidentifier():
        raise ImproperlyConfigured(
            f"{SETTING_NAME}['{name}']['SCOPE_URL_KWARG'] must be a valid Python "
            f"identifier, got {scope_url_kwarg!r}."
        )

    from django_scim2_server.adapters import BaseGroupAdapter, BaseUserAdapter

    auth_check = import_string(options.get("AUTH_CHECK", DEFAULT_AUTH_CHECK))
    if not callable(auth_check):
        raise ImproperlyConfigured(
            f"{SETTING_NAME}['{name}']['AUTH_CHECK'] must be a callable taking an "
            f"HttpRequest and returning a bool."
        )

    return SCIMConfig(
        name=name,
        user_adapter=_import_adapter(name, "USER_ADAPTER", options, BaseUserAdapter),
        group_adapter=_import_adapter(name, "GROUP_ADAPTER", options, BaseGroupAdapter),
        auth_check=auth_check,
        service_provider_config=import_string(
            options.get("SERVICE_PROVIDER_CONFIG", DEFAULT_SERVICE_PROVIDER_CONFIG)
        ),
        scope_url_kwarg=scope_url_kwarg,
    )


_DEFAULT_ADAPTERS = {
    "USER_ADAPTER": DEFAULT_USER_ADAPTER,
    "GROUP_ADAPTER": DEFAULT_GROUP_ADAPTER,
}


def _import_adapter(
    config_name: str,
    key: str,
    options: dict[str, Any],
    base: type[Any],
) -> Any:
    """Import an adapter class and check it derives from the expected base."""
    dotted_path = options.get(key, _DEFAULT_ADAPTERS[key])
    adapter = import_string(dotted_path)
    if not (isinstance(adapter, type) and issubclass(adapter, base)):
        raise ImproperlyConfigured(
            f"{SETTING_NAME}['{config_name}']['{key}'] must be a subclass of "
            f"{base.__module__}.{base.__qualname__}, got {dotted_path!r}."
        )
    return adapter


_config_cache: dict[str, SCIMConfig] = {}


def get_config(name: str) -> SCIMConfig:
    """
    Return the resolved configuration registered under ``name``.

    Raises ``ImproperlyConfigured`` if the configuration is not declared, declares an
    unknown key, or points at a dotted path that cannot be imported.
    """
    try:
        return _config_cache[name]
    except KeyError:
        config = _build_config(name)
        _config_cache[name] = config
        return config


def clear_config_cache() -> None:
    """Discard resolved configurations so they are rebuilt from the setting."""
    _config_cache.clear()


@receiver(setting_changed)
def _on_setting_changed(*, setting: str, **kwargs: Any) -> None:
    """Rebuild configurations when the setting is overridden, e.g. in tests."""
    if setting == SETTING_NAME:
        clear_config_cache()
