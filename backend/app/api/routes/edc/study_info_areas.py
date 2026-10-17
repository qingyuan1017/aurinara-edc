"""Study_Info_Area sub-area routes (R8.5, R8.8-R8.13).

Operational EDC surface for the Study_Info_Area sub-areas without a dedicated
backing data model yet: Alerts, SDR, Lab, External Data Source, Adjudication,
SAEs, and the Conversion / Data Validation / System Integration / eDiary /
eCOA / Workflow / Site Payment / Translation / IRT Integration group.

Each sub-area is a distinct router so the aggregate includes it as its own
operational surface, mirroring how CTMS/PV scaffolded resource routers. Thin
handlers delegate to ``study_info_areas_service``; design-dependent reads
resolve through the ``DesignConsumptionService`` inside the service (R8.14).
All reads use the existing operational ``study.read`` permission code.

Satisfies Requirements:
  - 8.5: Alerts.
  - 8.8: SDR.
  - 8.9: Lab.
  - 8.10: External Data Source.
  - 8.11: Adjudication (where enabled).
  - 8.12: SAEs.
  - 8.13: Conversion, Data Validation, System Integration, eDiary, eCOA,
          Workflow, Site Payment, Translation, IRT Integration.
  - 8.14: Design-dependent config read through the Design_Consumption_Contract.
  - 21.1: All endpoints mounted under /api/v1.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.edc.study_info import SubAreaSurface
from app.services.edc.study_info_areas_service import study_info_areas_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]
_StudyRead = Annotated[User, Depends(require_permission("study.read"))]


# ---------------------------------------------------------------------------
# Alerts (R8.5)
# ---------------------------------------------------------------------------

alerts_router = APIRouter(prefix="/studies", tags=["alerts"])


@alerts_router.get("/{study_id}/alerts", response_model=SubAreaSurface)
async def get_alerts(
    study_id: UUID, session: DbSession, current_user: _StudyRead
) -> SubAreaSurface:
    """Alerts surface for a study (R8.5). Permission: study.read."""
    return await study_info_areas_service.alerts(session, study_id)


# ---------------------------------------------------------------------------
# SDR (R8.8)
# ---------------------------------------------------------------------------

sdr_router = APIRouter(prefix="/studies", tags=["sdr"])


@sdr_router.get("/{study_id}/sdr", response_model=SubAreaSurface)
async def get_sdr(study_id: UUID, session: DbSession, current_user: _StudyRead) -> SubAreaSurface:
    """SDR surface for a study (R8.8). Permission: study.read."""
    return await study_info_areas_service.sdr(session, study_id)


# ---------------------------------------------------------------------------
# Lab (R8.9)
# ---------------------------------------------------------------------------

lab_router = APIRouter(prefix="/studies", tags=["lab"])


@lab_router.get("/{study_id}/lab", response_model=SubAreaSurface)
async def get_lab(study_id: UUID, session: DbSession, current_user: _StudyRead) -> SubAreaSurface:
    """Lab surface for a study (R8.9). Permission: study.read."""
    return await study_info_areas_service.lab(session, study_id)


# ---------------------------------------------------------------------------
# External Data Source (R8.10)
# ---------------------------------------------------------------------------

external_data_source_router = APIRouter(prefix="/studies", tags=["external-data-source"])


@external_data_source_router.get("/{study_id}/external-data-source", response_model=SubAreaSurface)
async def get_external_data_source(
    study_id: UUID, session: DbSession, current_user: _StudyRead
) -> SubAreaSurface:
    """External Data Source surface for a study (R8.10). Permission: study.read."""
    return await study_info_areas_service.external_data_source(session, study_id)


# ---------------------------------------------------------------------------
# Adjudication (R8.11, where enabled)
# ---------------------------------------------------------------------------

adjudication_router = APIRouter(prefix="/studies", tags=["adjudication"])


@adjudication_router.get("/{study_id}/adjudication", response_model=SubAreaSurface)
async def get_adjudication(
    study_id: UUID, session: DbSession, current_user: _StudyRead
) -> SubAreaSurface:
    """Adjudication surface for a study (R8.11, where enabled). study.read."""
    return await study_info_areas_service.adjudication(session, study_id)


# ---------------------------------------------------------------------------
# SAEs (R8.12)
# ---------------------------------------------------------------------------

saes_router = APIRouter(prefix="/studies", tags=["saes"])


@saes_router.get("/{study_id}/saes", response_model=SubAreaSurface)
async def get_saes(study_id: UUID, session: DbSession, current_user: _StudyRead) -> SubAreaSurface:
    """SAEs surface for a study (R8.12). Permission: study.read."""
    return await study_info_areas_service.saes(session, study_id)


# ---------------------------------------------------------------------------
# Integration group (R8.13)
# ---------------------------------------------------------------------------

integrations_router = APIRouter(prefix="/studies", tags=["integrations"])


@integrations_router.get("/{study_id}/integrations", response_model=SubAreaSurface)
async def get_integrations(
    study_id: UUID, session: DbSession, current_user: _StudyRead
) -> SubAreaSurface:
    """Conversion/Data Validation/System Integration/eDiary/eCOA/Workflow/Site
    Payment/Translation/IRT Integration surface for a study (R8.13)."""
    return await study_info_areas_service.integrations(session, study_id)


__all__ = [
    "adjudication_router",
    "alerts_router",
    "external_data_source_router",
    "integrations_router",
    "lab_router",
    "saes_router",
    "sdr_router",
]
