"""Shared, content-safe observability helpers for EDC and CTMS."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "credential",
        "authorization",
        "access_token",
        "refresh_token",
        "raw_event",
        "event_body",
        "clinical_data",
        "field_values",
        "source_document",
        "message_body",
        "query_message",
    }
)


def sanitize_error(exc: BaseException) -> dict[str, str]:
    """Convert an internal exception to a stable, non-sensitive error category."""

    return {
        "category": type(exc).__name__,
        "message": "dependency unavailable" if isinstance(exc, ConnectionError) else "request failed",
    }


def sanitize_fields(value: Any, *, key: str | None = None) -> Any:
    """Recursively remove sensitive observability fields and preserve metadata."""

    if key and key.lower() in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(child_key): sanitize_fields(child_value, key=str(child_key))
            for child_key, child_value in value.items()
            if str(child_key).lower() not in _SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_fields(item) for item in value]
    return value


def sanitized_log_extra(**fields: Any) -> dict[str, Any]:
    """Build safe structured log fields for request/worker metadata."""

    return sanitize_fields(fields)


__all__ = ["sanitize_error", "sanitize_fields", "sanitized_log_extra"]
