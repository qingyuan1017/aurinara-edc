"""Transactional outbox acceptance and deterministic CTMS coordination processing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.config import get_settings
from app.core.ctms import Module, utc_now
from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.metrics import get_metrics
from app.models.ctms.coordination import (
    CoordinationEvent,
    CoordinationEventLog,
    CoordinationEventStatus,
    CTMSEventAttempt,
    CTMSOutbox,
)
from app.models.ctms.retention import CTMSCoordinationConflict, CTMSFailedEvent
from app.services.ctms_health_service import ctms_health_service
from app.services.ctms_ownership_guard import assert_ctms_command_safe
from app.services.ctms_projection_service import ctms_projection_service
from app.services.notification_service import notification_service
from app.services.status_ownership_rule_service import StatusOwnershipRuleService

_TERMINAL_OUTCOMES = frozenset({"succeeded", "skipped", "failed", "conflict"})
_TERMINAL_EVENT_STATUSES = frozenset(
    {
        CoordinationEventStatus.SUCCEEDED.value,
        CoordinationEventStatus.SKIPPED.value,
        CoordinationEventStatus.FAILED.value,
        CoordinationEventStatus.CONFLICT.value,
    }
)

_RETRYABLE_CODES = frozenset({"RETRYABLE_STORAGE_ERROR", "SERVICE_UNAVAILABLE", "TIMEOUT"})
_CONFLICT_CODES = frozenset({
    "COORDINATION_OUT_OF_ORDER",
    "OUT_OF_ORDER",
    "OUT_OF_ORDER_EVENT",
    "STALE_PROJECTION",
    "OWNERSHIP_VIOLATION",
    "EDC_OWNERSHIP_VIOLATION",
    "PROJECTION_TARGET_NOT_CTMS",
    "COORDINATION_TARGET_REQUIRED",
    "CONFLICTING_OWNERSHIP_RULE",
    "AMBIGUOUS_OWNERSHIP_RULE",
})


@dataclass(frozen=True, slots=True)
class FailureClassification:
    """Sanitized processing category; never retains exception text or payloads."""

    code: str
    retryable: bool = False
    conflict: bool = False


def classify_coordination_failure(error: BaseException | str, *, reason: str | None = None) -> FailureClassification:
    """Map worker failures to the stable CTMS vocabulary.

    Storage/service failures are the only retryable class. All other classes
    are terminal and are retained as a Failed_Event or Coordination_Conflict.
    """
    details = getattr(error, "details", {}) if not isinstance(error, str) else {}
    raw_reason = reason or (error if isinstance(error, str) else (details.get("reason") if isinstance(details, Mapping) else None))
    code = str(raw_reason or "").upper()
    if isinstance(error, (ServiceUnavailableError, TimeoutError, ConnectionError, OperationalError, DBAPIError)):
        return FailureClassification("RETRYABLE_STORAGE_ERROR", retryable=True)
    if code in _RETRYABLE_CODES:
        return FailureClassification("RETRYABLE_STORAGE_ERROR", retryable=True)
    if isinstance(error, AuthorizationError) or code in {"AUTHORIZATION_FAILED", "AUTHORIZATION_VIOLATION"}:
        return FailureClassification("AUTHORIZATION_FAILED")
    if code in {"RECORD_NOT_FOUND", "UNKNOWN_REFERENCE", "INVALID_CANONICAL_REFERENCE"}:
        return FailureClassification("RECORD_NOT_FOUND")
    if code in {"AMBIGUOUS_REFERENCE", "AMBIGUOUS_IDENTITY"}:
        return FailureClassification("AMBIGUOUS_REFERENCE")
    if code in _CONFLICT_CODES:
        return FailureClassification(code, conflict=True)
    if code in {"DATA_MINIMIZATION_FAILED", "PROJECTION_FIELD_NOT_ALLOWED", "PROJECTION_PAYLOAD_INVALID"}:
        return FailureClassification("DATA_MINIMIZATION_FAILED")
    if code in {"OWNERSHIP_VIOLATION", "EDC_OWNERSHIP_VIOLATION"}:
        return FailureClassification("OWNERSHIP_VIOLATION", conflict=True)
    if code.startswith(("INVALID_", "SCHEMA_", "PROJECTION_")) or isinstance(error, ValidationError):
        return FailureClassification("SCHEMA_VALIDATION_FAILED")
    # Do not retry arbitrary exceptions: unknown application failures are
    # retained as sanitized schema/service failures rather than leaked.
    return FailureClassification("SCHEMA_VALIDATION_FAILED")


# Backwards-friendly short name for worker and test consumers.
classify_failure = classify_coordination_failure


class BoundedCoordinationQueue:
    """Non-blocking in-process admission bookkeeping for durable outbox rows."""

    def __init__(self, capacity: int | None = None) -> None:
        configured = capacity if capacity is not None else get_settings().ctms_queue_capacity
        self.capacity = max(1, int(configured))
        self._queued: set[UUID] = set()
        self._lock = RLock()

    def try_enqueue(self, event_id: UUID) -> bool:
        """Admit an event without waiting; durable persistence is caller-owned."""
        with self._lock:
            if event_id in self._queued:
                return True
            if len(self._queued) >= self.capacity:
                return False
            self._queued.add(event_id)
            return True

    def complete(self, event_id: UUID) -> None:
        with self._lock:
            self._queued.discard(event_id)

    def clear(self) -> None:
        with self._lock:
            self._queued.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._queued)

    @property
    def saturated(self) -> bool:
        return self.size >= self.capacity


@dataclass(frozen=True, slots=True)
class CoordinationResult:
    """Stable processing response returned for first and duplicate delivery."""

    event: CoordinationEvent
    outcome: str
    resulting_projection_id: UUID | None = None
    reason: str | None = None
    current_version: str | None = None
    duplicate: bool = False


class CoordinationService:
    """Accept, queue, and process approved events without cross-owner writes."""

    @staticmethod
    def _loaded_utc(value: datetime) -> datetime:
        """Normalize driver-returned timestamps before strict UTC validation.

        Some async database drivers (notably SQLite's datetime adapter) return
        timezone-aware columns without their UTC tzinfo after a round trip.
        The persisted value is already defined as UTC by the CTMS contract, so
        restoring that metadata at the worker boundary preserves the instant
        without allowing local timestamps from callers.
        """
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def __init__(
        self,
        *,
        queue: BoundedCoordinationQueue | None = None,
        projection_service=ctms_projection_service,
        identity_resolver: Any | None = None,
    ) -> None:
        self.queue = queue or BoundedCoordinationQueue()
        self.projection_service = projection_service
        self.identity_resolver = identity_resolver

    # ------------------------------------------------------------------
    # Admission and durable outbox
    # ------------------------------------------------------------------

    @staticmethod
    def _payload_fingerprint(payload: Mapping[str, Any]) -> str:
        return StatusOwnershipRuleService.fingerprint(payload)

    @staticmethod
    def _safe_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        """Copy only JSON-safe data; raw event bodies never enter the outbox."""
        if not isinstance(payload, Mapping):
            raise ValidationError("Coordination payload must be an object", {"reason": "INVALID_EVENT_PAYLOAD"})
        assert_ctms_command_safe(payload, operation="accept_coordination_event")

        def normalize(value: Any) -> Any:
            if isinstance(value, UUID):
                return str(value)
            if isinstance(value, datetime):
                return value.astimezone(UTC).isoformat()
            if isinstance(value, Mapping):
                return {str(key): normalize(child) for key, child in value.items()}
            if isinstance(value, (list, tuple)):
                return [normalize(child) for child in value]
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            raise ValidationError("Coordination payload contains an unsupported value", {"reason": "INVALID_EVENT_PAYLOAD"})

        return normalize(payload)

    @staticmethod
    def _validate_allowlist(payload: Mapping[str, Any], allowlist: Mapping[str, Any] | None) -> dict[str, Any]:
        selected = dict(allowlist or {})
        if not selected:
            return selected
        unknown = sorted(set(payload) - set(selected))
        if unknown:
            raise ValidationError(
                "Coordination payload contains fields outside its allowlist",
                {"reason": "PROJECTION_FIELD_NOT_ALLOWED", "rejected_field_count": len(unknown)},
            )
        return selected

    async def accept(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        source_module: Module | str,
        target_module: Module | str,
        entity_type: str,
        source_record_id: UUID,
        source_version: str | int,
        rule_version: int,
        payload: Mapping[str, Any],
        idempotency_key: str,
        correlation_id: str,
        source_sequence: int | None = None,
        source_timestamp: datetime | None = None,
        target_record_id: UUID | None = None,
        target_projection_type: str | None = None,
        allowlist: Mapping[str, Any] | None = None,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
    ) -> CoordinationEvent:
        """Accept one event and its outbox row in the caller's transaction."""
        source = source_module.value if isinstance(source_module, Module) else str(source_module)
        target = target_module.value if isinstance(target_module, Module) else str(target_module)
        if source not in {Module.EDC.value, Module.CTMS.value} or target not in {Module.EDC.value, Module.CTMS.value}:
            raise ValidationError("Coordination modules are invalid", {"reason": "INVALID_COORDINATION_MODULE"})
        if not idempotency_key or not idempotency_key.strip():
            raise ValidationError("Idempotency key is required", {"reason": "IDEMPOTENCY_KEY_REQUIRED"})
        if not correlation_id or not correlation_id.strip():
            raise ValidationError("Correlation identifier is required", {"reason": "CORRELATION_ID_REQUIRED"})
        if int(rule_version) < 1:
            raise ValidationError("Rule version must be positive", {"reason": "INVALID_RULE_VERSION"})
        if source_sequence is not None and (isinstance(source_sequence, bool) or int(source_sequence) < 0):
            raise ValidationError("Source sequence must be non-negative", {"reason": "INVALID_SOURCE_SEQUENCE"})
        safe_payload = self._safe_payload(payload)
        safe_allowlist = self._validate_allowlist(safe_payload, allowlist)
        existing = await session.scalar(
            select(CoordinationEvent).where(
                CoordinationEvent.source_module == source,
                CoordinationEvent.idempotency_key == idempotency_key.strip(),
            )
        )
        if existing is not None:
            return existing

        timestamp = source_timestamp or utc_now()
        event = CoordinationEvent(
            event_type=event_type,
            source_module=source,
            target_module=target,
            entity_type=entity_type,
            source_record_id=source_record_id,
            target_record_id=target_record_id,
            target_projection_type=target_projection_type,
            source_sequence=source_sequence,
            source_version=str(source_version).strip()[:128],
            source_timestamp=timestamp,
            rule_version=int(rule_version),
            allowlist_json=safe_allowlist,
            payload_json=safe_payload,
            payload_fingerprint=self._payload_fingerprint(safe_payload),
            idempotency_key=idempotency_key.strip()[:255],
            correlation_id=correlation_id.strip()[:128],
            study_id=study_id,
            site_id=site_id,
            status=CoordinationEventStatus.ACCEPTED.value,
        )
        session.add(event)
        await session.flush()
        outbox = CTMSOutbox(
            event_id=event.event_id,
            coordination_event_id=event.event_id,
            aggregate_type=entity_type,
            aggregate_id=source_record_id,
            event_type=event_type,
            module=source,
            source_module=source,
            target_module=target,
            source_record_id=source_record_id,
            target_record_id=target_record_id,
            target_projection_type=target_projection_type,
            source_sequence=source_sequence,
            source_version=event.source_version,
            rule_version=event.rule_version,
            allowlist_json=safe_allowlist,
            payload_json=safe_payload,
            payload_fingerprint=event.payload_fingerprint,
            idempotency_key=event.idempotency_key,
            correlation_id=event.correlation_id,
            status=CoordinationEventStatus.ACCEPTED.value,
        )
        session.add(outbox)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="coordination_event",
            entity_id=event.id,
            action="accepted",
            module=Module.CTMS,
            actor_kind="worker" if source == Module.EDC.value else "user",
            correlation_id=event.correlation_id,
            source_module=source,
            target_module=target,
            source_record_id=source_record_id,
            target_record_id=target_record_id,
            study_id=study_id,
            site_id=site_id,
            changed_fields=["status", "idempotency_key", "source_version", "rule_version"],
        )
        self.accepted(event.event_id)
        return event

    async def queue_event(self, session: AsyncSession, event: CoordinationEvent) -> CoordinationEvent:
        """Move an accepted event to queued state without committing."""
        if event.status == CoordinationEventStatus.ACCEPTED.value:
            event.status = CoordinationEventStatus.QUEUED.value
            event.queued_at = utc_now()
            outbox = await self._outbox(session, event)
            if outbox is not None:
                outbox.status = CoordinationEventStatus.QUEUED.value
            await session.flush()
        return event

    async def _outbox(self, session: AsyncSession, event: CoordinationEvent) -> CTMSOutbox | None:
        return await session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event.event_id))

    # ------------------------------------------------------------------
    # Deterministic processing
    # ------------------------------------------------------------------

    async def process(
        self,
        session: AsyncSession,
        *,
        event_id: UUID,
        worker_id: str,
    ) -> CoordinationResult:
        """Process one event; duplicate delivery returns the completed log."""
        event = await session.scalar(
            select(CoordinationEvent).where(
                or_(CoordinationEvent.event_id == event_id, CoordinationEvent.id == event_id)
            )
        )
        if event is None:
            raise ValidationError("Coordination event was not found", {"reason": "RECORD_NOT_FOUND"})
        event.source_timestamp = self._loaded_utc(event.source_timestamp)
        event.accepted_at = self._loaded_utc(event.accepted_at)
        previous = await session.scalar(
            select(CoordinationEventLog).where(CoordinationEventLog.event_id == event.event_id)
        )
        if previous is not None:
            return CoordinationResult(
                event=event,
                outcome=previous.outcome,
                resulting_projection_id=previous.target_projection_id,
                reason=previous.sanitized_reason,
                current_version=previous.current_version,
                duplicate=True,
            )
        if event.status in _TERMINAL_EVENT_STATUSES:
            return CoordinationResult(
                event=event,
                outcome=event.status,
                resulting_projection_id=event.resulting_projection_id,
                reason=event.sanitized_reason,
                current_version=event.current_version,
                duplicate=True,
            )

        await self.queue_event(session, event)
        event.status = CoordinationEventStatus.PROCESSING.value
        event.processing_at = utc_now()
        event.attempt_count = int(event.attempt_count or 0) + 1
        outbox = await self._outbox(session, event)
        if outbox is not None:
            outbox.status = CoordinationEventStatus.PROCESSING.value
            outbox.attempt_count = event.attempt_count
            outbox.claimed_at = event.processing_at
        attempt = CTMSEventAttempt(
            event_id=event.event_id,
            attempt_number=event.attempt_count,
            worker_id=worker_id[:128],
            started_at=event.processing_at,
        )
        session.add(attempt)
        await session.flush()

        try:
            await self.revalidate_current_policy(session, event)
            predecessor = await self._unprocessed_predecessor(session, event)
            if predecessor is not None:
                return await self._finish(
                    session, event, attempt, outbox,
                    outcome=CoordinationEventStatus.CONFLICT.value,
                    worker_id=worker_id,
                    reason="COORDINATION_OUT_OF_ORDER",
                )
            result = await self._apply_target(session, event, worker_id=worker_id)
            if result is None:
                outcome, reason, current_version, projection_id = "succeeded", None, None, None
            else:
                if result.rejected:
                    raise ValidationError(
                        "Projection payload failed minimization validation",
                        {"reason": "DATA_MINIMIZATION_FAILED"},
                    )
                if result.conflict:
                    raise ConflictError(
                        "Projection source cannot be applied",
                        {"reason": result.reason or "COORDINATION_CONFLICT"},
                    )
                outcome = result.outcome
                reason = result.reason
                current_version = result.current_version
                projection_id = result.projection.id if result.projection is not None else None
            if outcome not in _TERMINAL_OUTCOMES:
                outcome = "succeeded"
            return await self._finish(
                session, event, attempt, outbox,
                outcome=outcome,
                worker_id=worker_id,
                reason=reason,
                current_version=current_version,
                projection_id=projection_id,
            )
        except Exception as exc:
            classification = classify_coordination_failure(exc)
            if classification.retryable:
                max_attempts = max(1, int(get_settings().ctms_coordination_max_attempts))
                if event.attempt_count < max_attempts:
                    return await self._retry(
                        session, event, attempt, outbox, code=classification.code
                    )
                classification = FailureClassification("RETRY_LIMIT_EXCEEDED")
            return await self._finish(
                session, event, attempt, outbox,
                outcome="conflict" if classification.conflict else "failed",
                worker_id=worker_id,
                reason=classification.code,
            )

    async def revalidate_current_policy(self, session: AsyncSession, event: CoordinationEvent) -> None:
        """Re-check identity and the active rule immediately before mutation."""
        resolver = self.identity_resolver
        if resolver is not None:
            method = getattr(resolver, "resolve", None) or getattr(resolver, "resolve_reference", None)
            if method is not None:
                resolved = method(
                    session,
                    entity_type=event.entity_type,
                    source_record_id=event.source_record_id,
                    study_id=event.study_id,
                    site_id=event.site_id,
                )
                if hasattr(resolved, "__await__"):
                    resolved = await resolved
                if resolved is None:
                    raise ValidationError("Canonical coordination reference was not found", {"reason": "RECORD_NOT_FOUND"})
                if isinstance(resolved, (list, tuple, set)) and len(resolved) != 1:
                    reason = "AMBIGUOUS_REFERENCE" if resolved else "RECORD_NOT_FOUND"
                    raise ValidationError("Canonical coordination reference is not unique", {"reason": reason})

        rule_service = getattr(self.projection_service, "rule_service", None)
        if rule_service is None:
            return
        current = await rule_service.current_rule(session, event.entity_type, event.target_projection_type or event.entity_type)
        if current is None:
            # Events accepted before a database rule was persisted retain their
            # immutable acceptance rule and remain processable.
            return
        current_version = int(getattr(current, "version", 0))
        current_target = getattr(current, "projection_target", None)
        current_target = getattr(current_target, "value", current_target)
        if current_version != int(event.rule_version) or current_target not in {None, Module.CTMS.value}:
            raise ConflictError("The coordination ownership policy has changed", {"reason": "CONFLICTING_OWNERSHIP_RULE"})
        current_allowlist = getattr(current, "allowlist_json", getattr(current, "typed_allowlist", {})) or {}
        if event.allowlist_json and set(current_allowlist) != set(event.allowlist_json):
            raise ConflictError("The coordination projection allowlist has changed", {"reason": "PROJECTION_FIELD_NOT_ALLOWED"})

    @staticmethod
    def _backoff_seconds(attempt: int) -> int:
        settings = get_settings()
        base = max(1, int(settings.ctms_coordination_backoff_base_seconds))
        ceiling = max(base, int(settings.ctms_coordination_backoff_max_seconds))
        return min(ceiling, base * (2 ** max(0, attempt - 1)))

    async def _retry(
        self,
        session: AsyncSession,
        event: CoordinationEvent,
        attempt: CTMSEventAttempt,
        outbox: CTMSOutbox | None,
        *,
        code: str,
    ) -> CoordinationResult:
        """Retain a sanitized attempt and schedule only retryable failures."""
        now = utc_now()
        delay = self._backoff_seconds(event.attempt_count)
        attempt.finished_at = now
        attempt.outcome = CoordinationEventStatus.RETRYING.value
        attempt.error_category = code
        attempt.sanitized_detail = code
        event.status = CoordinationEventStatus.RETRYING.value
        event.sanitized_reason = code
        if outbox is not None:
            outbox.status = "Retrying"
            outbox.outcome = "retrying"
            outbox.last_error_category = code
            outbox.sanitized_reason = code
            outbox.available_at = now + timedelta(seconds=delay)
            outbox.attempt_count = event.attempt_count
        await session.flush()
        return CoordinationResult(event=event, outcome="retrying", reason=code)

    async def _unprocessed_predecessor(
        self, session: AsyncSession, event: CoordinationEvent
    ) -> CoordinationEvent | None:
        if event.source_sequence is None:
            return None
        return await session.scalar(
            select(CoordinationEvent)
            .where(
                CoordinationEvent.source_module == event.source_module,
                CoordinationEvent.entity_type == event.entity_type,
                CoordinationEvent.source_record_id == event.source_record_id,
                CoordinationEvent.source_sequence < event.source_sequence,
                CoordinationEvent.status.not_in(tuple(_TERMINAL_EVENT_STATUSES)),
            )
            .order_by(CoordinationEvent.source_sequence.desc())
        )

    async def _apply_target(self, session: AsyncSession, event: CoordinationEvent, *, worker_id: str):
        if event.target_projection_type is None:
            if event.target_record_id is None:
                return None
            raise ConflictError("Only explicitly named coordination targets may be updated", {"reason": "COORDINATION_TARGET_REQUIRED"})
        if event.target_module != Module.CTMS.value:
            raise ConflictError("The coordination target is not an approved CTMS projection", {"reason": "PROJECTION_TARGET_NOT_CTMS"})
        rule = {
            "entity_type": event.entity_type,
            "field_path": event.target_projection_type,
            "authoritative_module": event.source_module,
            "writable_module": event.source_module,
            "projection_target": event.target_module,
            "projection_type": event.target_projection_type,
            "typed_allowlist": event.allowlist_json,
            "allowed_transitions": {},
            "version": event.rule_version,
            "effective_from": event.accepted_at,
            "status": "active",
        }
        return await self.projection_service.apply_projection(
            session,
            rule=rule,
            projection_type=event.target_projection_type,
            source_module=event.source_module,
            source_record_id=event.source_record_id,
            payload=event.payload_json,
            source_version=event.source_version,
            source_sequence=event.source_sequence,
            source_timestamp=event.source_timestamp,
            rule_version=event.rule_version,
            correlation_id=event.correlation_id,
            study_id=event.study_id,
            site_id=event.site_id,
            worker_id=worker_id,
        )

    async def _record_failure_or_conflict(
        self,
        session: AsyncSession,
        event: CoordinationEvent,
        *,
        outcome: str,
        reason: str,
        current_version: str | None = None,
    ) -> None:
        """Persist only a stable code and references for remediation."""
        if outcome == "failed":
            existing = await session.scalar(
                select(CTMSFailedEvent).where(CTMSFailedEvent.event_id == event.event_id)
            )
            if existing is None:
                session.add(
                    CTMSFailedEvent(
                        event_id=event.event_id,
                        study_id=event.study_id,
                        site_id=event.site_id,
                        reason_code=reason[:100],
                        sanitized_details_json={"reason_code": reason[:100]},
                        attempt_count=event.attempt_count,
                        correlation_id=event.correlation_id,
                    )
                )
                await notification_service.on_failed_event(session, event, reason=reason)
        elif outcome == "conflict":
            existing = await session.scalar(
                select(CTMSCoordinationConflict).where(
                    CTMSCoordinationConflict.event_id == event.event_id,
                    CTMSCoordinationConflict.status == "open",
                )
            )
            if existing is None:
                conflict = CTMSCoordinationConflict(
                    event_id=event.event_id,
                    study_id=event.study_id,
                    site_id=event.site_id,
                    conflict_type=reason[:50],
                    source_version=event.source_version,
                    current_version=current_version,
                    correlation_id=event.correlation_id,
                    sanitized_details_json={"reason_code": reason[:100]},
                )
                session.add(conflict)
                await session.flush()
                await notification_service.on_coordination_conflict(session, conflict, reason=reason)

    async def _finish(
        self,
        session: AsyncSession,
        event: CoordinationEvent,
        attempt: CTMSEventAttempt,
        outbox: CTMSOutbox | None,
        *,
        outcome: str,
        worker_id: str,
        reason: str | None = None,
        current_version: str | None = None,
        projection_id: UUID | None = None,
    ) -> CoordinationResult:
        completed_at = utc_now()
        event.status = outcome
        event.processed_at = completed_at
        event.sanitized_reason = reason[:160] if reason else None
        event.current_version = current_version
        event.resulting_projection_id = projection_id
        attempt.finished_at = completed_at
        attempt.outcome = outcome
        attempt.error_category = event.sanitized_reason
        attempt.sanitized_detail = event.sanitized_reason
        if outbox is not None:
            outbox.status = "Published" if outcome in {"succeeded", "skipped"} else outcome.title()
            outbox.outcome = outcome
            outbox.processed_at = completed_at
            outbox.published_at = completed_at if outcome in {"succeeded", "skipped"} else None
            outbox.resulting_projection_id = projection_id
            outbox.current_version = current_version
            outbox.sanitized_reason = event.sanitized_reason
            outbox.last_error_category = event.sanitized_reason
        log = CoordinationEventLog(
            event_id=event.event_id,
            source_module=event.source_module,
            target_module=event.target_module,
            entity_type=event.entity_type,
            source_record_id=event.source_record_id,
            target_projection_id=projection_id,
            rule_version=event.rule_version,
            source_sequence=event.source_sequence,
            source_version=event.source_version,
            current_version=current_version,
            correlation_id=event.correlation_id,
            outcome=outcome,
            sanitized_reason=event.sanitized_reason,
            completed_at=completed_at,
        )
        session.add(log)
        await session.flush()
        if outcome in {"failed", "conflict"} and event.sanitized_reason:
            await self._record_failure_or_conflict(
                session,
                event,
                outcome=outcome,
                reason=event.sanitized_reason,
                current_version=current_version,
            )
        await audit_service.record(
            session,
            entity_type="coordination_event",
            entity_id=event.id,
            action=outcome,
            module=Module.CTMS,
            actor_kind="worker",
            worker_id=worker_id,
            correlation_id=event.correlation_id,
            source_module=event.source_module,
            target_module=event.target_module,
            source_record_id=event.source_record_id,
            target_record_id=projection_id,
            study_id=event.study_id,
            site_id=event.site_id,
            changed_fields=["status", "attempt_count", "resulting_projection_id", "current_version"],
            reason=event.sanitized_reason,
        )
        if outcome == "succeeded" or outcome == "skipped":
            self.processed(event.event_id)
        elif outcome == "conflict":
            self.conflict(event.event_id)
        else:
            self.failed(event.event_id)
        return CoordinationResult(
            event=event,
            outcome=outcome,
            resulting_projection_id=projection_id,
            reason=event.sanitized_reason,
            current_version=current_version,
        )

    async def replay_failed_event(
        self,
        session: AsyncSession,
        *,
        event_id: UUID,
        actor: Any,
        reason: str,
    ) -> CTMSOutbox:
        """Authorize and requeue a failed event after current-policy checks."""
        if not reason or not reason.strip():
            raise ValidationError("Replay reason is required", {"reason": "REASON_REQUIRED"})
        event = await session.scalar(select(CoordinationEvent).where(CoordinationEvent.event_id == event_id))
        outbox = await session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == event_id))
        if event is None or outbox is None:
            raise ValidationError("Coordination event was not found", {"reason": "RECORD_NOT_FOUND"})
        if hasattr(actor, "user_roles"):
            from app.services.permission_service import PermissionService

            PermissionService().require(
                actor,
                "ctms.coordination-replay",
                study_id=event.study_id,
                site_id=event.site_id,
            )
        failed = await session.scalar(select(CTMSFailedEvent).where(CTMSFailedEvent.event_id == event_id))
        if failed is None and event.status != CoordinationEventStatus.FAILED.value:
            raise ConflictError("Only failed events may be replayed", {"reason": "COORDINATION_REPLAY"})
        await self.revalidate_current_policy(session, event)
        event.status = CoordinationEventStatus.ACCEPTED.value
        event.sanitized_reason = None
        event.processed_at = None
        event.processing_at = None
        event.attempt_count = 0
        outbox.status = "Pending"
        outbox.outcome = None
        outbox.claimed_at = None
        outbox.processed_at = None
        outbox.published_at = None
        outbox.attempt_count = 0
        outbox.last_error_category = None
        outbox.sanitized_reason = None
        outbox.available_at = utc_now()
        await session.flush()
        if failed is not None:
            failed.sanitized_details_json = {"reason_code": "REPLAY_PENDING"}
        await audit_service.record(
            session,
            entity_type="coordination_event",
            entity_id=event.id,
            action="replay_requested",
            module=Module.CTMS,
            actor_id=getattr(actor, "id", None),
            correlation_id=event.correlation_id,
            source_module=event.source_module,
            target_module=event.target_module,
            source_record_id=event.source_record_id,
            study_id=event.study_id,
            site_id=event.site_id,
            changed_fields=["status", "attempt_count", "available_at"],
            reason=reason.strip()[:160],
        )
        return outbox

    async def process_batch(
        self, session: AsyncSession, events: Sequence[CoordinationEvent], *, worker_id: str
    ) -> list[CoordinationResult]:
        """Process a batch in the stable source order used by rebuilds/workers."""
        ordered = sorted(events, key=self.projection_service.source_order_key)
        return [await self.process(session, event_id=event.event_id, worker_id=worker_id) for event in ordered]

    # ------------------------------------------------------------------
    # Compatibility queue/worker bookkeeping
    # ------------------------------------------------------------------

    def accepted(self, event_id: UUID | None = None) -> bool:
        admitted = self.queue.try_enqueue(event_id or uuid4())
        get_metrics().record_ctms_event_accepted()
        ctms_health_service.set_queue_state(self.queue.size, self.queue.capacity, saturated=not admitted)
        if not admitted:
            ctms_health_service.set_worker_status("degraded")
        return admitted

    async def accept_outbox(self, session: AsyncSession, event: CTMSOutbox) -> CTMSOutbox:
        await session.flush()
        self.accepted(event.event_id)
        return event

    def processed(self, event_id: UUID | None = None) -> None:
        if event_id is not None:
            self.queue.complete(event_id)
        get_metrics().record_ctms_event_processed()
        ctms_health_service.set_queue_state(self.queue.size, self.queue.capacity, saturated=self.queue.saturated)
        ctms_health_service.record_successful_processing()

    def failed(self, event_id: UUID | None = None) -> None:
        if event_id is not None:
            self.queue.complete(event_id)
        get_metrics().record_ctms_failed_event()
        ctms_health_service.set_queue_state(self.queue.size, self.queue.capacity, saturated=self.queue.saturated)

    def conflict(self, event_id: UUID | None = None) -> None:
        if event_id is not None:
            self.queue.complete(event_id)
        get_metrics().record_ctms_conflict()
        ctms_health_service.set_queue_state(self.queue.size, self.queue.capacity, saturated=self.queue.saturated)

    async def failed_event(self, session: AsyncSession, event: CTMSOutbox, *, reason: str) -> CTMSOutbox:
        event.status = "Failed"
        event.last_error_category = str(reason)[:100]
        event.sanitized_reason = str(reason)[:160]
        if event.coordination_event_id is not None:
            coordination_event = await session.scalar(
                select(CoordinationEvent).where(CoordinationEvent.event_id == event.coordination_event_id)
            )
            if coordination_event is not None:
                coordination_event.status = CoordinationEventStatus.FAILED.value
                coordination_event.sanitized_reason = event.sanitized_reason
                coordination_event.processed_at = utc_now()
        await session.flush()
        coordination = await session.scalar(
            select(CoordinationEvent).where(CoordinationEvent.event_id == event.event_id)
        )
        if coordination is not None:
            await self._record_failure_or_conflict(
                session, coordination, outcome="failed", reason=event.sanitized_reason
            )
        self.failed(event.event_id)
        return event

    async def conflict_event(self, session: AsyncSession, event: CTMSOutbox, *, reason: str) -> CTMSOutbox:
        event.status = "Conflict"
        event.outcome = "conflict"
        event.last_error_category = str(reason)[:100]
        event.sanitized_reason = str(reason)[:160]
        event.processed_at = utc_now()
        coordination = None
        if event.coordination_event_id is not None:
            coordination = await session.scalar(
                select(CoordinationEvent).where(CoordinationEvent.event_id == event.coordination_event_id)
            )
            if coordination is not None:
                coordination.status = CoordinationEventStatus.CONFLICT.value
                coordination.sanitized_reason = event.sanitized_reason
                coordination.processed_at = event.processed_at
                await self._record_failure_or_conflict(
                    session, coordination, outcome="conflict", reason=event.sanitized_reason
                )
        await session.flush()
        self.conflict(event.event_id)
        return event

    def worker_unavailable(self) -> None:
        """Mark outage without touching durable accepted events."""
        ctms_health_service.set_worker_status("unavailable")

    def worker_available(self) -> None:
        ctms_health_service.set_worker_status("available")


coordination_service = CoordinationService()

__all__ = [
    "BoundedCoordinationQueue",
    "CoordinationResult",
    "CoordinationService",
    "FailureClassification",
    "classify_coordination_failure",
    "classify_failure",
    "coordination_service",
]
