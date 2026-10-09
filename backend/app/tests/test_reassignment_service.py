"""Unit tests for the Phase 4 ReassignmentService (Migration Phase 4).

Validates:
  - R11.7: reassignments are recorded as immutable audit events — exactly one
           per reassigned record set, carrying the correct source/target module
           ownership scope (design-time → DESIGNER, operational stays EDC).
  - R11.8: existing audit history is preserved with no physical removal; a
           verification helper confirms no pre-existing audit row was deleted.

Tests run against a real in-memory SQLite async session so the audit events are
written through the shared ``audit_service`` exactly as in production. These are
NOT the Property 15/17 property tests (tasks 19.3/19.5).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.ctms import Module
from app.core.database import Base
from app.models.shared.audit import AuditEvent
from app.services.designer.migration.reassignment_service import (
    REASSIGN_ACTION,
    ReassignmentService,
    reassignment_service,
)
from app.services.designer.migration.snapshot_service import (
    DESIGN_TIME_SETS,
    OPERATIONAL_SETS,
    RECORD_SET_MODELS,
)

_ACTOR_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")


@pytest.fixture
async def db_session() -> AsyncSession:
    """Yield a fresh in-memory SQLite async session with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# --- Seed helper ------------------------------------------------------------


async def _seed_preexisting_audit(session: AsyncSession, n: int) -> list[uuid.UUID]:
    """Insert ``n`` pre-existing audit events; return their ids (ordered)."""
    ids: list[uuid.UUID] = []
    for _i in range(n):
        event = AuditEvent(
            id=uuid.uuid4(),
            actor_id=_ACTOR_ID,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            entity_type="subject",
            entity_id=uuid.uuid4(),
            module="EDC",
            action="create",
            request_id=uuid.uuid4(),
        )
        session.add(event)
        ids.append(event.id)
    await session.flush()
    return ids


async def _count_audit(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(AuditEvent))
    return int(result.scalar_one())


# --- R11.7: one reassignment event per set with correct module scope --------


async def test_reassign_record_set_records_one_event(db_session: AsyncSession):
    """One design-time set reassignment writes exactly one audit event."""
    service = ReassignmentService()

    event = await service.reassign_record_set(
        db_session, record_set="form_definitions", actor_id=_ACTOR_ID
    )

    assert event.record_set == "form_definitions"
    assert event.source_module == Module.EDC
    assert event.target_module == Module.DESIGNER
    assert await _count_audit(db_session) == 1


async def test_design_time_set_reassigns_edc_to_designer(db_session: AsyncSession):
    """Design-time sets carry source=EDC → target=DESIGNER (R11.7)."""
    service = ReassignmentService()

    for record_set in DESIGN_TIME_SETS:
        event = await service.reassign_record_set(
            db_session, record_set=record_set, actor_id=_ACTOR_ID
        )
        assert event.source_module == Module.EDC
        assert event.target_module == Module.DESIGNER


async def test_operational_set_stays_edc(db_session: AsyncSession):
    """Operational sets stay source=EDC → target=EDC (ownership formalized)."""
    service = ReassignmentService()

    for record_set in OPERATIONAL_SETS:
        event = await service.reassign_record_set(
            db_session, record_set=record_set, actor_id=_ACTOR_ID
        )
        assert event.source_module == Module.EDC
        assert event.target_module == Module.EDC


async def test_audit_event_fields_match_reassignment(db_session: AsyncSession):
    """The persisted audit row records action, module scope, entity, actor."""
    service = ReassignmentService()

    await service.reassign_record_set(
        db_session, record_set="edit_checks", actor_id=_ACTOR_ID
    )

    result = await db_session.execute(select(AuditEvent))
    row = result.scalars().one()
    assert row.action == REASSIGN_ACTION
    assert row.entity_type == "edit_checks"
    assert row.source_module == Module.EDC.value
    assert row.target_module == Module.DESIGNER.value
    assert row.module == Module.DESIGNER.value
    assert row.actor_id == _ACTOR_ID
    assert row.timestamp is not None


async def test_reassign_all_records_one_event_per_set(db_session: AsyncSession):
    """reassign_all records exactly one event per declared record set (R11.7)."""
    result = await reassignment_service.reassign_all(db_session, actor_id=_ACTOR_ID)

    assert len(result.events) == len(RECORD_SET_MODELS)
    recorded_sets = {e.record_set for e in result.events}
    assert recorded_sets == set(RECORD_SET_MODELS)
    # One audit row per set — no duplicates, no omissions.
    assert await _count_audit(db_session) == len(RECORD_SET_MODELS)


