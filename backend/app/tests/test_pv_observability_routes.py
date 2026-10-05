"""Integration tests for PV health, readiness, and metrics endpoints.

Validates: Requirements 24.2, 25.1, 25.2, 25.3, 25.4

Exercises the real FastAPI application and the shared PV authorization
dependency against an in-memory database. Confirms that:

  - ``/api/v1/pv/health`` reports liveness, ``/api/v1/pv/ready`` reports
    readiness, and ``/api/v1/pv/metrics`` returns the windowed PV signals;
  - the metrics endpoint reflects PV request activity recorded by the metrics
    middleware and never leaks safety content or raw payloads;
  - every observability route enforces the shared PV permission guard and
    echoes ``X-Request-ID``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.core.database import Base
from app.core.permissions import PV_PERMISSION_CODES
from app.core.security import create_access_token
from app.main import create_app
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.services.pv_observability_service import pv_observability_service


@pytest.fixture(autouse=True)
def _reset_observability():
    pv_observability_service.reset()
    yield
    pv_observability_service.reset()


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models  # noqa: F401 - register every mapped model

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
        await session.commit()


@pytest.fixture
async def users(db_session: AsyncSession) -> dict[str, Any]:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    permissions = {
        code: Permission(id=uuid4(), code=code, description=code)
        for code in PV_PERMISSION_CODES
    }
    db_session.add_all(permissions.values())

    safety_role = Role(
        id=uuid4(), name=f"Safety Admin {uuid4()}", scope_level="system", is_system=True
    )
    viewer_role = Role(
        id=uuid4(), name=f"Safety Viewer {uuid4()}", scope_level="system", is_system=True
    )
    db_session.add_all([safety_role, viewer_role])
    await db_session.flush()

    db_session.add_all(
        [
            RolePermission(role_id=safety_role.id, permission_id=permission.id)
            for permission in permissions.values()
        ]
        + [
            RolePermission(
                role_id=viewer_role.id,
                permission_id=permissions["safety_case.read"].id,
            )
        ]
    )

    safety_user = User(
        id=uuid4(), email=f"pv-admin-{uuid4()}@example.test", first_name="PV",
        last_name="Admin", status=UserStatus.active, last_activity=now,
    )
    viewer = User(
        id=uuid4(), email=f"pv-viewer-{uuid4()}@example.test", first_name="PV",
        last_name="Viewer", status=UserStatus.active, last_activity=now,
    )
    db_session.add_all([safety_user, viewer])
    await db_session.flush()
    db_session.add_all(
        [
            UserRole(user_id=safety_user.id, role_id=safety_role.id),
            UserRole(user_id=viewer.id, role_id=viewer_role.id),
        ]
    )
    await db_session.commit()
    return {"safety_user": safety_user, "viewer": viewer}


@pytest.fixture
def app(async_engine):
    application = create_app()

    async def override_get_db():
        factory = async_sessionmaker(
            bind=async_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.mark.asyncio
async def test_health_reports_liveness(client, users):
    """25.1: liveness returns a Healthy status and echoes X-Request-ID."""
    response = await client.get("/api/v1/pv/health", headers=_auth(users["safety_user"]))
    assert response.status_code == 200
    body = response.json()
    assert body["module"] == "PV"
    assert body["status"] == "Healthy"
    assert response.headers.get("X-Request-ID")


@pytest.mark.asyncio
async def test_ready_reports_readiness(client, users):
    """25.2: readiness returns Ready, and Not Ready when a dependency is down."""
    response = await client.get("/api/v1/pv/ready", headers=_auth(users["safety_user"]))
    assert response.status_code == 200
    assert response.json()["status"] == "Ready"

    pv_observability_service.set_ready(False)
    response = await client.get("/api/v1/pv/ready", headers=_auth(users["safety_user"]))
    assert response.json()["status"] == "Not Ready"


@pytest.mark.asyncio
async def test_metrics_returns_windowed_signals(client, users):
    """25.4: metrics expose PV latency, error rate, and failure/overdue signals."""
    response = await client.get("/api/v1/pv/metrics", headers=_auth(users["safety_user"]))
    assert response.status_code == 200
    body = response.json()
    assert body["module"] == "PV"
    assert body["window_seconds"] >= 300
    assert "api_latency_ms" in body
    assert "error_rate" in body
    assert "worker_job_failures" in body
    assert "export_failures" in body
    assert "overdue_regulatory_reports" in body


@pytest.mark.asyncio
async def test_metrics_reflect_recorded_pv_requests(client, users):
    """25.3/25.4: PV requests handled by the app are counted in the window."""
    headers = _auth(users["safety_user"])
    # Make a couple of PV requests, then read metrics.
    await client.get("/api/v1/pv/health", headers=headers)
    await client.get("/api/v1/pv/ready", headers=headers)

    response = await client.get("/api/v1/pv/metrics", headers=headers)
    body = response.json()
    # At least the two prior PV requests are recorded in the window.
    assert body["api_latency_ms"]["count"] >= 2


@pytest.mark.asyncio
async def test_observability_routes_require_permission(client, users):
    """25.x: observability routes enforce the shared PV permission guard."""
    headers = _auth(users["viewer"])  # lacks safety.audit_read
    for path in ("/api/v1/pv/health", "/api/v1/pv/ready", "/api/v1/pv/metrics"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 403, path


@pytest.mark.asyncio
async def test_metrics_output_has_no_sensitive_keys(client, users):
    """24.2/16.3: the metrics payload carries no sensitive field names."""
    response = await client.get("/api/v1/pv/metrics", headers=_auth(users["safety_user"]))
    text = response.text.lower()
    for forbidden in ("password", "token", "secret", "credential", "raw_event", "clinical_data"):
        assert forbidden not in text
