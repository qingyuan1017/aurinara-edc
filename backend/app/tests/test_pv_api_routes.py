"""Authenticated PV/Safety API route wiring and boundary tests (Task 7.1).

**Validates: Requirements 16.1, 16.2, 16.3, 16.5, 16.6, 18.1, 18.2, 18.4,
23.4, 23.5**

These tests exercise the real FastAPI application, the shared authorization
dependency, the SQLAlchemy session boundary, and the PV routes against an
in-memory database. They confirm that:

  - authenticated PV routes are mounted under ``/api/v1/pv`` and delegate to the
    PV services (case intake, adverse-event capture, lifecycle, assessment,
    narrative, dashboard, export);
  - every route enforces the shared PV permission guard, returns the standard
    sanitized error envelope, and echoes ``X-Request-ID``;
  - a Safety_Data mutation persists exactly one PV safety Audit_Event;
  - PV exposes no mutation route for an EDC clinical or CTMS operational record.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.core.database import Base
from app.core.permissions import PV_PERMISSION_CODES
from app.core.security import create_access_token
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.models.pv.safety_case import CaseState, SafetyCase
from app.models.site import Site
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject


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
async def seeded(db_session: AsyncSession) -> dict[str, Any]:
    """Seed a PV-capable safety user, a read-only user, and canonical identity."""

    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    # Seed every PV permission plus one read-only permission.
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

    study = Study(
        id=uuid4(), study_code=f"PV-{uuid4()}", title="Safety study",
        status=StudyStatus.active, created_by=safety_user.id, created_at=now,
    )
    db_session.add(study)
    await db_session.flush()

    version = StudyVersion(
        id=uuid4(), study_id=study.id, version_number="1.0",
        status=StudyVersionStatus.published, published_at=now,
        published_by=safety_user.id, created_at=now,
    )
    site = Site(
        id=uuid4(), study_id=study.id, site_number="001", name="Site A",
        created_at=now,
    )
    db_session.add_all([version, site])
    await db_session.flush()

    subject = Subject(
        id=uuid4(), study_id=study.id, site_id=site.id, study_version_id=version.id,
        subject_number="S-001", created_by=safety_user.id, created_at=now,
    )
    db_session.add(subject)
    await db_session.commit()

    return {
        "safety_user": safety_user,
        "viewer": viewer,
        "study": study,
        "site": site,
        "subject": subject,
    }


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


async def _audit_count(session: AsyncSession, entity_type: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_type == entity_type
        )
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# Happy-path wiring: intake -> capture -> assessment -> lifecycle -> dashboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_intake_capture_and_lifecycle_flow(client, db_session, seeded):
    """A safety user can drive a case through the wired PV service layer."""

    headers = _auth(seeded["safety_user"])

    create = await client.post(
        "/api/v1/pv/cases",
        json={
            "study_id": str(seeded["study"].id),
            "site_id": str(seeded["site"].id),
            "subject_reference": str(seeded["subject"].id),
            "case_type": "Adverse Event",
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    case = create.json()
    assert case["lifecycle_state"] == CaseState.OPEN.value
    assert case["study_id"] == str(seeded["study"].id)
    # A Safety_Data mutation emits exactly one PV safety Audit_Event.
    assert await _audit_count(db_session, "safety_case") == 1
    case_id = case["id"]

    ae = await client.post(
        f"/api/v1/pv/cases/{case_id}/adverse-events",
        json={
            "verbatim_term": "Headache",
            "onset_date": "2025-01-02",
            "outcome": "Recovered",
        },
        headers=headers,
    )
    assert ae.status_code == 201, ae.text
    ae_id = ae.json()["id"]

    seriousness = await client.post(
        f"/api/v1/pv/adverse-events/{ae_id}/seriousness",
        json={"serious": True, "criteria": ["hospitalization"]},
        headers=headers,
    )
    assert seriousness.status_code == 201, seriousness.text

    transition = await client.post(
        f"/api/v1/pv/cases/{case_id}/transition",
        json={"target": "In Review"},
        headers=headers,
    )
    assert transition.status_code == 200, transition.text
    assert transition.json()["lifecycle_state"] == "In Review"

    listing = await client.get(
        "/api/v1/pv/cases",
        params={"study_id": str(seeded["study"].id)},
        headers=headers,
    )
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["items"][0]["id"] == case_id

    dashboard = await client.get(
        f"/api/v1/pv/studies/{seeded['study'].id}/dashboard",
        headers=headers,
    )
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["study_id"] == str(seeded["study"].id)


@pytest.mark.asyncio
async def test_narrative_create_and_history(client, db_session, seeded):
    """Narrative creation and version history route through the service."""

    headers = _auth(seeded["safety_user"])
    case = (
        await client.post(
            "/api/v1/pv/cases",
            json={
                "study_id": str(seeded["study"].id),
                "site_id": str(seeded["site"].id),
                "subject_reference": str(seeded["subject"].id),
                "case_type": "Adverse Event",
            },
            headers=headers,
        )
    ).json()

    narrative = await client.post(
        f"/api/v1/pv/cases/{case['id']}/narratives",
        json={"text": "Initial narrative text."},
        headers=headers,
    )
    assert narrative.status_code == 201, narrative.text
    narrative_id = narrative.json()["id"]
    assert narrative.json()["current_version_number"] == 1

    history = await client.get(
        f"/api/v1/pv/narratives/{narrative_id}/versions",
        headers=headers,
    )
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1


# ---------------------------------------------------------------------------
# Permission enforcement, error envelope, and request-ID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected_with_request_id(client, seeded):
    """16.5/18.4: an unauthenticated PV mutation is denied and echoes X-Request-ID."""

    response = await client.post(
        "/api/v1/pv/cases",
        json={
            "study_id": str(seeded["study"].id),
            "site_id": str(seeded["site"].id),
            "subject_reference": str(seeded["subject"].id),
            "case_type": "Adverse Event",
        },
    )
    assert response.status_code in {401, 403}
    assert response.headers.get("X-Request-ID")
    body = response.json()
    assert isinstance(body.get("error"), dict)
    assert {"code", "message", "details"}.issubset(body["error"])


@pytest.mark.asyncio
async def test_read_only_user_cannot_mutate_but_can_read(client, db_session, seeded):
    """18.4: a read-only PV user is denied a case mutation with no state change."""

    before = await _audit_count(db_session, "safety_case")
    denied = await client.post(
        "/api/v1/pv/cases",
        json={
            "study_id": str(seeded["study"].id),
            "site_id": str(seeded["site"].id),
            "subject_reference": str(seeded["subject"].id),
            "case_type": "Adverse Event",
        },
        headers=_auth(seeded["viewer"]),
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["details"].get("reason") == "PV_SCOPE_DENIED"
    assert await _audit_count(db_session, "safety_case") == before

    listing = await client.get(
        "/api/v1/pv/cases",
        params={"study_id": str(seeded["study"].id)},
        headers=_auth(seeded["viewer"]),
    )
    assert listing.status_code == 200, listing.text


@pytest.mark.asyncio
async def test_validation_error_uses_sanitized_envelope(client, seeded):
    """16.3: an invalid adverse-event payload returns the sanitized error envelope."""

    headers = _auth(seeded["safety_user"])
    case = (
        await client.post(
            "/api/v1/pv/cases",
            json={
                "study_id": str(seeded["study"].id),
                "site_id": str(seeded["site"].id),
                "subject_reference": str(seeded["subject"].id),
                "case_type": "Adverse Event",
            },
            headers=headers,
        )
    ).json()

    # resolution_date earlier than onset_date is rejected by the service.
    invalid = await client.post(
        f"/api/v1/pv/cases/{case['id']}/adverse-events",
        json={
            "verbatim_term": "Rash",
            "onset_date": "2025-02-01",
            "outcome": "Ongoing",
            "resolution_date": "2025-01-01",
        },
        headers=headers,
    )
    assert invalid.status_code in {400, 409, 422}, invalid.text
    assert invalid.headers.get("X-Request-ID")
    assert isinstance(invalid.json().get("error"), dict)


# ---------------------------------------------------------------------------
# Ownership boundary: no PV mutation route for EDC/CTMS records
# ---------------------------------------------------------------------------


_EDC_CLINICAL_MODELS = (SafetyCase, Subject, StudyVersion, AuditEvent)


async def _snapshot(session: AsyncSession) -> dict[str, tuple]:
    snapshot: dict[str, tuple] = {}
    for model in _EDC_CLINICAL_MODELS:
        rows = list((await session.scalars(select(model))).all())
        columns = [c.key for c in inspect(model).mapper.column_attrs]
        encoded = [
            tuple((c, repr(getattr(row, c))) for c in columns) for row in rows
        ]
        snapshot[model.__tablename__] = tuple(sorted(encoded))
    return snapshot


@pytest.mark.asyncio
async def test_pv_exposes_no_edc_or_ctms_mutation_routes(client, db_session, seeded):
    """23.4/23.5: PV publishes no route that mutates an EDC/CTMS record."""

    before = await _snapshot(db_session)
    headers = _auth(seeded["safety_user"])
    subject_id = seeded["subject"].id
    study_id = seeded["study"].id

    denied = [
        await client.post(
            f"/api/v1/pv/subjects/{subject_id}",
            json={"subject_number": "PV-COMPETING"},
            headers=headers,
        ),
        await client.patch(
            f"/api/v1/pv/visits/{uuid4()}",
            json={"status": "Completed"},
            headers=headers,
        ),
        await client.post(
            f"/api/v1/pv/studies/{study_id}/versions",
            json={"version_number": "2.0"},
            headers=headers,
        ),
        await client.post(
            f"/api/v1/pv/queries/{uuid4()}/respond",
            json={"message": "clinical"},
            headers=headers,
        ),
    ]
    # None of these paths exist on the PV router (thin, additive boundary).
    for response in denied:
        assert response.status_code in {404, 405}, response.text

    assert await _snapshot(db_session) == before


@pytest.mark.asyncio
async def test_pv_openapi_publishes_expected_routes(app):
    """16.1: PV request/response routes are discoverable under /api/v1/pv."""

    schema = app.openapi()
    paths = set(schema["paths"])
    for expected in (
        "/api/v1/pv/cases",
        "/api/v1/pv/cases/{case_id}/adverse-events",
        "/api/v1/pv/adverse-events/{ae_id}/seriousness",
        "/api/v1/pv/adverse-events/{ae_id}/meddra-codings",
        "/api/v1/pv/cases/{case_id}/narratives",
        "/api/v1/pv/cases/{case_id}/reportability",
        "/api/v1/pv/reconciliation/runs",
        "/api/v1/pv/cases/{case_id}/attachments",
        "/api/v1/pv/studies/{study_id}/exports",
        "/api/v1/pv/studies/{study_id}/dashboard",
        "/api/v1/pv/health",
        "/api/v1/pv/metrics",
    ):
        assert expected in paths, expected
