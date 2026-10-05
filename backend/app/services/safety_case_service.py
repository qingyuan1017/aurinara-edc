"""PV Safety_Case service boundary.

Owns Safety_Case intake, Adverse_Event_Record capture, the case lifecycle state
machine, and Case_Version sequencing. PV never creates, allocates, or mutates an
EDC clinical subject record or a CTMS operational record. Concrete behavior lands
in the safety-case intake, lifecycle, and versioning tasks; this module
establishes the additive service boundary and interface.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.pv import ActorContext, CaseState, utc_now
from app.models.pv.safety_case import (
    AdverseEventRecord,
    CaseVersion,
    CaseVersionKind,
    CaseVersionStatus,
    SafetyCase,
)
from app.models.pv.safety_case import CaseState as CaseLifecycle
from app.repositories.pv.safety_case_repository import SafetyCaseRepository
from app.services.pv_atomicity_service import pv_atomicity_service
from app.services.pv_identity_service import (
    CanonicalIdentity,
    IdentityReferenceMetadata,
    PVIdentityResolver,
)
from app.services.pv_ownership_guard import assert_pv_command_safe

# Verbatim-term bounds for an Adverse_Event_Record (Requirement 3.3, 3.7).
_VERBATIM_MIN_LENGTH = 1
_VERBATIM_MAX_LENGTH = 200
# Bounds mirrored from the persistence layer for a case type/identifier.
_CASE_TYPE_MAX_LENGTH = 100
_CASE_IDENTIFIER_MAX_LENGTH = 100
_OUTCOME_MAX_LENGTH = 100
# Reason_For_Change bound for post-submission changes (Requirements 4.6, 4.7).
_REASON_MAX_LENGTH = 4000

# The constrained case lifecycle transitions (Requirement 4.1). Any transition
# not listed here is rejected without changing case state or content
# (Requirement 4.2).
_ALLOWED_TRANSITIONS: dict[CaseLifecycle, frozenset[CaseLifecycle]] = {
    CaseLifecycle.OPEN: frozenset({CaseLifecycle.IN_REVIEW}),
    CaseLifecycle.IN_REVIEW: frozenset(
        {
            CaseLifecycle.FOLLOW_UP_REQUIRED,
            CaseLifecycle.READY_TO_REPORT,
            CaseLifecycle.CLOSED,
        }
    ),
    CaseLifecycle.FOLLOW_UP_REQUIRED: frozenset({CaseLifecycle.IN_REVIEW}),
    CaseLifecycle.READY_TO_REPORT: frozenset(
        {CaseLifecycle.REPORTED, CaseLifecycle.IN_REVIEW}
    ),
    CaseLifecycle.REPORTED: frozenset(
        {CaseLifecycle.CLOSED, CaseLifecycle.FOLLOW_UP_REQUIRED}
    ),
    CaseLifecycle.CLOSED: frozenset({CaseLifecycle.REOPENED}),
    CaseLifecycle.REOPENED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class ResolvedCaseIdentity:
    """Read-only canonical identities and their traceability metadata for a case.

    The resolved identities preserve the canonical Study/Site identity and the
    EDC ``Subject_Reference`` on the PV record without duplicating any EDC
    clinical record. ``reference_metadata`` records the source module, resolved
    source identifier, active ownership-rule version, and correlation identifier
    for each referenced identity.
    """

    study: CanonicalIdentity
    site: CanonicalIdentity
    subject_reference: CanonicalIdentity
    reference_metadata: tuple[IdentityReferenceMetadata, ...]


class SafetyCaseService:
    """Authoritative service for PV safety cases and adverse-event capture.

    A Safety_Data mutation and its PV safety Audit_Event commit atomically in one
    transaction; the service receives an ``AsyncSession`` from the route or worker
    and never opens an independent session.
    """

    # ------------------------------------------------------------------
    # Cross-module ownership and canonical identity (Task 2.1)
    # ------------------------------------------------------------------

    @staticmethod
    def guard_command(
        payload: Mapping[str, Any] | None = None,
        *,
        operation: str | None = None,
    ) -> None:
        """Reject EDC-/CTMS-owned fields or operations before any state change.

        Called by every PV mutation entry point before a transaction is opened,
        so a command that targets an EDC clinical or CTMS operational record
        changes no PV safety state and no audit state (Requirements 16.6, 23.4,
        23.5).
        """

        assert_pv_command_safe(payload, operation=operation)

    async def resolve_case_identity(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        site_id: UUID,
        subject_reference: UUID,
        actor: ActorContext,
        ownership_rule_version: int = 1,
    ) -> ResolvedCaseIdentity:
        """Resolve canonical Study/Site and the EDC Subject_Reference by stable ID.

        Unknown or ambiguous references are rejected before any Safety_Case is
        created. PV references the EDC clinical subject identity and never
        creates, allocates, or mutates an EDC clinical subject or protocol visit
        (Requirements 3.10, 23.1, 23.2, 23.3). Each resolved identity carries
        source/rule/correlation traceability metadata for the PV record.
        """

        resolver = PVIdentityResolver(session)
        study = await resolver.resolve_study(study_id)
        site = await resolver.resolve_site(site_id, study_id=study_id)
        subject = await resolver.resolve_subject_reference(
            subject_reference, study_id=study_id, site_id=site_id
        )
        metadata = tuple(
            identity.reference_metadata(
                target_reference=None,
                ownership_rule_version=ownership_rule_version,
                correlation_id=actor.correlation_id,
            )
            for identity in (study, site, subject)
        )
        return ResolvedCaseIdentity(
            study=study,
            site=site,
            subject_reference=subject,
            reference_metadata=metadata,
        )

    async def create_case(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        site_id: UUID,
        subject_reference: UUID,
        case_type: str,
        payload: Mapping[str, Any],
        actor: ActorContext,
    ) -> SafetyCase:
        """Create exactly one Safety_Case bound to canonical identity.

        The command is guarded, then canonical Study/Site and the EDC
        Subject_Reference are resolved by stable id (unknown or ambiguous
        references are rejected before any state change). A globally unique
        safety case identifier is generated, or a caller-supplied identifier is
        validated for uniqueness; a duplicate is rejected and changes no
        existing record. The Safety_Case and its single PV safety Audit_Event
        are staged on the caller's transaction so they commit or roll back
        together. PV never creates, allocates, or mutates an EDC clinical
        subject record (Requirements 3.1, 3.2, 3.5, 3.6, 3.8, 3.9, 3.10).
        """

        self.guard_command(payload, operation="create_case")

        case_type_value = self._validate_case_type(case_type)
        # Resolve canonical identity before generating an identifier so a bad
        # reference cannot consume an identifier or persist anything.
        await self.resolve_case_identity(
            session,
            study_id=study_id,
            site_id=site_id,
            subject_reference=subject_reference,
            actor=actor,
        )

        repository = SafetyCaseRepository(session)
        case_identifier = await self._resolve_case_identifier(repository, payload)

        case = await repository.add_case(
            case_identifier=case_identifier,
            study_id=study_id,
            site_id=site_id,
            subject_reference=subject_reference,
            case_type=case_type_value,
            lifecycle_state=CaseLifecycle.OPEN.value,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="safety_case",
            entity_id=case.id,
            action="create",
            actor=actor,
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_reference,
            changed_fields=("case_identifier", "case_type", "lifecycle_state"),
            field_name="lifecycle_state",
            old_value=None,
            new_value=CaseLifecycle.OPEN.value,
        )
        return case

    async def add_adverse_event(
        self,
        session: AsyncSession,
        *,
        case_id: UUID,
        payload: Mapping[str, Any],
        actor: ActorContext,
    ) -> AdverseEventRecord:
        """Capture one Adverse_Event_Record under an existing Safety_Case.

        The verbatim term must be 1-200 characters, an onset date and outcome
        are required, and a resolution date is persisted only when it is no
        earlier than the onset date. Invalid input is rejected before any state
        change, persisting neither the invalid data nor a change event. A valid
        save stages the record and its single PV safety Audit_Event on the
        caller's transaction (Requirements 3.3, 3.4, 3.7, 3.8, 3.9).
        """

        self.guard_command(payload, operation="add_adverse_event")

        repository = SafetyCaseRepository(session)
        case = await repository.get_case(case_id)
        if case is None:
            raise NotFoundError(
                message="Safety_Case was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_case"},
            )

        verbatim_term = self._validate_verbatim(payload.get("verbatim_term"))
        onset_date = self._require_date(payload.get("onset_date"), field="onset_date")
        outcome = self._validate_outcome(payload.get("outcome"))
        resolution_date = self._validate_resolution(
            payload.get("resolution_date"), onset_date=onset_date
        )

        record = await repository.add_adverse_event(
            case=case,
            verbatim_term=verbatim_term,
            onset_date=onset_date,
            outcome=outcome,
            resolution_date=resolution_date,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="adverse_event_record",
            entity_id=record.id,
            action="create",
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            subject_id=case.subject_reference,
            changed_fields=("verbatim_term", "onset_date", "outcome", "resolution_date"),
            field_name="verbatim_term",
            old_value=None,
            new_value=verbatim_term,
        )
        return record

    # ------------------------------------------------------------------
    # Validation and identifier helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_case_type(case_type: Any) -> str:
        if not isinstance(case_type, str):
            raise ValidationError(
                message="case_type is required",
                details={"reason": "INVALID_FIELD", "field": "case_type"},
            )
        value = case_type.strip()
        if not (1 <= len(value) <= _CASE_TYPE_MAX_LENGTH):
            raise ValidationError(
                message="case_type must be 1 to 100 characters",
                details={"reason": "INVALID_FIELD", "field": "case_type"},
            )
        return value

    async def _resolve_case_identifier(
        self, repository: SafetyCaseRepository, payload: Mapping[str, Any]
    ) -> str:
        """Return a validated, globally unique safety case identifier.

        A caller-supplied identifier is validated and rejected when it already
        exists (Requirement 3.6); otherwise one is generated (Requirement 3.2).
        """

        supplied = payload.get("case_identifier")
        if supplied is not None:
            if not isinstance(supplied, str) or not supplied.strip():
                raise ValidationError(
                    message="case_identifier must be a non-empty string",
                    details={"reason": "INVALID_FIELD", "field": "case_identifier"},
                )
            candidate = supplied.strip()
            if len(candidate) > _CASE_IDENTIFIER_MAX_LENGTH:
                raise ValidationError(
                    message="case_identifier must be at most 100 characters",
                    details={"reason": "INVALID_FIELD", "field": "case_identifier"},
                )
            if await repository.case_identifier_exists(candidate):
                raise ConflictError(
                    message="A Safety_Case already uses this identifier",
                    details={
                        "reason": "DUPLICATE_CASE_IDENTIFIER",
                        "field": "case_identifier",
                    },
                )
            return candidate

        # Generate a platform-unique identifier. The UUID keeps generation
        # collision-free; the uniqueness check defends against any external
        # collision before persisting.
        for _ in range(5):
            candidate = f"PV-{uuid4().hex[:16].upper()}"
            if not await repository.case_identifier_exists(candidate):
                return candidate
        raise ConflictError(
            message="Could not allocate a unique safety case identifier",
            details={"reason": "DUPLICATE_CASE_IDENTIFIER", "field": "case_identifier"},
        )

    @staticmethod
    def _validate_verbatim(value: Any) -> str:
        if not isinstance(value, str):
            raise ValidationError(
                message="verbatim_term is required",
                details={"reason": "INVALID_FIELD", "field": "verbatim_term"},
            )
        # Length is measured on the exact stored value (persisted 1-200 chars).
        if not (_VERBATIM_MIN_LENGTH <= len(value) <= _VERBATIM_MAX_LENGTH):
            raise ValidationError(
                message="verbatim_term must be 1 to 200 characters",
                details={"reason": "INVALID_FIELD", "field": "verbatim_term"},
            )
        return value

    @staticmethod
    def _validate_outcome(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                message="outcome is required",
                details={"reason": "INVALID_FIELD", "field": "outcome"},
            )
        outcome = value.strip()
        if len(outcome) > _OUTCOME_MAX_LENGTH:
            raise ValidationError(
                message="outcome must be at most 100 characters",
                details={"reason": "INVALID_FIELD", "field": "outcome"},
            )
        return outcome

    @staticmethod
    def _require_date(value: Any, *, field: str) -> date:
        parsed = SafetyCaseService._coerce_date(value, field=field)
        if parsed is None:
            raise ValidationError(
                message=f"{field} is required",
                details={"reason": "INVALID_FIELD", "field": field},
            )
        return parsed

    @staticmethod
    def _validate_resolution(value: Any, *, onset_date: date) -> date | None:
        resolution_date = SafetyCaseService._coerce_date(value, field="resolution_date")
        if resolution_date is None:
            return None
        if resolution_date < onset_date:
            raise ValidationError(
                message="resolution_date must not be earlier than onset_date",
                details={"reason": "INVALID_FIELD", "field": "resolution_date"},
            )
        return resolution_date

    @staticmethod
    def _coerce_date(value: Any, *, field: str) -> date | None:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError as exc:
                raise ValidationError(
                    message=f"{field} must be an ISO-8601 date",
                    details={"reason": "INVALID_FIELD", "field": field},
                ) from exc
        raise ValidationError(
            message=f"{field} must be a date",
            details={"reason": "INVALID_FIELD", "field": field},
        )

    # ------------------------------------------------------------------
    # Case lifecycle and Case_Version state machine (Task 2.4)
    # ------------------------------------------------------------------

    async def transition(
        self,
        session: AsyncSession,
        *,
        case_id: UUID,
        target: CaseState,
        reason: str | None,
        actor: ActorContext,
    ) -> SafetyCase:
        """Move a Safety_Case to ``target`` if the transition is permitted.

        Only the constrained transitions in Requirement 4.1 are accepted. Any
        other transition is rejected before any state change so the case state
        and content are left unchanged (Requirement 4.2). A permitted transition
        emits exactly one PV safety Audit_Event capturing the action, actor, and
        timestamp on the caller's transaction (Requirement 4.9).
        """

        target_state = self._coerce_target_state(target)

        repository = SafetyCaseRepository(session)
        case = await repository.get_case(case_id)
        if case is None:
            raise NotFoundError(
                message="Safety_Case was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_case"},
            )

        current_state = self._coerce_current_state(case.lifecycle_state)
        allowed = _ALLOWED_TRANSITIONS.get(current_state, frozenset())
        if target_state not in allowed:
            raise ValidationError(
                message="The requested lifecycle transition is not permitted",
                details={
                    "reason": "TRANSITION_NOT_PERMITTED",
                    "from_state": current_state.value,
                    "to_state": target_state.value,
                },
            )

        await repository.update_lifecycle_state(
            case=case,
            lifecycle_state=target_state.value,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="safety_case",
            entity_id=case.id,
            action="transition",
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            subject_id=case.subject_reference,
            changed_fields=("lifecycle_state",),
            field_name="lifecycle_state",
            old_value=current_state.value,
            new_value=target_state.value,
            reason=reason,
        )
        return case

    async def submit_version(
        self,
        session: AsyncSession,
        *,
        case_id: UUID,
        actor: ActorContext,
    ) -> CaseVersion:
        """Submit an immutable initial or follow-up Case_Version snapshot.

        With no prior submitted version the snapshot is the initial version with
        sequence number 1; otherwise it is a follow-up with a sequence number of
        the highest existing submitted sequence number plus 1 (Requirements 4.3,
        4.4). The captured content is snapshotted immutably once Submitted, and
        no prior submitted version is deleted or overwritten (Requirements 4.5,
        4.8). Exactly one PV safety Audit_Event is emitted for the submission
        (Requirement 4.9).
        """

        repository = SafetyCaseRepository(session)
        case = await repository.get_case(case_id)
        if case is None:
            raise NotFoundError(
                message="Safety_Case was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_case"},
            )

        max_sequence = await repository.max_submitted_sequence_number(case_id)
        if max_sequence is None:
            sequence_number = 1
            version_kind = CaseVersionKind.INITIAL.value
        else:
            sequence_number = max_sequence + 1
            version_kind = CaseVersionKind.FOLLOW_UP.value

        captured_content = await self._snapshot_case_content(repository, case)

        version = await repository.add_submitted_version(
            case=case,
            sequence_number=sequence_number,
            version_kind=version_kind,
            captured_content=captured_content,
            submitted_at=utc_now(),
            submitted_by=actor.user_id,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="case_version",
            entity_id=version.id,
            action="submit",
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            subject_id=case.subject_reference,
            changed_fields=("sequence_number", "version_kind", "status"),
            field_name="status",
            old_value=None,
            new_value=CaseVersionStatus.SUBMITTED.value,
        )
        return version

    async def change_submitted_data(
        self,
        session: AsyncSession,
        *,
        case_id: UUID,
        changes: Mapping[str, Any],
        reason_for_change: str,
        actor: ActorContext,
    ) -> SafetyCase:
        """Apply a post-submission change to submitted Safety_Data.

        A change requires a Reason_For_Change that is non-empty after trimming
        and no more than 4,000 characters; an empty or over-length reason is
        rejected and leaves the submitted Safety_Data unchanged (Requirements
        4.6, 4.7). A prior submitted Case_Version's captured content is immutable
        and is never modified by this path; an attempt to modify a submitted
        version is rejected (Requirement 4.5). Exactly one PV safety Audit_Event
        records the change together with the Reason_For_Change.
        """

        self.guard_command(changes, operation="change_submitted_data")
        reason = self._validate_reason_for_change(reason_for_change)

        repository = SafetyCaseRepository(session)
        case = await repository.get_case(case_id)
        if case is None:
            raise NotFoundError(
                message="Safety_Case was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_case"},
            )

        # A submitted Case_Version's captured content is immutable; a change
        # request must never target one (Requirement 4.5).
        version_id = changes.get("version_id")
        if version_id is not None:
            version = await repository.get_version(self._coerce_uuid(version_id))
            if version is not None and version.status == CaseVersionStatus.SUBMITTED.value:
                raise ValidationError(
                    message="A submitted Case_Version is immutable",
                    details={
                        "reason": "VERSION_IMMUTABLE",
                        "entity_type": "case_version",
                    },
                )

        applied = self._apply_case_changes(case, changes)
        # Persist the actor/correlation update on the case; the lifecycle state
        # is unchanged by a data change. The Reason_For_Change is recorded on
        # the PV safety Audit_Event below (Requirement 4.7).
        await repository.update_lifecycle_state(
            case=case,
            lifecycle_state=case.lifecycle_state,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="safety_case",
            entity_id=case.id,
            action="change_submitted_data",
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            subject_id=case.subject_reference,
            changed_fields=tuple(applied),
            reason=reason,
        )
        return case

    # ------------------------------------------------------------------
    # Lifecycle / version helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_target_state(target: CaseState | str) -> CaseLifecycle:
        value = target.value if isinstance(target, CaseState) else str(target)
        try:
            return CaseLifecycle(value)
        except ValueError as exc:
            raise ValidationError(
                message="Unknown target lifecycle state",
                details={"reason": "INVALID_FIELD", "field": "target"},
            ) from exc

    @staticmethod
    def _coerce_current_state(value: str) -> CaseLifecycle:
        try:
            return CaseLifecycle(value)
        except ValueError as exc:  # pragma: no cover - guarded by DB constraint
            raise ValidationError(
                message="Safety_Case has an unknown lifecycle state",
                details={"reason": "INVALID_STATE", "field": "lifecycle_state"},
            ) from exc

    @staticmethod
    def _coerce_uuid(value: Any) -> UUID:
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (ValueError, TypeError) as exc:
            raise ValidationError(
                message="version_id must be a valid identifier",
                details={"reason": "INVALID_FIELD", "field": "version_id"},
            ) from exc

    @staticmethod
    def _validate_reason_for_change(reason: Any) -> str:
        if not isinstance(reason, str):
            raise ValidationError(
                message="A valid Reason_For_Change is required",
                details={"reason": "INVALID_REASON_FOR_CHANGE", "field": "reason_for_change"},
            )
        trimmed = reason.strip()
        if not trimmed or len(reason) > _REASON_MAX_LENGTH:
            raise ValidationError(
                message="A valid Reason_For_Change is required",
                details={"reason": "INVALID_REASON_FOR_CHANGE", "field": "reason_for_change"},
            )
        return reason

    async def _snapshot_case_content(
        self, repository: SafetyCaseRepository, case: SafetyCase
    ) -> dict[str, Any]:
        """Build an immutable snapshot of a case's captured content.

        The snapshot contains only PV-owned safety fields and read-only
        canonical references; it never copies an EDC clinical payload.
        """

        events = await repository.list_adverse_events(case.id)
        return {
            "case_identifier": case.case_identifier,
            "study_id": str(case.study_id),
            "site_id": str(case.site_id),
            "subject_reference": str(case.subject_reference),
            "case_type": case.case_type,
            "lifecycle_state": case.lifecycle_state,
            "adverse_events": [
                {
                    "id": str(event.id),
                    "verbatim_term": event.verbatim_term,
                    "onset_date": event.onset_date.isoformat()
                    if event.onset_date
                    else None,
                    "outcome": event.outcome,
                    "resolution_date": event.resolution_date.isoformat()
                    if event.resolution_date
                    else None,
                }
                for event in events
            ],
        }

    @staticmethod
    def _apply_case_changes(case: SafetyCase, changes: Mapping[str, Any]) -> list[str]:
        """Apply mutable PV-owned case fields from a change payload.

        Only ``case_type`` is a mutable case-level field here; identity and
        lifecycle fields are never changed through this path. Unknown fields are
        ignored so a change payload cannot mutate a read-only canonical
        reference.
        """

        applied: list[str] = []
        if "case_type" in changes:
            new_case_type = SafetyCaseService._validate_case_type(changes["case_type"])
            if new_case_type != case.case_type:
                case.case_type = new_case_type
                applied.append("case_type")
        return applied


safety_case_service = SafetyCaseService()

__all__ = ["ResolvedCaseIdentity", "SafetyCaseService", "safety_case_service"]
