"""PV Reconciliation service.

Owns one-way, read-only reconciliation of PV safety events against the approved,
minimized ``Safety_Operational_Projection`` of EDC adverse events. ``diff`` is a
pure, deterministic function over two record sets so it can be exercised directly
by property-based tests.

Reconciliation is one-way and read-only. No reconciliation path creates,
allocates, or mutates any EDC clinical record or CTMS operational record: ``run``
reads PV Safety_Cases and the read-only EDC projection, records a PV-owned
``ReconciliationRun`` with match/discrepancy counts, and writes one PV-owned
``ReconciliationDiscrepancy`` per differing record (Requirements 10.1, 10.2,
10.3). When the required projection is unavailable or stale, ``run`` produces no
results and returns an error indicating the EDC projection is unavailable
(Requirement 10.5). A reconciliation operation may not modify an EDC clinical
record; :meth:`ReconciliationService.run` never writes EDC state and rejects any
caller-supplied EDC mutation intent, changing neither EDC clinical nor PV safety
state (Requirement 10.6). Creating a discrepancy emits one PV safety Audit_Event,
and resolving one emits another (Requirement 10.7).

The service stages rows on the caller-provided session and never commits; the
request or worker unit of work owns the commit/rollback boundary so the run, its
discrepancies, and their PV safety Audit_Events commit or roll back together.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ServiceUnavailableError, ValidationError
from app.core.pv import ActorContext, utc_now
from app.models.pv.coordination import ProjectionStatus
from app.models.pv.reconciliation import (
    RECONCILED_FIELDS,
    DiscrepancyStatus,
    ReconciliationDiscrepancy,
    ReconciliationRun,
)
from app.repositories.pv.assessment_repository import AssessmentRepository
from app.repositories.pv.projection_repository import ProjectionRepository
from app.repositories.pv.reconciliation_repository import ReconciliationRepository
from app.services.pv_atomicity_service import pv_atomicity_service


@dataclass(frozen=True, slots=True)
class ReconciliationDiff:
    """One differing record produced by :meth:`ReconciliationService.diff`.

    ``case_id`` names the affected Safety_Case, ``edc_reference`` the projected
    EDC source record, and ``differing_fields`` the reconciled fields that differ
    (a subset of :data:`RECONCILED_FIELDS`).
    """

    case_id: UUID | None
    edc_reference: UUID | None
    differing_fields: tuple[str, ...]

    def as_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "edc_reference": self.edc_reference,
            "differing_fields": list(self.differing_fields),
        }


def _normalize_date(value: Any) -> date | None:
    """Render an onset date as a ``date`` for stable comparison."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _normalize_uuid(value: Any) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def _match_key(record: Mapping[str, Any]) -> tuple[Any, Any]:
    """Return the natural key tying a safety event to a projected EDC event.

    Records are the same underlying adverse event when they share the subject
    reference and the verbatim term.
    """

    return (
        _normalize_uuid(record.get("subject_reference")),
        _normalize_text(record.get("verbatim_term")),
    )


def _differing_fields(
    safety: Mapping[str, Any], edc: Mapping[str, Any]
) -> tuple[str, ...]:
    """Return the reconciled fields whose values differ between two records."""

    differences: list[str] = []
    # subject_reference and verbatim_term form the match key; when two records
    # match they share those values, but a mismatch is still reported when only
    # one is present (handled by unmatched records in ``diff``).
    if _normalize_uuid(safety.get("subject_reference")) != _normalize_uuid(
        edc.get("subject_reference")
    ):
        differences.append("subject_reference")
    if _normalize_text(safety.get("verbatim_term")) != _normalize_text(
        edc.get("verbatim_term")
    ):
        differences.append("verbatim_term")
    if _normalize_date(safety.get("onset_date")) != _normalize_date(edc.get("onset_date")):
        differences.append("onset_date")
    if _normalize_text(safety.get("seriousness")) != _normalize_text(edc.get("seriousness")):
        differences.append("seriousness")
    # Preserve the canonical reconciled-field order.
    return tuple(field for field in RECONCILED_FIELDS if field in differences)


