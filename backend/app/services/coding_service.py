"""PV Coding service.

Owns MedDRA and WHODrug coding assignments (Requirement 6). Each assignment is
PV-owned Safety_Data referencing a PV ``Adverse_Event_Record`` (MedDRA) or a
reported product (WHODrug); it never creates, allocates, or mutates an EDC
clinical record.

Behavioral contract (Requirement 6):

  - ``assign_meddra`` codes an Adverse_Event_Record verbatim term and
    ``assign_whodrug`` codes a reported product, persisting the selected term,
    the ``Coding_Dictionary_Version`` used, and the assigning actor and
    timestamp (6.1, 6.2).
  - A coding referencing a term absent from the identified dictionary version is
    rejected with an error identifying the invalid term and version, and no
    coding is persisted (6.3).
  - A coding referencing a missing or unavailable ``Coding_Dictionary_Version``
    is rejected with an error indicating the version is unavailable, and no
    coding is persisted (6.4).
  - ``recode`` retains the prior assignment and its dictionary version immutably
    and records the traceability link from the prior assignment to the new one
    (6.5).
  - Each created or changed coding emits exactly one PV safety Audit_Event
    capturing the actor, timestamp, prior/new value, and dictionary version
    (6.6).

Term validation uses a deterministic, in-memory
:class:`~app.services.pv_coding_dictionary.CodingDictionaryProvider` rather than
an external dictionary service. Version availability is resolved against the
``pv_coding_dictionary_versions`` registry.

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
from app.models.pv.coding import CodingSystem, MedDraCoding, WhoDrugCoding
from app.models.pv.safety_case import CaseState, SafetyCase
from app.repositories.pv.coding_repository import CodingRepository
from app.services.pv_atomicity_service import pv_atomicity_service
from app.services.pv_coding_dictionary import (
    CodingDictionaryProvider,
    default_coding_dictionary,
)

_TERM_ID_MAX_LENGTH = 100
_TERM_LABEL_MAX_LENGTH = 255
_DICTIONARY_VERSION_MAX_LENGTH = 50


class CodingService:
    """Authoritative service for PV MedDRA/WHODrug coding."""

    def __init__(self, dictionary: CodingDictionaryProvider | None = None) -> None:
        self._dictionary = dictionary or default_coding_dictionary

    # ------------------------------------------------------------------
    # MedDRA
    # ------------------------------------------------------------------

    async def assign_meddra(
        self,
        session: AsyncSession,
        *,
        ae_id: UUID,
        term_id: str,
        dictionary_version: str,
        actor: ActorContext,
        term_label: str | None = None,
    ) -> MedDraCoding:
        """Assign a MedDRA coding to an Adverse_Event_Record verbatim term.

        The Adverse_Event_Record must exist and its parent Safety_Case must not
        be Closed. The identified ``Coding_Dictionary_Version`` must be
        registered and available, and the term must exist within it; otherwise
        no coding is persisted (Requirements 6.1, 6.3, 6.4). A valid assignment
        stages the coding and its single PV safety Audit_Event on the caller's
        transaction (Requirement 6.6).
        """

        repository = CodingRepository(session)

        ae = await repository.get_adverse_event(ae_id)
        if ae is None:
            raise NotFoundError(
                message="Adverse_Event_Record was not found",
                details={
                    "reason": "RECORD_NOT_FOUND",
                    "entity_type": "adverse_event_record",
                },
            )
        case = await self._require_open_case(repository, ae.case_id)

        term = self._validate_term_id(term_id)
        label = self._validate_term_label(term_label)
        version = self._validate_version_string(dictionary_version)

        await self._require_valid_term(
            repository,
            coding_system=CodingSystem.MEDDRA,
            version=version,
            term_id=term,
        )

        assigned_at = utc_now()
        coding = await repository.add_meddra_coding(
            ae_id=ae_id,
            term_id=term,
            term_label=label,
            dictionary_version=version,
            assigned_at=assigned_at,
            assigned_by=actor.user_id,
            prior_coding_id=None,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        await self._record_audit(
            session,
            entity_type="meddra_coding",
            entity_id=coding.id,
            action="create",
            actor=actor,
            case=case,
            old_value=None,
            new_value=self._coding_value(term, version),
            dictionary_version=version,
        )
        return coding

    # ------------------------------------------------------------------
    # WHODrug
    # ------------------------------------------------------------------

    async def assign_whodrug(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        term_id: str,
        dictionary_version: str,
        actor: ActorContext,
        term_label: str | None = None,
    ) -> WhoDrugCoding:
        """Assign a WHODrug coding to a reported product.

        The identified ``Coding_Dictionary_Version`` must be registered and
        available, and the term must exist within it; otherwise no coding is
        persisted (Requirements 6.2, 6.3, 6.4). A valid assignment stages the
        coding and its single PV safety Audit_Event on the caller's transaction
        (Requirement 6.6).
        """

        repository = CodingRepository(session)

        term = self._validate_term_id(term_id)
        label = self._validate_term_label(term_label)
        version = self._validate_version_string(dictionary_version)

        await self._require_valid_term(
            repository,
            coding_system=CodingSystem.WHODRUG,
            version=version,
            term_id=term,
        )

        assigned_at = utc_now()
        coding = await repository.add_whodrug_coding(
            product_id=product_id,
            term_id=term,
            term_label=label,
            dictionary_version=version,
            assigned_at=assigned_at,
            assigned_by=actor.user_id,
            prior_coding_id=None,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        await self._record_audit(
            session,
            entity_type="whodrug_coding",
            entity_id=coding.id,
            action="create",
            actor=actor,
            case=None,
            old_value=None,
            new_value=self._coding_value(term, version),
            dictionary_version=version,
        )
        return coding

    # ------------------------------------------------------------------
    # Recode (traceability)
    # ------------------------------------------------------------------

    async def recode(
        self,
        session: AsyncSession,
        *,
        prior_coding_id: UUID,
        term_id: str,
        dictionary_version: str,
        actor: ActorContext,
        term_label: str | None = None,
    ) -> MedDraCoding | WhoDrugCoding:
        """Recode a previously coded term, retaining the prior assignment.

        The prior coding assignment and its dictionary version are retained
        immutably. A new coding row of the same coding system is created with a
        traceability link (``prior_coding_id``) to the prior assignment, and the
        new term/version are validated exactly as for an initial assignment;
        otherwise no coding is persisted (Requirements 6.3, 6.4, 6.5). Exactly
        one PV safety Audit_Event records the actor, timestamp, prior/new value,
        and dictionary version (Requirement 6.6).
        """

        repository = CodingRepository(session)

        term = self._validate_term_id(term_id)
        label = self._validate_term_label(term_label)
        version = self._validate_version_string(dictionary_version)

        # The prior assignment may be either a MedDRA or a WHODrug coding; the
        # recode keeps the same coding system so the traceability link stays
        # within one dictionary family.
        prior_meddra = await repository.get_meddra_coding(prior_coding_id)
        prior_whodrug: WhoDrugCoding | None = None
        if prior_meddra is None:
            prior_whodrug = await repository.get_whodrug_coding(prior_coding_id)
        if prior_meddra is None and prior_whodrug is None:
            raise NotFoundError(
                message="The prior coding assignment was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "coding"},
            )

        if prior_meddra is not None:
            case = await self._require_open_case(repository, None, adverse_event_id=prior_meddra.ae_id)
            await self._require_valid_term(
                repository,
                coding_system=CodingSystem.MEDDRA,
                version=version,
                term_id=term,
            )
            new_coding = await repository.add_meddra_coding(
                ae_id=prior_meddra.ae_id,
                term_id=term,
                term_label=label,
                dictionary_version=version,
                assigned_at=utc_now(),
                assigned_by=actor.user_id,
                prior_coding_id=prior_meddra.id,
                actor_id=actor.user_id,
                correlation_id=actor.correlation_id,
            )
            await self._record_audit(
                session,
                entity_type="meddra_coding",
                entity_id=new_coding.id,
                action="recode",
                actor=actor,
                case=case,
                old_value=self._coding_value(
                    prior_meddra.term_id, prior_meddra.dictionary_version
                ),
                new_value=self._coding_value(term, version),
                dictionary_version=version,
            )
            return new_coding

        assert prior_whodrug is not None
        await self._require_valid_term(
            repository,
            coding_system=CodingSystem.WHODRUG,
            version=version,
            term_id=term,
        )
        new_who = await repository.add_whodrug_coding(
            product_id=prior_whodrug.product_id,
            term_id=term,
            term_label=label,
            dictionary_version=version,
            assigned_at=utc_now(),
            assigned_by=actor.user_id,
            prior_coding_id=prior_whodrug.id,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )
        await self._record_audit(
            session,
            entity_type="whodrug_coding",
            entity_id=new_who.id,
            action="recode",
            actor=actor,
            case=None,
            old_value=self._coding_value(
                prior_whodrug.term_id, prior_whodrug.dictionary_version
            ),
            new_value=self._coding_value(term, version),
            dictionary_version=version,
        )
        return new_who

    # ------------------------------------------------------------------
    # Guards and helpers
    # ------------------------------------------------------------------

    async def _require_open_case(
        self,
        repository: CodingRepository,
        case_id: UUID | None,
        *,
        adverse_event_id: UUID | None = None,
    ) -> SafetyCase:
        """Resolve the parent Safety_Case and reject Closed cases.

        A Closed parent case rejects new or changed coding and preserves the
        existing state (Requirement 6, consistent with the Closed-case rule for
        safety data). When ``adverse_event_id`` is supplied the case is resolved
        through the adverse event.
        """

        if case_id is None and adverse_event_id is not None:
            ae = await repository.get_adverse_event(adverse_event_id)
            if ae is None:
                raise NotFoundError(
                    message="Adverse_Event_Record was not found",
                    details={
                        "reason": "RECORD_NOT_FOUND",
                        "entity_type": "adverse_event_record",
                    },
                )
            case_id = ae.case_id

        assert case_id is not None
        case = await repository.get_case(case_id)
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

    async def _require_valid_term(
        self,
        repository: CodingRepository,
        *,
        coding_system: CodingSystem,
        version: str,
        term_id: str,
    ) -> None:
        """Reject a missing/unavailable version or a term absent from it.

        Version availability is resolved against the dictionary registry
        (Requirement 6.4); term membership uses the deterministic in-memory
        provider (Requirement 6.3). Both checks run before any coding is
        persisted.
        """

        dictionary = await repository.get_dictionary_version(
            coding_system=coding_system, version=version
        )
        if dictionary is None or not dictionary.available:
            raise ValidationError(
                message="The Coding_Dictionary_Version is missing or unavailable",
                details={
                    "reason": "CODING_DICTIONARY_UNAVAILABLE",
                    "coding_system": coding_system.value,
                    "dictionary_version": version,
                },
            )

        if not self._dictionary.term_exists(
            coding_system=coding_system, version=version, term_id=term_id
        ):
            raise ValidationError(
                message="The term does not exist in the identified dictionary version",
                details={
                    "reason": "CODING_TERM_NOT_FOUND",
                    "coding_system": coding_system.value,
                    "dictionary_version": version,
                    "term_id": term_id,
                },
            )

    @staticmethod
    def _validate_term_id(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                message="term_id is required",
                details={"reason": "INVALID_FIELD", "field": "term_id"},
            )
        term = value.strip()
        if len(term) > _TERM_ID_MAX_LENGTH:
            raise ValidationError(
                message=f"term_id must be at most {_TERM_ID_MAX_LENGTH} characters",
                details={"reason": "INVALID_FIELD", "field": "term_id"},
            )
        return term

    @staticmethod
    def _validate_term_label(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValidationError(
                message="term_label must be text",
                details={"reason": "INVALID_FIELD", "field": "term_label"},
            )
        label = value.strip()
        if not label:
            return None
        if len(label) > _TERM_LABEL_MAX_LENGTH:
            raise ValidationError(
                message=f"term_label must be at most {_TERM_LABEL_MAX_LENGTH} characters",
                details={"reason": "INVALID_FIELD", "field": "term_label"},
            )
        return label

    @staticmethod
    def _validate_version_string(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                message="dictionary_version is required",
                details={"reason": "INVALID_FIELD", "field": "dictionary_version"},
            )
        version = value.strip()
        if len(version) > _DICTIONARY_VERSION_MAX_LENGTH:
            raise ValidationError(
                message=(
                    f"dictionary_version must be at most "
                    f"{_DICTIONARY_VERSION_MAX_LENGTH} characters"
                ),
                details={"reason": "INVALID_FIELD", "field": "dictionary_version"},
            )
        return version

    @staticmethod
    def _coding_value(term_id: str, dictionary_version: str) -> str:
        """Render a coding assignment as a scalar audit value."""

        return f"{term_id}@{dictionary_version}"

    @staticmethod
    async def _record_audit(
        session: AsyncSession,
        *,
        entity_type: str,
        entity_id: UUID,
        action: str,
        actor: ActorContext,
        case: SafetyCase | None,
        old_value: str | None,
        new_value: str,
        dictionary_version: str,
    ) -> None:
        """Emit exactly one PV safety Audit_Event for the coding assignment.

        The event captures the acting user, timestamp, prior/new value, and the
        ``Coding_Dictionary_Version`` on the caller's transaction so the coding
        and its Audit_Event commit or roll back together (Requirement 6.6).
        """

        await pv_atomicity_service.record_mutation(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            study_id=case.study_id if case else None,
            site_id=case.site_id if case else None,
            subject_id=case.subject_reference if case else None,
            changed_fields=("term_id", "dictionary_version"),
            field_name="dictionary_version",
            old_value=old_value,
            new_value=f"{new_value}|dict={dictionary_version}",
        )


coding_service = CodingService()

__all__ = ["CodingService", "coding_service"]
