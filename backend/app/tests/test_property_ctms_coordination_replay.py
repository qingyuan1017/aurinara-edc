"""Property 14: current-policy validation gates failed-event replay.

**Validates: Requirements 9.16, 10.9-10.10**

A failed event may be replayed only against the policy that is current when
replay is requested.  The generated scenario changes one or more of the
authorization, canonical identity, ownership, or typed-allowlist checks after
the event has failed.  Rejected replay requests must not alter the failed
record, outbox source metadata, or coordination event source metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import AuthorizationError, ConflictError, ValidationError
from app.models.ctms.coordination import CoordinationEventStatus, CTMSOutbox
from app.models.ctms.retention import CTMSFailedEvent
from app.services.coordination_service import CoordinationService


@pytest.fixture
async def db_session() -> AsyncSession:
    """Use real coordination persistence while keeping each test isolated."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@dataclass(frozen=True, slots=True)
class ReplayScenario:
    """Policy mutations made after the event has entered Failed_Event state."""

    authorization_allowed: bool
    identity_resolved: bool
    ownership_unchanged: bool
    allowlist_unchanged: bool


@st.composite
def replay_scenarios(draw: st.DrawFn) -> ReplayScenario:
    return ReplayScenario(
        authorization_allowed=draw(st.booleans()),
        identity_resolved=draw(st.booleans()),
        ownership_unchanged=draw(st.booleans()),
        allowlist_unchanged=draw(st.booleans()),
    )


class _MutableIdentityResolver:
    def __init__(self) -> None:
        self.resolved = False

    async def resolve(self, *_args, **_kwargs):
        return object() if self.resolved else None


class _MutablePolicy:
    """Small current-policy adapter matching the coordination service contract."""

    def __init__(self, allowlist: dict[str, str]) -> None:
        self.version = 1
        self.projection_target = "CTMS"
        self.allowlist_json = dict(allowlist)

    async def current_rule(self, *_args, **_kwargs):
        return SimpleNamespace(
            version=self.version,
            projection_target=self.projection_target,
            allowlist_json=dict(self.allowlist_json),
        )


class _ReplayProjectionService:
    def __init__(self, policy: _MutablePolicy) -> None:
        self.rule_service = policy


class _RolePermission:
    def __init__(self, code: str) -> None:
        self.permission = SimpleNamespace(code=code)


class _ReplayActor:
    def __init__(self, *, allowed: bool, study_id: UUID) -> None:
        role_permissions = (
            [_RolePermission("ctms.coordination-replay")] if allowed else []
        )
        self.id = uuid4()
        self.status = "active"
        self.user_roles = [
            SimpleNamespace(
                role=SimpleNamespace(role_permissions=role_permissions),
                study_id=study_id,
                site_id=None,
            )
        ]


ALLOWLIST = {
    "subject_id": "uuid",
    "status": "string",
    "source_version": "string",
}


async def _accept_failed_event(
    session: AsyncSession,
    service: CoordinationService,
    source_id: UUID,
    study_id: UUID,
    allowlist: dict[str, str],
):
    event = await service.accept(
        session,
        event_type="SUBJECT_STATUS_PROJECTION",
        source_module="EDC",
        target_module="CTMS",
        entity_type="Subject",
        source_record_id=source_id,
        source_version="1",
        rule_version=1,
        source_sequence=1,
        payload={
            "subject_id": str(source_id),
            "status": "Enrolled",
            "source_version": "1",
        },
        allowlist=allowlist,
        idempotency_key=f"replay-{source_id}",
        correlation_id=f"correlation-{source_id}",
        target_projection_type="subject_status",
        study_id=study_id,
    )
    result = await service.process(session, event_id=event.event_id, worker_id="property-worker")
    assert result.outcome == "failed"
    failed = await session.scalar(
        select(CTMSFailedEvent).where(CTMSFailedEvent.event_id == event.event_id)
    )
    assert failed is not None
    return event, failed


@given(scenario=replay_scenarios())
@settings(
    max_examples=100,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_replay_revalidates_current_policy(
    scenario: ReplayScenario,
    db_session: AsyncSession,
) -> None:
    """Replay succeeds iff every current authorization and policy check passes.

    **Validates: Requirements 9.16, 10.9-10.10**
    """

    study_id = uuid4()
    source_id = uuid4()
    identity = _MutableIdentityResolver()
    policy = _MutablePolicy(ALLOWLIST)
    service = CoordinationService(
        identity_resolver=identity,
        projection_service=_ReplayProjectionService(policy),
    )
    event, failed = await _accept_failed_event(db_session, service, source_id, study_id, ALLOWLIST)
    outbox = await db_session.scalar(
        select(CTMSOutbox).where(CTMSOutbox.event_id == event.event_id)
    )
    assert outbox is not None

    source_snapshot = (
        event.source_module,
        event.target_module,
        event.entity_type,
        event.source_record_id,
        event.source_version,
        event.rule_version,
        dict(event.allowlist_json),
        dict(event.payload_json),
        event.correlation_id,
        outbox.source_record_id,
        outbox.source_version,
        outbox.rule_version,
        dict(outbox.allowlist_json),
        dict(outbox.payload_json),
    )
    failed_snapshot = (failed.reason_code, dict(failed.sanitized_details_json), failed.attempt_count)

    # These are the policy changes that happen after the Failed_Event was
    # retained.  Replay must use these current values, not the acceptance copy.
    identity.resolved = scenario.identity_resolved
    if not scenario.ownership_unchanged:
        policy.projection_target = "EDC"
    if not scenario.allowlist_unchanged:
        policy.allowlist_json = {"subject_id": "uuid", "status": "string"}
    actor = _ReplayActor(allowed=scenario.authorization_allowed, study_id=study_id)
    all_checks_pass = (
        scenario.authorization_allowed
        and scenario.identity_resolved
        and scenario.ownership_unchanged
        and scenario.allowlist_unchanged
    )

    if all_checks_pass:
        replayed = await service.replay_failed_event(
            db_session,
            event_id=event.event_id,
            actor=actor,
            reason="Revalidate current policy",
        )
        assert replayed.event_id == event.event_id
        assert event.status == CoordinationEventStatus.ACCEPTED.value
        assert outbox.status == "Pending"
        assert failed.sanitized_details_json == {"reason_code": "REPLAY_PENDING"}
    else:
        with pytest.raises((AuthorizationError, ConflictError, ValidationError)):
            await service.replay_failed_event(
                db_session,
                event_id=event.event_id,
                actor=actor,
                reason="Revalidate current policy",
            )
        assert event.status == CoordinationEventStatus.FAILED.value
        assert outbox.status == "Failed"
        assert (failed.reason_code, dict(failed.sanitized_details_json), failed.attempt_count) == failed_snapshot

    # Neither an accepted replay nor a rejected replay may rewrite the source
    # event/outbox payload or canonical source identity.
    assert (
        event.source_module,
        event.target_module,
        event.entity_type,
        event.source_record_id,
        event.source_version,
        event.rule_version,
        dict(event.allowlist_json),
        dict(event.payload_json),
        event.correlation_id,
        outbox.source_record_id,
        outbox.source_version,
        outbox.rule_version,
        dict(outbox.allowlist_json),
        dict(outbox.payload_json),
    ) == source_snapshot