class ReconciliationService:
    """Authoritative service for PV one-way, read-only EDC reconciliation."""

    async def run(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        actor: ActorContext,
    ) -> ReconciliationRun:
        """Reconcile Safety_Cases against the read-only EDC projection for a study.

        Compares each captured PV adverse event against the approved, minimized,
        read-only EDC adverse-event projection for the study on the reconciled
        field set (subject reference, verbatim term, onset date, seriousness),
        records one :class:`ReconciliationRun` with the match and discrepancy
        counts, and writes one :class:`ReconciliationDiscrepancy` per differing
        record. When the required projection is unavailable or stale, no results
        are produced and a :class:`ServiceUnavailableError` is raised
        (Requirement 10.5). This method never writes EDC clinical or CTMS
        operational state (Requirement 10.6).
        """

        projection_repo = ProjectionRepository(session)
        projections = await projection_repo.current_projections_for_study(study_id)
        if not projections:
            # No current projection is available for the study; produce no
            # results and signal that the EDC projection is unavailable.
            raise ServiceUnavailableError(
                "The EDC adverse-event projection is unavailable or stale",
                {"reason": "EDC_PROJECTION_UNAVAILABLE", "study_id": str(study_id)},
            )

        edc_projection = [
            {
                "edc_reference": projection.source_record_id,
                "subject_reference": projection.subject_reference,
                "verbatim_term": projection.verbatim_term,
                "onset_date": projection.onset_date,
                "seriousness": projection.seriousness,
            }
            for projection in projections
            if projection.projection_status == ProjectionStatus.CURRENT.value
        ]

        safety_events = await self._collect_safety_events(session, study_id)

        differences = self.diff(safety_events, edc_projection)

        match_count = max(len(safety_events) - len(differences), 0)
        now = utc_now()

        reconciliation_repo = ReconciliationRepository(session)
        run = await reconciliation_repo.add_run(
            study_id=study_id,
            match_count=match_count,
            discrepancy_count=len(differences),
            run_at=now,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

        for difference in differences:
            case_id = _normalize_uuid(difference.get("case_id"))
            edc_reference = _normalize_uuid(difference.get("edc_reference"))
            differing_fields = list(difference.get("differing_fields", ()))
            discrepancy = await reconciliation_repo.add_discrepancy(
                run_id=run.id,
                case_id=case_id if case_id is not None else run.id,
                edc_reference=edc_reference,
                differing_fields=differing_fields,
                actor_id=actor.user_id,
                correlation_id=actor.correlation_id,
            )
            # One PV safety Audit_Event per created discrepancy (Requirement 10.7).
            await pv_atomicity_service.record_mutation(
                session,
                entity_type="reconciliation_discrepancy",
                entity_id=discrepancy.id,
                action="create",
                actor=actor,
                study_id=study_id,
                new_value=",".join(differing_fields),
                changed_fields=("differing_fields",),
            )

        # One PV safety Audit_Event recording the run and its counts.
        await pv_atomicity_service.record_mutation(
            session,
            entity_type="reconciliation_run",
            entity_id=run.id,
            action="run",
            actor=actor,
            study_id=study_id,
            changed_fields=("match_count", "discrepancy_count"),
        )
        return run

    async def resolve(
        self,
        session: AsyncSession,
        *,
        discrepancy_id: UUID,
        actor: ActorContext,
    ) -> ReconciliationDiscrepancy:
        """Mark a Reconciliation_Discrepancy resolved.

        Resolving a discrepancy changes only PV-owned reconciliation state and
        emits one PV safety Audit_Event (Requirement 10.7). It never writes EDC
        clinical or CTMS operational state (Requirement 10.6).
        """

        reconciliation_repo = ReconciliationRepository(session)
        discrepancy = await reconciliation_repo.get_discrepancy(discrepancy_id)
        if discrepancy is None:
            raise NotFoundError(
                "Reconciliation discrepancy not found",
                {"discrepancy_id": str(discrepancy_id)},
            )
        if discrepancy.status == DiscrepancyStatus.RESOLVED.value:
            raise ValidationError(
                "Reconciliation discrepancy is already resolved",
                {"discrepancy_id": str(discrepancy_id)},
            )

        prior_status = discrepancy.status
        discrepancy.status = DiscrepancyStatus.RESOLVED.value
        discrepancy.resolved_at = utc_now()
        discrepancy.resolved_by = actor.user_id
        discrepancy.updated_by = actor.user_id
        session.add(discrepancy)
        await session.flush()

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="reconciliation_discrepancy",
            entity_id=discrepancy.id,
            action="resolve",
            actor=actor,
            field_name="status",
            old_value=prior_status,
            new_value=discrepancy.status,
            changed_fields=("status",),
        )
        return discrepancy

    def diff(
        self,
        safety_events: list[Mapping[str, Any]],
        edc_projection: list[Mapping[str, Any]],
    ) -> list[Mapping[str, Any]]:
        """Return one discrepancy per differing record (pure function).

        A safety event and a projected EDC adverse event are the same underlying
        record when they share the subject reference and verbatim term. For each
        matched pair, the reconciled fields whose values differ are recorded. A
        safety event with no matching projected record, or a projected record
        with no matching safety event, is reported as a discrepancy on the fields
        that are present only on one side.

        The function is deterministic and performs no I/O so it can be exercised
        directly by property-based tests (Requirements 10.1, 10.2).
        """

        edc_by_key: dict[tuple[Any, Any], Mapping[str, Any]] = {}
        for record in edc_projection:
            edc_by_key.setdefault(_match_key(record), record)

        discrepancies: list[Mapping[str, Any]] = []
        matched_keys: set[tuple[Any, Any]] = set()

        for safety in safety_events:
            key = _match_key(safety)
            edc = edc_by_key.get(key)
            if edc is None:
                # No projected EDC record matches this safety event; every
                # reconciled field the safety event carries is a discrepancy.
                discrepancies.append(
                    ReconciliationDiff(
                        case_id=_normalize_uuid(safety.get("case_id")),
                        edc_reference=None,
                        differing_fields=_present_fields(safety),
                    ).as_mapping()
                )
                continue
            matched_keys.add(key)
            differing = _differing_fields(safety, edc)
            if differing:
                discrepancies.append(
                    ReconciliationDiff(
                        case_id=_normalize_uuid(safety.get("case_id")),
                        edc_reference=_normalize_uuid(edc.get("edc_reference")),
                        differing_fields=differing,
                    ).as_mapping()
                )

        # Projected EDC records with no matching safety event are also
        # discrepancies (a captured safety case is missing).
        for record in edc_projection:
            key = _match_key(record)
            if key in matched_keys:
                continue
            discrepancies.append(
                ReconciliationDiff(
                    case_id=None,
                    edc_reference=_normalize_uuid(record.get("edc_reference")),
                    differing_fields=_present_fields(record),
                ).as_mapping()
            )
        return discrepancies

    async def _collect_safety_events(
        self, session: AsyncSession, study_id: UUID
    ) -> list[Mapping[str, Any]]:
        """Build reconciled-field mappings for a study's captured adverse events.

        Each mapping carries the subject reference (from the Safety_Case),
        verbatim term and onset date (from the Adverse_Event_Record), and the
        latest seriousness determination (from the Seriousness_Assessment), plus
        the affected ``case_id`` and ``edc_reference``/``ae_id`` for identification.
        """

        reconciliation_repo = ReconciliationRepository(session)
        assessment_repo = AssessmentRepository(session)
        cases = await reconciliation_repo.cases_for_study(study_id)

        events: list[Mapping[str, Any]] = []
        for case in cases:
            adverse_events = await reconciliation_repo.adverse_events_for_case(case.id)
            for ae in adverse_events:
                seriousness_assessment = await assessment_repo.latest_seriousness(ae.id)
                seriousness = _seriousness_label(seriousness_assessment)
                events.append(
                    {
                        "case_id": case.id,
                        "ae_id": ae.id,
                        "subject_reference": case.subject_reference,
                        "verbatim_term": ae.verbatim_term,
                        "onset_date": ae.onset_date,
                        "seriousness": seriousness,
                    }
                )
        return events


def _present_fields(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the reconciled fields present (non-empty) on an unmatched record."""

    present: list[str] = []
    if _normalize_uuid(record.get("subject_reference")) is not None:
        present.append("subject_reference")
    if _normalize_text(record.get("verbatim_term")):
        present.append("verbatim_term")
    if _normalize_date(record.get("onset_date")) is not None:
        present.append("onset_date")
    if _normalize_text(record.get("seriousness")):
        present.append("seriousness")
    return tuple(field for field in RECONCILED_FIELDS if field in present)


def _seriousness_label(assessment: Any) -> str | None:
    """Render a seriousness determination as a stable reconciled value."""

    if assessment is None:
        return None
    return "serious" if getattr(assessment, "serious", False) else "not-serious"


reconciliation_service = ReconciliationService()

__all__ = [
    "ReconciliationDiff",
    "ReconciliationService",
    "reconciliation_service",
]
