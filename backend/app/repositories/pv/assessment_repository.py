"""Persistence for PV safety assessments.

The repository owns SQLAlchemy access for the PV assessment tables
(``pv_seriousness_assessments``, ``pv_causality_assessments``,
``pv_expectedness_assessments``, ``pv_severity_grades``). It only reads and
stages ORM objects on the caller-provided :class:`AsyncSession`; it never
commits. The commit/rollback boundary belongs to the request or worker unit of
work so an assessment change and its PV safety Audit_Event commit or roll back
together.

Assessments are PV-owned Safety_Data referencing a PV ``Adverse_Event_Record``.
The repository never copies a clinical payload and never mutates an EDC clinical
record.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pv.assessment import (
    CausalityAssessment,
    ExpectednessAssessment,
    SeriousnessAssessment,
    SeverityGrade,
)
from app.models.pv.safety_case import AdverseEventRecord, SafetyCase


class AssessmentRepository:
    """Repository seam for PV safety assessments."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_adverse_event(
        self, ae_id: UUID, *, include_deleted: bool = False
    ) -> AdverseEventRecord | None:
        """Load an Adverse_Event_Record by id, excluding soft-deleted rows."""

        statement = select(AdverseEventRecord).where(AdverseEventRecord.id == ae_id)
        if not include_deleted:
            statement = statement.where(AdverseEventRecord.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_case(
        self, case_id: UUID, *, include_deleted: bool = False
    ) -> SafetyCase | None:
        """Load the parent Safety_Case for an adverse event."""

        statement = select(SafetyCase).where(SafetyCase.id == case_id)
        if not include_deleted:
            statement = statement.where(SafetyCase.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Latest-assessment reads (for prior-value auditing)
    # ------------------------------------------------------------------

    async def latest_seriousness(self, ae_id: UUID) -> SeriousnessAssessment | None:
        return await self._latest(SeriousnessAssessment, ae_id)

    async def latest_causality(self, ae_id: UUID) -> CausalityAssessment | None:
        return await self._latest(CausalityAssessment, ae_id)

    async def latest_expectedness(self, ae_id: UUID) -> ExpectednessAssessment | None:
        return await self._latest(ExpectednessAssessment, ae_id)

    async def latest_severity(self, ae_id: UUID) -> SeverityGrade | None:
        return await self._latest(SeverityGrade, ae_id)

    async def _latest(self, model: type, ae_id: UUID):
        statement = (
            select(model)
            .where(model.ae_id == ae_id, model.deleted_at.is_(None))
            .order_by(model.created_at.desc(), model.id.desc())
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Staging writes
    # ------------------------------------------------------------------

    async def add_seriousness(
        self,
        *,
        ae_id: UUID,
        serious: bool,
        criteria: list[str],
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> SeriousnessAssessment:
        assessment = SeriousnessAssessment(
            ae_id=ae_id,
            serious=serious,
            criteria=criteria,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(assessment)
        await self.session.flush()
        return assessment

    async def add_causality(
        self,
        *,
        ae_id: UUID,
        suspect_product: str,
        causality_category: str,
        assessed_at: datetime,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> CausalityAssessment:
        assessment = CausalityAssessment(
            ae_id=ae_id,
            suspect_product=suspect_product,
            causality_category=causality_category,
            assessed_at=assessed_at,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(assessment)
        await self.session.flush()
        return assessment

    async def add_expectedness(
        self,
        *,
        ae_id: UUID,
        expected: bool,
        reference_safety_information: str | None,
        assessed_at: datetime,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> ExpectednessAssessment:
        assessment = ExpectednessAssessment(
            ae_id=ae_id,
            expected=expected,
            reference_safety_information=reference_safety_information,
            assessed_at=assessed_at,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(assessment)
        await self.session.flush()
        return assessment

    async def add_severity(
        self,
        *,
        ae_id: UUID,
        grade: str,
        assessed_at: datetime,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> SeverityGrade:
        assessment = SeverityGrade(
            ae_id=ae_id,
            grade=grade,
            assessed_at=assessed_at,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(assessment)
        await self.session.flush()
        return assessment


__all__ = ["AssessmentRepository"]
