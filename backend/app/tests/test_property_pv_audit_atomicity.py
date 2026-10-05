"""Property 4: Safety audit atomicity and immutability.

**Validates: Requirements 11, 16, 18, 20**

*For any* PV Safety_Data mutation or Safety_Attachment action, the change and
its PV safety Audit_Event commit or roll back together, the event contains
actor, UTC timestamp, entity, action, and applicable old/new values and reason,
completed Audit_Events cannot be updated or deleted, and scoped audit search
returns matching events ordered by UTC timestamp ascending with ties broken by
Audit_Event identifier ascending.

The test exercises the real ``PVAtomicityService`` and ``PVSharedIntegrationService``
(task 1.6) against deterministic in-memory fakes and an in-memory SQLite unit of
work. No database server, queue, object storage, or other external service is
used. It complements the example-based ``test_pv_shared_primitives.py`` with a
Hypothesis property covering many generated mutation/attachment sequences,
forced audit-write failures, and the deterministic scoped-search ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.pv import ActorContext
from app.models.audit import AuditEvent, _reject_audit_mutation
from app.models.ctms.coordination import CTMSOutbox
from app.services.pv_atomicity_service import PVAtomicityService

pytestmark = pytest.mark.asyncio

# PV Safety_Data / Safety_Attachment entity types and the actions PV records
# through the atomic Audit_Event write.
_SAFETY_ENTITIES = (
    "safety_case",
    "adverse_event_record",
    "seriousness_assessment",
    "case_version",
    "safety_attachment",
)
_MUTATION_ACTIONS = ("create", "update", "submit", "transition")
_ATTACHMENT_ACTIONS = ("upload", "download", "deletion")


class InjectedFlushError(RuntimeError):
    """Raised by the in-memory unit of work at a chosen flush boundary."""


@dataclass
class InMemoryUnitOfWork:
    """Minimal commit/rollback fake mirroring the request unit of work.

    ``failure_flush`` names the 1-indexed flush call that raises, letting a
    generated example force the audit-write flush to fail so the whole change
    must roll back with no committed rows.
    """

    failure_flush: int | None = None
    pending: list[Any] = field(default_factory=list)
    committed: list[Any] = field(default_factory=list)
    flush_count: int = 0
    commit_count: int = 0
    rollback_count: int = 0

    def add(self, value: Any) -> None:
        self.pending.append(value)

    async def flush(self) -> None:
        self.flush_count += 1
        if self.failure_flush == self.flush_count:
            raise InjectedFlushError(f"injected flush failure #{self.flush_count}")

    async def commit(self) -> None:
        self.commit_count += 1
        self.committed.extend(self.pending)
        self.pending.clear()

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.pending.clear()


@dataclass(frozen=True)
class Mutation:
    """One generated PV Safety_Data / Safety_Attachment mutation."""

    entity_type: str
    entity_id: UUID
    action: str
    old_value: str | None
    new_value: str | None
    reason: str | None
    emit_outbox: bool


@st.composite
def _mutations(draw: st.DrawFn) -> Mutation:
    """Generate a single valid PV mutation descriptor."""

    entity_type = draw(st.sampled_from(_SAFETY_ENTITIES))
    if entity_type == "safety_attachment":
        action = draw(st.sampled_from(_ATTACHMENT_ACTIONS))
    else:
        action = draw(st.sampled_from(_MUTATION_ACTIONS))

    text = st.text(min_size=0, max_size=40)
    old_value = draw(st.none() | text)
    new_value = draw(st.none() | text)
    # Post-submission changes carry a Reason_For_Change (non-empty, <= 4000).
    reason = draw(st.none() | st.text(min_size=1, max_size=60))
    emit_outbox = draw(st.booleans())
    return Mutation(
        entity_type=entity_type,
        entity_id=uuid4(),
        action=action,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        emit_outbox=emit_outbox,
    )


def _actor() -> ActorContext:
    return ActorContext(
        user_id=uuid4(),
        request_id=str(uuid4()),
        correlation_id=f"corr-{uuid4()}",
    )


def _rows(uow: InMemoryUnitOfWork, row_type: type[Any]) -> list[Any]:
    return [row for row in uow.committed if isinstance(row, row_type)]


# ---------------------------------------------------------------------------
# Atomicity + content: mutation and Audit_Event commit or roll back together.
# ---------------------------------------------------------------------------


@given(
    mutations=st.lists(_mutations(), min_size=1, max_size=6),
    fail_index=st.one_of(st.none(), st.integers(min_value=0, max_value=5)),
)
@settings(max_examples=200, deadline=None, derandomize=True)
async def test_pv_mutation_and_audit_commit_or_rollback_together(
    mutations: list[Mutation],
    fail_index: int | None,
) -> None:
    """The change and its PV Audit_Event commit together, or neither persists.

    **Validates: Requirements 11, 16, 18**
    """

    service = PVAtomicityService()
    actor = _actor()
    study_id = uuid4()
    site_id = uuid4()

    # Each mutation runs in its own request-scoped unit of work: on success the
    # data change and its Audit_Event commit together; on a forced audit-write
    # failure the whole unit of work rolls back so neither persists.
    target: Mutation | None = None
    if fail_index is not None and fail_index < len(mutations):
        target = mutations[fail_index]

    committed_ok: list[Mutation] = []
    failed_entities: set[UUID] = set()

    for mutation in mutations:
        uow = InMemoryUnitOfWork()
        if mutation is target:
            # Fail the audit flush for this mutation. An emit_outbox mutation
            # flushes the outbox first (flush #1) then the audit (flush #2);
            # otherwise the audit flush is the first and only flush.
            uow.failure_flush = 2 if mutation.emit_outbox else 1
            with pytest.raises(InjectedFlushError):
                await service.record_mutation(
                    uow,
                    entity_type=mutation.entity_type,
                    entity_id=mutation.entity_id,
                    action=mutation.action,
                    actor=actor,
                    study_id=study_id,
                    site_id=site_id,
                    old_value=mutation.old_value,
                    new_value=mutation.new_value,
                    reason=mutation.reason,
                    emit_outbox=mutation.emit_outbox,
                )
            await uow.rollback()

            # Atomic rollback: nothing committed, no Audit_Event, no outbox row.
            assert uow.commit_count == 0
            assert uow.rollback_count == 1
            assert uow.committed == []
            assert _rows(uow, AuditEvent) == []
            assert _rows(uow, CTMSOutbox) == []
            failed_entities.add(mutation.entity_id)
            continue

        record = await service.record_mutation(
            uow,
            entity_type=mutation.entity_type,
            entity_id=mutation.entity_id,
            action=mutation.action,
            actor=actor,
            study_id=study_id,
            site_id=site_id,
            old_value=mutation.old_value,
            new_value=mutation.new_value,
            reason=mutation.reason,
            emit_outbox=mutation.emit_outbox,
        )
        # Content: every event carries actor, UTC timestamp, entity, action, and
        # the applicable old/new values and reason.
        audit = record.audit
        assert audit.module == "PV"
        assert audit.actor_id == actor.user_id
        assert audit.entity_type == mutation.entity_type
        assert audit.entity_id == mutation.entity_id
        assert audit.action == mutation.action
        assert audit.study_id == study_id
        assert audit.site_id == site_id
        assert audit.timestamp.tzinfo is not None
        assert audit.timestamp.utcoffset() == timedelta(0)
        assert audit.old_value == mutation.old_value
        assert audit.new_value == mutation.new_value
        assert audit.reason == mutation.reason
        assert (record.outbox is not None) == mutation.emit_outbox

        await uow.commit()

        # The data change and its Audit_Event committed together.
        committed_audits = _rows(uow, AuditEvent)
        committed_outboxes = _rows(uow, CTMSOutbox)
        assert len(committed_audits) == 1
        assert committed_audits[0] is audit
        assert len(committed_outboxes) == (1 if mutation.emit_outbox else 0)
        committed_ok.append(mutation)

    # The failed mutation's entity never produced a committed Audit_Event.
    assert failed_entities == (
        {target.entity_id} if target is not None else set()
    )
    assert all(m.entity_id not in failed_entities for m in committed_ok)


# ---------------------------------------------------------------------------
# Immutability: completed Audit_Events cannot be updated or deleted.
# ---------------------------------------------------------------------------


@given(mutations=st.lists(_mutations(), min_size=1, max_size=6))
@settings(max_examples=100, deadline=None, derandomize=True)
async def test_completed_pv_audit_events_reject_update_and_delete(
    mutations: list[Mutation],
) -> None:
    """Any recorded PV Audit_Event rejects update and delete.

    **Validates: Requirements 11, 18, 20**
    """

    service = PVAtomicityService()
    actor = _actor()
    uow = InMemoryUnitOfWork()

    for mutation in mutations:
        await service.record_mutation(
            uow,
            entity_type=mutation.entity_type,
            entity_id=mutation.entity_id,
            action=mutation.action,
            actor=actor,
            old_value=mutation.old_value,
            new_value=mutation.new_value,
            reason=mutation.reason,
        )
    await uow.commit()

    audits = _rows(uow, AuditEvent)
    assert len(audits) == len(mutations)
    for audit in audits:
        with pytest.raises(ValueError, match="immutable"):
            _reject_audit_mutation(None, None, audit)
        with pytest.raises(ValueError, match="immutable"):
            _reject_audit_mutation(None, None, audit)


# ---------------------------------------------------------------------------
# Scoped search ordering: UTC timestamp ascending, ties broken by id ascending.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopedEvent:
    """A generated event with a controlled timestamp for ordering checks."""

    entity_type: str
    action: str
    second_offset: int


@st.composite
def _scoped_events(draw: st.DrawFn) -> ScopedEvent:
    return ScopedEvent(
        entity_type=draw(st.sampled_from(_SAFETY_ENTITIES)),
        action=draw(st.sampled_from(_MUTATION_ACTIONS + _ATTACHMENT_ACTIONS)),
        # A small offset range guarantees frequent timestamp ties so the
        # secondary Audit_Event-identifier tie-break is exercised.
        second_offset=draw(st.integers(min_value=0, max_value=3)),
    )


async def _make_scoped_session() -> tuple[AsyncSession, Any]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


@given(events=st.lists(_scoped_events(), min_size=1, max_size=12))
@settings(
    max_examples=100,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_scoped_audit_search_orders_by_timestamp_then_id(
    events: list[ScopedEvent],
) -> None:
    """Scoped audit search returns events ordered by UTC timestamp then id ascending.

    Deliberately clustered timestamps force ties so the secondary ordering by
    Audit_Event identifier ascending is verified.

    **Validates: Requirements 11, 16, 18, 20**
    """

    session, engine = await _make_scoped_session()
    study_id = uuid4()
    site_id = uuid4()
    base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    # An out-of-scope event that must never appear in the scoped result.
    other_study = uuid4()

    try:
        for spec in events:
            event = AuditEvent(
                actor_id=uuid4(),
                timestamp=base + timedelta(seconds=spec.second_offset),
                entity_type=spec.entity_type,
                entity_id=uuid4(),
                module="PV",
                action=spec.action,
                study_id=study_id,
                site_id=site_id,
                request_id=uuid4(),
            )
            session.add(event)
        # One out-of-scope PV event and one non-PV event.
        session.add(
            AuditEvent(
                actor_id=uuid4(),
                timestamp=base,
                entity_type="safety_case",
                entity_id=uuid4(),
                module="PV",
                action="create",
                study_id=other_study,
                site_id=uuid4(),
                request_id=uuid4(),
            )
        )
        session.add(
            AuditEvent(
                actor_id=uuid4(),
                timestamp=base,
                entity_type="subject",
                entity_id=uuid4(),
                module="EDC",
                action="create",
                study_id=study_id,
                site_id=site_id,
                request_id=uuid4(),
            )
        )
        await session.commit()

        # Scoped PV audit search: module=PV within the study/site scope,
        # ordered by UTC timestamp ascending, ties broken by identifier ascending.
        result = await session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.module == "PV",
                AuditEvent.study_id == study_id,
                AuditEvent.site_id == site_id,
            )
            .order_by(AuditEvent.timestamp.asc(), AuditEvent.id.asc())
        )
        rows = list(result.scalars().all())

        # Scope: only in-scope PV events are returned.
        assert len(rows) == len(events)
        assert all(row.module == "PV" for row in rows)
        assert all(row.study_id == study_id for row in rows)

        # Ordering: timestamp ascending, then id ascending on ties. SQLite may
        # return naive datetimes, so normalize to aware UTC before comparing.
        def _as_utc(value: datetime) -> datetime:
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

        keys = [(_as_utc(row.timestamp), str(row.id)) for row in rows]
        assert keys == sorted(keys, key=lambda k: (k[0], k[1]))
        for earlier, later in pairwise(keys):
            assert earlier[0] <= later[0]
            if earlier[0] == later[0]:
                assert earlier[1] <= later[1]
    finally:
        await session.close()
        await engine.dispose()
