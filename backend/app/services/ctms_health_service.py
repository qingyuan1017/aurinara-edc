"""Sanitized CTMS health and readiness reporting.

The service exposes operational counters and worker state only.  It never
returns queue payloads, clinical values, credentials, or audit/event bodies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any

from app.core.metrics import get_metrics


class CTMSHealthService:
    """Report CTMS worker/readiness metadata without content disclosure."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._worker_status = "available"
        self._last_successful_processing: datetime | None = None
        self._queue_size = 0
        self._queue_capacity = 1
        self._queue_saturated = False

    @property
    def worker_status(self) -> str:
        with self._lock:
            return self._worker_status

    def set_worker_status(self, status: str) -> None:
        """Set a bounded operational status used by readiness and health APIs."""
        normalized = str(status).lower()
        if normalized not in {"available", "degraded", "unavailable"}:
            raise ValueError("worker status must be available, degraded, or unavailable")
        with self._lock:
            self._worker_status = normalized

    def record_successful_processing(self, at: datetime | None = None) -> None:
        """Record only the UTC time of the most recent successful worker run."""
        timestamp = at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("processing timestamps must include timezone information")
        with self._lock:
            self._last_successful_processing = timestamp.astimezone(UTC)
            self._worker_status = "available"

    def set_queue_state(self, size: int, capacity: int, *, saturated: bool = False) -> None:
        """Record bounded queue admission state without retaining event content."""
        with self._lock:
            self._queue_size = max(0, int(size))
            self._queue_capacity = max(1, int(capacity))
            self._queue_saturated = bool(saturated)

    def snapshot(self) -> dict[str, Any]:
        """Return the sanitized CTMS health contract."""
        with self._lock:
            worker_status = self._worker_status
            last_success = self._last_successful_processing
            queue_size = self._queue_size
            queue_capacity = self._queue_capacity
            queue_saturated = self._queue_saturated
        counters = get_metrics().ctms_snapshot()
        return {
            "status": "ready" if worker_status == "available" else "degraded",
            "worker_status": worker_status,
            "pending_event_count": counters["pending_event_count"],
            "failed_event_count": counters["failed_event_count"],
            "conflict_count": counters["conflict_count"],
            "projection_lag_seconds": counters["projection_lag_seconds"],
            "last_successful_processing_time": (
                last_success.isoformat() if last_success is not None else None
            ),
            "queue": {
                "queued_count": queue_size,
                "capacity": queue_capacity,
                "backpressure": queue_saturated,
            },
        }



ctms_health_service = CTMSHealthService()

__all__ = ["CTMSHealthService", "ctms_health_service"]
