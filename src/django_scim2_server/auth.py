"""Built-in authentication check callables for SCIM views."""

from __future__ import annotations

from django.http import HttpRequest


def is_superuser(request: HttpRequest) -> bool:
    """Allow access only to authenticated superusers (default)."""
    user = request.user
    return bool(user and user.is_authenticated and user.is_superuser)


def is_authenticated(request: HttpRequest) -> bool:
    """Allow access to any authenticated user."""
    return bool(request.user and request.user.is_authenticated)


def get_bearer_token(request: HttpRequest) -> str | None:
    """Return the token of an ``Authorization: Bearer <token>`` header, if any."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()
