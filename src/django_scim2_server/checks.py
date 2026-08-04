"""System checks validating the ``SCIM2_SERVER_CONFIGS`` setting."""

from __future__ import annotations

from typing import Any

from django.core.checks import CheckMessage, Error, Warning
from django.core.exceptions import ImproperlyConfigured

from django_scim2_server.conf import SETTING_NAME, get_config, get_setting

NO_CONFIGS = "django_scim2_server.W001"
INVALID_CONFIG = "django_scim2_server.E001"


def check_configs(**kwargs: Any) -> list[CheckMessage]:
    """
    Validate every declared SCIM configuration.

    Resolving a configuration imports its adapters and access-control callable and
    checks their types, so this surfaces typos at ``manage.py check`` time rather
    than on the first SCIM request.
    """
    setting = get_setting()
    if not setting:
        return [
            Warning(
                f"{SETTING_NAME} is empty, so no SCIM endpoints will work.",
                hint=(
                    f"Declare at least one configuration, e.g. "
                    f'{SETTING_NAME} = {{"default": {{}}}}.'
                ),
                id=NO_CONFIGS,
            )
        ]

    messages: list[CheckMessage] = []
    for name in sorted(setting):
        try:
            get_config(name)
        except ImproperlyConfigured as exc:
            messages.append(
                Error(f"{SETTING_NAME}['{name}'] is invalid: {exc}", id=INVALID_CONFIG)
            )
        except ImportError as exc:
            messages.append(
                Error(
                    f"{SETTING_NAME}['{name}'] points at something that cannot be "
                    f"imported: {exc}",
                    id=INVALID_CONFIG,
                )
            )
    return messages
