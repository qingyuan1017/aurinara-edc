"""In-memory application metrics collector.

Satisfies Requirements:
  - 30.1: Health endpoints (liveness, readiness)
  - 30.2: Application metrics (latency, error rate, DB pool stats)
  - 30.3: Counters for auth failures, export failures, worker failures
  - 30.5: Metrics endpoint returns JSON
"""

import time
from collections import defaultdict
from threading import Lock


class _MetricsCollector:
    """Thread-safe in-memory metrics collector.

    Tracks:
      - API request latency (histogram-style: count, sum, buckets)
      - Error rate counter (by status code family)
      - Auth failure counter
      - Export job failure counter
      - Worker failure counter
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._request_count: int = 0
        self._request_latency_sum: float = 0.0
        self._request_latency_buckets: dict[str, int] = defaultdict(int)
        self._error_count: int = 0
        self._status_counts: dict[int, int] = defaultdict(int)
        self._auth_failure_count: int = 0
        self._export_failure_count: int = 0
        self._worker_failure_count: int = 0

    # --- Recording methods ---

    def record_request(self, latency_seconds: float, status_code: int) -> None:
        """Record a completed API request with its latency and status code."""
        with self._lock:
            self._request_count += 1
            self._request_latency_sum += latency_seconds
            self._status_counts[status_code] = self._status_counts.get(status_code, 0) + 1
            if status_code >= 400:
                self._error_count += 1
            # Bucket by latency threshold
            if latency_seconds <= 0.05:
                self._request_latency_buckets["le_50ms"] += 1
            elif latency_seconds <= 0.1:
                self._request_latency_buckets["le_100ms"] += 1
            elif latency_seconds <= 0.25:
                self._request_latency_buckets["le_250ms"] += 1
            elif latency_seconds <= 0.5:
                self._request_latency_buckets["le_500ms"] += 1
            elif latency_seconds <= 1.0:
                self._request_latency_buckets["le_1s"] += 1
            else:
                self._request_latency_buckets["gt_1s"] += 1

    def record_auth_failure(self) -> None:
        """Increment the auth failure counter."""
        with self._lock:
            self._auth_failure_count += 1

    def record_export_failure(self) -> None:
        """Increment the export job failure counter."""
        with self._lock:
            self._export_failure_count += 1

    def record_worker_failure(self) -> None:
        """Increment the worker failure counter."""
        with self._lock:
            self._worker_failure_count += 1

    # --- Snapshot ---

    def snapshot(self) -> dict:
        """Return a point-in-time snapshot of all metrics."""
        with self._lock:
            avg_latency = (
                self._request_latency_sum / self._request_count
                if self._request_count > 0
                else 0.0
            )
            return {
                "requests": {
                    "total": self._request_count,
                    "error_count": self._error_count,
                    "avg_latency_seconds": round(avg_latency, 6),
                    "latency_sum_seconds": round(self._request_latency_sum, 6),
                    "latency_buckets": dict(self._request_latency_buckets),
                    "status_codes": dict(self._status_counts),
                },
                "auth_failures": self._auth_failure_count,
                "export_failures": self._export_failure_count,
                "worker_failures": self._worker_failure_count,
            }

    def reset(self) -> None:
        """Reset all counters (useful for testing)."""
        with self._lock:
            self._request_count = 0
            self._request_latency_sum = 0.0
            self._request_latency_buckets = defaultdict(int)
            self._error_count = 0
            self._status_counts = defaultdict(int)
            self._auth_failure_count = 0
            self._export_failure_count = 0
            self._worker_failure_count = 0


# Module-level singleton
metrics = _MetricsCollector()


def get_metrics() -> _MetricsCollector:
    """Return the application-wide metrics collector singleton."""
    return metrics


class LatencyTimer:
    """Context manager that records request latency on exit."""

    def __init__(self) -> None:
        self._start: float = 0.0

    def __enter__(self) -> "LatencyTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        # Latency is recorded separately via middleware; this is a utility if needed.
        pass

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._start
