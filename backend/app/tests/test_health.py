"""Tests for health, readiness, and metrics endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Legacy health endpoint returns 200 with status ok."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_liveness_endpoint(client):
    """Liveness probe returns 200 with status alive."""
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_readiness_endpoint_healthy(client):
    """Readiness probe returns 200 when DB is reachable."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_connect = AsyncMock()
    mock_connect.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_connect.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.routes.health.engine") as mock_engine:
        mock_engine.connect.return_value = mock_connect
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_readiness_endpoint_unhealthy(client):
    """Readiness probe returns 503 when DB is unreachable."""
    mock_connect = AsyncMock()
    mock_connect.__aenter__ = AsyncMock(side_effect=ConnectionError("DB down"))
    mock_connect.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.routes.health.engine") as mock_engine:
        mock_engine.connect.return_value = mock_connect
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["error"]["category"] == "ConnectionError"
    assert data["error"]["message"] == "dependency unavailable"
    assert "DB down" not in str(data)


@pytest.mark.asyncio
async def test_metrics_endpoint(client):
    """Metrics endpoint returns JSON with expected structure."""
    # Mock the engine pool — pool methods are synchronous (MagicMock, not AsyncMock)
    mock_pool = MagicMock()
    mock_pool.size.return_value = 10
    mock_pool.checkedin.return_value = 8
    mock_pool.checkedout.return_value = 2
    mock_pool.overflow.return_value = 0

    with patch("app.api.routes.health.engine") as mock_engine:
        mock_engine.pool = mock_pool
        response = await client.get("/api/v1/metrics")

    assert response.status_code == 200
    data = response.json()

    # Verify top-level structure
    assert "requests" in data
    assert "auth_failures" in data
    assert "export_failures" in data
    assert "worker_failures" in data
    assert "db_connections" in data

    # Verify requests sub-structure
    req = data["requests"]
    assert "total" in req
    assert "error_count" in req
    assert "avg_latency_seconds" in req
    assert "latency_buckets" in req
    assert "status_codes" in req

    # Verify DB connections sub-structure
    db = data["db_connections"]
    assert db["pool_size"] == 10
    assert db["checked_in"] == 8
    assert db["checked_out"] == 2
    assert db["overflow"] == 0


@pytest.mark.asyncio
async def test_openapi_available(client):
    """OpenAPI schema is served under /api/v1."""
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "paths" in data
    assert "/api/v1/health" in data["paths"]
    assert "/api/v1/health/live" in data["paths"]
    assert "/api/v1/health/ready" in data["paths"]
    assert "/api/v1/metrics" in data["paths"]
