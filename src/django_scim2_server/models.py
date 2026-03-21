"""SCIM 2.0 proxy models for Users and Groups."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class SCIMUser(models.Model):
    """SCIM metadata linked to a Django user."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="scim",
    )
    external_id = models.CharField(
        max_length=255, blank=True, default="", db_index=True
    )
    scim_username = models.CharField(max_length=255, unique=True)
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:  # noqa: D106
        verbose_name = "SCIM User"
        verbose_name_plural = "SCIM Users"

    def __str__(self) -> str:  # noqa: D105
        return self.scim_username


class SCIMGroup(models.Model):
    """SCIM metadata linked to a Django group."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.OneToOneField(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="scim",
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

    def __str__(self) -> str:  # noqa: D105
        return self.display_name
