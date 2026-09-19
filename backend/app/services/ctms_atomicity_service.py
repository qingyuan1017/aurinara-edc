"""Transaction-coupled CTMS mutation bookkeeping.

CTMS services mutate their authoritative aggregate using the caller-provided
``AsyncSession`` and then call this helper. The helper deliberately never
commits: the aggregate, status history, immutable audit event, and outbox row
are flushed in the same transaction and therefore commit or roll back
atomically at the request/worker unit-of-work boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.models.ctms.coordination import CTMSOutbox, CTMSStatusHistory
from app.services.coordination_service import coordination_service


def _correlation_uuid(value: UUID | str) -> UUID:
    """Return a database-compatible correlation UUID deterministically."""

    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return uuid5(NAMESPACE_URL, str(value))


def _safe_payload(payload: Mapping[str, object] | None) -> dict[str, object]:
    """Keep outbox payloads to identifiers and scalar operational metadata."""

    safe: dict[str, object] = {}
    for key, value in (payload or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, UUID):
            safe[key] = str(value)
        elif isinstance(value, datetime):
            safe[key] = value.astimezone(UTC).isoformat()
    return safe


class CTMSAtomicityService:
    """Write CTMS mutation bookkeeping on the active transaction."""

    async def record_mutation(
        self,
        session: AsyncSession,
        *,
        entity_type: str,
        entity_id: UUID,
        study_id: UUID | None,
        site_id: UUID | None,
        actor_id: UUID | None,
        correlation_id: UUID | str,
        action: str,
        changed_fields: Sequence[str] = (),
        previous_status: str | None = None,
        status: str | None = None,
        reason: str | None = None,
        event_type: str | None = None,
        payload: Mapping[str, object] | None = None,
        source_sequence: int | None = None,
        source_version: str | int | None = None,
        rule_version: int | None = None,
        idempotency_key: str | None = None,
        worker_id: str | None = None,
    ) -> tuple[CTMSStatusHistory | None, CTMSOutbox, object]:
        """Record status history, audit, and outbox state without committing.

        ``status`` may be omitted for non-status mutations. All persisted
        records carry the same correlation identifier and scope.
        """

        correlation_text = str(correlation_id)
        history: CTMSStatusHistory | None = None
        if status is not None:
            history = CTMSStatusHistory(
                entity_type=entity_type,
                entity_id=entity_id,
                study_id=study_id,
                site_id=site_id,
                previous_status=previous_status,
                status=status,
                changed_by=actor_id,
                changed_at=datetime.now(UTC),
                reason=reason,
                correlation_id=_correlation_uuid(correlation_id),
            )
            session.add(history)

        safe_payload = _safe_payload(payload)
        resolved_source_sequence = source_sequence
        if resolved_source_sequence is None and isinstance(safe_payload.get("source_sequence"), int):
            resolved_source_sequence = int(safe_payload["source_sequence"])
        resolved_source_version = source_version
        if resolved_source_version is None and safe_payload.get("source_version") is not None:
            resolved_source_version = str(safe_payload["source_version"])
        resolved_rule_version = rule_version
        if resolved_rule_version is None and isinstance(safe_payload.get("rule_version"), int):
            resolved_rule_version = int(safe_payload["rule_version"])
        outbox = CTMSOutbox(
            event_id=uuid4(),
            aggregate_type=entity_type,
            aggregate_id=entity_id,
            event_type=event_type or action,
            module=Module.CTMS.value,
            source_module=Module.CTMS.value,
            target_module=Module.CTMS.value,
            source_record_id=entity_id,
            source_sequence=resolved_source_sequence,
            source_version=resolved_source_version,
            rule_version=resolved_rule_version,
            idempotency_key=idempotency_key or str(uuid4()),
            outcome="accepted",
            correlation_id=correlation_text,
            payload_json=safe_payload,
        )
        session.add(outbox)
        await session.flush()

        audit = await audit_service.record(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            module=Module.CTMS,
            actor_kind="worker" if worker_id else "user",
            worker_id=worker_id,
            actor_id=actor_id,
            correlation_id=correlation_text,
            scope={"study_id": study_id, "site_id": site_id},
            changed_fields=changed_fields,
            source_module=Module.CTMS,
            source_record_id=entity_id,
            study_id=study_id,
            site_id=site_id,
            reason=reason,
            new_value=(f"status={status}" if status is not None else None),
        )
        await session.flush()
        coordination_service.accepted(outbox.event_id)
        return history, outbox, audit


ctms_atomicity_service = CTMSAtomicityService()

__all__ = ["CTMSAtomicityService", "ctms_atomicity_service"]
