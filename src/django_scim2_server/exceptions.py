"""SCIM 2.0 error types and response helpers."""

from __future__ import annotations

from django.http import JsonResponse
from scim2_models import Error

from django_scim2_server.constants import SCIM_CONTENT_TYPE


class SCIMError(Exception):
    """Base exception for SCIM errors."""

    def __init__(
        self,
        detail: str,
        status: int = 400,
        scim_type: str = "",
    ) -> None:
        self.detail = detail
        self.status = status
        self.scim_type = scim_type
        super().__init__(detail)


class NotFoundError(SCIMError):
    """Resource not found."""

    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(detail=detail, status=404)


class ConflictError(SCIMError):
    """Resource conflict (e.g. uniqueness violation)."""

    def __init__(self, detail: str = "Conflict") -> None:
        super().__init__(detail=detail, status=409, scim_type="uniqueness")


class BadRequestError(SCIMError):
    """Malformed or invalid request."""

    def __init__(self, detail: str = "Bad request") -> None:
        super().__init__(detail=detail, status=400)


class InvalidFilterError(SCIMError):
    """Invalid SCIM filter expression."""

    def __init__(self, detail: str = "Invalid filter") -> None:
        super().__init__(detail=detail, status=400, scim_type="invalidFilter")


class InvalidValueError(SCIMError):
    """Invalid value in request body."""

    def __init__(self, detail: str = "Invalid value") -> None:
        super().__init__(detail=detail, status=400, scim_type="invalidValue")


def scim_error_response(error: SCIMError) -> JsonResponse:
    """Build a SCIM-compliant error JsonResponse."""
    err = Error(
        detail=error.detail,
        status=error.status,
        scim_type=error.scim_type or None,
    )
    body = err.model_dump(mode="json", by_alias=True, exclude_none=True)
    return JsonResponse(body, status=error.status, content_type=SCIM_CONTENT_TYPE)
