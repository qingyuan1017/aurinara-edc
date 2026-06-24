"""Tests for the in-memory metrics collector."""

import pytest

from app.core.metrics import _MetricsCollector


@pytest.fixture
def collector():
    """Fresh metrics collector for each test."""
    return _MetricsCollector()


def test_record_request_success(collector):
    """Successful requests are counted with correct latency bucket."""
    collector.record_request(0.03, 200)
    snap = collector.snapshot()
    assert snap["requests"]["total"] == 1
    assert snap["requests"]["error_count"] == 0
    assert snap["requests"]["latency_buckets"]["le_50ms"] == 1
    assert snap["requests"]["status_codes"][200] == 1


def test_record_request_error(collector):
    """4xx/5xx requests increment the error counter."""
    collector.record_request(0.1, 500)
    snap = collector.snapshot()
    assert snap["requests"]["total"] == 1
    assert snap["requests"]["error_count"] == 1
    assert snap["requests"]["latency_buckets"]["le_100ms"] == 1


def test_latency_buckets(collector):
    """Requests are sorted into correct latency buckets."""
    collector.record_request(0.04, 200)   # le_50ms
    collector.record_request(0.08, 200)   # le_100ms
    collector.record_request(0.2, 200)    # le_250ms
    collector.record_request(0.4, 200)    # le_500ms
    collector.record_request(0.8, 200)    # le_1s
    collector.record_request(2.0, 200)    # gt_1s
    snap = collector.snapshot()
    buckets = snap["requests"]["latency_buckets"]
    assert buckets["le_50ms"] == 1
    assert buckets["le_100ms"] == 1
    assert buckets["le_250ms"] == 1
    assert buckets["le_500ms"] == 1
    assert buckets["le_1s"] == 1
    assert buckets["gt_1s"] == 1


def test_avg_latency(collector):
    """Average latency is computed correctly."""
    collector.record_request(0.1, 200)
    collector.record_request(0.3, 200)
    snap = collector.snapshot()
    assert snap["requests"]["avg_latency_seconds"] == pytest.approx(0.2, abs=1e-6)


def test_auth_failure_counter(collector):
    """Auth failure counter increments correctly."""
    collector.record_auth_failure()
    collector.record_auth_failure()
    snap = collector.snapshot()
    assert snap["auth_failures"] == 2


def test_export_failure_counter(collector):
    """Export failure counter increments correctly."""
    collector.record_export_failure()
    snap = collector.snapshot()
    assert snap["export_failures"] == 1


def test_worker_failure_counter(collector):
    """Worker failure counter increments correctly."""
    collector.record_worker_failure()
    collector.record_worker_failure()
    collector.record_worker_failure()
    snap = collector.snapshot()
    assert snap["worker_failures"] == 3


def test_reset(collector):
    """Reset clears all counters."""
    collector.record_request(0.1, 200)
    collector.record_auth_failure()
    collector.record_export_failure()
    collector.record_worker_failure()
    collector.reset()
    snap = collector.snapshot()
    assert snap["requests"]["total"] == 0
    assert snap["auth_failures"] == 0
    assert snap["export_failures"] == 0
    assert snap["worker_failures"] == 0


def test_snapshot_empty(collector):
    """Empty collector returns zero values without error."""
    snap = collector.snapshot()
    assert snap["requests"]["total"] == 0
    assert snap["requests"]["avg_latency_seconds"] == 0.0
