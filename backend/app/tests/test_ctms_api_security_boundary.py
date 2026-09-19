"""Direct API security and EDC-boundary integration tests for CTMS.

# Feature: ctms-integration, Task 6.7: API security and EDC-boundary integration tests

These tests use the real FastAPI application, shared authorization dependency,
SQLAlchemy session boundary, CTMS routes, and EDC clinical models.  Every
negative request is checked against a before/after snapshot so a denial cannot
silently write an operational record, projection, coordination record, audit
event, or clinical record.

**Validates: Requirements 1.5, 1.8, 5.6-5.13, 6.12-6.15, 8.8-8.10,
10.11-10.18, 11.6-11.10, 14.4-14.5**
"""

from __future__ import annotations

from datetime import UTC, datetime, date
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.core.database import Base
from app.core.security import create_access_token
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.ctms.coordination import CTMSCoordinationEventLog, CTMSOutbox
from app.models.ctms.enrollment import EnrollmentTarget, OperationalMilestone
from app.models.ctms.monitoring import (
    MonitoringActivity,
    MonitoringActivityScheduleHistory,
    MonitoringPlan,
    MonitoringPlanVersion,
)
from app.models.ctms.operational_site import ActivationAction, OperationalSite
from app.models.ctms.operational_study import (
    EnrollmentPlan,
    OperationalStudy,
    ReadinessCriterion,
    StudyOperationalMilestone,
    StudyPlan,
)
from app.models.ctms.projection import CTMSOperationalProjection
from app.models.ctms.work import (
    OperationalContact,
    OperationalTask,
    TaskDependency,
    TaskEscalation,
)
from app.models.file_attachment import FileAttachment
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.models.query import Query, QueryMessage, QueryStatus, QueryTargetType
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitInstance, VisitInstanceStatus


