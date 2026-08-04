"""SCIM 2.0 proxy models for Users and Groups."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class SCIMUser(models.Model):
    """SCIM metadata linked to a Django user."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    config = models.CharField(max_length=100, db_index=True)
    """Name of the SCIM configuration that provisioned this resource."""

    scope = models.CharField(max_length=255, blank=True, default="", db_index=True)
    """Tenant key within the configuration, empty for unscoped configurations."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="scim_records",
    )
    external_id = models.CharField(
        max_length=255, blank=True, default="", db_index=True
    )
    scim_username = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:  # noqa: D106
        verbose_name = "SCIM User"
        verbose_name_plural = "SCIM Users"
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["config", "scope", "scim_username"],
                name="scim2_unique_username_per_scope",
            ),
            models.UniqueConstraint(
                fields=["config", "scope", "user"],
                name="scim2_unique_user_per_scope",
            ),
        ]

    def __str__(self) -> str:  # noqa: D105
        return self.scim_username


class SCIMGroup(models.Model):
    """SCIM metadata linked to a Django group."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    config = models.CharField(max_length=100, db_index=True)
    """Name of the SCIM configuration that provisioned this resource."""

    scope = models.CharField(max_length=255, blank=True, default="", db_index=True)
    """Tenant key within the configuration, empty for unscoped configurations."""

    group = models.ForeignKey(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="scim_records",
    )
    external_id = models.CharField(
        max_length=255, blank=True, default="", db_index=True
    )
    display_name = models.CharField(max_length=255)
    created = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:  # noqa: D106
        verbose_name = "SCIM Group"
        verbose_name_plural = "SCIM Groups"
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["config", "scope", "group"],
                name="scim2_unique_group_per_scope",
            ),
        ]

    def __str__(self) -> str:  # noqa: D105
        return self.display_name
