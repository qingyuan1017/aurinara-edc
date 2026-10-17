"""Study_Info_Area sub-area surface service (R8.5, R8.8-R8.13).

Operational surface for the Study_Info_Area sub-areas that do not yet have a
dedicated backing data model: Alerts, SDR, Lab, External Data Source,
Adjudication, SAEs, and the Conversion / Data Validation / System Integration /
eDiary / eCOA / Workflow / Site Payment / Translation / IRT Integration group.

Each method returns a stable, structured ``SubAreaSurface`` describing the
sub-area's defined operational capabilities (its known sub-sections) so the
surface is mountable and smoke-testable as the operational boundary (task
20.3), mirroring how CTMS/PV scaffolded resource routers. When a capability is
design-dependent, the service resolves the study's bound ``Published_Design``
**only** through the ``DesignConsumptionService`` (R8.14) and never touches a
Designer write path.

This service owns no Operational_Record mutation path and no Designer write
path; it is a read surface over operational configuration boundaries.

Satisfies Requirements:
  - 8.5: Alerts (AE, eDiary, CRF, Subject Phase, Query, Visit Window, Edit
         Check, Non-Compliance, Payment).
  - 8.8: SDR (SDR Setting, SDR Workload, SDR Result).
  - 8.9: Lab (Lab Define, Site Normal Range, External Lab Data, Summary of Lab,
         Conversion Factor and Range Report, Operational History).
  - 8.10: External Data Source (Data Import, Data Sync).
  - 8.11: Adjudication (where enabled).
  - 8.12: SAEs (SAE Form Define, Related Form, SAE Report Setting, SAE Alert,
          SAE Report, SAE Audit).
  - 8.13: Conversion, Data Validation, System Integration, eDiary, eCOA,
          Workflow, Site Payment, Translation, IRT Integration.
  - 8.14: Design-dependent config read through the Design_Consumption_Contract.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.edc.study_info import SubAreaItem, SubAreaSurface
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)
from app.services.edc.study_service import StudyService, study_service

logger = logging.getLogger(__name__)


# Known sub-sections per sub-area, keyed to the acceptance criteria. These
# describe the operational capability surface of each sub-area; the detail
# payload stays empty until a backing model is introduced.
_ALERT_SECTIONS = (
    ("ae", "AE Alert"),
    ("ediary", "eDiary Alert"),
    ("crf", "CRF Alert"),
    ("subject_phase", "Subject Phase Alert"),
    ("query", "Query Alert"),
    ("visit_window", "Visit Window Alert"),
    ("edit_check", "Edit Check Alert"),
    ("non_compliance", "Non-Compliance Alert"),
    ("payment", "Payment Alert"),
)

_SDR_SECTIONS = (
    ("sdr_setting", "SDR Setting"),
    ("sdr_workload", "SDR Workload"),
    ("sdr_result", "SDR Result"),
)

_LAB_SECTIONS = (
    ("lab_define", "Lab Define"),
    ("site_normal_range", "Site Normal Range"),
    ("external_lab_data", "External Lab Data"),
    ("summary_of_lab", "Summary of Lab"),
    ("conversion_factor_range_report", "Conversion Factor and Range Report"),
    ("operational_history", "Operational History"),
)

_EXTERNAL_DATA_SOURCE_SECTIONS = (
    ("data_import", "Data Import"),
    ("data_sync", "Data Sync"),
)

_ADJUDICATION_SECTIONS = (("adjudication", "Adjudication"),)

_SAE_SECTIONS = (
    ("sae_form_define", "SAE Form Define"),
    ("related_form", "Related Form"),
    ("sae_report_setting", "SAE Report Setting"),
    ("sae_alert", "SAE Alert"),
    ("sae_report", "SAE Report"),
    ("sae_audit", "SAE Audit"),
)

_INTEGRATION_SECTIONS = (
    ("conversion", "Conversion"),
    ("data_validation", "Data Validation"),
    ("system_integration", "System Integration"),
    ("ediary", "eDiary"),
    ("ecoa", "eCOA"),
    ("workflow", "Workflow"),
    ("site_payment", "Site Payment"),
    ("translation", "Translation"),
    ("irt_integration", "IRT Integration"),
)


class StudyInfoAreasService:
    """Read-only surface for backing-model-free Study_Info_Area sub-areas.

    Design-dependent reads resolve the bound ``Published_Design`` through the
    injected ``DesignConsumptionService`` (R8.14); no Designer write path is
    ever used.
    """

    def __init__(
        self,
        *,
        design_service: DesignConsumptionService | None = None,
        studies: StudyService | None = None,
    ) -> None:
        self._design = design_service or design_consumption_service
        self._studies = studies or study_service

    async def _surface(
        self,
        session: AsyncSession,
        study_id: UUID,
        sections: tuple[tuple[str, str], ...],
    ) -> SubAreaSurface:
        """Build a structured sub-area surface for a study.

        Validates the study exists (operational ownership) and resolves the
        study's bound Published_Design through the consumption contract so the
        surface reports the design version its config is read against (R8.14).
        """
        study = await self._studies.get_study(session, study_id)
        design = await self._design.get_latest_published_design(session, study.id)
        return SubAreaSurface(
            study_id=study.id,
            design_version_id=design.design_version_id if design else None,
            available=True,
            items=[SubAreaItem(key=key, label=label, detail={}) for key, label in sections],
        )

    async def alerts(self, session: AsyncSession, study_id: UUID) -> SubAreaSurface:
        """Return the Alerts surface for a study (R8.5)."""
        return await self._surface(session, study_id, _ALERT_SECTIONS)

    async def sdr(self, session: AsyncSession, study_id: UUID) -> SubAreaSurface:
        """Return the SDR surface for a study (R8.8)."""
        return await self._surface(session, study_id, _SDR_SECTIONS)

    async def lab(self, session: AsyncSession, study_id: UUID) -> SubAreaSurface:
        """Return the Lab surface for a study (R8.9)."""
        return await self._surface(session, study_id, _LAB_SECTIONS)

    async def external_data_source(self, session: AsyncSession, study_id: UUID) -> SubAreaSurface:
        """Return the External Data Source surface for a study (R8.10)."""
        return await self._surface(session, study_id, _EXTERNAL_DATA_SOURCE_SECTIONS)

    async def adjudication(self, session: AsyncSession, study_id: UUID) -> SubAreaSurface:
        """Return the Adjudication surface for a study (R8.11, where enabled)."""
        return await self._surface(session, study_id, _ADJUDICATION_SECTIONS)

    async def saes(self, session: AsyncSession, study_id: UUID) -> SubAreaSurface:
        """Return the SAEs surface for a study (R8.12)."""
        return await self._surface(session, study_id, _SAE_SECTIONS)

    async def integrations(self, session: AsyncSession, study_id: UUID) -> SubAreaSurface:
        """Return the integration group surface for a study (R8.13).

        Covers Conversion, Data Validation, System Integration, eDiary, eCOA,
        Workflow, Site Payment, Translation, and IRT Integration.
        """
        return await self._surface(session, study_id, _INTEGRATION_SECTIONS)


# Module-level singleton for convenience (mirrors other EDC services).
study_info_areas_service = StudyInfoAreasService()
