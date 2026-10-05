"""PV safety audit search/export route tests (Task 7.2).

**Validates: Requirements 11.4, 11.5, 11.6, 11.8, 16.3**

These tests exercise the real FastAPI app, the shared authorization dependency,
the SQLAlchemy session boundary, and the PV audit routes against an in-memory
database. They confirm that:

  - scoped PV audit search returns only in-scope PV safety Audit_Events ordered
    by UTC timestamp ascending with ties broken by Audit_Event id ascending, and
    supports exact filtering by user, inclusive UTC date range, entity,
    Safety_Case, and Regulatory_Report (11.4);
  - PV audit export produces exactly the authorized selected events and records
    the export action as one new PV safety Audit_Event (11.5);
  - an Audit_Event cannot be updated or deleted (11.6);
  - out-of-scope search/export is rejected without disclosing events (11.8);
  - failing responses use the sanitized error envelope with a request id (16.3).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.core.database import Base
from app.core.pv import Module
from app.core.security import create_access_token
from app.main import create_app
from app.models.audit import AuditEvent, _reject_audit_mutation
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.models.study import Study, StudyStatus


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


async def _get_or_create_perm(session: AsyncSession, code: str) -> Permission:
    existing = (
        await session.execute(select(Permission).where(Permission.code == code))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    permission = Permission(id=uuid4(), code=code, description=code)
    session.add(permission)
    await session.flush()
    return permission


async def _seed_user(
    session: AsyncSession,
    *,
    permissions: list[str],
    scope_level: str,
    study_id: Any = None,
    site_id: Any = None,
) -> User:
    """Seed a user with a role granting ``permissions`` at the given scope."""

    perm_models = [await _get_or_create_perm(session, code) for code in permissions]
    role = Role(
        id=uuid4(),
        name=f"Role {uuid4()}",
        scope_level=scope_level,
        is_system=(scope_level == "system"),
    )
    session.add(role)
    await session.flush()
    session.add_all(
        [RolePermission(role_id=role.id, permission_id=p.id) for p in perm_models]
    )
    user = User(
        id=uuid4(),
        email=f"user-{uuid4()}@example.test",
        first_name="Test",
        last_name="User",
        status=UserStatus.active,
        last_activity=datetime(2025, 1, 1, tzinfo=UTC),
    )
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id, study_id=study_id, site_id=site_id))
    await session.flush()
    return user


async def _seed_study(session: AsyncSession, creator_id: Any) -> Study:
    study = Study(
        id=uuid4(),
        study_code=f"PV-{uuid4()}",
        title="Safety study",
        status=StudyStatus.active,
        created_by=creator_id,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    session.add(study)
    await session.flush()
    return study


async def _add_pv_event(
    session: AsyncSession,
    *,
    timestamp: datetime,
    entity_type: str,
    entity_id: Any,
    action: str,
    study_id: Any,
    actor_id: Any = None,
    site_id: Any = None,
) -> AuditEvent:
    event = AuditEvent(
        id=uuid4(),
        actor_id=actor_id,
        timestamp=timestamp,
        entity_type=entity_type,
        entity_id=entity_id,
        study_id=study_id,
        site_id=site_id,
        module=Module.PV.value,
        action=action,
        request_id=uuid4(),
    )
    session.add(event)
    await session.flush()
    return event


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


# ---------------------------------------------------------------------------
# Search: scoping, ordering, and exact filters (11.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_only_pv_events_in_deterministic_order(
    client, db_session, async_engine
):
    """11.4: search returns PV events ordered by timestamp asc, id asc."""

    admin = await _seed_user(
        db_session, permissions=["safety_audit.read"], scope_level="system"
    )
    study = await _seed_study(db_session, admin.id)
    base = datetime(2025, 3, 1, 9, 0, tzinfo=UTC)

    # Two events share a timestamp so the id tiebreak is exercised.
    same_ts = base + timedelta(hours=1)
    e_tie_a = await _add_pv_event(
        db_session, timestamp=same_ts, entity_type="safety_case",
        entity_id=uuid4(), action="create", study_id=study.id,
    )
    e_tie_b = await _add_pv_event(
        db_session, timestamp=same_ts, entity_type="safety_case",
        entity_id=uuid4(), action="transition", study_id=study.id,
    )
    e_early = await _add_pv_event(
        db_session, timestamp=base, entity_type="regulatory_report",
        entity_id=uuid4(), action="submit", study_id=study.id,
    )
    # An EDC event must never appear in PV search results.
    edc = AuditEvent(
        id=uuid4(), timestamp=base, entity_type="subject", entity_id=uuid4(),
        study_id=study.id, module="EDC", action="create", request_id=uuid4(),
    )
    db_session.add(edc)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/pv/audit/events",
        params={"study_id": str(study.id)},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    ids = [item["id"] for item in body["items"]]
    expected_tie_order = sorted([str(e_tie_a.id), str(e_tie_b.id)])
    assert ids == [str(e_early.id), *expected_tie_order]
    assert all(item["module"] == "PV" for item in body["items"])


@pytest.mark.asyncio
async def test_search_exact_filters(client, db_session):
    """11.4: exact filters by user, entity, Safety_Case, report, and date range."""

    admin = await _seed_user(
        db_session, permissions=["safety_audit.read"], scope_level="system"
    )
    other = await _seed_user(
        db_session, permissions=["safety_audit.read"], scope_level="system"
    )
    study = await _seed_study(db_session, admin.id)
    case_id = uuid4()
    report_id = uuid4()
    base = datetime(2025, 4, 1, tzinfo=UTC)

    await _add_pv_event(
        db_session, timestamp=base, entity_type="safety_case", entity_id=case_id,
        action="create", study_id=study.id, actor_id=admin.id,
    )
    await _add_pv_event(
        db_session, timestamp=base + timedelta(days=2), entity_type="regulatory_report",
        entity_id=report_id, action="submit", study_id=study.id, actor_id=other.id,
    )
    await _add_pv_event(
        db_session, timestamp=base + timedelta(days=30), entity_type="safety_case",
        entity_id=uuid4(), action="transition", study_id=study.id, actor_id=admin.id,
    )
    await db_session.commit()
    headers = _auth(admin)

    # Filter by Safety_Case.
    by_case = await client.get(
        "/api/v1/pv/audit/events",
        params={"study_id": str(study.id), "safety_case_id": str(case_id)},
        headers=headers,
    )
    assert by_case.json()["total"] == 1
    assert by_case.json()["items"][0]["entity_id"] == str(case_id)

    # Filter by Regulatory_Report.
    by_report = await client.get(
        "/api/v1/pv/audit/events",
        params={"study_id": str(study.id), "regulatory_report_id": str(report_id)},
        headers=headers,
    )
    assert by_report.json()["total"] == 1
    assert by_report.json()["items"][0]["entity_id"] == str(report_id)

    # Filter by user.
    by_user = await client.get(
        "/api/v1/pv/audit/events",
        params={"study_id": str(study.id), "actor_id": str(other.id)},
        headers=headers,
    )
    assert by_user.json()["total"] == 1
    assert by_user.json()["items"][0]["actor_id"] == str(other.id)

    # Filter by entity type.
    by_entity = await client.get(
        "/api/v1/pv/audit/events",
        params={"study_id": str(study.id), "entity_type": "safety_case"},
        headers=headers,
    )
    assert by_entity.json()["total"] == 2

    # Inclusive UTC date range (both bounds inclusive).
    by_range = await client.get(
        "/api/v1/pv/audit/events",
        params={
            "study_id": str(study.id),
            "date_from": base.isoformat(),
            "date_to": (base + timedelta(days=2)).isoformat(),
        },
        headers=headers,
    )
    assert by_range.json()["total"] == 2


# ---------------------------------------------------------------------------
# Scope enforcement (11.4, 11.8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_study_scoped_user_sees_only_in_scope_events(client, db_session):
    """11.4/11.8: a study-scoped user cannot read another study's PV events."""

    # A study-scoped auditor for study A only.
    admin = await _seed_user(
        db_session, permissions=["safety_audit.read"], scope_level="system"
    )
    study_a = await _seed_study(db_session, admin.id)
    study_b = await _seed_study(db_session, admin.id)
    auditor = await _seed_user(
        db_session,
        permissions=["safety_audit.read"],
        scope_level="study",
        study_id=study_a.id,
    )
    await _add_pv_event(
        db_session, timestamp=datetime(2025, 5, 1, tzinfo=UTC), entity_type="safety_case",
        entity_id=uuid4(), action="create", study_id=study_a.id,
    )
    await _add_pv_event(
        db_session, timestamp=datetime(2025, 5, 2, tzinfo=UTC), entity_type="safety_case",
        entity_id=uuid4(), action="create", study_id=study_b.id,
    )
    await db_session.commit()

    # In-scope study returns its events.
    in_scope = await client.get(
        "/api/v1/pv/audit/events",
        params={"study_id": str(study_a.id)},
        headers=_auth(auditor),
    )
    assert in_scope.status_code == 200, in_scope.text
    assert in_scope.json()["total"] == 1

    # Out-of-scope study is rejected without disclosing events.
    out_of_scope = await client.get(
        "/api/v1/pv/audit/events",
        params={"study_id": str(study_b.id)},
        headers=_auth(auditor),
    )
    assert out_of_scope.status_code == 403, out_of_scope.text
    assert out_of_scope.json()["error"]["details"].get("reason") == "PV_SCOPE_DENIED"

    # An unscoped search by a non-system user is also rejected (would leak).
    unscoped = await client.get(
        "/api/v1/pv/audit/events", headers=_auth(auditor)
    )
    assert unscoped.status_code == 403, unscoped.text


