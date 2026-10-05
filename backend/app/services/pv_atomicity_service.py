"""Transaction-coupled PV Safety_Data mutation bookkeeping.

PV services mutate their authoritative Safety_Data aggregate using the
caller-provided ``AsyncSession`` and then call this helper. The helper never
commits: the Safety_Data change, its immutable PV safety ``Audit_Event``, and any
required Coordination_Service outbox row are flushed on the same transaction and
therefore commit or roll back atomically at the request/worker unit-of-work
boundary.

If the audit write or the outbox write fails, the whole transaction is rolled
back by the caller's unit of work so that no Safety_Data or Safety_Attachment
state persists without its Audit_Event (Requirements 11.1, 11.3, 11.7, 16.4,
18.1, 18.2, 18.3).

The helper emits PV safety Audit_Event content only (``module="PV"``); it never
alters EDC clinical or CTMS operational audit content, and it reuses the shared
``Audit_Service`` and ``Coordination_Service`` transactional outbox rather than
forking them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.pv import ActorContext, Module
from app.models.audit import AuditEvent
from app.models.ctms.coordination import CTMSOutbox

# PV safety data is never physically deleted; a mutation that logically removes a
# record still records its action as a value change on the retained row.
_SCALAR_TYPES = (str, int, float, bool)


def _stringify(value: object) -> str | None:
    """Render an old/new audit value as a caller-safe string.

    Only identifiers and scalar values are serialized. Structured payloads and
    prohibited safety content never enter the audit ``old_value``/``new_value``
    columns; callers pass already-sanitized scalars.
    """

    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, _SCALAR_TYPES):
        return str(value)
    return str(value)


def _safe_payload(payload: Mapping[str, object] | None) -> dict[str, object]:
    """Keep outbox payloads to identifiers and scalar safety metadata.

    Structured or unknown values are dropped so no prohibited safety content or
    raw coordination payload leaks into the shared outbox row.
    """

    safe: dict[str, object] = {}
    for key, value in (payload or {}).items():
        if value is None or isinstance(value, _SCALAR_TYPES):
            safe[key] = value
        elif isinstance(value, UUID):
            safe[key] = str(value)
        elif isinstance(value, datetime):
            safe[key] = value.astimezone(UTC).isoformat()
    return safe


@dataclass(frozen=True, slots=True)
class PVMutationRecord:
    """Result of a recorded PV mutation.

    ``outbox`` is ``None`` when the mutation required no coordination event.
    """

    audit: AuditEvent
    outbox: CTMSOutbox | None


class PVAtomicityService:
    """Write PV mutation bookkeeping on the active transaction.

    A Safety_Data mutation and its PV safety Audit_Event commit or roll back
    together. The helper adds records to the caller's session and flushes them,
    but deliberately never commits: the caller's request or worker unit of work
    owns the commit/rollback boundary.
    """

    async def record_mutation(
        self,
        session: AsyncSession,
        *,
        entity_type: str,
        entity_id: UUID,
        action: str,
        actor: ActorContext | None = None,
        actor_id: UUID | None = None,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        subject_id: UUID | None = None,
        correlation_id: str | None = None,
        request_id: str | None = None,
        changed_fields: Sequence[str] = (),
        field_name: str | None = None,
        old_value: object = None,
        new_value: object = None,
        reason: str | None = None,
        worker_id: str | None = None,
        emit_outbox: bool = False,
        event_type: str | None = None,
        payload: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
        target_module: Module | str = Module.PV,
        target_record_id: UUID | None = None,
    ) -> PVMutationRecord:
        """Record a PV safety Audit_Event and any outbox row without committing.

        Args:
            session: The active SQLAlchemy async session (caller's transaction).
            entity_type: The PV entity type (for example ``safety_case``).
            entity_id: The primary key of the affected PV record.
            action: The action performed (for example ``create``, ``update``,
                ``submit``, ``transition``, ``upload``, ``download``, ``delete``).
            actor: Optional request-scoped ``ActorContext`` supplying actor,
                request, and correlation identifiers.
            actor_id: Explicit acting user; overrides ``actor.user_id``.
            study_id: PV study scope.
            site_id: PV site scope.
            subject_id: Referenced EDC Subject_Reference for the record.
            correlation_id: Correlation identifier; defaults to ``actor``.
            request_id: Request identifier; defaults to ``actor``.
            changed_fields: Names of the fields that changed.
            field_name: Optional single field name for field-level changes.
            old_value: Prior value for value changes (scalar/identifier only).
            new_value: New value for value changes (scalar/identifier only).
            reason: Reason_For_Change for post-submission changes.
            worker_id: Worker identifier when the actor is a background worker.
            emit_outbox: When true, append a Coordination_Service outbox row in
                the same transaction.
            event_type: Coordination event type; defaults to ``action``.
            payload: Sanitized scalar payload for the outbox row.
            idempotency_key: Idempotency key for the outbox row.
            target_module: Target module for a coordination event.
            target_record_id: Target record identifier for a coordination event.

        Returns:
            A :class:`PVMutationRecord` with the created Audit_Event and the
            outbox row (or ``None`` when no coordination event was required).
        """

        resolved_actor_id = actor_id
        if resolved_actor_id is None and actor is not None:
            resolved_actor_id = actor.user_id
        resolved_correlation = correlation_id
        if resolved_correlation is None and actor is not None:
            resolved_correlation = actor.correlation_id
        resolved_request_id = request_id
        if resolved_request_id is None and actor is not None:
            resolved_request_id = actor.request_id

        outbox: CTMSOutbox | None = None
        if emit_outbox:
            target = (
                target_module.value if isinstance(target_module, Module) else str(target_module)
            )
            outbox = CTMSOutbox(
                event_id=uuid4(),
                aggregate_type=entity_type,
                aggregate_id=entity_id,
                event_type=event_type or action,
                module=Module.PV.value,
                source_module=Module.PV.value,
                target_module=target,
                source_record_id=entity_id,
                target_record_id=target_record_id,
                idempotency_key=idempotency_key or str(uuid4()),
                outcome="accepted",
                status="Pending",
                correlation_id=(resolved_correlation or str(uuid4())),
                payload_json=_safe_payload(payload),
            )
            session.add(outbox)
            await session.flush()

        audit = await audit_service.record(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            module=Module.PV,
            actor_kind="worker" if worker_id else "user",
            worker_id=worker_id,
            actor_id=resolved_actor_id,
            correlation_id=resolved_correlation,
            request_id=resolved_request_id,
            scope={"study_id": study_id, "site_id": site_id},
            changed_fields=changed_fields,
            source_module=Module.PV,
            source_record_id=entity_id,
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            field_name=field_name,
            old_value=_stringify(old_value),
            new_value=_stringify(new_value),
            reason=reason,
        )
        await session.flush()
        return PVMutationRecord(audit=audit, outbox=outbox)


pv_atomicity_service = PVAtomicityService()

__all__ = ["PVAtomicityService", "PVMutationRecord", "pv_atomicity_service"]
