"""Typed application failures that are safe to translate at the HTTP edge.

The exception message is intentionally public.  Internal details belong in the
chained exception (``raise ... from exc``), where Flask can log them without
putting them in an API response.
"""
from __future__ import annotations

from typing import Any, Mapping


class AppError(Exception):
    """Base class for an expected, centrally-rendered application failure."""

    status_code = 500
    default_message = 'Internal server error'
    default_code = 'internal_error'

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        public_fields: Mapping[str, Any] | None = None,
    ) -> None:
        self.public_message = message or self.default_message
        self.code = code or self.default_code
        self.public_fields = dict(public_fields or {})
        super().__init__(self.public_message)

    def response_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'error': self.public_message,
            'code': self.code,
        }
        # Callers may preserve documented, deliberately public fields such as a
        # remediation hint.  Exception objects and upstream payloads never enter
        # this mapping implicitly.
        payload.update(self.public_fields)
        return payload


class ValidationError(AppError):
    status_code = 400
    default_message = 'Invalid request'
    default_code = 'validation_error'


class NotFoundError(AppError):
    status_code = 404
    default_message = 'Resource not found'
    default_code = 'not_found'


class ConflictError(AppError):
    status_code = 409
    default_message = 'Conflict'
    default_code = 'conflict'


class UpstreamError(AppError):
    status_code = 502
    default_message = 'Upstream service failed'
    default_code = 'upstream_error'


class DependencyUnavailableError(AppError):
    status_code = 503
    default_message = 'Service unavailable'
    default_code = 'dependency_unavailable'


class PersistenceError(AppError):
    status_code = 500
    default_message = 'Unable to save data'
    default_code = 'persistence_error'
