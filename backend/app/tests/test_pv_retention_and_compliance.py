"""PV environment isolation, retention/backup/restore, and compliance tests.

These tests use an in-memory async SQLAlchemy database and deterministic local
values only. They verify Task 8.1 controls:

* :class:`PVRetentionService` archives aged PV Safety_Data, soft-deletes aged PV
  attachments, records an immutable actor/time/reason ledger row plus one PV
  safety Audit_Event, and never touches EDC/CTMS-owned shared rows.
* PV retention actions are append-only (immutable history).
* Restore requires an actor and a non-empty reason and preserves the ledger.
* :mod:`app.core.pv_compliance` exposes a complete Traceability_Matrix, distinct
  Safety_Case states, the 5-second clock-agreement bound, and non-secret
  environment/backup/restore controls.
* Per-Environment settings isolation exposes only non-secret PV metadata.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Environment, Settings
from app.core.database import Base
from app.core.pv_compliance import (
    PV_DISTINCT_CASE_STATES,
    PV_TRACEABILITY_MATRIX,
    build_environment_controls,
    build_traceability_matrix,
    case_states_are_distinct,
    clock_agreement_within_tolerance,
)
from app.models.audit import AuditEvent
from app.models.export import Export
from app.models.file_attachment import FileAttachment
from app.models.notification import Notification
from app.models.pv import AdverseEventRecord, SafetyCase
from app.models.pv.retention import PVRetentionAction
from app.services.pv_retention_service import PVRetentionService, RetentionMode


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _old(now: datetime) -> datetime:
    return now - timedelta(days=30)


def _safety_case(now: datetime, created_at: datetime | None = None) -> SafetyCase:
    return SafetyCase(
        id=uuid4(),
        case_identifier=f"PV-{uuid4().hex[:10]}",
        study_id=uuid4(),
        site_id=uuid4(),
        subject_reference=uuid4(),
        case_type="Spontaneous",
        lifecycle_state="Open",
        retention_state="active",
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=created_at or _old(now),
        updated_at=created_at or _old(now),
    )


def _adverse_event(case_id, now: datetime) -> AdverseEventRecord:
    return AdverseEventRecord(
        id=uuid4(),
        case_id=case_id,
        verbatim_term="headache",
        onset_date=date(2024, 1, 1),
        outcome="Recovered",
        retention_state="active",
        created_by=uuid4(),
        created_at=_old(now),
        updated_at=_old(now),
    )


# --- Retention run -----------------------------------------------------------


@pytest.mark.asyncio
async def test_retention_archives_aged_pv_safety_data_and_records_ledger(db_session: AsyncSession):
    now = datetime(2033, 1, 1, tzinfo=UTC)
    service = PVRetentionService(settings=Settings(pv_retention_days=2555))
    old_case = _safety_case(now, created_at=now - timedelta(days=3000))
    old_ae = _adverse_event(old_case.id, now)
    old_ae.created_at = now - timedelta(days=3000)
    old_ae.updated_at = old_ae.created_at
    recent_case = _safety_case(now, created_at=now - timedelta(days=10))
    db_session.add_all([old_case, old_ae, recent_case])
    await db_session.flush()

    result = await service.run(db_session, actor_id=uuid4(), reason="7-year retention cutoff", now=now)

    assert result.archived >= 2
    assert old_case.retention_state == "archived"
    assert old_case.archived_at == now
    assert old_case.archived_by is not None
    assert old_case.retention_reason == "7-year retention cutoff"
    assert old_ae.retention_state == "archived"
    # Recent case is well within the 7-year floor and untouched.
    assert recent_case.retention_state == "active"

    ledger = (
        await db_session.scalars(
            select(PVRetentionAction).where(PVRetentionAction.entity_id == old_case.id)
        )
    ).all()
    assert [item.action for item in ledger] == ["retention_archive"]
    assert ledger[0].module == "PV"
    # One PV safety Audit_Event per action.
    audit = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.entity_id == old_case.id)
    )
    assert audit is not None
    assert audit.module == "PV"


@pytest.mark.asyncio
async def test_retention_soft_deletes_aged_pv_attachment_with_actor_time_reason(db_session: AsyncSession):
    now = datetime(2033, 1, 1, tzinfo=UTC)
    actor = uuid4()
    attachment = FileAttachment(
        id=uuid4(),
        module="PV",
        attachment_type="Safety_Attachment",
        object_type="safety_case",
        object_id=uuid4(),
        study_id=uuid4(),
        filename="narrative.pdf",
        content_type="application/pdf",
        size_bytes=42,
        storage_key="pv/narrative.pdf",
        uploaded_by=uuid4(),
        uploaded_at=now - timedelta(days=3000),
    )
    db_session.add(attachment)
    await db_session.flush()

    result = await PVRetentionService(settings=Settings(pv_retention_days=2555)).run(
        db_session, actor_id=actor, reason="attachment retention elapsed", now=now
    )

    assert result.soft_deleted >= 1
    assert attachment.deleted_at is not None
    assert attachment.deleted_by == actor
    assert attachment.delete_reason == "attachment retention elapsed"
    assert attachment.retention_state == "soft_deleted"


@pytest.mark.asyncio
async def test_retention_does_not_touch_edc_or_ctms_shared_rows(db_session: AsyncSession):
    now = datetime(2033, 1, 1, tzinfo=UTC)
    old = now - timedelta(days=3000)
    study_id = uuid4()
    pv_export = Export(
        id=uuid4(), study_id=study_id, module="PV", content_owner="PV",
        export_type="json", status="Completed", requested_by=uuid4(), created_at=old,
    )
    edc_export = Export(
        id=uuid4(), study_id=study_id, module="EDC", content_owner="EDC",
        export_type="json", status="Completed", requested_by=uuid4(), created_at=old,
    )
    ctms_notification = Notification(
        id=uuid4(), user_id=uuid4(), module="CTMS", type="ctms_failed_event",
        payload_json={}, created_at=old,
    )
    pv_notification = Notification(
        id=uuid4(), user_id=uuid4(), module="PV", type="pv_serious_case",
        payload_json={}, created_at=old,
    )
    db_session.add_all([pv_export, edc_export, ctms_notification, pv_notification])
    await db_session.flush()

    await PVRetentionService(settings=Settings(pv_retention_days=2555)).run(
        db_session, actor_id=uuid4(), reason="resource cutoff", now=now
    )

    assert pv_export.retention_state == "archived"
    assert pv_notification.retention_state == "archived"
    # EDC/CTMS-owned shared rows are never reached by PV retention.
    assert edc_export.retention_state == "active"
    assert ctms_notification.retention_state == "active"


# --- Restore and immutability -----------------------------------------------


@pytest.mark.asyncio
async def test_restore_requires_actor_reason_and_keeps_ledger(db_session: AsyncSession):
    now = datetime(2033, 1, 1, tzinfo=UTC)
    service = PVRetentionService(settings=Settings(pv_retention_days=2555))
    case = _safety_case(now)
    db_session.add(case)
    await db_session.flush()
    await service.archive(db_session, case, actor_id=uuid4(), reason="case aged out", now=now, resource="safety_case")

    with pytest.raises(Exception, match="reason"):
        await service.restore(db_session, case, actor_id=uuid4(), reason="", now=now)

    actor = uuid4()
    await service.restore(db_session, case, actor_id=actor, reason="approved reopening", now=now)
    assert case.retention_state == "active"
    actions = (
        await db_session.scalars(
            select(PVRetentionAction).where(PVRetentionAction.entity_id == case.id)
        )
    ).all()
    assert [item.action for item in actions] == ["retention_archive", "retention_restore"]
    assert actions[-1].actor_id == actor
    assert actions[-1].reason == "approved reopening"


@pytest.mark.asyncio
async def test_pv_retention_action_history_is_immutable(db_session: AsyncSession):
    now = datetime(2033, 1, 1, tzinfo=UTC)
    service = PVRetentionService(settings=Settings(pv_retention_days=2555))
    case = _safety_case(now)
    db_session.add(case)
    await db_session.flush()
    await service.archive(db_session, case, actor_id=uuid4(), reason="case aged out", now=now, resource="safety_case")
    await db_session.commit()

    action = await db_session.scalar(select(PVRetentionAction))
    assert action is not None
    action.reason = "tampered"
    with pytest.raises(ValueError, match="immutable"):
        await db_session.flush()
    await db_session.rollback()

    action = await db_session.scalar(select(PVRetentionAction))
    assert action is not None
    await db_session.delete(action)
    with pytest.raises(ValueError, match="immutable"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_archive_rejects_missing_actor_and_reason(db_session: AsyncSession):
    now = datetime(2033, 1, 1, tzinfo=UTC)
    service = PVRetentionService(settings=Settings(pv_retention_days=2555))
    case = _safety_case(now)
    db_session.add(case)
    await db_session.flush()

    with pytest.raises(Exception, match="actor"):
        await service.archive(db_session, case, actor_id=None, reason="x", now=now, resource="safety_case")
    with pytest.raises(Exception, match="reason"):
        await service.archive(db_session, case, actor_id=uuid4(), reason="  ", now=now, resource="safety_case")


# --- Compliance controls -----------------------------------------------------


def test_traceability_matrix_covers_all_pv_requirements():
    matrix = build_traceability_matrix()
    assert matrix is PV_TRACEABILITY_MATRIX
    assert len(matrix) == 25
    for entry in matrix:
        assert entry.requirement
        assert entry.design_reference
        assert entry.qualification_test
        assert set(entry.as_dict()) == {"requirement", "design_reference", "qualification_test"}


def test_required_case_states_are_distinct():
    assert case_states_are_distinct() is True
    values = {state.value for state in PV_DISTINCT_CASE_STATES}
    assert values == {"Open", "In Review", "Ready to Report", "Reported", "Closed"}


def test_clock_agreement_within_and_outside_tolerance():
    base = datetime(2033, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert clock_agreement_within_tolerance(base, base + timedelta(seconds=4)) is True
    assert clock_agreement_within_tolerance(base, base + timedelta(seconds=5)) is True
    assert clock_agreement_within_tolerance(base, base + timedelta(seconds=6)) is False


def test_clock_agreement_rejects_naive_timestamps():
    aware = datetime(2033, 1, 1, tzinfo=UTC)
    naive = datetime(2033, 1, 1)  # intentionally naive for the test
    with pytest.raises(ValueError, match="timezone"):
        clock_agreement_within_tolerance(aware, naive)


def test_environment_controls_meet_regulatory_targets_and_hide_secrets():
    settings = Settings(
        environment=Environment.PRODUCTION,
        pv_retention_days=2555,
        pv_backup_enabled=True,
        pv_backup_interval_hours=24,
        pv_restore_enabled=True,
        pv_restore_target_hours=4,
        pv_clock_skew_tolerance_seconds=5,
        secret_key="super-secret-value",
    )
    controls = build_environment_controls(settings)

    assert controls["retention"]["meets_seven_year_minimum"] is True
    assert controls["backup"]["meets_daily_minimum"] is True
    assert controls["restore"]["meets_four_hour_target"] is True
    assert controls["clock"]["meets_five_second_agreement"] is True
    assert controls["case_states_distinct"] is True
    assert controls["traceability_matrix_size"] == 25

    # Only non-secret metadata is exposed anywhere in the controls payload.
    assert "super-secret-value" not in str(controls)
    env = controls["environment"]
    assert env["environment"] == "production"
    assert env["pv_enabled"] is True


def test_environment_metadata_isolates_namespaces_without_secrets():
    settings = Settings(
        environment=Environment.STAGING,
        environment_namespace="staging",
        secrets_namespace="staging",
        logging_namespace="staging",
        object_storage_namespace="staging",
        secret_key="another-secret",
    )
    metadata = settings.pv_environment_metadata

    assert metadata["environment"] == "staging"
    assert metadata["namespace"] == "staging"
    assert metadata["secrets_namespace"] == "staging"
    assert metadata["database_isolated"] is True
    # No secret value leaks through the isolation metadata.
    assert "another-secret" not in str(metadata)


def test_retention_policies_define_seven_year_floor_and_protected_audit():
    service = PVRetentionService(settings=Settings(pv_retention_days=2555))
    policies = {p.resource: p for p in service.policies()}
    assert policies["safety_data"].days == 2555
    assert policies["attachments"].mode is RetentionMode.SOFT_DELETE
    assert policies["audit"].mode is RetentionMode.PROTECTED


def test_pv_specific_retention_override_applies():
    service = PVRetentionService(
        settings=Settings(pv_retention_days=2555, pv_attachment_retention_days=30)
    )
    policies = {p.resource: p for p in service.policies()}
    assert policies["attachments"].days == 30
    # Unset overrides inherit the floor.
    assert policies["coding"].days == 2555
