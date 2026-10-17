"""Study_Info_Service — operational Study Information and CRF Version reads (R8.1, R8.2).

Thin operational service backing the design-dependent parts of the
Study_Info_Area. All design-dependent configuration is read **only** through
the ``DesignConsumptionService`` (R8.14); this service never imports or calls a
Designer write service and never mutates a Designer_Definition. It owns no
Operational_Record mutation path either — it is a read surface over operational
study metadata plus the bound ``Published_Design``.

Satisfies Requirements:
  - 8.1: Study Information (Study Information, Status Configuration, ID Configuration).
  - 8.2: CRF Version management (Version History, Edit Check Testing Case, Access Control).
  - 8.14: Design-dependent config read through the Design_Consumption_Contract.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.edc.study import StudyStatus, StudyVersion
from app.schemas.edc.study_info import (
    AccessControl,
    AccessControlEntry,
    CrfVersionHistory,
    CrfVersionHistoryEntry,
    EditCheckTestingCase,
    EditCheckTestingCases,
    IdConfiguration,
    StatusConfiguration,
    StudyInformation,
)
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)
from app.services.edc.study_service import _LEGAL_TRANSITIONS, StudyService, study_service

logger = logging.getLogger(__name__)


class StudyInfoService:
    """Read-only operational Study Information + CRF Version management.

    Design-dependent reads are delegated to the injected
    ``DesignConsumptionService`` so the Study_Info_Area never reaches a Designer
    write path (R8.14).
    """

    def __init__(
        self,
        *,
        design_service: DesignConsumptionService | None = None,
        studies: StudyService | None = None,
    ) -> None:
        self._design = design_service or design_consumption_service
        self._studies = studies or study_service

    # ------------------------------------------------------------------
    # R8.1 — Study Information
    # ------------------------------------------------------------------

    async def get_study_information(
        self, session: AsyncSession, study_id: UUID
    ) -> StudyInformation:
        """Return the operational Study Information summary (R8.1)."""
        study = await self._studies.get_study(session, study_id)
        return StudyInformation(
            study_id=study.id,
            study_code=study.study_code,
            title=study.title,
            sponsor=study.sponsor,
            phase=study.phase,
            status=str(study.status),
            therapeutic_area=study.therapeutic_area,
            indication=study.indication,
        )

    async def get_status_configuration(
        self, session: AsyncSession, study_id: UUID
    ) -> StatusConfiguration:
        """Return Status Configuration: current status + reachable statuses (R8.1)."""
        study = await self._studies.get_study(session, study_id)
        current = StudyStatus(study.status)
        allowed = _LEGAL_TRANSITIONS.get(current, set())
        return StatusConfiguration(
            study_id=study.id,
            current_status=current.value,
            allowed_transitions=sorted(s.value for s in allowed),
        )

    async def get_id_configuration(self, session: AsyncSession, study_id: UUID) -> IdConfiguration:
        """Return ID Configuration, resolving design-dependent format (R8.1, R8.14).

        The design version is resolved from the study's latest Published_Design
        through the consumption contract; id formats default to ``None`` until a
        design-level format is configured, keeping the surface stable.
        """
        study = await self._studies.get_study(session, study_id)
        design = await self._design.get_latest_published_design(session, study.id)
        return IdConfiguration(
            study_id=study.id,
            design_version_id=design.design_version_id if design else None,
            subject_id_format=None,
            screening_id_format=None,
        )

    # ------------------------------------------------------------------
    # R8.2 — CRF Version management
    # ------------------------------------------------------------------

    async def get_version_history(self, session: AsyncSession, study_id: UUID) -> CrfVersionHistory:
        """Return the study's CRF Version History (R8.2).

        Lists every ``StudyVersion`` for the study (draft and published) ordered
        by creation so the operational surface can present full history. Only
        the design *content* of a published version is readable through the
        consumption contract; this list is version metadata the EDC owns a read
        over for operational version management.
        """
        # Ensure the study exists (operational ownership check).
        await self._studies.get_study(session, study_id)
        result = await session.execute(
            select(StudyVersion)
            .where(StudyVersion.study_id == study_id)
            .order_by(StudyVersion.created_at, StudyVersion.id)
        )
        entries = [
            CrfVersionHistoryEntry(
                design_version_id=v.id,
                version_number=v.version_number,
                status=str(v.status),
                published_at=v.published_at.isoformat() if v.published_at else None,
            )
            for v in result.scalars().all()
        ]
        return CrfVersionHistory(study_id=study_id, entries=entries)

    async def get_edit_check_testing_cases(
        self, session: AsyncSession, design_version_id: UUID
    ) -> EditCheckTestingCases:
        """Return the published edit-check rules for operational test review (R8.2).

        Reads the bound design's edit-check rules **only** through the
        consumption contract (R8.14). A draft or missing version is rejected by
        the contract's published-only guard.
        """
        rules = await self._design.list_edit_check_rules(session, design_version_id)
        cases = [
            EditCheckTestingCase(
                edit_check_id=rule.id,
                name=rule.name,
                severity=rule.severity,
                is_active=rule.is_active,
            )
            for rule in rules
        ]
        return EditCheckTestingCases(design_version_id=design_version_id, cases=cases)

    async def get_access_control(
        self, session: AsyncSession, design_version_id: UUID
    ) -> AccessControl:
        """Return the design-time CRF access matrix for operational review (R8.2).

        Reads CRF access definitions **only** through the consumption contract
        (R8.14); these are design-time read/write grants projected read-only for
        the operational Access Control surface.
        """
        definitions = await self._design.list_crf_access_definitions(session, design_version_id)
        entries = [
            AccessControlEntry(
                role=d.role,
                form_definition_id=d.form_definition_id,
                field_definition_id=d.field_definition_id,
                can_read=d.can_read,
                can_write=d.can_write,
            )
            for d in definitions
        ]
        return AccessControl(design_version_id=design_version_id, entries=entries)


# Module-level singleton for convenience (mirrors other EDC services).
study_info_service = StudyInfoService()
