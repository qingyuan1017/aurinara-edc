"""Unit tests for the sanitized PV observability service (Requirement 25).

Validates: Requirements 24.2, 25.1, 25.2, 25.3, 25.4

These tests exercise the rolling-window collector directly with deterministic
timestamps and require no database, queue, object storage, or other external
service.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.pv_observability_service import (
    METRICS_WINDOW_SECONDS,
    PVObservabilityService,
)


@pytest.fixture
def service() -> PVObservabilityService:
    return PVObservabilityService()


def test_window_is_at_least_five_minutes():
    """25.4: the reporting window covers at least the preceding 5 minutes."""
    assert METRICS_WINDOW_SECONDS >= 300


def test_readiness_defaults_ready_and_toggles(service: PVObservabilityService):
    """25.2: readiness reports Ready unless a dependency is marked unavailable."""
    assert service.is_ready() is True
    service.set_ready(False)
    assert service.is_ready() is False
    service.set_ready(True)
    assert service.is_ready() is True


def test_snapshot_reports_zeroes_when_empty(service: PVObservabilityService):
    snap = service.metrics_snapshot()
    assert snap["module"] == "PV"
    assert snap["window_seconds"] >= 300
    assert snap["api_latency_ms"]["count"] == 0
    assert snap["error_rate"] == 0.0
    assert snap["worker_job_failures"] == 0
    assert snap["export_failures"] == 0
    assert snap["overdue_regulatory_reports"] == 0


def test_snapshot_aggregates_latency_and_error_rate(service: PVObservabilityService):
    """25.4: the snapshot reports PV API latency and error rate."""
    now = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    service.record_request(latency_ms=100.0, status_code=200, now=now)
    service.record_request(latency_ms=300.0, status_code=200, now=now)
    service.record_request(latency_ms=200.0, status_code=500, now=now)

    snap = service.metrics_snapshot(now=now)
    assert snap["api_latency_ms"]["count"] == 3
    assert snap["api_latency_ms"]["avg"] == pytest.approx(200.0)
    assert snap["api_latency_ms"]["max"] == pytest.approx(300.0)
    assert snap["error_count"] == 1
    assert snap["error_rate"] == pytest.approx(1 / 3, abs=1e-6)


def test_worker_and_export_failures_counted(service: PVObservabilityService):
    """25.4: worker job failures and export failures are reported."""
    now = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    service.record_worker_failure(now=now)
    service.record_worker_failure(now=now)
    service.record_export_failure(now=now)

    snap = service.metrics_snapshot(now=now)
    assert snap["worker_job_failures"] == 2
    assert snap["export_failures"] == 1


def test_overdue_reports_gauge(service: PVObservabilityService):
    """25.4: overdue regulatory reports are reported as a gauge."""
    service.set_overdue_reports(4)
    assert service.metrics_snapshot()["overdue_regulatory_reports"] == 4
    # A gauge is replaced, not accumulated.
    service.set_overdue_reports(1)
    assert service.metrics_snapshot()["overdue_regulatory_reports"] == 1


def test_stale_samples_evicted_outside_window(service: PVObservabilityService):
    """25.4: samples older than the window no longer affect the snapshot."""
    start = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    service.record_request(latency_ms=500.0, status_code=500, now=start)
    service.record_worker_failure(now=start)
    service.record_export_failure(now=start)

    # Advance beyond the window; the old samples must be evicted on read.
    later = start + timedelta(seconds=METRICS_WINDOW_SECONDS + 1)
    service.record_request(latency_ms=50.0, status_code=200, now=later)

    snap = service.metrics_snapshot(now=later)
    assert snap["api_latency_ms"]["count"] == 1
    assert snap["error_count"] == 0
    assert snap["worker_job_failures"] == 0
    assert snap["export_failures"] == 0


def test_recent_samples_retained_within_window(service: PVObservabilityService):
    start = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    service.record_request(latency_ms=120.0, status_code=200, now=start)
    within = start + timedelta(seconds=METRICS_WINDOW_SECONDS - 1)
    service.record_request(latency_ms=80.0, status_code=200, now=within)

    snap = service.metrics_snapshot(now=within)
    assert snap["api_latency_ms"]["count"] == 2


def test_naive_timestamp_rejected(service: PVObservabilityService):
    with pytest.raises(ValueError):
        service.record_request(latency_ms=10.0, status_code=200, now=datetime(2025, 1, 1))


def test_snapshot_contains_only_sanitized_scalar_fields(service: PVObservabilityService):
    """24.2/16.3: the snapshot exposes only non-sensitive counters and rates."""
    now = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    service.record_request(latency_ms=10.0, status_code=200, now=now)
    snap = service.metrics_snapshot(now=now)

    allowed = {
        "module",
        "window_seconds",
        "generated_at",
        "api_latency_ms",
        "error_rate",
        "error_count",
        "worker_job_failures",
        "export_failures",
        "overdue_regulatory_reports",
    }
    assert set(snap) == allowed
    # No nested field carries free-form content; latency is a scalar summary.
    assert set(snap["api_latency_ms"]) == {"count", "avg", "max", "p95"}
