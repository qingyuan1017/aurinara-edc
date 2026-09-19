"""Property 29: Unlock requires a reason and clears the lock.

**Validates: Requirements 16.4**

The property exercises the real LockService against a transactional SQLite
schema. For both freeze and lock controls, blank reasons are rejected without
changing the active control; a nonblank reason clears the control, preserves
its original lock metadata, stores unlock metadata, and creates an audit event
with the normalized reason.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ValidationError
from app.models.audit import AuditEvent
from app.models.identity import User, UserStatus
from app.models.lock import FreezeLock, FreezeLockObjectType, FreezeLockType
from app.services.lock_service import LockService

# Feature: clinical-edc-system, Property 29: Unlock requires a reason and clears the lock
# **Validates: Requirements 16.4**


empty_reason_st = st.one_of(
    st.none(),
    st.just(""),
    st.text(
        alphabet=st.sampled_from([" ", "\t", "\n", "\r"]),
        min_size=1,
        max_size=12,
    ),
)

valid_reason_st = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Zs"), max_codepoint=0x024F),
    min_size=1,
    max_size=200,
).filter(lambda value: value.strip() != "")


@pytest.fixture
async def db_session():
    """Provide an isolated transactional database for each generated example."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    lock_type=st.sampled_from([FreezeLockType.freeze, FreezeLockType.lock]),
    blank_reason=empty_reason_st,
    reason=valid_reason_st,
)
@pytest.mark.asyncio
async def test_unlock_requires_nonblank_reason_clears_control_and_records_reason(
    db_session: AsyncSession,
    lock_type: FreezeLockType,
    blank_reason: str | None,
    reason: str,
):
    """Unlock rejects blank reasons and records metadata for successful unlocks."""
    actor_id = uuid.uuid4()
    target_id = uuid.uuid4()
    now = datetime.now(UTC)
    actor = User(
        id=actor_id,
        email=f"unlock-{actor_id}@example.test",
        first_name="Unlock",
        last_name="Tester",
        status=UserStatus.active,
        created_at=now,
    )
    db_session.add(actor)
    await db_session.flush()

    service = LockService()
    activate = service.freeze if lock_type is FreezeLockType.freeze else service.lock
    control = await activate(
        db_session,
        actor_id=actor_id,
        object_type=FreezeLockObjectType.study,
        object_id=target_id,
    )
    original_locked_by = control.locked_by
    original_locked_at = control.locked_at
    action = "unfreeze" if lock_type is FreezeLockType.freeze else "unlock"

    with pytest.raises(ValidationError, match="reason"):
        await service.unlock(
            db_session,
            reason=blank_reason,
            actor_id=actor_id,
            lock_type=lock_type,
            object_type=FreezeLockObjectType.study,
            object_id=target_id,
        )

    active_result = await db_session.execute(
        select(FreezeLock).where(
            FreezeLock.object_type == FreezeLockObjectType.study.value,
            FreezeLock.object_id == target_id,
            FreezeLock.lock_type == lock_type.value,
        )
    )
    active_control = active_result.scalars().one()
    assert active_control.is_active is True
    assert active_control.unlock_reason is None
    assert active_control.unlocked_by is None
    assert active_control.unlocked_at is None

    expected_reason = reason.strip()
    unlocked = await service.unlock(
        db_session,
        reason=reason,
        actor_id=actor_id,
        lock_type=lock_type,
        object_type=FreezeLockObjectType.study,
        object_id=target_id,
    )

    assert unlocked.is_active is False
    assert unlocked.locked_by == original_locked_by
    assert unlocked.locked_at == original_locked_at
    assert unlocked.unlocked_by == actor_id
    assert unlocked.unlocked_at is not None
    assert unlocked.unlock_reason == expected_reason

    audit_result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.entity_type == FreezeLockObjectType.study.value,
            AuditEvent.entity_id == target_id,
            AuditEvent.action == action,
        )
    )
    unlock_events = audit_result.scalars().all()
    assert len(unlock_events) == 1
    assert unlock_events[0].actor_id == actor_id
    assert unlock_events[0].reason == expected_reason
