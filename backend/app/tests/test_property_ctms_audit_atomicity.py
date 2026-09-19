"""Property 16: CTMS audit, correlation, and transaction atomicity.

**Validates: Requirements 2.4, 2.6, 2.7, 2.11, 11.7-11.10, 12.1-12.5,
13.8-13.11, 14.5**

The property uses the real ``CTMSAtomicityService`` and ``AuditService`` with a
fully deterministic in-memory transaction fake.  No database, queue, object
storage, or other external service is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.audit import AuditEvent
from app.models.ctms.coordination import CTMSOutbox, CTMSStatusHistory
from app.services.ctms_atomicity_service import CTMSAtomicityService


@dataclass(frozen=True)
class MutationScenario:
    """One authorized or denied CTMS mutation and its injected failure point."""

    allowed: bool
    actor_id: UUID
    study_id: UUID
    site_id: UUID
    correlation_id: str
    idempotency_key: str
    entity_type: str
    action: str
    previous_status: str
    status: str
    changed_fields: tuple[str, ...]
    worker_id: str | None
    clinical_payload: str
    failure_flush: int | None


@dataclass
class FakeCTMSRecord:
    """Minimal authoritative CTMS record; clinical payload is never persisted."""

    id: UUID
    study_id: UUID
    site_id: UUID
    actor_id: UUID
    correlation_id: str
    idempotency_key: str
    status: str


class ExpectedFlushError(RuntimeError):
    """Raised by the fake at a generated transaction boundary."""


@dataclass
class InMemoryTransaction:
    """Small unit-of-work fake with commit/rollback semantics."""

    failure_flush: int | None
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
            raise ExpectedFlushError(f"injected flush failure {self.flush_count}")

    async def commit(self) -> None:
        self.commit_count += 1
        self.committed.extend(self.pending)
        self.pending.clear()

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.pending.clear()


_SAFE_OPERATION_TEXT = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
    min_size=1,
    max_size=24,
)


@st.composite
def mutation_scenario(draw: st.DrawFn) -> MutationScenario:
    """Generate mutation metadata, authorization, status, and failure points."""

    return MutationScenario(
        allowed=draw(st.booleans()),
        actor_id=draw(st.uuids()),
        study_id=draw(st.uuids()),
        site_id=draw(st.uuids()),
        correlation_id=f"corr-{draw(_SAFE_OPERATION_TEXT)}",
        idempotency_key=f"idem-{draw(_SAFE_OPERATION_TEXT)}",
        entity_type=draw(st.sampled_from(("operational_study", "operational_site", "operational_task"))),
        action=draw(
            st.sampled_from(
                ("create", "update", "status_transition", "projection_update", "coordination_update")
            )
        ),
        previous_status=draw(st.sampled_from(("Draft", "Planning", "Ready", "Active"))),
        status=draw(st.sampled_from(("Draft", "Planning", "Ready", "Active", "Closed"))),
        changed_fields=tuple(
            draw(
                st.lists(
                    st.sampled_from(("status", "owner", "planned_date", "readiness")),
                    min_size=1,
                    max_size=4,
                    unique=True,
                )
            )
        ),
        worker_id=draw(st.one_of(st.none(), _SAFE_OPERATION_TEXT.map(lambda value: f"worker-{value}"))),
        clinical_payload=f"clinical-secret-{draw(_SAFE_OPERATION_TEXT)}",
        # The real path has four flush boundaries: aggregate, outbox/history,
        # audit, and final bookkeeping flush.
        failure_flush=draw(st.one_of(st.none(), st.integers(min_value=1, max_value=4))),
    )


async def _apply_scenario(scenario: MutationScenario) -> InMemoryTransaction:
    """Run one mutation in a fake unit of work and roll back expected failures."""

    transaction = InMemoryTransaction(failure_flush=scenario.failure_flush)
    if not scenario.allowed:
        # Authorization is checked before the aggregate is added to the unit of work.
        return transaction

    try:
        record = FakeCTMSRecord(
            id=uuid4(),
            study_id=scenario.study_id,
            site_id=scenario.site_id,
            actor_id=scenario.actor_id,
            correlation_id=scenario.correlation_id,
            idempotency_key=scenario.idempotency_key,
            status=scenario.status,
        )
        transaction.add(record)
        await transaction.flush()

        await CTMSAtomicityService().record_mutation(
            transaction,
            entity_type=scenario.entity_type,
            entity_id=record.id,
            study_id=scenario.study_id,
            site_id=scenario.site_id,
            actor_id=scenario.actor_id,
            correlation_id=scenario.correlation_id,
            action=scenario.action,
            changed_fields=scenario.changed_fields,
            previous_status=scenario.previous_status,
            status=scenario.status,
            reason="generated operational transition",
            event_type="CTMS_OPERATIONAL_MUTATION",
            payload={
                "status": scenario.status,
                "idempotency_key": scenario.idempotency_key,
                # Nested values are deliberately prohibited from the outbox.
                "clinical_data": {"value": scenario.clinical_payload},
            },
            worker_id=scenario.worker_id,
        )
        await transaction.commit()
    except ExpectedFlushError:
        await transaction.rollback()

    return transaction


def _rows(transaction: InMemoryTransaction, row_type: type[Any]) -> list[Any]:
    """Return committed rows of one type from the fake transaction."""

    return [row for row in transaction.committed if isinstance(row, row_type)]


def _assert_sanitized(transaction: InMemoryTransaction, clinical_payload: str) -> None:
    """Ensure no clinical payload reaches any committed or pending fake row."""

    assert clinical_payload not in repr(transaction.committed)
    assert clinical_payload not in repr(transaction.pending)


class TestCTMSAuditCorrelationAtomicity:
    """Property 16: CTMS traceability metadata and writes are complete/atomic."""

    @settings(max_examples=100, deadline=None)
    @given(scenario=mutation_scenario())
    @pytest.mark.asyncio
    async def test_ctms_mutation_audit_and_side_effects_commit_or_rollback_together(
        self, scenario: MutationScenario
    ) -> None:
        """Allowed success is complete; denied/failing work has no partial state."""

        transaction = await _apply_scenario(scenario)
        expected_success = scenario.allowed and scenario.failure_flush is None

        if not expected_success:
            assert transaction.committed == []
            assert transaction.pending == []
            assert transaction.commit_count == 0
            assert transaction.rollback_count == (1 if scenario.allowed else 0)
            assert _rows(transaction, AuditEvent) == []
            assert _rows(transaction, CTMSStatusHistory) == []
            assert _rows(transaction, CTMSOutbox) == []
            _assert_sanitized(transaction, scenario.clinical_payload)
            return

        records = [row for row in transaction.committed if isinstance(row, FakeCTMSRecord)]
        histories = _rows(transaction, CTMSStatusHistory)
        audits = _rows(transaction, AuditEvent)
        outboxes = _rows(transaction, CTMSOutbox)

        assert transaction.commit_count == 1
        assert transaction.rollback_count == 0
        assert len(records) == len(histories) == len(audits) == len(outboxes) == 1

        record = records[0]
        history = histories[0]
        audit = audits[0]
        outbox = outboxes[0]

        # The same aggregate, correlation, actor, scope, and status transition
        # must be traversable across all four committed records.
        assert record.correlation_id == scenario.correlation_id
        assert record.idempotency_key == scenario.idempotency_key
        assert history.entity_id == record.id
        assert history.correlation_id is not None
        assert history.changed_by == scenario.actor_id
        assert history.previous_status == scenario.previous_status
        assert history.status == scenario.status
        assert history.changed_at.tzinfo is not None
        assert history.changed_at.utcoffset() == UTC.utcoffset(history.changed_at)
        assert outbox.aggregate_id == record.id
        assert outbox.correlation_id == scenario.correlation_id
        assert outbox.payload_json == {
            "status": scenario.status,
            "idempotency_key": scenario.idempotency_key,
        }

        # Exactly one shared, sanitized audit event is written for the mutation.
        assert audit.module == "CTMS"
        assert audit.actor_id == scenario.actor_id
        assert audit.actor_kind == ("worker" if scenario.worker_id else "user")
        assert audit.worker_id == scenario.worker_id
        assert audit.correlation_id == scenario.correlation_id
        assert audit.entity_id == record.id
        assert audit.action == scenario.action
        assert audit.changed_fields == list(scenario.changed_fields)
        assert audit.scope_json == {
            "study_id": str(scenario.study_id),
            "site_id": str(scenario.site_id),
        }
        assert audit.timestamp.tzinfo is not None
        assert audit.timestamp.utcoffset() == UTC.utcoffset(audit.timestamp)
        assert audit.new_value == f"status={scenario.status}"
        assert audit.source_module == "CTMS"
        assert audit.source_record_id == record.id
        _assert_sanitized(transaction, scenario.clinical_payload)
