"""Persistence for PV Safety_Case intake and Adverse_Event_Record capture.

The repository owns SQLAlchemy access for the ``pv_safety_cases`` and
``pv_adverse_event_records`` tables. It only reads and stages ORM objects on the
caller-provided :class:`AsyncSession`; it never commits. The commit/rollback
boundary belongs to the request or worker unit of work so a Safety_Data change
and its PV safety Audit_Event commit or roll back together.

The repository stores only PV-owned safety fields plus read-only canonical
references (``study_id``, ``site_id``, ``subject_reference``). It never copies a
clinical payload and never creates, allocates, or mutates an EDC clinical
subject record.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pv.safety_case import (
    AdverseEventRecord,
    CaseVersion,
    CaseVersionStatus,
    SafetyCase,
)


class SafetyCaseRepository:
    """Repository seam for PV safety cases and adverse-event records."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def case_identifier_exists(self, case_identifier: str) -> bool:
        """Return whether a Safety_Case already uses ``case_identifier``.

        The safety case identifier is globally unique across the
        Unified_Clinical_Platform, so this check spans every study and site and
        does not exclude soft-deleted rows (a retained identifier is still in
        use).
        """

        statement = select(SafetyCase.id).where(
            SafetyCase.case_identifier == case_identifier
        )
        result = await self.session.execute(statement)
        return result.first() is not None

    async def get_case(
        self, case_id: UUID, *, include_deleted: bool = False
    ) -> SafetyCase | None:
        """Load a Safety_Case by id, excluding soft-deleted rows by default."""

        statement = select(SafetyCase).where(SafetyCase.id == case_id)
        if not include_deleted:
            statement = statement.where(SafetyCase.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def add_case(
        self,
        *,
        case_identifier: str,
        study_id: UUID,
        site_id: UUID,
        subject_reference: UUID,
        case_type: str,
        lifecycle_state: str,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> SafetyCase:
        """Stage exactly one Safety_Case row and flush to assign its id."""

        case = SafetyCase(
            case_identifier=case_identifier,
            study_id=study_id,
            site_id=site_id,
            subject_reference=subject_reference,
            case_type=case_type,
            lifecycle_state=lifecycle_state,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(case)
        await self.session.flush()
        return case

    async def list_adverse_events(
        self, case_id: UUID, *, include_deleted: bool = False
    ) -> list[AdverseEventRecord]:
        """Return the Adverse_Event_Records for a case ordered by creation.

        The query reads current rows directly rather than relying on a cached
        ORM relationship so a snapshot taken within the same transaction as a
        capture sees the just-added records.
        """

        statement = (
            select(AdverseEventRecord)
            .where(AdverseEventRecord.case_id == case_id)
            .order_by(AdverseEventRecord.created_at, AdverseEventRecord.id)
        )
        if not include_deleted:
            statement = statement.where(AdverseEventRecord.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def add_adverse_event(
        self,
        *,
        case: SafetyCase,
        verbatim_term: str,
        onset_date: Any,
        outcome: str,
        resolution_date: Any | None,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> AdverseEventRecord:
        """Stage one Adverse_Event_Record bound to ``case`` and flush."""

        record = AdverseEventRecord(
            case_id=case.id,
            verbatim_term=verbatim_term,
            onset_date=onset_date,
            outcome=outcome,
            resolution_date=resolution_date,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def update_lifecycle_state(
        self,
        *,
        case: SafetyCase,
        lifecycle_state: str,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> SafetyCase:
        """Persist a new lifecycle state on an existing Safety_Case."""

        case.lifecycle_state = lifecycle_state
        case.updated_by = actor_id
        if correlation_id is not None:
            case.correlation_id = correlation_id
        self.session.add(case)
        await self.session.flush()
        return case

    async def max_submitted_sequence_number(self, case_id: UUID) -> int | None:
        """Return the highest submitted Case_Version sequence number for a case.

        Submitted versions are never deleted or overwritten, so the maximum is
        computed across all submitted versions (including any soft-deleted rows,
        which do not exist for submitted versions) to guarantee monotonic
        follow-up sequencing (Requirements 4.3, 4.4, 4.8).
        """

        statement = select(func.max(CaseVersion.sequence_number)).where(
            CaseVersion.case_id == case_id,
            CaseVersion.status == CaseVersionStatus.SUBMITTED.value,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_version(
        self, version_id: UUID, *, include_deleted: bool = False
    ) -> CaseVersion | None:
        """Load a Case_Version by id, excluding soft-deleted rows by default."""

        statement = select(CaseVersion).where(CaseVersion.id == version_id)
        if not include_deleted:
            statement = statement.where(CaseVersion.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def add_submitted_version(
        self,
        *,
        case: SafetyCase,
        sequence_number: int,
        version_kind: str,
        captured_content: Mapping[str, Any],
        submitted_at: datetime,
        submitted_by: UUID | None,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> CaseVersion:
        """Stage one immutable Submitted Case_Version snapshot and flush.

        The ``captured_content`` snapshot is copied so later mutation of the
        source mapping cannot alter the retained version (Requirement 4.5).
        """

        version = CaseVersion(
            case_id=case.id,
            sequence_number=sequence_number,
            version_kind=version_kind,
            status=CaseVersionStatus.SUBMITTED.value,
            captured_content=dict(captured_content),
            submitted_at=submitted_at,
            submitted_by=submitted_by,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(version)
        await self.session.flush()
        return version

    @staticmethod
    def scalar_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
        """Return a shallow copy of a payload mapping (never ``None``)."""

        return dict(payload or {})


__all__ = ["SafetyCaseRepository"]
