from django.apps import AppConfig
from django.core.checks import register
from django.utils.translation import gettext_lazy as _


class Scim2ServerAppConfig(AppConfig):
    """App config for Django SCIM2 Server."""

    name = "django_scim2_server"
    verbose_name = _("scim2 server")

    def ready(self) -> None:
        """Register the system checks validating the declared configurations."""
        from django_scim2_server.checks import check_configs

        register(check_configs)
