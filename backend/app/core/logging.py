"""Structured logging configuration.

Configures Python logging to emit JSON-formatted log entries when log_json is
enabled (production), or human-readable entries otherwise (local development).
Every log record is enriched with the current request_id from contextvars so
that all log lines within a single request are correlated.

Satisfies Requirement 30.4.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.observability import sanitize_fields
from app.core.request_context import get_actor, get_correlation_id, get_request_id, get_trace_id


class StructuredFormatter(logging.Formatter):
    """JSON formatter that injects request_id and actor into every log record."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
            "correlation_id": get_correlation_id(),
            "trace_id": get_trace_id(),
        }

        actor = get_actor()
        if actor is not None:
            log_entry["actor"] = str(actor)

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception_type"] = record.exc_info[0].__name__

        # Include only safe extra fields attached to the record.
        if hasattr(record, "extra_fields"):
            log_entry.update(sanitize_fields(record.extra_fields))

        return json.dumps(log_entry, default=str)


class ReadableFormatter(logging.Formatter):
    """Human-readable formatter for local development that still shows request_id."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        req_id = get_request_id() or "-"
        correlation_id = get_correlation_id() or "-"
        trace_id = get_trace_id() or "-"
        base = f"{ts} [{record.levelname:<8}] {record.name} | req={req_id} corr={correlation_id} trace={trace_id} | {record.getMessage()}"
        if record.exc_info and record.exc_info[0] is not None:
            base += f"\nexception={record.exc_info[0].__name__}"
        return base


def setup_logging(*, log_level: str = "INFO", log_json: bool = False) -> None:
    """Configure root logger with the appropriate formatter.

    Args:
        log_level: Minimum severity (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_json: If True, emit structured JSON; otherwise human-readable lines.
    """
    root = logging.getLogger()
    root.setLevel(log_level.upper())

    # Remove any existing handlers to avoid duplicates on re-init
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level.upper())

    if log_json:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(ReadableFormatter())

    root.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