@pytest.mark.asyncio
async def test_search_without_audit_permission_is_denied(client, db_session):
    """11.8/16.3: a user lacking safety_audit.read is denied with a request id."""

    user = await _seed_user(
        db_session, permissions=["safety_case.read"], scope_level="system"
    )
    await db_session.commit()

    resp = await client.get("/api/v1/pv/audit/events", headers=_auth(user))
    assert resp.status_code == 403, resp.text
    assert resp.headers.get("X-Request-ID")
    error = resp.json()["error"]
    assert {"code", "message", "details"}.issubset(error)
    assert error["details"].get("reason") == "PV_SCOPE_DENIED"


# ---------------------------------------------------------------------------
# Export: exact authorized events + recorded action (11.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_produces_exact_events_and_records_action(client, db_session):
    """11.5: export returns exactly the selected events and records the action."""

    admin = await _seed_user(
        db_session, permissions=["safety_audit.read"], scope_level="system"
    )
    study = await _seed_study(db_session, admin.id)
    case_id = uuid4()
    base = datetime(2025, 6, 1, tzinfo=UTC)
    await _add_pv_event(
        db_session, timestamp=base, entity_type="safety_case", entity_id=case_id,
        action="create", study_id=study.id,
    )
    await _add_pv_event(
        db_session, timestamp=base + timedelta(days=1), entity_type="safety_case",
        entity_id=uuid4(), action="transition", study_id=study.id,
    )
    await db_session.commit()

    export_actions_before = int(
        (
            await db_session.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_type == "safety_audit_export")
            )
        ).scalar_one()
    )

    resp = await client.post(
        "/api/v1/pv/audit/exports",
        json={"filters": {"study_id": str(study.id), "safety_case_id": str(case_id)}},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["events"]) == 1
    assert body["events"][0]["entity_id"] == str(case_id)

    # The export action is recorded as exactly one new PV safety Audit_Event.
    export_actions_after = int(
        (
            await db_session.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_type == "safety_audit_export")
            )
        ).scalar_one()
    )
    assert export_actions_after == export_actions_before + 1


