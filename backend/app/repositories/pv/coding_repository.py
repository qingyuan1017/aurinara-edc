"""Persistence for PV MedDRA/WHODrug coding and the dictionary-version registry.

The repository owns SQLAlchemy access for ``pv_coding_dictionary_versions``,
``pv_meddra_codings``, and ``pv_whodrug_codings``. It only reads and stages ORM
objects on the caller-provided :class:`AsyncSession`; it never commits. The
commit/rollback boundary belongs to the request or worker unit of work so a
coding change and its PV safety Audit_Event commit or roll back together.

Coding rows are PV-owned Safety_Data. Recoding never mutates a prior row: a new
row is staged with ``prior_coding_id`` pointing at the prior assignment, which
remains immutable. The repository never copies or mutates an EDC clinical
payload.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pv.coding import (
    CodingDictionaryVersion,
    CodingSystem,
    MedDraCoding,
    WhoDrugCoding,
)
from app.models.pv.safety_case import AdverseEventRecord, SafetyCase


class CodingRepository:
    """Repository seam for PV coding assignments and dictionary versions."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Parent / reference reads
    # ------------------------------------------------------------------

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
        """Load a Safety_Case by id, excluding soft-deleted rows."""

        statement = select(SafetyCase).where(SafetyCase.id == case_id)
        if not include_deleted:
            statement = statement.where(SafetyCase.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_dictionary_version(
        self, *, coding_system: CodingSystem, version: str
    ) -> CodingDictionaryVersion | None:
        """Load a live dictionary version for a coding system by version string."""

        statement = select(CodingDictionaryVersion).where(
            CodingDictionaryVersion.coding_system == coding_system.value,
            CodingDictionaryVersion.version == version,
            CodingDictionaryVersion.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def add_dictionary_version(
        self,
        *,
        coding_system: CodingSystem,
        version: str,
        available: bool = True,
        actor_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CodingDictionaryVersion:
        """Stage one dictionary-version registry row and flush."""

        record = CodingDictionaryVersion(
            coding_system=coding_system.value,
            version=version,
            available=available,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    # ------------------------------------------------------------------
    # MedDRA coding
    # ------------------------------------------------------------------

    async def get_meddra_coding(
        self, coding_id: UUID, *, include_deleted: bool = False
    ) -> MedDraCoding | None:
        statement = select(MedDraCoding).where(MedDraCoding.id == coding_id)
        if not include_deleted:
            statement = statement.where(MedDraCoding.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def add_meddra_coding(
        self,
        *,
        ae_id: UUID,
        term_id: str,
        term_label: str | None,
        dictionary_version: str,
        assigned_at: datetime,
        assigned_by: UUID | None,
        prior_coding_id: UUID | None,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> MedDraCoding:
        coding = MedDraCoding(
            ae_id=ae_id,
            term_id=term_id,
            term_label=term_label,
            dictionary_version=dictionary_version,
            assigned_at=assigned_at,
            assigned_by=assigned_by,
            prior_coding_id=prior_coding_id,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(coding)
        await self.session.flush()
        return coding

    # ------------------------------------------------------------------
    # WHODrug coding
    # ------------------------------------------------------------------

    async def get_whodrug_coding(
        self, coding_id: UUID, *, include_deleted: bool = False
    ) -> WhoDrugCoding | None:
        statement = select(WhoDrugCoding).where(WhoDrugCoding.id == coding_id)
        if not include_deleted:
            statement = statement.where(WhoDrugCoding.deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def add_whodrug_coding(
        self,
        *,
        product_id: UUID,
        term_id: str,
        term_label: str | None,
        dictionary_version: str,
        assigned_at: datetime,
        assigned_by: UUID | None,
        prior_coding_id: UUID | None,
        actor_id: UUID | None,
        correlation_id: str | None,
    ) -> WhoDrugCoding:
        coding = WhoDrugCoding(
            product_id=product_id,
            term_id=term_id,
            term_label=term_label,
            dictionary_version=dictionary_version,
            assigned_at=assigned_at,
            assigned_by=assigned_by,
            prior_coding_id=prior_coding_id,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id,
        )
        self.session.add(coding)
        await self.session.flush()
        return coding


__all__ = ["CodingRepository"]
