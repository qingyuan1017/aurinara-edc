"""Example-based coverage for the PV read-only EDC projection consumption.

Feature: pv-safety-module, Task 5.1
Validates: Requirements 10.4, 23.6, 23.7, 23.8, 23.10, 17.6

Exercises the PVProjectionService and pv_projection_worker against an in-memory
database. Covers upserting the minimized projection read model, enforcing the
approved field allowlist, denying and recording an unapproved/unauthorized
projection with no content, idempotent processing by idempotency key, the stale
guard that never overwrites a current projection, coordination-reference
traceability by correlation identifier, and the read-only nature of the
projection. The worker claims one outbox event and delegates to the service.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.audit import AuditEvent
from app.models.ctms.coordination import CTMSOutbox
from app.models.pv.coordination import (
    APPROVED_PROJECTION_FIELDS,
    CoordinationRef,
    EdcAeProjection,
)
from app.services.pv_projection_service import PVProjectionService
from app.workers.pv_projection_worker import PVProjectionWorker


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_outbox(
    *,
    payload: dict,
    allowlist: dict | None = None,
    source_record_id=None,
    source_version: str = "1",
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
    target_module: str = "PV",
) -> CTMSOutbox:
    """Build one approved EDC->PV Safety_Operational_Projection outbox event."""

    return CTMSOutbox(
        event_id=uuid4(),
        aggregate_type="edc_adverse_event",
        aggregate_id=source_record_id or uuid4(),
        event_type="safety_operational_projection",
        module="EDC",
        source_module="EDC",
        target_module=target_module,
        source_record_id=source_record_id or uuid4(),
        source_version=source_version,
        rule_version=1,
        allowlist_json=allowlist if allowlist is not None else {f: "string" for f in APPROVED_PROJECTION_FIELDS},
        payload_json=payload,
        idempotency_key=idempotency_key or str(uuid4()),
        correlation_id=correlation_id or str(uuid4()),
        status="Pending",
        available_at=datetime.now(UTC),
    )


def _approved_payload(subject_id=None) -> dict:
    return {
        "subject_reference": str(subject_id or uuid4()),
        "verbatim_term": "Headache",
        "onset_date": "2024-02-01",
        "seriousness": "serious",
    }


async def _count(session: AsyncSession, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


class TestProjectionApply:
    async def test_upserts_minimized_projection_read_model(self, db_session: AsyncSession) -> None:
        subject_id = uuid4()
        event = _make_outbox(payload=_approved_payload(subject_id))
        db_session.add(event)
        await db_session.flush()

        service = PVProjectionService()
        result = await service.process_event(db_session, event)

        assert result.applied is True
        assert result.outcome == "applied"
        projection = result.projection
        assert projection is not None
        assert projection.projection_status == "Current"
        assert projection.read_only is True
        assert projection.subject_reference == subject_id
        assert projection.verbatim_term == "Headache"
        assert projection.onset_date == date(2024, 2, 1)
        assert projection.seriousness == "serious"
        # Only the approved minimized fields are stored.
        assert projection.payload_fingerprint

    async def test_records_coordination_reference_by_correlation_id(
        self, db_session: AsyncSession
    ) -> None:
        correlation = str(uuid4())
        event = _make_outbox(payload=_approved_payload(), correlation_id=correlation)
        db_session.add(event)
        await db_session.flush()

        result = await PVProjectionService().process_event(db_session, event)

        ref = result.ref
        assert ref.correlation_id == correlation
        assert ref.outcome == "applied"
        assert ref.projection_id == result.projection.id
        assert ref.event_id == event.event_id
        assert ref.idempotency_key == event.idempotency_key

    async def test_marks_outbox_row_published(self, db_session: AsyncSession) -> None:
        event = _make_outbox(payload=_approved_payload())
        db_session.add(event)
        await db_session.flush()

        await PVProjectionService().process_event(db_session, event)

        assert event.status == "Published"
        assert event.outcome == "succeeded"
        assert event.resulting_projection_id is not None

    async def test_records_one_pv_safety_audit_event(self, db_session: AsyncSession) -> None:
        event = _make_outbox(payload=_approved_payload())
        db_session.add(event)
        await db_session.flush()

        await PVProjectionService().process_event(db_session, event)

        result = await db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.entity_type == "edc_ae_projection")
        )
        assert int(result.scalar_one()) == 1


class TestAllowlistAndAuthorization:
    async def test_unapproved_field_is_denied_with_no_content(
        self, db_session: AsyncSession
    ) -> None:
        payload = _approved_payload()
        payload["patient_name"] = "Jane Doe"  # prohibited clinical field
        event = _make_outbox(payload=payload)
        db_session.add(event)
        await db_session.flush()

        result = await PVProjectionService().process_event(db_session, event)

        assert result.denied is True
        assert result.outcome == "denied"
        projection = result.projection
        assert projection is not None
        assert projection.projection_status == "Rejected"
        # No content delivered: no minimized fields persisted.
        assert projection.subject_reference is None
        assert projection.verbatim_term is None
        assert projection.onset_date is None
        assert projection.seriousness is None
        assert projection.rejection_reason == "PROJECTION_FIELD_NOT_ALLOWED"

    async def test_expanded_allowlist_beyond_approved_set_is_denied(
        self, db_session: AsyncSession
    ) -> None:
        event = _make_outbox(
            payload=_approved_payload(),
            allowlist={**{f: "string" for f in APPROVED_PROJECTION_FIELDS}, "diagnosis": "string"},
        )
        db_session.add(event)
        await db_session.flush()

        result = await PVProjectionService().process_event(db_session, event)

        assert result.denied is True
        assert result.projection.projection_status == "Rejected"

    async def test_denied_projection_records_reference_and_audit(
        self, db_session: AsyncSession
    ) -> None:
        payload = _approved_payload()
        payload["secret_token"] = "abc"
        event = _make_outbox(payload=payload)
        db_session.add(event)
        await db_session.flush()

        await PVProjectionService().process_event(db_session, event)

        assert await _count(db_session, CoordinationRef) == 1
        audit = await db_session.execute(
            select(AuditEvent).where(AuditEvent.entity_type == "edc_ae_projection")
        )
        events = list(audit.scalars().all())
        assert len(events) == 1
        assert events[0].action == "reject"


class TestIdempotency:
    async def test_reprocessing_same_event_is_a_noop(self, db_session: AsyncSession) -> None:
        key = str(uuid4())
        service = PVProjectionService()

        # At-least-once delivery re-claims the same outbox row (same idempotency
        # key), so redelivery is modeled by processing the same event twice.
        event = _make_outbox(payload=_approved_payload(), idempotency_key=key)
        db_session.add(event)
        await db_session.flush()

        first = await service.process_event(db_session, event)
        assert first.applied is True

        second = await service.process_event(db_session, event)
        assert second.duplicate is True

        # Still exactly one projection and one reference for this key.
        assert await _count(db_session, EdcAeProjection) == 1
        assert await _count(db_session, CoordinationRef) == 1


class TestStaleGuard:
    async def test_stale_event_does_not_overwrite_current(
        self, db_session: AsyncSession
    ) -> None:
        service = PVProjectionService()
        source_id = uuid4()

        newer = _make_outbox(
            payload={**_approved_payload(), "verbatim_term": "Newer term"},
            source_record_id=source_id,
            source_version="5",
        )
        db_session.add(newer)
        await db_session.flush()
        await service.process_event(db_session, newer)

        older = _make_outbox(
            payload={**_approved_payload(), "verbatim_term": "Older term"},
            source_record_id=source_id,
            source_version="2",
        )
        db_session.add(older)
        await db_session.flush()
        result = await service.process_event(db_session, older)

        assert result.stale is True
        assert result.outcome == "skipped_stale"

        # The current projection still reflects the newer source version.
        current = await db_session.execute(
            select(EdcAeProjection).where(
                EdcAeProjection.source_record_id == source_id,
                EdcAeProjection.projection_status == "Current",
            )
        )
        current_rows = list(current.scalars().all())
        assert len(current_rows) == 1
        assert current_rows[0].source_version == "5"
        assert current_rows[0].verbatim_term == "Newer term"

    async def test_newer_event_supersedes_prior_current(
        self, db_session: AsyncSession
    ) -> None:
        service = PVProjectionService()
        source_id = uuid4()

        first = _make_outbox(
            payload=_approved_payload(), source_record_id=source_id, source_version="1"
        )
        db_session.add(first)
        await db_session.flush()
        await service.process_event(db_session, first)

        second = _make_outbox(
            payload={**_approved_payload(), "verbatim_term": "Updated"},
            source_record_id=source_id,
            source_version="2",
        )
        db_session.add(second)
        await db_session.flush()
        result = await service.process_event(db_session, second)

        assert result.applied is True
        current = await db_session.execute(
            select(EdcAeProjection).where(
                EdcAeProjection.source_record_id == source_id,
                EdcAeProjection.projection_status == "Current",
            )
        )
        assert len(list(current.scalars().all())) == 1
        stale = await db_session.execute(
            select(func.count())
            .select_from(EdcAeProjection)
            .where(
                EdcAeProjection.source_record_id == source_id,
                EdcAeProjection.projection_status == "Stale",
            )
        )
        assert int(stale.scalar_one()) == 1


class TestWorker:
    async def test_worker_claims_and_processes_one_pv_event(
        self, db_session: AsyncSession
    ) -> None:
        event = _make_outbox(payload=_approved_payload())
        db_session.add(event)
        await db_session.flush()

        worker = PVProjectionWorker()
        result = await worker.process_next(db_session)

        assert result is not None
        assert result.applied is True
        assert event.status == "Published"

    async def test_worker_returns_none_when_no_pv_event(
        self, db_session: AsyncSession
    ) -> None:
        # A CTMS-targeted event must not be claimed by the PV worker.
        event = _make_outbox(payload=_approved_payload(), target_module="CTMS")
        db_session.add(event)
        await db_session.flush()

        worker = PVProjectionWorker()
        result = await worker.process_next(db_session)

        assert result is None
        assert await _count(db_session, EdcAeProjection) == 0


class TestMigrationAdditivity:
    def test_projection_revision_is_additive_and_pv_prefixed(self) -> None:
        path = (
            Path(__file__).parents[2]
            / "alembic"
            / "versions"
            / "0044_create_pv_edc_ae_projections.py"
        )
        spec = importlib.util.spec_from_file_location("pv_projection_revision", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert module.revision == "0044"
        assert module.down_revision == "0043"
        assert set(module._PROJECTION_TABLES) == {
            "pv_edc_ae_projections",
            "pv_coordination_refs",
        }
        assert all(name.startswith("pv_") for name in module._PROJECTION_TABLES)
        assert all(not name.startswith("ctms_") for name in module._PROJECTION_TABLES)

    def test_projection_tables_use_expected_conventions(self) -> None:
        import app.models  # noqa: F401 - register mapped models

        tables = Base.metadata.tables
        assert {"pv_edc_ae_projections", "pv_coordination_refs"}.issubset(tables)

        projection = tables["pv_edc_ae_projections"]
        columns = set(projection.c.keys())
        for column in (
            "source_module", "source_record_id", "source_version", "rule_version",
            "correlation_id", "idempotency_key", "projected_at", "payload_fingerprint",
            "projection_status", "subject_reference", "verbatim_term", "onset_date",
            "seriousness", "deleted_at", "deleted_by", "deletion_reason",
        ):
            assert column in columns, column
        assert projection.c.projected_at.type.timezone is True

        ref = tables["pv_coordination_refs"]
        ref_columns = set(ref.c.keys())
        for column in ("event_id", "correlation_id", "idempotency_key", "outcome", "processed_at"):
            assert column in ref_columns, column
