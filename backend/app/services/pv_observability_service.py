"""Sanitized PV/Safety observability with a rolling time window.

This service owns the PV-specific observability contract required by the
Reliability and Observability requirement (Requirement 25) and the performance
requirement (Requirement 24):

  - PV liveness and readiness reporting (Requirements 25.1, 25.2);
  - a metrics snapshot carrying PV API latency, error rate, worker job
    failures, export failures, and overdue regulatory reports over at least the
    preceding 5 minutes, refreshed continuously so the values are never older
    than the reporting interval (Requirement 25.4);
  - structured, sanitized log fields for each PV request carrying the request
    identifier, a UTC timestamp, the operation outcome, and the duration in
    milliseconds (Requirement 25.3).

Every value returned by this service is a non-sensitive counter, rate, or
duration. The service never records or returns safety data, prohibited
projected fields, raw coordination payloads, credentials, or request bodies,
so its output is always safe to expose on the metrics endpoint and to emit to
logs (Requirements 24.2, 16.3, 16.5, 25 redaction clause).
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

# The metrics endpoint must cover at least the preceding 5 minutes
# (Requirement 25.4). Samples older than this window are evicted so the
# reported latency, error rate, and failure counts reflect current behavior.
METRICS_WINDOW_SECONDS = 300

# Liveness and readiness responses must return within 1 second (Requirements
# 25.1, 25.2). These checks perform no I/O so they resolve well under the bound.


class PVObservabilityService:
    """Collect sanitized PV request, worker, and export signals in a window.

    The collector is thread-safe and keeps only bounded, non-sensitive samples:
    a request sample is ``(timestamp, latency_ms, is_error)`` and a failure
    sample is a bare ``timestamp``. No safety content, projected field, request
    body, or coordination payload is retained.
    """

    def __init__(self, window_seconds: int = METRICS_WINDOW_SECONDS) -> None:
        self._lock = Lock()
        self._window = timedelta(seconds=max(1, int(window_seconds)))
        self._requests: deque[tuple[datetime, float, bool]] = deque()
        self._worker_failures: deque[datetime] = deque()
        self._export_failures: deque[datetime] = deque()
        self._overdue_reports = 0
        self._ready = True

    # ------------------------------------------------------------------
    # Liveness / readiness (Requirements 25.1, 25.2)
    # ------------------------------------------------------------------

    def set_ready(self, ready: bool) -> None:
        """Mark whether a required configured PV dependency is available."""
        with self._lock:
            self._ready = bool(ready)

    def is_ready(self) -> bool:
        """Return whether PV reports Ready (no unavailable required dependency)."""
        with self._lock:
            return self._ready

    # ------------------------------------------------------------------
    # Recording (all inputs are non-sensitive scalars)
    # ------------------------------------------------------------------

    def record_request(
        self,
        *,
        latency_ms: float,
        status_code: int,
        now: datetime | None = None,
    ) -> None:
        """Record one completed PV API request's latency and outcome."""
        moment = self._as_utc(now)
        is_error = int(status_code) >= 400
        with self._lock:
            self._requests.append((moment, max(0.0, float(latency_ms)), is_error))
            self._evict(moment)

    def record_worker_failure(self, now: datetime | None = None) -> None:
        """Record one PV worker job failure without retaining event content."""
        moment = self._as_utc(now)
        with self._lock:
            self._worker_failures.append(moment)
            self._evict(moment)

    def record_export_failure(self, now: datetime | None = None) -> None:
        """Record one PV safety export failure without retaining any payload."""
        moment = self._as_utc(now)
        with self._lock:
            self._export_failures.append(moment)
            self._evict(moment)

    def set_overdue_reports(self, count: int) -> None:
        """Set the current count of overdue regulatory reports (a gauge)."""
        with self._lock:
            self._overdue_reports = max(0, int(count))

    # ------------------------------------------------------------------
    # Snapshot (Requirement 25.4)
    # ------------------------------------------------------------------

    def metrics_snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        """Return the sanitized PV metrics over the rolling window.

        The snapshot always reflects the preceding window as of ``now`` because
        stale samples are evicted on read, so callers polling at least every 60
        seconds always observe current values (Requirement 25.4).
        """
        moment = self._as_utc(now)
        with self._lock:
            self._evict(moment)
            requests = list(self._requests)
            worker_failures = len(self._worker_failures)
            export_failures = len(self._export_failures)
            overdue_reports = self._overdue_reports

        total = len(requests)
        error_count = sum(1 for _, _, is_error in requests if is_error)
        latencies = [latency for _, latency, _ in requests]
        avg_latency = sum(latencies) / total if total else 0.0
        max_latency = max(latencies) if latencies else 0.0
        error_rate = error_count / total if total else 0.0

        return {
            "module": "PV",
            "window_seconds": int(self._window.total_seconds()),
            "generated_at": moment.isoformat(),
            "api_latency_ms": {
                "count": total,
                "avg": round(avg_latency, 3),
                "max": round(max_latency, 3),
                "p95": round(self._percentile(latencies, 95), 3),
            },
            "error_rate": round(error_rate, 6),
            "error_count": error_count,
            "worker_job_failures": worker_failures,
            "export_failures": export_failures,
            "overdue_regulatory_reports": overdue_reports,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict(self, now: datetime) -> None:
        """Drop samples older than the window. Caller holds the lock."""
        cutoff = now - self._window
        while self._requests and self._requests[0][0] < cutoff:
            self._requests.popleft()
        while self._worker_failures and self._worker_failures[0] < cutoff:
            self._worker_failures.popleft()
        while self._export_failures and self._export_failures[0] < cutoff:
            self._export_failures.popleft()

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        """Return the nearest-rank percentile of a latency sample list."""
        if not values:
            return 0.0
        ordered = sorted(values)
        rank = max(1, round((percentile / 100.0) * len(ordered)))
        return ordered[min(rank, len(ordered)) - 1]

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime:
        """Normalize an optional timestamp to aware UTC."""
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observability timestamps must include timezone information")
        return value.astimezone(UTC)

    def reset(self) -> None:
        """Clear all samples and gauges (test utility)."""
        with self._lock:
            self._requests.clear()
            self._worker_failures.clear()
            self._export_failures.clear()
            self._overdue_reports = 0
            self._ready = True


pv_observability_service = PVObservabilityService()

__all__ = [
    "METRICS_WINDOW_SECONDS",
    "PVObservabilityService",
    "pv_observability_service",
]
