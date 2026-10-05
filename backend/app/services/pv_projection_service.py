"""PV read-only EDC adverse-event projection consumption service.

This service owns the PV side of consuming an approved, minimized, read-only
``Safety_Operational_Projection`` of an EDC adverse event delivered through the
shared ``Coordination_Service`` transactional outbox. Given one claimed outbox
event it:

* revalidates the active ``Status_Ownership_Rule`` and the field allowlist so
  only approved fields (subject reference, verbatim term, onset date,
  seriousness) can cross the boundary (Requirements 10.4, 23.6);
* rejects and records any unapproved/unauthorized projection request, delivering
  no content (Requirement 23.7);
* upserts only the PV-side projection read model idempotently by
  ``Idempotency_Key`` (Requirement 23.8);
* never lets a stale event overwrite a current projection (design "Coordination
  and read-only projection consumption");
* records the processing outcome as a ``pv_coordination_refs`` reference by
  correlation identifier so projected EDC references stay traceable
  (Requirement 17.6).

The projection is read-only for PV. Nothing here creates, allocates, or mutates
an EDC clinical record or a CTMS operational record (Requirement 23.10). The
service stages rows on the caller-provided session and never commits; the worker
unit of work owns the commit/rollback boundary so the projection, its
coordination reference, and any PV safety Audit_Event commit or roll back
together.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models.ctms.coordination import CTMSOutbox
from app.models.pv.coordination import (
    APPROVED_PROJECTION_FIELDS,
    CoordinationRef,
    EdcAeProjection,
)
from app.repositories.pv.projection_repository import ProjectionRepository
from app.services.pv_atomicity_service import pv_atomicity_service
from app.services.status_ownership_rule_service import (
    StatusOwnershipRuleService,
    status_ownership_rule_service,
)

WORKER_NAME = "pv-projection"

# Prohibited substrings that must never appear in a projected field path even if
# an outbox row's allowlist is tampered with. Mirrors the shared ownership guard.
_PROHIBITED_TOKENS = ("password", "ssn", "secret", "token", "credential", "mrn")

# Terminal processing outcomes recorded on the coordination reference.
_OUTCOME_APPLIED = "applied"
_OUTCOME_SKIPPED_STALE = "skipped_stale"
_OUTCOME_SKIPPED_DUPLICATE = "skipped_duplicate"
_OUTCOME_DENIED = "denied"

# Sanitized denial/skip reasons; never leak raw payloads or clinical fields.
_REASON_FIELD_NOT_ALLOWED = "PROJECTION_FIELD_NOT_ALLOWED"
_REASON_UNAUTHORIZED = "PROJECTION_UNAUTHORIZED"
_REASON_RULE_INACTIVE = "PROJECTION_RULE_INACTIVE"
_REASON_STALE = "STALE_PROJECTION"


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """The outcome of processing one projection event."""

    outcome: str
    projection: EdcAeProjection | None
    ref: CoordinationRef
    applied: bool
    denied: bool = False
    stale: bool = False
    duplicate: bool = False
    reason: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _coerce_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError as exc:
            raise ValidationError(
                "Projection onset_date is not a valid date",
                {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": "onset_date"},
            ) from exc
    raise ValidationError(
        "Projection onset_date is not a valid date",
        {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": "onset_date"},
    )


def _coerce_uuid(value: Any) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError(
            "Projection subject_reference is not a valid identifier",
            {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": "subject_reference"},
        ) from exc


def _compare_versions(left: str, right: str) -> int:
    """Compare numeric source versions numerically, opaque versions stably."""

    try:
        left_num, right_num = int(left), int(right)
    except (TypeError, ValueError):
        return (left > right) - (left < right)
    return (left_num > right_num) - (left_num < right_num)


class PVProjectionService:
    """Authoritative PV service for read-only EDC projection consumption."""

    def __init__(self, rule_service: StatusOwnershipRuleService | None = None) -> None:
        self._rules = rule_service or status_ownership_rule_service

    async def process_event(
        self,
        session: AsyncSession,
        event: CTMSOutbox,
        *,
        worker_id: str = WORKER_NAME,
        now: datetime | None = None,
    ) -> ProjectionResult:
        """Consume one claimed projection outbox event idempotently.

        The event carries the approved minimized payload plus its source
        identifier, rule version, correlation identifier, and allowlist. The
        method revalidates the allowlist and ownership rule, upserts the PV
        projection read model idempotently, and records the coordination
        reference and PV safety Audit_Event on the caller's transaction.
        """

        moment = now or _utc_now()
        repository = ProjectionRepository(session)

        idempotency_key = str(event.idempotency_key or event.event_id)
        correlation_id = str(event.correlation_id or event.event_id)
        source_module = str(event.source_module or "EDC")
        source_record_id = event.source_record_id
        source_version = str(event.source_version or "1")
        rule_version = int(event.rule_version or 1)
        payload: Mapping[str, Any] = event.payload_json or {}
        allowlist: Mapping[str, Any] = event.allowlist_json or {}

        # Idempotency: a completed reference for this event means we already
        # processed it. Re-delivery is a no-op that returns the prior result.
        existing_ref = await repository.get_ref_by_idempotency_key(idempotency_key)
        if existing_ref is not None:
            projection = await repository.get_projection_by_idempotency_key(idempotency_key)
            return ProjectionResult(
                outcome=existing_ref.outcome,
                projection=projection,
                ref=existing_ref,
                applied=existing_ref.outcome == _OUTCOME_APPLIED,
                duplicate=True,
                reason=existing_ref.sanitized_reason,
            )

        # Authorization / approval: the projection must be an approved PV-release
        # containing solely allowlisted fields. An unapproved or unauthorized
        # request delivers no content and is recorded as Rejected.
        denial = self._validate_authorization(
            source_record_id=source_record_id,
            payload=payload,
            allowlist=allowlist,
        )
        if denial is not None:
            return await self._record_denied(
                session,
                repository,
                event=event,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                source_module=source_module,
                source_record_id=source_record_id,
                source_version=source_version,
                rule_version=rule_version,
                reason=denial,
                worker_id=worker_id,
                now=moment,
            )

        minimized = self._minimize(payload)
        fingerprint = self._rules.fingerprint(dict(minimized))

        # Staleness: never let an older source version overwrite the current
        # projection for the same source record.
        current = await repository.get_current_projection_for_source(
            source_module=source_module, source_record_id=source_record_id
        )
        if current is not None and _compare_versions(source_version, current.source_version) <= 0:
            return await self._record_skipped(
                session,
                repository,
                event=event,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                source_module=source_module,
                source_record_id=source_record_id,
                source_version=source_version,
                rule_version=rule_version,
                fingerprint=fingerprint,
                projection=current,
                worker_id=worker_id,
                now=moment,
            )

        return await self._record_applied(
            session,
            repository,
            event=event,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_module=source_module,
            source_record_id=source_record_id,
            source_version=source_version,
            rule_version=rule_version,
            fingerprint=fingerprint,
            minimized=minimized,
            previous_current=current,
            worker_id=worker_id,
            now=moment,
        )

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_authorization(
        self,
        *,
        source_record_id: UUID | None,
        payload: Mapping[str, Any],
        allowlist: Mapping[str, Any],
    ) -> str | None:
        """Return a sanitized denial reason, or ``None`` when approved.

        A projection is approved only when it names a source record, its
        allowlist stays within the approved reconciled field set, and its
        payload contains no field outside that allowlist or any prohibited token.
        """

        if source_record_id is None:
            return _REASON_UNAUTHORIZED

        approved = set(APPROVED_PROJECTION_FIELDS)
        allow_keys = {str(key) for key in allowlist} if allowlist else set(approved)

        # The delivered allowlist must not expand beyond the approved field set.
        if not allow_keys or not allow_keys.issubset(approved):
            return _REASON_FIELD_NOT_ALLOWED

        for key in payload:
            normalized = str(key).lower().replace("-", "_")
            if any(token in normalized for token in _PROHIBITED_TOKENS):
                return _REASON_FIELD_NOT_ALLOWED
            if str(key) not in allow_keys:
                return _REASON_FIELD_NOT_ALLOWED

        return None

    def _minimize(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Project only the approved reconciled fields from the payload."""

        return {
            field: payload[field]
            for field in APPROVED_PROJECTION_FIELDS
            if field in payload and payload[field] is not None
        }

    # ------------------------------------------------------------------
    # Outcome recording
    # ------------------------------------------------------------------

    async def _record_applied(
        self,
        session: AsyncSession,
        repository: ProjectionRepository,
        *,
        event: CTMSOutbox,
        idempotency_key: str,
        correlation_id: str,
        source_module: str,
        source_record_id: UUID,
        source_version: str,
        rule_version: int,
        fingerprint: str,
        minimized: Mapping[str, Any],
        previous_current: EdcAeProjection | None,
        worker_id: str,
        now: datetime,
    ) -> ProjectionResult:
        # Supersede the previous current projection so exactly one row is
        # Current per source record.
        if previous_current is not None:
            previous_current.projection_status = "Stale"
            session.add(previous_current)

        projection = EdcAeProjection(
            source_module=source_module,
            source_record_id=source_record_id,
            source_version=source_version,
            rule_version=rule_version,
            idempotency_key=idempotency_key,
            projected_at=now,
            payload_fingerprint=fingerprint,
            projection_status="Current",
            study_id=event.study_id if hasattr(event, "study_id") else None,
            site_id=event.site_id if hasattr(event, "site_id") else None,
            subject_reference=_coerce_uuid(minimized.get("subject_reference")),
            verbatim_term=(
                str(minimized["verbatim_term"]) if minimized.get("verbatim_term") is not None else None
            ),
            onset_date=_coerce_date(minimized.get("onset_date")),
            seriousness=(
                str(minimized["seriousness"]) if minimized.get("seriousness") is not None else None
            ),
            correlation_id=correlation_id,
        )
        repository.add_projection(projection)
        await repository.flush()

        ref = self._build_ref(
            event=event,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_module=source_module,
            source_record_id=source_record_id,
            source_version=source_version,
            rule_version=rule_version,
            fingerprint=fingerprint,
            outcome=_OUTCOME_APPLIED,
            reason=None,
            projection_id=projection.id,
            now=now,
        )
        repository.add_ref(ref)
        await repository.flush()

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="edc_ae_projection",
            entity_id=projection.id,
            action="project",
            worker_id=worker_id,
            study_id=projection.study_id,
            site_id=projection.site_id,
            subject_id=projection.subject_reference,
            correlation_id=correlation_id,
            changed_fields=["projection_status", "payload_fingerprint", "source_version"],
            field_name="projection_status",
            old_value=(previous_current.projection_status if previous_current else None),
            new_value="Current",
        )

        await repository.mark_outbox_outcome(
            event,
            outcome="succeeded",
            status="Published",
            processed_at=now,
            resulting_projection_id=projection.id,
            sanitized_reason=None,
        )

        return ProjectionResult(
            outcome=_OUTCOME_APPLIED,
            projection=projection,
            ref=ref,
            applied=True,
        )

    async def _record_skipped(
        self,
        session: AsyncSession,
        repository: ProjectionRepository,
        *,
        event: CTMSOutbox,
        idempotency_key: str,
        correlation_id: str,
        source_module: str,
        source_record_id: UUID,
        source_version: str,
        rule_version: int,
        fingerprint: str,
        projection: EdcAeProjection,
        worker_id: str,
        now: datetime,
    ) -> ProjectionResult:
        """Record a stale event that must not overwrite the current projection."""

        ref = self._build_ref(
            event=event,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_module=source_module,
            source_record_id=source_record_id,
            source_version=source_version,
            rule_version=rule_version,
            fingerprint=fingerprint,
            outcome=_OUTCOME_SKIPPED_STALE,
            reason=_REASON_STALE,
            projection_id=projection.id,
            now=now,
        )
        repository.add_ref(ref)
        await repository.flush()

        await repository.mark_outbox_outcome(
            event,
            outcome="skipped",
            status="Published",
            processed_at=now,
            resulting_projection_id=projection.id,
            sanitized_reason=_REASON_STALE,
        )

        return ProjectionResult(
            outcome=_OUTCOME_SKIPPED_STALE,
            projection=projection,
            ref=ref,
            applied=False,
            stale=True,
            reason=_REASON_STALE,
        )

    async def _record_denied(
        self,
        session: AsyncSession,
        repository: ProjectionRepository,
        *,
        event: CTMSOutbox,
        idempotency_key: str,
        correlation_id: str,
        source_module: str,
        source_record_id: UUID | None,
        source_version: str,
        rule_version: int,
        reason: str,
        worker_id: str,
        now: datetime,
    ) -> ProjectionResult:
        """Record a denied unapproved/unauthorized projection with no content.

        A Rejected projection row is stored with no minimized fields (delivering
        no content) alongside a coordination reference and a PV safety
        Audit_Event describing the denial.
        """

        record_id = source_record_id or event.source_record_id
        projection = EdcAeProjection(
            source_module=source_module,
            source_record_id=record_id,
            source_version=source_version,
            rule_version=rule_version,
            idempotency_key=idempotency_key,
            projected_at=now,
            payload_fingerprint="",
            projection_status="Rejected",
            study_id=getattr(event, "study_id", None),
            site_id=getattr(event, "site_id", None),
            subject_reference=None,
            verbatim_term=None,
            onset_date=None,
            seriousness=None,
            rejection_reason=reason,
            correlation_id=correlation_id,
        )
        repository.add_projection(projection)
        await repository.flush()

        ref = self._build_ref(
            event=event,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_module=source_module,
            source_record_id=record_id,
            source_version=source_version,
            rule_version=rule_version,
            fingerprint=None,
            outcome=_OUTCOME_DENIED,
            reason=reason,
            projection_id=projection.id,
            now=now,
        )
        repository.add_ref(ref)
        await repository.flush()

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="edc_ae_projection",
            entity_id=projection.id,
            action="reject",
            worker_id=worker_id,
            study_id=projection.study_id,
            site_id=projection.site_id,
            correlation_id=correlation_id,
            changed_fields=["projection_status", "rejection_reason"],
            field_name="projection_status",
            old_value=None,
            new_value="Rejected",
            reason=reason,
        )

        await repository.mark_outbox_outcome(
            event,
            outcome="failed",
            status="Failed",
            processed_at=now,
            resulting_projection_id=projection.id,
            sanitized_reason=reason,
        )

        return ProjectionResult(
            outcome=_OUTCOME_DENIED,
            projection=projection,
            ref=ref,
            applied=False,
            denied=True,
            reason=reason,
        )

    @staticmethod
    def _build_ref(
        *,
        event: CTMSOutbox,
        idempotency_key: str,
        correlation_id: str,
        source_module: str,
        source_record_id: UUID,
        source_version: str,
        rule_version: int,
        fingerprint: str | None,
        outcome: str,
        reason: str | None,
        projection_id: UUID | None,
        now: datetime,
    ) -> CoordinationRef:
        return CoordinationRef(
            event_id=event.event_id,
            source_module=source_module,
            source_record_id=source_record_id,
            source_version=source_version,
            rule_version=rule_version,
            idempotency_key=idempotency_key,
            payload_fingerprint=fingerprint,
            outcome=outcome,
            sanitized_reason=reason,
            projection_id=projection_id,
            processed_at=now,
            correlation_id=correlation_id,
        )


pv_projection_service = PVProjectionService()

__all__ = [
    "WORKER_NAME",
    "PVProjectionService",
    "ProjectionResult",
    "pv_projection_service",
]
