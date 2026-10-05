"""Persistence for selecting in-scope Safety_Cases for a PV safety export.

The repository reads only PV-owned safety tables (``pv_safety_cases``,
``pv_adverse_event_records``, ``pv_seriousness_assessments``,
``pv_regulatory_reports``). It never queries an EDC clinical table or a CTMS
operational table, so a PV safety export can only ever contain PV-owned safety
content (Requirement 12.6). Soft-deleted rows are excluded.

The applied filters (study, site, subject reference, case status, seriousness,
report status, and an inclusive UTC date range) combine as an intersection: a
Safety_Case is selected only when it satisfies every provided filter
(Requirement 12.3). When no case qualifies the repository returns an empty list
(Requirement 12.2).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pv.assessment import SeriousnessAssessment
from app.models.pv.regulatory import RegulatoryReport
from app.models.pv.safety_case import AdverseEventRecord, SafetyCase


class PVExportRepository:
    """Query seam for the PV-owned rows produced by a safety export."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def select_cases(
        self,
        *,
        study_id: UUID,
        site_id: UUID | None = None,
        subject_reference: UUID | None = None,
        case_statuses: list[str] | None = None,
        seriousness: bool | None = None,
        report_statuses: list[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[SafetyCase]:
        """Return the in-scope Safety_Cases matching every provided filter.

        Every filter narrows the result as an intersection. The study filter is
        always applied from the export's study scope. Seriousness is resolved
        through the case's Adverse_Event_Records and their
        Seriousness_Assessments; report status is resolved through the case's
        Regulatory_Reports. The inclusive UTC date range is applied to the case
        creation timestamp.
        """

        statement = (
            select(SafetyCase)
            .where(SafetyCase.study_id == study_id)
            .where(SafetyCase.deleted_at.is_(None))
        )

        if site_id is not None:
            statement = statement.where(SafetyCase.site_id == site_id)
        if subject_reference is not None:
            statement = statement.where(SafetyCase.subject_reference == subject_reference)
        if case_statuses:
            statement = statement.where(SafetyCase.lifecycle_state.in_(case_statuses))
        if date_from is not None:
            statement = statement.where(SafetyCase.created_at >= date_from)
        if date_to is not None:
            statement = statement.where(SafetyCase.created_at <= date_to)

        if seriousness is not None:
            serious_case_ids = (
                select(AdverseEventRecord.case_id)
                .join(
                    SeriousnessAssessment,
                    SeriousnessAssessment.ae_id == AdverseEventRecord.id,
                )
                .where(AdverseEventRecord.deleted_at.is_(None))
                .where(SeriousnessAssessment.deleted_at.is_(None))
                .where(SeriousnessAssessment.serious.is_(seriousness))
            )
            statement = statement.where(SafetyCase.id.in_(serious_case_ids))

        if report_statuses:
            reported_case_ids = (
                select(RegulatoryReport.case_id)
                .where(RegulatoryReport.deleted_at.is_(None))
                .where(RegulatoryReport.status.in_(report_statuses))
            )
            statement = statement.where(SafetyCase.id.in_(reported_case_ids))

        statement = statement.order_by(SafetyCase.created_at, SafetyCase.id)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_adverse_events(self, case_id: UUID) -> list[AdverseEventRecord]:
        """Return the non-deleted Adverse_Event_Records for a case."""
        statement = (
            select(AdverseEventRecord)
            .where(AdverseEventRecord.case_id == case_id)
            .where(AdverseEventRecord.deleted_at.is_(None))
            .order_by(AdverseEventRecord.created_at, AdverseEventRecord.id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())


__all__ = ["PVExportRepository"]