async def test_reassign_all_target_modules_match_partition(db_session: AsyncSession):
    """Each reassigned set's target module matches the design/operational split."""
    result = await reassignment_service.reassign_all(db_session, actor_id=_ACTOR_ID)

    by_set = {e.record_set: e for e in result.events}
    for name in DESIGN_TIME_SETS:
        assert by_set[name].target_module == Module.DESIGNER
    for name in OPERATIONAL_SETS:
        assert by_set[name].target_module == Module.EDC


async def test_reassign_entity_ids_are_deterministic(db_session: AsyncSession):
    """The per-set correlation id is stable across runs (idempotent-friendly)."""
    first = await reassignment_service.reassign_record_set(
        db_session, record_set="codelists", actor_id=_ACTOR_ID
    )
    result = await db_session.execute(
        select(AuditEvent).where(AuditEvent.entity_type == "codelists")
    )
    entity_id = result.scalars().one().entity_id

    # A second service instance derives the same entity id for the same set.
    assert ReassignmentService() is not None
    assert first.record_set == "codelists"
    # Re-deriving via a fresh engine yields the same deterministic entity id.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as other:
            await reassignment_service.reassign_record_set(
                other, record_set="codelists", actor_id=_ACTOR_ID
            )
            other_result = await other.execute(
                select(AuditEvent).where(AuditEvent.entity_type == "codelists")
            )
            assert other_result.scalars().one().entity_id == entity_id
    finally:
        await engine.dispose()


async def test_unknown_record_set_rejected(db_session: AsyncSession):
    """An unknown record set is rejected without writing an audit event."""
    service = ReassignmentService()

    with pytest.raises(ValueError):
        await service.reassign_record_set(
            db_session, record_set="not_a_real_set", actor_id=_ACTOR_ID
        )
    assert await _count_audit(db_session) == 0


# --- R11.8: audit-history preservation (no physical removal) ----------------


async def test_preexisting_audit_history_preserved(db_session: AsyncSession):
    """Reassignment adds events and removes none of the pre-existing rows."""
    preexisting_ids = await _seed_preexisting_audit(db_session, 5)
    before = await _count_audit(db_session)
    assert before == 5

    result = await reassignment_service.reassign_all(db_session, actor_id=_ACTOR_ID)

    after = await _count_audit(db_session)
    # Purely additive: pre-existing rows + one new event per set.
    assert after == before + len(RECORD_SET_MODELS)
    assert result.audit_history_preserved is True
    assert result.preexisting_audit_count == before

    # Every pre-existing audit row still exists (none physically removed).
    surviving = await db_session.execute(
        select(AuditEvent.id).where(AuditEvent.id.in_(preexisting_ids))
    )
    assert set(surviving.scalars().all()) == set(preexisting_ids)


async def test_assert_preservation_passes_when_additive(db_session: AsyncSession):
    """The preservation assertion passes when only additions occurred."""
    service = ReassignmentService()
    await _seed_preexisting_audit(db_session, 3)
    before = await service.count_audit_history(db_session)

    await service.reassign_record_set(
        db_session, record_set="studies", actor_id=_ACTOR_ID
    )

    # Should not raise: 3 pre-existing + 1 added == current.
    await service.assert_audit_history_preserved(
        db_session, preexisting_count=before, added=1
    )


async def test_assert_preservation_detects_removed_history(db_session: AsyncSession):
    """The assertion fails if the current count is below the pre-existing count."""
    service = ReassignmentService()
    await _seed_preexisting_audit(db_session, 2)
    current = await service.count_audit_history(db_session)

    # Claim there were more rows before than exist now → history was removed.
    with pytest.raises(AssertionError):
        await service.assert_audit_history_preserved(
            db_session, preexisting_count=current + 1, added=0
        )


async def test_assert_preservation_detects_missing_added_event(db_session: AsyncSession):
    """The assertion fails if a claimed appended event is missing."""
    service = ReassignmentService()
    before = await service.count_audit_history(db_session)

    # No event was actually recorded, but we claim one was added.
    with pytest.raises(AssertionError):
        await service.assert_audit_history_preserved(
            db_session, preexisting_count=before, added=1
        )


async def test_reassign_all_with_no_preexisting_history(db_session: AsyncSession):
    """Reassignment works on a fresh audit log and reports zero pre-existing."""
    result = await reassignment_service.reassign_all(db_session, actor_id=_ACTOR_ID)

    assert result.preexisting_audit_count == 0
    assert result.audit_history_preserved is True
    assert await _count_audit(db_session) == len(RECORD_SET_MODELS)
