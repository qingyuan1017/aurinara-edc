"""Phase 1 CTMS integration and EDC-boundary qualification.

Feature: ctms-integration, Task 7.1
Validates: Requirements 14.1, 14.4-14.6

This suite intentionally crosses the API, shared authorization, CTMS services,
transaction bookkeeping, and frontend-facing contracts.  It snapshots every
EDC-owned record type that a Phase 1 command must not mutate before and after
the CTMS workflow.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.core.audit import audit_service
from app.core.database import Base
from app.core.security import create_access_token
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.ctms.enrollment import EnrollmentTarget, OperationalMilestone
from app.models.ctms.operational_site import ActivationAction, OperationalSite
from app.models.ctms.operational_study import OperationalStudy, StudyPlan
from app.models.export import Export
from app.models.file_attachment import FileAttachment
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.identity import Permission, Role, RolePermission, User, UserRole, UserStatus
from app.models.query import Query, QueryMessage, QueryStatus, QueryTargetType
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitDefinition, VisitInstance, VisitInstanceStatus
from app.services.operational_study_service import OperationalStudyService


@pytest.fixture
async def phase1_engine():
    """Create the complete local schema, including both module boundaries."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models  # noqa: F401 - register all mapped EDC and CTMS models

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def phase1_session(phase1_engine):
    factory = async_sessionmaker(bind=phase1_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        if session.in_transaction():
            await session.rollback()


@pytest.fixture
async def phase1_data(phase1_session: AsyncSession) -> dict[str, Any]:
    """Seed one canonical EDC graph and the shared CTMS role/scope model."""

    now = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    permissions = {
        code: Permission(id=uuid4(), code=code, description=code)
        for code in {
            "ctms.operational-data-read",
            "ctms.operational_data_read",
            "ctms.operational-study-management",
            "ctms.operational_study_management",
            "ctms.operational-site-management",
            "ctms.enrollment-management",
        }
    }
    phase1_session.add_all(permissions.values())
    admin_role = Role(
        id=uuid4(), name=f"CTMS_Admin_{uuid4()}", scope_level="system", is_system=True
    )
    viewer_role = Role(
        id=uuid4(), name=f"CTMS_Viewer_{uuid4()}", scope_level="system", is_system=True
    )
    scoped_role = Role(
        id=uuid4(), name=f"CTMS_Site_Viewer_{uuid4()}", scope_level="study", is_system=False
    )
    phase1_session.add_all([admin_role, viewer_role, scoped_role])
    await phase1_session.flush()

    admin_codes = {
        "ctms.operational-data-read",
        "ctms.operational_data_read",
        "ctms.operational-study-management",
        "ctms.operational_study_management",
        "ctms.operational-site-management",
        "ctms.enrollment-management",
    }
    phase1_session.add_all(
        [
            RolePermission(role_id=admin_role.id, permission_id=permissions[code].id)
            for code in admin_codes
        ]
        + [
            RolePermission(
                role_id=viewer_role.id,
                permission_id=permissions["ctms.operational-data-read"].id,
            ),
            RolePermission(
                role_id=viewer_role.id,
                permission_id=permissions["ctms.operational_data_read"].id,
            ),
            RolePermission(
                role_id=scoped_role.id,
                permission_id=permissions["ctms.operational-data-read"].id,
            ),
            RolePermission(
                role_id=scoped_role.id,
                permission_id=permissions["ctms.operational_data_read"].id,
            ),
        ]
    )

    admin = User(
        id=uuid4(), email=f"phase1-admin-{uuid4()}@example.test", first_name="Phase", last_name="Admin",
        status=UserStatus.active, last_activity=now,
    )
    viewer = User(
        id=uuid4(), email=f"phase1-viewer-{uuid4()}@example.test", first_name="Phase", last_name="Viewer",
        status=UserStatus.active, last_activity=now,
    )
    scoped = User(
        id=uuid4(), email=f"phase1-scoped-{uuid4()}@example.test", first_name="Phase", last_name="Scoped",
        status=UserStatus.active, last_activity=now,
    )
    phase1_session.add_all([admin, viewer, scoped])
    await phase1_session.flush()

    study = Study(
        id=uuid4(), study_code=f"PHASE1-{uuid4()}", title="Phase 1 qualification study",
        status=StudyStatus.active, created_by=admin.id, created_at=now,
    )
    other_study = Study(
        id=uuid4(), study_code=f"PHASE1-OTHER-{uuid4()}", title="Out of scope study",
        status=StudyStatus.active, created_by=admin.id, created_at=now,
    )
    phase1_session.add_all([study, other_study])
    await phase1_session.flush()
    site = Site(
        id=uuid4(), study_id=study.id, site_number="P1-001", name="Canonical Phase 1 site",
        status=SiteStatus.active, created_at=now,
    )
    version = StudyVersion(
        id=uuid4(), study_id=study.id, version_number="1.0", status=StudyVersionStatus.published,
        published_at=now, published_by=admin.id, created_at=now,
    )
    phase1_session.add_all([site, version])
    await phase1_session.flush()
    subject = Subject(
        id=uuid4(), study_id=study.id, site_id=site.id, study_version_id=version.id,
        subject_number="P1-001-0001", status=SubjectStatus.enrolled,
        created_by=admin.id, created_at=now,
    )
    visit_definition = VisitDefinition(
        id=uuid4(), study_version_id=version.id, name="Week 4", visit_number=2,
        visit_type="scheduled", target_day=28, window_before=3, window_after=5,
        display_order=2, is_required=True, created_at=now,
    )
    phase1_session.add_all([subject, visit_definition])
    await phase1_session.flush()
    visit = VisitInstance(
        id=uuid4(), subject_id=subject.id, visit_definition_id=visit_definition.id,
        name="Week 4", visit_date=date(2026, 2, 12), window_status="in_window",
        status=VisitInstanceStatus.scheduled, created_at=now,
    )
    form = FormDefinition(
        id=uuid4(), study_version_id=version.id, name="Demographics", form_code="DM",
        display_order=1, is_repeating=False, created_at=now,
    )
    phase1_session.add_all([visit, form])
    await phase1_session.flush()
    section = FormSection(id=uuid4(), form_definition_id=form.id, name="Subject", display_order=1)
    phase1_session.add(section)
    await phase1_session.flush()
    field = FieldDefinition(
        id=uuid4(), form_section_id=section.id, label="Age", variable_name="age",
        control_type="integer", data_type="integer", is_required=True, display_order=1,
    )
    phase1_session.add(field)
    await phase1_session.flush()
    form_instance = FormInstance(
        id=uuid4(), subject_id=subject.id, visit_instance_id=visit.id,
        form_definition_id=form.id, status=FormInstanceStatus.in_progress,
        data_jsonb={"age": 42}, created_at=now,
    )
    phase1_session.add(form_instance)
    await phase1_session.flush()
    field_value = FieldValue(
        id=uuid4(), form_instance_id=form_instance.id, field_definition_id=field.id,
        value="42", is_not_applicable=False, created_at=now, updated_by=admin.id,
    )
    query = Query(
        id=uuid4(), study_id=study.id, site_id=site.id, subject_id=subject.id,
        target_type=QueryTargetType.subject.value, target_id=subject.id,
        text="EDC query remains clinical authority", status=QueryStatus.open,
        created_by=admin.id, created_at=now,
    )
    query_message = QueryMessage(
        id=uuid4(), query_id=query.id, author_id=admin.id,
        message="Unrestricted EDC query message", created_at=now,
    )
    clinical_attachment = FileAttachment(
        id=uuid4(), module="EDC", attachment_type="Clinical_Attachment",
        object_type="subject", object_id=subject.id, study_id=study.id, site_id=site.id,
        subject_id=subject.id, filename="source.pdf", content_type="application/pdf",
        size_bytes=128, storage_key="clinical/source.pdf", uploaded_by=admin.id, uploaded_at=now,
    )
    clinical_export = Export(
        id=uuid4(), study_id=study.id, module="EDC", content_owner="EDC",
        export_type="json", status="Completed", filters={"site_id": str(site.id)},
        file_path="clinical/export.json", file_size=128, requested_by=admin.id, created_at=now,
    )
    phase1_session.add_all([field_value, query, query_message, clinical_attachment, clinical_export])
    phase1_session.add_all([
        UserRole(user_id=admin.id, role_id=admin_role.id),
        UserRole(user_id=viewer.id, role_id=viewer_role.id),
        UserRole(user_id=scoped.id, role_id=scoped_role.id, study_id=other_study.id),
    ])
    await phase1_session.commit()
    return {
        "admin": admin, "viewer": viewer, "scoped": scoped, "study": study,
        "other_study": other_study, "site": site, "version": version, "subject": subject,
        "visit": visit, "form_instance": form_instance, "field_value": field_value,
        "query": query, "clinical_attachment": clinical_attachment, "clinical_export": clinical_export,
    }


@pytest.fixture
def phase1_app(phase1_engine):
    application = create_app()

    async def override_get_db():
        factory = async_sessionmaker(bind=phase1_engine, class_=AsyncSession, expire_on_commit=False)
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
async def phase1_client(phase1_app):
    async with AsyncClient(transport=ASGITransport(app=phase1_app), base_url="http://test") as client:
        yield client


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


_EDC_BOUNDARY_MODELS = (
    StudyVersion,
    Subject,
    VisitInstance,
    FormInstance,
    FieldValue,
    Query,
    QueryMessage,
    FileAttachment,
    Export,
)


async def _snapshot_edc(session: AsyncSession) -> dict[str, tuple[tuple[str, str], ...]]:
    """Snapshot mapped columns only, excluding relationship identity state."""

    def encoded_value(value: object) -> str:
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        if hasattr(value, "value") and isinstance(value.value, str):
            value = value.value
        return repr(value)

    snapshot: dict[str, tuple[tuple[str, str], ...]] = {}
    for model in _EDC_BOUNDARY_MODELS:
        rows = list((await session.scalars(select(model))).all())
        columns = [column.key for column in inspect(model).mapper.column_attrs]
        encoded = [
            tuple((column, encoded_value(getattr(row, column))) for column in columns)
            for row in rows
        ]
        snapshot[model.__tablename__] = tuple(sorted(encoded))
    return snapshot


def _load_revision():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "0024_create_ctms_phase1.py"
    spec = importlib.util.spec_from_file_location("ctms_phase1_revision_qualification", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase1_migration_is_additive_and_model_boundary_has_no_clinical_duplicates():
    revision = _load_revision()
    edc_tables = {
        "studies", "sites", "study_versions", "subjects", "visit_instances",
        "form_instances", "field_values", "queries", "file_attachments", "exports",
    }
    assert revision.revision == "0024"
    assert revision.down_revision == "0023"
    assert all(table.startswith("ctms_") for table in revision._CTMS_TABLES)
    assert edc_tables.isdisjoint(revision._CTMS_TABLES)
    assert set(revision._REQUIRED_EDC_TABLES) == {"users", "studies", "sites", "subjects"}
    assert edc_tables.issubset(Base.metadata.tables)
    assert set(revision._CTMS_TABLES).issubset(Base.metadata.tables)
    assert "study_id" in Base.metadata.tables["ctms_operational_studies"].c
    assert "site_id" in Base.metadata.tables["ctms_operational_sites"].c
    assert "subject_id" in Base.metadata.tables["ctms_operational_milestones"].c


@pytest.mark.asyncio
async def test_phase1_api_workflow_and_all_edc_boundary_snapshots_remain_unchanged(
    phase1_client: AsyncClient, phase1_session: AsyncSession, phase1_data: dict[str, Any]
):
    """Run Phase 1 commands through the real API and prove clinical non-mutation."""

    before = await _snapshot_edc(phase1_session)
    admin_headers = _headers(phase1_data["admin"])
    study_id = phase1_data["study"].id
    site_id = phase1_data["site"].id
    subject_id = phase1_data["subject"].id
    now = "2026-01-15T12:00:00Z"

    capabilities = await phase1_client.get("/api/v1/ctms/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["enabled"] is True
    assert "canonical_study_references" in capabilities.json()["capabilities"]
    assert "enrollment_planning" in capabilities.json()["capabilities"]

    profile_response = await phase1_client.post(
        f"/api/v1/ctms/studies/{study_id}/operational-profile",
        json={
            "sponsor": "Operational sponsor",
            "phase": "Phase II",
            "therapeutic_area": "Oncology",
            "indication": "Qualification indication",
            "planning_metadata": {"region": "Global"},
            "readiness_criteria": {"minimum_sites": 1},
            "correlation_id": "phase1-profile",
        },
        headers=admin_headers,
    )
    assert profile_response.status_code == 201, profile_response.text
    profile = profile_response.json()
    assert UUID(profile["study_id"]) == study_id
    assert profile["status"] == "Draft"
    profile_id = profile["id"]

    plan = await phase1_client.post(
        f"/api/v1/ctms/studies/{study_id}/plans",
        json={"title": "Site start-up", "objective": "Open canonical site", "planning_scope": {"region": "Global"}},
        headers=admin_headers,
    )
    assert plan.status_code == 201, plan.text

    site_profile = await phase1_client.post(
        f"/api/v1/ctms/sites/{site_id}/operational-profile",
        json={"study_id": str(study_id), "monitoring_readiness": "Ready", "responsible_role": "CRA"},
        headers=admin_headers,
    )
    assert site_profile.status_code == 201, site_profile.text
    assert UUID(site_profile.json()["site_id"]) == site_id

    activation = await phase1_client.post(
        f"/api/v1/ctms/sites/{site_id}/activation",
        json={"action_type": "Regulatory approval"},
        headers=admin_headers,
    )
    assert activation.status_code == 201, activation.text
    duplicate_activation = await phase1_client.post(
        f"/api/v1/ctms/sites/{site_id}/activation",
        json={"action_type": "Regulatory approval"},
        headers=admin_headers,
    )
    assert duplicate_activation.status_code == 201, duplicate_activation.text
    assert duplicate_activation.json()["id"] == activation.json()["id"]

    target = await phase1_client.post(
        f"/api/v1/ctms/studies/{study_id}/enrollment-targets",
        json={
            "study_id": str(study_id), "site_id": str(site_id), "target_type": "Enrollment",
            "target_quantity": 25, "planning_period_start": now,
            "planning_period_end": "2026-12-31T12:00:00Z",
        },
        headers=admin_headers,
    )
    assert target.status_code == 201, target.text
    assert target.json()["status"] == "Draft"

    milestone = await phase1_client.post(
        f"/api/v1/ctms/subjects/{subject_id}/operational-milestones",
        json={
            "study_id": str(study_id), "site_id": str(site_id), "subject_id": str(subject_id),
            "approved_pseudonym": "P1-0001", "milestone_type": "Enrollment",
            "milestone_date": now, "status": "Enrolled",
        },
        headers=admin_headers,
    )
    assert milestone.status_code == 201, milestone.text
    assert UUID(milestone.json()["subject_id"]) == subject_id

    for status, reason in (("Planning", "Planning approved"), ("Ready", "Readiness verified"), ("Active", "Launch approved")):
        transition = await phase1_client.post(
            f"/api/v1/ctms/operational-studies/{profile_id}/transition",
            json={"status": status, "reason": reason}, headers=admin_headers,
        )
        assert transition.status_code == 200, transition.text

    dashboard = await phase1_client.get(
        f"/api/v1/ctms/studies/{study_id}/dashboard", headers=admin_headers
    )
    assert dashboard.status_code == 200, dashboard.text
    dashboard_body = dashboard.json()
    assert dashboard_body["operational"]["enrollment"]["targets"]["Enrollment"]["target"] == 25
    assert dashboard_body["operational"]["enrollment"]["targets"]["Enrollment"]["actual"] == 1

    paginated = await phase1_client.get(
        f"/api/v1/ctms/studies/{study_id}/plans?page=1&page_size=10", headers=admin_headers
    )
    assert paginated.status_code == 200
    assert {"items", "page", "page_size", "total"}.issubset(paginated.json())
    assert paginated.headers.get("X-Request-ID")

    archive = await phase1_client.post(
        f"/api/v1/ctms/operational-studies/{profile_id}/archive",
        json={"reason": "Phase 1 qualification cleanup"}, headers=admin_headers,
    )
    assert archive.status_code == 200, archive.text
    assert archive.json()["retention_state"] == "archived"

    after = await _snapshot_edc(phase1_session)
    assert after == before

    # The CTMS side effects are present and are linked to the canonical IDs,
    # while the clinical snapshot above remains byte-for-byte equivalent.
    assert await phase1_session.scalar(select(OperationalStudy).where(OperationalStudy.id == UUID(profile_id)))
    assert await phase1_session.scalar(select(StudyPlan).where(StudyPlan.study_id == study_id))
    assert await phase1_session.scalar(select(OperationalSite).where(OperationalSite.site_id == site_id))
    assert await phase1_session.scalar(select(EnrollmentTarget).where(EnrollmentTarget.study_id == study_id))
    assert await phase1_session.scalar(select(OperationalMilestone).where(OperationalMilestone.subject_id == subject_id))
    assert await phase1_session.scalar(select(ActivationAction).where(ActivationAction.site_id == site_id))
    assert await phase1_session.scalar(select(AuditEvent).where(AuditEvent.module == "CTMS"))


@pytest.mark.asyncio
async def test_phase1_roles_scope_and_viewer_denials_are_side_effect_free(
    phase1_client: AsyncClient, phase1_session: AsyncSession, phase1_data: dict[str, Any]
):
    before = await _snapshot_edc(phase1_session)
    study_id = phase1_data["study"].id
    profile = await phase1_client.post(
        f"/api/v1/ctms/studies/{study_id}/operational-profile",
        json={"sponsor": "Scoped test"}, headers=_headers(phase1_data["admin"]),
    )
    assert profile.status_code == 201, profile.text

    viewer_write = await phase1_client.post(
        f"/api/v1/ctms/studies/{study_id}/plans",
        json={"title": "Viewer must not write"}, headers=_headers(phase1_data["viewer"]),
    )
    assert viewer_write.status_code == 403, viewer_write.text
    assert viewer_write.headers.get("X-Request-ID")

    out_of_scope_read = await phase1_client.get(
        f"/api/v1/ctms/studies/{study_id}/operational-profile",
        headers=_headers(phase1_data["scoped"]),
    )
    assert out_of_scope_read.status_code == 403, out_of_scope_read.text
    assert await _snapshot_edc(phase1_session) == before


@pytest.mark.asyncio
async def test_phase1_audit_failure_rolls_back_ctms_mutation_without_touching_edc(
    phase1_session: AsyncSession, phase1_data: dict[str, Any], monkeypatch
):
    """The CTMS aggregate, audit, status history, and outbox share one rollback."""

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(audit_service, "record", fail_audit)
    service = OperationalStudyService()
    before = await _snapshot_edc(phase1_session)

    other_study_id = phase1_data["other_study"].id
    with pytest.raises(RuntimeError, match="injected audit failure"):
        await service.create_profile(
            phase1_session,
            study_id=other_study_id,
            actor_id=phase1_data["admin"].id,
            payload={"sponsor": "Must roll back"},
            correlation_id="phase1-audit-failure",
        )
    await phase1_session.rollback()

    assert await phase1_session.scalar(
        select(OperationalStudy).where(OperationalStudy.study_id == other_study_id)
    ) is None
    assert await _snapshot_edc(phase1_session) == before
