"""PV Assessment service.

Owns seriousness, causality, expectedness, and severity assessments for
Adverse_Event_Records (Requirement 5). Each assessment is PV-owned Safety_Data:
it references a PV ``Adverse_Event_Record`` and never creates, allocates, or
mutates an EDC clinical record.

Behavioral contract (Requirement 5):

  - A serious ``Seriousness_Assessment`` requires at least one seriousness
    criterion; a not-serious determination is persisted with no criteria; a
    serious determination without a criterion is rejected and the prior state is
    preserved (5.1, 5.2, 5.3).
  - ``Causality_Assessment`` persists the suspect product, causality category,
    and the assessing actor and timestamp (5.4).
  - ``Expectedness_Assessment`` persists an expected/unexpected determination
    against referenced safety information (5.5).
  - ``Severity_Grade`` persists the configured severity classification (5.6).
  - An assessment referencing a missing Adverse_Event_Record (or missing suspect
    product) is rejected and persists no assessment (5.7).
  - When the parent Safety_Case is Closed, new or changed assessments are
    rejected and the existing state is preserved (5.8).
  - Each created or changed assessment emits exactly one PV safety Audit_Event
    capturing the actor, timestamp, prior value, and new value (5.9).

A Safety_Data mutation and its PV safety Audit_Event commit atomically in one
transaction; the service receives an ``AsyncSession`` from the route or worker
and never opens an independent session.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.pv import ActorContext, utc_now
from app.models.pv.assessment import SeriousnessCriterion
from app.models.pv.safety_case import (
    AdverseEventRecord,
    CaseState,
    SafetyCase,
)
from app.repositories.pv.assessment_repository import AssessmentRepository
from app.services.pv_atomicity_service import pv_atomicity_service

_SUSPECT_PRODUCT_MAX_LENGTH = 200
_CAUSALITY_CATEGORY_MAX_LENGTH = 100
_SEVERITY_GRADE_MAX_LENGTH = 100
_REFERENCE_SAFETY_INFORMATION_MAX_LENGTH = 20000

# The valid seriousness criterion values (Requirement 5.1).
_VALID_CRITERIA: frozenset[str] = frozenset(c.value for c in SeriousnessCriterion)


class AssessmentService:
    """Authoritative service for PV safety assessments."""

    async def record_seriousness(
        self,
        session: AsyncSession,
        *,
        ae_id: UUID,
        serious: bool,
        criteria: frozenset[str],
        actor: ActorContext,
    ) -> Any:
        """Record a Seriousness_Assessment for an Adverse_Event_Record.

        A serious determination requires at least one recognized seriousness
        criterion; a not-serious determination persists no criteria. A serious
        determination without a criterion is rejected before any state change and
        the existing assessment state is preserved (Requirements 5.1, 5.2, 5.3).
        """

        repository = AssessmentRepository(session)
        _ae, case = await self._require_open_adverse_event(repository, ae_id)

        normalized = self._validate_seriousness(serious, criteria)

        prior = await repository.latest_seriousness(ae_id)
        assessment = await repository.add_seriousness(
            ae_id=ae_id,
            serious=serious,
            criteria=normalized,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        prior_value = self._seriousness_value(prior.serious, prior.criteria) if prior else None
        await self._record_audit(
            session,
            entity_type="seriousness_assessment",
            entity_id=assessment.id,
            action="create" if prior is None else "update",
            actor=actor,
            case=case,
            changed_fields=("serious", "criteria"),
            field_name="serious",
            old_value=prior_value,
            new_value=self._seriousness_value(serious, normalized),
        )
        return assessment

    async def record_causality(
        self,
        session: AsyncSession,
        *,
        ae_id: UUID,
        suspect_product: str,
        category: str,
        actor: ActorContext,
    ) -> Any:
        """Record a Causality_Assessment for an Adverse_Event_Record.

        Persists the suspect product, the causality category, and the assessing
        actor and timestamp. A missing suspect product or causality category is
        rejected and persists no assessment (Requirements 5.4, 5.7).
        """

        repository = AssessmentRepository(session)
        _ae, case = await self._require_open_adverse_event(repository, ae_id)

        product = self._require_text(
            suspect_product,
            field="suspect_product",
            max_length=_SUSPECT_PRODUCT_MAX_LENGTH,
        )
        causality_category = self._require_text(
            category,
            field="category",
            max_length=_CAUSALITY_CATEGORY_MAX_LENGTH,
        )
        assessed_at = utc_now()

        prior = await repository.latest_causality(ae_id)
        assessment = await repository.add_causality(
            ae_id=ae_id,
            suspect_product=product,
            causality_category=causality_category,
            assessed_at=assessed_at,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        prior_value = (
            f"{prior.suspect_product}:{prior.causality_category}" if prior else None
        )
        await self._record_audit(
            session,
            entity_type="causality_assessment",
            entity_id=assessment.id,
            action="create" if prior is None else "update",
            actor=actor,
            case=case,
            changed_fields=("suspect_product", "causality_category"),
            field_name="causality_category",
            old_value=prior_value,
            new_value=f"{product}:{causality_category}",
        )
        return assessment

    async def record_expectedness(
        self,
        session: AsyncSession,
        *,
        ae_id: UUID,
        expected: bool,
        actor: ActorContext,
        reference_safety_information: str | None = None,
    ) -> Any:
        """Record an Expectedness_Assessment for an Adverse_Event_Record.

        Persists an expected/unexpected determination against the referenced
        safety information (Requirement 5.5).
        """

        repository = AssessmentRepository(session)
        _ae, case = await self._require_open_adverse_event(repository, ae_id)

        rsi = self._optional_text(
            reference_safety_information,
            field="reference_safety_information",
            max_length=_REFERENCE_SAFETY_INFORMATION_MAX_LENGTH,
        )
        assessed_at = utc_now()

        prior = await repository.latest_expectedness(ae_id)
        assessment = await repository.add_expectedness(
            ae_id=ae_id,
            expected=expected,
            reference_safety_information=rsi,
            assessed_at=assessed_at,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        prior_value = self._expectedness_value(prior.expected) if prior else None
        await self._record_audit(
            session,
            entity_type="expectedness_assessment",
            entity_id=assessment.id,
            action="create" if prior is None else "update",
            actor=actor,
            case=case,
            changed_fields=("expected",),
            field_name="expected",
            old_value=prior_value,
            new_value=self._expectedness_value(expected),
        )
        return assessment

    async def record_severity(
        self,
        session: AsyncSession,
        *,
        ae_id: UUID,
        grade: str,
        actor: ActorContext,
    ) -> Any:
        """Record a Severity_Grade for an Adverse_Event_Record.

        Persists the configured severity classification (Requirement 5.6).
        """

        repository = AssessmentRepository(session)
        _ae, case = await self._require_open_adverse_event(repository, ae_id)

        grade_value = self._require_text(
            grade, field="grade", max_length=_SEVERITY_GRADE_MAX_LENGTH
        )
        assessed_at = utc_now()

        prior = await repository.latest_severity(ae_id)
        assessment = await repository.add_severity(
            ae_id=ae_id,
            grade=grade_value,
            assessed_at=assessed_at,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        await self._record_audit(
            session,
            entity_type="severity_grade",
            entity_id=assessment.id,
            action="create" if prior is None else "update",
            actor=actor,
            case=case,
            changed_fields=("grade",),
            field_name="grade",
            old_value=prior.grade if prior else None,
            new_value=grade_value,
        )
        return assessment

    # ------------------------------------------------------------------
    # Shared guards and helpers
    # ------------------------------------------------------------------

    async def _require_open_adverse_event(
        self, repository: AssessmentRepository, ae_id: UUID
    ) -> tuple[AdverseEventRecord, SafetyCase]:
        """Resolve the Adverse_Event_Record and reject Closed parent cases.

        A missing Adverse_Event_Record is rejected before any state change so no
        assessment is persisted (Requirement 5.7). When the parent Safety_Case is
        Closed, new or changed assessments are rejected and the existing
        assessment state is preserved (Requirement 5.8). Returns the adverse
        event and its parent case so the audit event carries study/site scope.
        """

        ae = await repository.get_adverse_event(ae_id)
        if ae is None:
            raise NotFoundError(
                message="Adverse_Event_Record was not found",
                details={
                    "reason": "RECORD_NOT_FOUND",
                    "entity_type": "adverse_event_record",
                },
            )

        case = await repository.get_case(ae.case_id)
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
        return ae, case

    def _validate_seriousness(
        self, serious: bool, criteria: frozenset[str]
    ) -> list[str]:
        """Return a validated, deterministic criteria list for a determination.

        Rejects an unrecognized criterion and a serious determination without at
        least one criterion; a not-serious determination discards any criteria
        (Requirements 5.1, 5.2, 5.3).
        """

        provided = set(criteria or ())
        unknown = provided - _VALID_CRITERIA
        if unknown:
            raise ValidationError(
                message="Unknown seriousness criterion",
                details={
                    "reason": "INVALID_FIELD",
                    "field": "criteria",
                    "invalid": sorted(unknown),
                },
            )

        if not serious:
            return []

        if not provided:
            raise ValidationError(
                message="A serious determination requires at least one seriousness criterion",
                details={"reason": "SERIOUSNESS_CRITERION_REQUIRED", "field": "criteria"},
            )
        # Persist in the canonical enum order for deterministic snapshots.
        return [c.value for c in SeriousnessCriterion if c.value in provided]

    @staticmethod
    def _require_text(value: Any, *, field: str, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                message=f"{field} is required",
                details={"reason": "INVALID_FIELD", "field": field},
            )
        trimmed = value.strip()
        if len(trimmed) > max_length:
            raise ValidationError(
                message=f"{field} must be at most {max_length} characters",
                details={"reason": "INVALID_FIELD", "field": field},
            )
        return trimmed

    @staticmethod
    def _optional_text(value: Any, *, field: str, max_length: int) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValidationError(
                message=f"{field} must be text",
                details={"reason": "INVALID_FIELD", "field": field},
            )
        trimmed = value.strip()
        if not trimmed:
            return None
        if len(trimmed) > max_length:
            raise ValidationError(
                message=f"{field} must be at most {max_length} characters",
                details={"reason": "INVALID_FIELD", "field": field},
            )
        return trimmed

    @staticmethod
    def _seriousness_value(serious: bool, criteria: list[str]) -> str:
        return f"{'serious' if serious else 'not-serious'}:{','.join(criteria)}"

    @staticmethod
    def _expectedness_value(expected: bool) -> str:
        return "expected" if expected else "unexpected"

    @staticmethod
    async def _record_audit(
        session: AsyncSession,
        *,
        entity_type: str,
        entity_id: UUID,
        action: str,
        actor: ActorContext,
        case: SafetyCase,
        changed_fields: tuple[str, ...],
        field_name: str,
        old_value: Any,
        new_value: Any,
    ) -> None:
        """Emit exactly one PV safety Audit_Event for the assessment.

        The event captures the acting user, timestamp, prior value, and new
        value on the caller's transaction so the assessment and its Audit_Event
        commit or roll back together (Requirement 5.9).
        """

        await pv_atomicity_service.record_mutation(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            subject_id=case.subject_reference,
            changed_fields=changed_fields,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
        )


assessment_service = AssessmentService()

__all__ = ["AssessmentService", "assessment_service"]
