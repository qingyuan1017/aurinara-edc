"""Persistence for PV regulatory reporting.

The repository owns SQLAlchemy access for ``pv_reportability_rules``,
``pv_regulatory_reports``, and ``pv_regulatory_clocks``. It only reads and
stages ORM objects on the caller-provided :class:`AsyncSession`; it never
commits. The commit/rollback boundary belongs to the request or worker unit of
work so a report change and its PV safety Audit_Event commit or roll back
together.

Regulatory reports and clocks are PV-owned Safety_Data referencing the PV-owned
``pv_safety_cases`` root. The repository never copies a clinical payload and
never mutates an EDC clinical or CTMS operational record.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pv.regulatory import (
    RegulatoryClock,
    RegulatoryReport,
    ReportabilityRule,
)
from app.models.pv.safety_case import SafetyCase


class RegulatoryReportingRepository:
    """Repository seam for PV regulatory reports, clocks, and rules."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_case(
        self, case_id: UUID, *, include_deleted: bool = False
    ) -> SafetyCase | None:
        """Load a Safety_Case by id, excluding soft-deleted rows by default."""

        statement = select(SafetyCase).where(SafetyCase.id == case_id)
        if not include_deleted:
            statement = statement.where(SafetyCase.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_report(
        self, report_id: UUID, *, include_deleted: bool = False
    ) -> RegulatoryReport | None:
        """Load a Regulatory_Report by id, excluding soft-deleted rows."""

        statement = select(RegulatoryReport).where(RegulatoryReport.id == report_id)
        if not include_deleted:
            statement = statement.where(RegulatoryReport.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def active_rules_for_study(self, study_id: UUID) -> list[ReportabilityRule]:
        """Return the live, active reportability rules for a study.

        Rules are returned in a deterministic order (creation time then id) so
        reportability evaluation creates reports predictably.
        """

        statement = (
            select(ReportabilityRule)
            .where(
                ReportabilityRule.study_id == study_id,
                ReportabilityRule.active.is_(True),
                ReportabilityRule.deleted_at.is_(None),
            )
            .order_by(ReportabilityRule.created_at, ReportabilityRule.id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def reports_for_case(self, case_id: UUID) -> list[RegulatoryReport]:
        """Return the live Regulatory_Reports for a case."""

        statement = (
            select(RegulatoryReport)
            .where(
                RegulatoryReport.case_id == case_id,
                RegulatoryReport.deleted_at.is_(None),
            )
            .order_by(RegulatoryReport.created_at, RegulatoryReport.id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def add_report_with_clock(
        self,
        *,
        case_id: UUID,
        rule_id: UUID | None,
        report_type: str,
        destination: str,
        awareness_date: date,
        timeline_days: int,
        due_date: date,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> RegulatoryReport:
        """Stage one Pending Regulatory_Report plus its Regulatory_Clock and flush."""

        report = RegulatoryReport(
            case_id=case_id,
            rule_id=rule_id,
            report_type=report_type,
            destination=destination,
            awareness_date=awareness_date,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(report)
        await self.session.flush()

        clock = RegulatoryClock(
            report_id=report.id,
            awareness_date=awareness_date,
            timeline_days=timeline_days,
            due_date=due_date,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(clock)
        await self.session.flush()
        return report

    async def update_report(
        self,
        report: RegulatoryReport,
        *,
        status: str,
        actor_id: UUID | None,
        correlation_id: str | None,
        submitted_at: datetime | None = None,
        submitted_by: UUID | None = None,
        e2b_message_ref: str | None = None,
    ) -> RegulatoryReport:
        """Advance a report's status and, on submission, its submission metadata."""

        report.status = status
        report.updated_by = actor_id
        if correlation_id is not None:
            report.correlation_id = correlation_id
        if submitted_at is not None:
            report.submitted_at = submitted_at
        if submitted_by is not None:
            report.submitted_by = submitted_by
        if e2b_message_ref is not None:
            report.e2b_message_ref = e2b_message_ref
        self.session.add(report)
        await self.session.flush()
        return report


__all__ = ["RegulatoryReportingRepository"]
