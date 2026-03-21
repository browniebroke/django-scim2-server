from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class Scim2ServerAppConfig(AppConfig):
    """App config for Django SCIM2 Server."""

    name = "django_scim2_server"
    verbose_name = _("scim2 server")
