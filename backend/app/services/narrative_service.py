"""PV Narrative service: authoritative versioned Case_Narratives.

Owns Case_Narrative authoring and revision. A narrative belongs to exactly one
Safety_Case and keeps a retained chain of immutable versions: version 1 is the
authoring version and every revision appends a new version while preserving all
prior versions (Requirements 7.1, 7.2).

Validation rules (Requirements 7.1, 7.2, 7.3):
  - Narrative text is non-empty after trimming leading/trailing whitespace and
    is at most 20,000 characters.
  - A revision Reason_For_Change is non-empty after trimming and at most 4,000
    characters.
  - Invalid text or reason is rejected before any state change; the existing
    narrative state is preserved and no change event is written.

When the parent Safety_Case is Closed a new or revised narrative is rejected and
the existing narrative state is preserved (Requirement 7.4). Each creation or
revision emits exactly one PV safety Audit_Event on the caller's transaction, so
the narrative change and its audit event commit or roll back together
(Requirement 7.5). PV never creates, allocates, or mutates an EDC clinical
record.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.pv import ActorContext, utc_now
from app.models.pv.narrative import (
    NARRATIVE_REASON_MAX_LENGTH,
    NARRATIVE_TEXT_MAX_LENGTH,
    CaseNarrative,
    NarrativeVersion,
)
from app.models.pv.safety_case import CaseState, SafetyCase
from app.repositories.pv.narrative_repository import NarrativeRepository
from app.repositories.pv.safety_case_repository import SafetyCaseRepository
from app.services.pv_atomicity_service import pv_atomicity_service


class NarrativeService:
    """Authoritative service for PV case narratives.

    A narrative mutation and its PV safety Audit_Event commit atomically in one
    transaction; the service receives an ``AsyncSession`` from the route or
    worker and never opens an independent session.
    """

    async def create(
        self,
        session: AsyncSession,
        *,
        case_id: UUID,
        text: str,
        actor: ActorContext,
    ) -> CaseNarrative:
        """Author a new Case_Narrative for a Safety_Case.

        The narrative text must be non-empty after trimming and at most 20,000
        characters; an invalid value is rejected before any state change and no
        narrative or change event is persisted (Requirements 7.1, 7.3). When the
        parent Safety_Case is Closed the creation is rejected and no narrative is
        persisted (Requirement 7.4). A valid save stages the narrative, its
        authoring version (number 1), and a single PV safety Audit_Event on the
        caller's transaction (Requirement 7.5).
        """

        text_value = self._validate_text(text)
        case = await self._require_open_case(session, case_id)

        repository = NarrativeRepository(session)
        narrative = await repository.add_narrative(
            case_id=case.id,
            text_value=text_value,
            authored_at=utc_now(),
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="case_narrative",
            entity_id=narrative.id,
            action="create",
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            subject_id=case.subject_reference,
            changed_fields=("current_text", "current_version_number"),
            field_name="current_version_number",
            old_value=None,
            new_value=narrative.current_version_number,
        )
        return narrative

    async def revise(
        self,
        session: AsyncSession,
        *,
        narrative_id: UUID,
        text: str,
        reason_for_change: str,
        actor: ActorContext,
    ) -> NarrativeVersion:
        """Revise an existing Case_Narrative, retaining the prior version.

        The revised narrative text must be non-empty after trimming and at most
        20,000 characters, and the Reason_For_Change must be non-empty after
        trimming and at most 4,000 characters. An invalid text or reason is
        rejected before any state change; the existing narrative state is
        preserved and no change event is written (Requirement 7.3). When the
        parent Safety_Case is Closed the revision is rejected and the existing
        narrative state is preserved (Requirement 7.4). A valid revision appends
        a new version with sequence ``max + 1`` while retaining all prior
        versions, advances the narrative's current text, and stages a single PV
        safety Audit_Event on the caller's transaction (Requirements 7.2, 7.5).
        """

        # Validate both inputs before touching any state so an invalid text or
        # reason preserves the existing narrative (Requirement 7.3).
        text_value = self._validate_text(text)
        reason = self._validate_reason_for_change(reason_for_change)

        repository = NarrativeRepository(session)
        narrative = await repository.get_narrative(narrative_id)
        if narrative is None:
            raise NotFoundError(
                message="Case_Narrative was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "case_narrative"},
            )

        case = await self._require_open_case(session, narrative.case_id)

        previous_version_number = narrative.current_version_number
        next_version = (await repository.max_version_number(narrative.id) or 0) + 1

        version = await repository.add_revision(
            narrative=narrative,
            text_value=text_value,
            version_number=next_version,
            reason_for_change=reason,
            authored_at=utc_now(),
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="case_narrative",
            entity_id=narrative.id,
            action="revise",
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            subject_id=case.subject_reference,
            changed_fields=("current_text", "current_version_number"),
            field_name="current_version_number",
            old_value=previous_version_number,
            new_value=version.version_number,
            reason=reason,
        )
        return version

    # ------------------------------------------------------------------
    # Shared guards and validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _require_open_case(
        session: AsyncSession, case_id: UUID
    ) -> SafetyCase:
        """Resolve the parent Safety_Case and reject a Closed one.

        A missing Safety_Case is rejected before any state change. When the case
        is Closed the operation is rejected and the existing narrative state is
        preserved (Requirement 7.4).
        """

        case = await SafetyCaseRepository(session).get_case(case_id)
        if case is None:
            raise NotFoundError(
                message="Safety_Case was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_case"},
            )
        if case.lifecycle_state == CaseState.CLOSED.value:
            raise ValidationError(
                message="The Safety_Case is Closed",
                details={"reason": "CASE_CLOSED", "entity_type": "safety_case"},
            )
        return case

    @staticmethod
    def _validate_text(value: Any) -> str:
        """Return validated narrative text (non-empty after trim, <= 20,000).

        The stored value is the trimmed text so the persisted narrative never
        carries leading/trailing whitespace, and the length bound is measured on
        that stored value (Requirements 7.1, 7.3).
        """

        if not isinstance(value, str):
            raise ValidationError(
                message="narrative text is required",
                details={"reason": "INVALID_FIELD", "field": "text"},
            )
        trimmed = value.strip()
        if not (1 <= len(trimmed) <= NARRATIVE_TEXT_MAX_LENGTH):
            raise ValidationError(
                message=(
                    "narrative text must be non-empty after trimming and at most "
                    f"{NARRATIVE_TEXT_MAX_LENGTH} characters"
                ),
                details={"reason": "INVALID_FIELD", "field": "text"},
            )
        return trimmed

    @staticmethod
    def _validate_reason_for_change(value: Any) -> str:
        """Return a validated Reason_For_Change (non-empty after trim, <= 4,000).

        The stored value is the trimmed reason and the length bound is measured
        on it (Requirements 7.2, 7.3).
        """

        if not isinstance(value, str):
            raise ValidationError(
                message="reason_for_change is required",
                details={
                    "reason": "INVALID_REASON_FOR_CHANGE",
                    "field": "reason_for_change",
                },
            )
        trimmed = value.strip()
        if not (1 <= len(trimmed) <= NARRATIVE_REASON_MAX_LENGTH):
            raise ValidationError(
                message=(
                    "reason_for_change must be non-empty after trimming and at most "
                    f"{NARRATIVE_REASON_MAX_LENGTH} characters"
                ),
                details={
                    "reason": "INVALID_REASON_FOR_CHANGE",
                    "field": "reason_for_change",
                },
            )
        return trimmed


narrative_service = NarrativeService()

__all__ = ["NarrativeService", "narrative_service"]