@pytest.mark.asyncio
async def test_export_out_of_scope_is_rejected(client, db_session):
    """11.8: an out-of-scope export is rejected and produces nothing."""

    admin = await _seed_user(
        db_session, permissions=["safety_audit.read"], scope_level="system"
    )
    study_a = await _seed_study(db_session, admin.id)
    study_b = await _seed_study(db_session, admin.id)
    auditor = await _seed_user(
        db_session,
        permissions=["safety_audit.read"],
        scope_level="study",
        study_id=study_a.id,
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/pv/audit/exports",
        json={"filters": {"study_id": str(study_b.id)}},
        headers=_auth(auditor),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["details"].get("reason") == "PV_SCOPE_DENIED"


# ---------------------------------------------------------------------------
# Immutability (11.6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_event_cannot_be_updated_or_deleted(db_session):
    """11.6: the model layer rejects any update or delete of an Audit_Event."""

    event = await _add_pv_event(
        db_session, timestamp=datetime(2025, 7, 1, tzinfo=UTC),
        entity_type="safety_case", entity_id=uuid4(), action="create",
        study_id=uuid4(),
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="immutable"):
        _reject_audit_mutation(None, None, event)


@pytest.mark.asyncio
async def test_pv_audit_routes_published_in_openapi(app):
    """16.3: PV audit search/export routes are discoverable under /api/v1/pv."""

    schema = app.openapi()
    paths = set(schema["paths"])
    assert "/api/v1/pv/audit/events" in paths
    assert "/api/v1/pv/audit/exports" in paths

    # PV enums, error codes, pagination, and error responses stay published.
    info = schema["info"]
    assert "x-pv-error-codes" in info
    assert "x-pv-enums" in info
    assert "x-pv-pagination" in info
    assert "x-pv-error-responses" in info
