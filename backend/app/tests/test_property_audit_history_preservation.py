"""Property-based test for audit-history preservation across migration.

**Validates: Requirements 11.8**

Property 17: Audit history is preserved across migration.

Phase 4 of the migration (``ReassignmentService.reassign_all``) records the
ownership reassignment of each record set as **additive, immutable** audit
events. It MUST NEVER physically remove or rewrite a pre-existing
``audit_events`` row (R11.8).

This property generates a random pre-existing audit history (a varying number
of ``audit_events`` rows with varying actions / entity types), captures their
ids and cheaply-checkable fields, runs ``reassign_all``, then asserts the
reassignment was purely additive:

* every pre-existing audit row id still exists after reassignment,
* the total row count equals ``pre_count + number_of_reassigned_record_sets``,
* each surviving pre-existing row's ``action`` / ``entity_type`` is byte
  identical to what was seeded (no rewrite).

The test exercises the real ``audit_service`` write path against an in-memory
SQLite async session so events persist exactly as in production.
"""

# Feature: designer-edc-refactor, Property 17: Audit history is preserved across migration

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.shared.audit import AuditEvent
from app.services.designer.migration.reassignment_service import reassignment_service
from app.services.designer.migration.snapshot_service import RECORD_SET_MODELS

_ACTOR_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")

# A small pool of entity types / actions so the seeded rows vary in kind while
# staying representative of the real audit vocabulary.
_ENTITY_TYPES = ["subject", "form_instance", "study", "visit_instance", "field_value"]
_ACTIONS = ["create", "update", "submit", "sign", "lock"]


@st.composite
def _preexisting_audit_rows(draw: st.DrawFn) -> list[dict[str, str]]:
    """Generate a random set of pre-existing audit-event payloads.

    Varies both the count (including zero) and the kind of each row so the
    property holds across arbitrary pre-existing histories.
    """
    count = draw(st.integers(min_value=0, max_value=12))
    return [
        {
            "entity_type": draw(st.sampled_from(_ENTITY_TYPES)),
            "action": draw(st.sampled_from(_ACTIONS)),
        }
        for _ in range(count)
    ]


async def _seed(session: AsyncSession, rows: list[dict[str, str]]) -> list[uuid.UUID]:
    """Insert the generated pre-existing rows; return their ids in order."""
    ids: list[uuid.UUID] = []
    for row in rows:
        event = AuditEvent(
            id=uuid.uuid4(),
            actor_id=_ACTOR_ID,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            entity_type=row["entity_type"],
            entity_id=uuid.uuid4(),
            module="EDC",
            action=row["action"],
            request_id=uuid.uuid4(),
        )
        session.add(event)
        ids.append(event.id)
    await session.flush()
    return ids


async def _count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(AuditEvent))
    return int(result.scalar_one())


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(rows=_preexisting_audit_rows())
async def test_reassignment_preserves_all_preexisting_audit_history(rows):
    """For any pre-existing audit history, reassign_all is purely additive (R11.8).

    **Validates: Requirements 11.8**

    No pre-existing row is deleted or rewritten; the post count equals the pre
    count plus exactly one reassignment event per reassigned record set.
    """
    # A fresh engine per example keeps Hypothesis examples fully isolated and
    # avoids sharing an event loop / connection across generated inputs.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            # Seed the random pre-existing history and snapshot it.
            preexisting_ids = await _seed(session, rows)
            pre_count = await _count(session)
            assert pre_count == len(rows)

            seeded_fields = {
                row.id: (row.entity_type, row.action)
                for row in (
                    await session.execute(
                        select(AuditEvent).where(AuditEvent.id.in_(preexisting_ids))
                    )
                ).scalars()
            }

            # Run Phase 4 reassignment.
            result = await reassignment_service.reassign_all(
                session, actor_id=_ACTOR_ID
            )

            # Additive invariant: total == pre_count + one event per record set.
            post_count = await _count(session)
            assert post_count == pre_count + len(RECORD_SET_MODELS)
            assert len(result.events) == len(RECORD_SET_MODELS)
            assert result.audit_history_preserved is True
            assert result.preexisting_audit_count == pre_count

            # Every pre-existing row still exists — none physically removed.
            surviving = (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.id.in_(preexisting_ids))
                )
            ).scalars().all()
            surviving_ids = {row.id for row in surviving}
            assert surviving_ids == set(preexisting_ids)

            # Every pre-existing row is unchanged (not rewritten) where cheaply
            # checkable: its action / entity_type match what was seeded.
            for row in surviving:
                assert (row.entity_type, row.action) == seeded_fields[row.id]
    finally:
        await engine.dispose()