@pytest.fixture
async def async_engine():
    """Create the complete local schema without external services."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models  # noqa: F401 - register every mapped model

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.commit()


@pytest.fixture
async def seeded(db_session: AsyncSession) -> dict[str, Any]:
    """Seed two studies, a clinical subject graph, CTMS roles, and sensitive rows."""

    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    permission_codes = {
        "ctms.operational-data-read",
        "ctms.operational-study-management",
        "ctms.operational-site-management",
        "ctms.enrollment-management",
        "ctms.monitoring-activity-management",
        "ctms.coordination-replay",
        "ctms.conflict-management",
    }
    permissions = {
        code: Permission(id=uuid4(), code=code, description=code)
        for code in permission_codes
    }
    db_session.add_all(permissions.values())

    admin_role = Role(
        id=uuid4(), name=f"CTMS Admin {uuid4()}", scope_level="system", is_system=True
    )
    viewer_role = Role(
        id=uuid4(), name=f"CTMS Viewer {uuid4()}", scope_level="system", is_system=True
    )
    out_of_scope_role = Role(
        id=uuid4(), name=f"CTMS Scoped Viewer {uuid4()}", scope_level="study", is_system=False
    )
    db_session.add_all([admin_role, viewer_role, out_of_scope_role])
    await db_session.flush()

    db_session.add_all(
        [
            RolePermission(role_id=admin_role.id, permission_id=permission.id)
            for permission in permissions.values()
        ]
        + [
            RolePermission(
                role_id=viewer_role.id,
                permission_id=permissions["ctms.operational-data-read"].id,
            ),
            RolePermission(
                role_id=out_of_scope_role.id,
                permission_id=permissions["ctms.operational-data-read"].id,
            ),
        ]
    )

    admin = User(
        id=uuid4(), email=f"ctms-admin-{uuid4()}@example.test", first_name="CTMS",
        last_name="Admin", status=UserStatus.active, last_activity=now,
    )
    viewer = User(
        id=uuid4(), email=f"ctms-viewer-{uuid4()}@example.test", first_name="CTMS",
        last_name="Viewer", status=UserStatus.active, last_activity=now,
    )
    out_of_scope = User(
        id=uuid4(), email=f"ctms-outscope-{uuid4()}@example.test", first_name="Out",
        last_name="OfScope", status=UserStatus.active, last_activity=now,
    )
    db_session.add_all([admin, viewer, out_of_scope])
    await db_session.flush()

    study = Study(
        id=uuid4(), study_code=f"SEC-{uuid4()}", title="Security boundary study",
        status=StudyStatus.active, created_by=admin.id, created_at=now,
    )
    other_study = Study(
        id=uuid4(), study_code=f"OTHER-{uuid4()}", title="Out of scope study",
        status=StudyStatus.active, created_by=admin.id, created_at=now,
    )
    db_session.add_all([study, other_study])
    await db_session.flush()

    db_session.add_all(
        [
            UserRole(user_id=admin.id, role_id=admin_role.id),
            UserRole(user_id=viewer.id, role_id=viewer_role.id),
            UserRole(
                user_id=out_of_scope.id,
                role_id=out_of_scope_role.id,
                study_id=other_study.id,
            ),
        ]
    )
    site = Site(
        id=uuid4(), study_id=study.id, site_number="SEC-001", name="Security site",
        status=SiteStatus.active, created_at=now,
    )
    version = StudyVersion(
        id=uuid4(), study_id=study.id, version_number="1.0",
        status=StudyVersionStatus.published, published_at=now, published_by=admin.id,
        created_at=now,
    )
    db_session.add_all([site, version])
    await db_session.flush()

    subject = Subject(
        id=uuid4(), study_id=study.id, site_id=site.id, study_version_id=version.id,
        subject_number="SEC-001-0001", status=SubjectStatus.enrolled,
        created_by=admin.id, created_at=now,
    )
    visit = VisitInstance(
        id=uuid4(), subject_id=subject.id, name="Week 4", visit_date=date(2025, 2, 1),
        window_status="in_window", status=VisitInstanceStatus.scheduled, created_at=now,
    )
    query = Query(
        id=uuid4(), study_id=study.id, site_id=site.id, subject_id=subject.id,
        target_type=QueryTargetType.subject.value, target_id=subject.id,
        text="EDC-owned query text must never become CTMS data", status=QueryStatus.open,
        created_by=admin.id, created_at=now,
    )
    query_message = QueryMessage(
        id=uuid4(), query_id=query.id, author_id=admin.id,
        message="EDC unrestricted query message", created_at=now,
    )
    db_session.add_all([subject, visit, query, query_message])

    projection = CTMSOperationalProjection(
        id=uuid4(), projection_type="subject_status", source_module="EDC",
        source_record_id=subject.id, study_id=study.id, site_id=site.id,
        subject_id=subject.id, source_version="1", source_timestamp=now,
        rule_version=1, correlation_id="security-projection", projected_at=now,
        payload_json={"subject_id": str(subject.id), "status": "Enrolled", "source_version": "1"},
        payload_fingerprint="projection-fingerprint",
    )
    failed_event = CTMSOutbox(
        id=uuid4(), event_id=uuid4(), aggregate_type="subject", aggregate_id=subject.id,
        event_type="subject.status.changed", module="EDC", source_module="EDC",
        target_module="CTMS", source_record_id=subject.id, correlation_id="failed-event",
        status="Failed", last_error_category="PROJECTION_FIELD_NOT_ALLOWED", available_at=now,
        payload_json={
            "study_id": str(study.id),
            "raw_event_body": "RAW_EVENT_SECRET",
            "clinical_data": "CLINICAL_SECRET",
            "unrestricted_query_message": "QUERY_SECRET",
        },
    )
    conflict_event = CTMSOutbox(
        id=uuid4(), event_id=uuid4(), aggregate_type="subject", aggregate_id=subject.id,
        event_type="subject.status.conflict", module="EDC", source_module="EDC",
        target_module="CTMS", source_record_id=subject.id, correlation_id="conflict-event",
        status="Conflict", last_error_category="COORDINATION_CONFLICT", available_at=now,
        payload_json={"study_id": str(study.id)},
    )
    attachment = FileAttachment(
        id=uuid4(), module="EDC", attachment_type="Clinical_Attachment",
        object_type="subject", object_id=subject.id, study_id=study.id, site_id=site.id,
        subject_id=subject.id, filename="clinical-source.txt", content_type="text/plain",
        size_bytes=19, storage_key="clinical/secret-source.txt", uploaded_by=admin.id,
        uploaded_at=now,
    )
    db_session.add_all([projection, failed_event, conflict_event, attachment])
    await db_session.commit()

    return {
        "admin": admin,
        "viewer": viewer,
        "out_of_scope": out_of_scope,
        "study": study,
        "other_study": other_study,
        "site": site,
        "version": version,
        "subject": subject,
        "visit": visit,
        "query": query,
        "projection": projection,
        "failed_event": failed_event,
        "conflict_event": conflict_event,
        "attachment": attachment,
    }


@pytest.fixture
def app(async_engine):
    application = create_app()

    async def override_get_db():
        factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
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


_SNAPSHOT_MODELS = (
    OperationalStudy,
    OperationalSite,
    ActivationAction,
    StudyPlan,
    EnrollmentPlan,
    ReadinessCriterion,
    StudyOperationalMilestone,
    EnrollmentTarget,
    OperationalMilestone,
    MonitoringPlan,
    MonitoringPlanVersion,
    MonitoringActivity,
    MonitoringActivityScheduleHistory,
    OperationalTask,
    OperationalContact,
    TaskDependency,
    TaskEscalation,
    CTMSOperationalProjection,
    CTMSCoordinationEventLog,
    CTMSOutbox,
    AuditEvent,
    StudyVersion,
    Subject,
    VisitInstance,
    Query,
    QueryMessage,
    FileAttachment,
)


async def _snapshot(session: AsyncSession) -> dict[str, tuple[tuple[str, str], ...]]:
    """Capture all boundary rows using mapped columns, not ORM identity state."""

    snapshot: dict[str, tuple[tuple[str, str], ...]] = {}
    for model in _SNAPSHOT_MODELS:
        rows = list((await session.scalars(select(model))).all())
        columns = [column.key for column in inspect(model).mapper.column_attrs]
        encoded = []
        for row in rows:
            encoded.append(tuple((column, repr(getattr(row, column))) for column in columns))
        snapshot[model.__tablename__] = tuple(sorted(encoded))
    return snapshot


def _assert_denied(response, *, allowed_statuses: set[int] | None = None) -> None:
    statuses = allowed_statuses or {401, 403, 404, 405, 409, 422}
    assert response.status_code in statuses, response.text
    if response.status_code != 404:
        body = response.json()
        if response.status_code == 405:
            assert body.get("detail") == "Method Not Allowed" or isinstance(body.get("error"), dict)
        else:
            assert isinstance(body.get("error"), dict)
            assert {"code", "message", "details"}.issubset(body["error"])
    assert response.headers.get("X-Request-ID")


@pytest.mark.asyncio
async def test_ctms_denial_matrix_is_side_effect_free(client, db_session, seeded):
    """Reject clinical writes, scope violations, viewer writes, and remediation bypasses."""

    before = await _snapshot(db_session)
    admin_headers = _auth(seeded["admin"])
    viewer_headers = _auth(seeded["viewer"])
    out_scope_headers = _auth(seeded["out_of_scope"])
    study_id = seeded["study"].id
    subject_id = seeded["subject"].id
    visit_id = seeded["visit"].id
    query_id = seeded["query"].id
    failed_event_id = seeded["failed_event"].event_id
    conflict_id = seeded["conflict_event"].id

    denied = []
    denied.append(
        await client.post(
            f"/api/v1/ctms/studies/{study_id}/operational-profile",
            json={
                "sponsor": "Operations only",
                "planning_metadata": {"clinical_data": "CLINICAL_SECRET"},
            },
            headers=admin_headers,
        )
    )
    # CTMS exposes no competing clinical-subject creation endpoint.  The
    # operational milestone endpoint also forbids EDC-owned injection fields.
    denied.append(
        await client.post(
            f"/api/v1/ctms/subjects/{subject_id}",
            json={"subject_number": "COMPETING-CLINICAL-SUBJECT"},
            headers=admin_headers,
        )
    )
    denied.append(
        await client.post(
            f"/api/v1/ctms/subjects/{subject_id}/operational-milestones",
            json={
                "study_id": str(study_id),
                "subject_id": str(subject_id),
                "milestone_type": "Enrolled",
                "milestone_date": "2025-03-01T00:00:00Z",
                "status": "Enrolled",
                "clinical_subject_id": str(subject_id),
            },
            headers=admin_headers,
        )
    )
    # No CTMS route can mutate protocol visits or EDC query lifecycle/messages.
    denied.append(
        await client.patch(
            f"/api/v1/ctms/visits/{visit_id}",
            json={"visit_date": "2025-04-01", "status": "Completed"},
            headers=admin_headers,
        )
    )
    denied.append(
        await client.post(
            f"/api/v1/ctms/queries/{query_id}/respond",
            json={"message": "QUERY_SECRET"},
            headers=admin_headers,
        )
    )
    # Projection persistence is service/worker-only; the public API is read-only.
    denied.append(
        await client.post(
            f"/api/v1/ctms/projections/{seeded['projection'].id}",
            json={"clinical_data": "CLINICAL_SECRET"},
            headers=admin_headers,
        )
    )
    denied.append(
        await client.post(
            f"/api/v1/ctms/studies/{study_id}/tasks",
            json={
                "study_id": str(study_id),
                "title": "Injected clinical data",
                "clinical_data": "CLINICAL_SECRET",
            },
            headers=admin_headers,
        )
    )
    # Study-scoped read must not disclose the in-scope operational profile.
    denied.append(
        await client.get(
            f"/api/v1/ctms/studies/{study_id}/operational-profile",
            headers=out_scope_headers,
        )
    )
    # CTMS_Viewer is read-only, including coordination remediation.
    denied.append(
        await client.post(
            f"/api/v1/ctms/studies/{study_id}/operational-profile",
            json={"sponsor": "Viewer mutation"},
            headers=viewer_headers,
        )
    )
    denied.append(
        await client.post(
            f"/api/v1/ctms/coordination-events/{failed_event_id}/replay",
            json={"reason": "Unauthorized replay"},
            headers=viewer_headers,
        )
    )
    denied.append(
        await client.post(
            f"/api/v1/ctms/coordination-conflicts/{conflict_id}/resolve",
            json={"policy": "force", "reason": "Unauthorized conflict resolution"},
            headers=viewer_headers,
        )
    )
    # CTMS operational permissions cannot download an EDC clinical attachment.
    denied.append(
        await client.get(
            f"/api/v1/files/{seeded['attachment'].id}/download",
            headers=viewer_headers,
        )
    )

    for response in denied:
        _assert_denied(response)
    assert await _snapshot(db_session) == before


@pytest.mark.asyncio
async def test_out_of_scope_reads_and_clinical_attachment_access_are_server_denied(
    client, db_session, seeded
):
    """Scope and attachment checks remain enforced even when IDs are known."""

    before = await _snapshot(db_session)
    headers = _auth(seeded["out_of_scope"])
    profile = await client.get(
        f"/api/v1/ctms/studies/{seeded['study'].id}/operational-profile",
        headers=headers,
    )
    attachment = await client.get(
        f"/api/v1/files/{seeded['attachment'].id}/download",
        headers=headers,
    )
    _assert_denied(profile, allowed_statuses={403})
    _assert_denied(attachment, allowed_statuses={403})
    assert await _snapshot(db_session) == before


@pytest.mark.asyncio
async def test_coordination_api_returns_sanitized_event_metadata_without_raw_leakage(
    client, db_session, seeded, caplog
):
    """Event inspection exposes metadata only, never raw clinical/event payloads."""

    before = await _snapshot(db_session)
    response = await client.get(
        f"/api/v1/ctms/coordination-events/{seeded['failed_event'].event_id}",
        headers=_auth(seeded["admin"]),
    )
    assert response.status_code == 200, response.text
    assert "RAW_EVENT_SECRET" not in response.text
    assert "CLINICAL_SECRET" not in response.text
    assert "QUERY_SECRET" not in response.text
    assert "raw_event_body" not in response.text.lower()
    assert "clinical_data" not in response.text.lower()
    assert "unrestricted_query_message" not in response.text.lower()
    assert "RAW_EVENT_SECRET" not in caplog.text
    assert "CLINICAL_SECRET" not in caplog.text
    assert "QUERY_SECRET" not in caplog.text
    assert await _snapshot(db_session) == before
