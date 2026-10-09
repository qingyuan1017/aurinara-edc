"""Study Information + CRF Version management routes (R8.1, R8.2).

Operational EDC surface for the design-dependent parts of the Study_Info_Area.
Thin handlers delegate to ``study_info_service``; design-dependent reads resolve
through the ``DesignConsumptionService`` inside the service (R8.14), never
touching a Designer write path. All reads use the existing operational
``study.read`` permission code.

Satisfies Requirements:
  - 8.1: Study Information, Status Configuration, ID Configuration.
  - 8.2: CRF Version management — Version History, Edit Check Testing Case,
         Access Control, and Version Upgrade (R8.3/R8.15, task 15.2).
  - 8.3: Version Upgrade rebinds affected Operational_Records to a newer
         Published_Design and audits the upgrade (served via subject.update).
  - 8.15: A failed Version Upgrade leaves records on the prior design version,
         audits the failed attempt, and returns an error.
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
from app.schemas.edc.study_info import (
    AccessControl,
    CrfVersionHistory,
    EditCheckTestingCases,
    IdConfiguration,
    StatusConfiguration,
    StudyInformation,
    VersionUpgradeRequest,
    VersionUpgradeResult,
)
from app.services.edc.study_info_service import study_info_service
from app.services.edc.version_upgrade_service import version_upgrade_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

# ---------------------------------------------------------------------------
# Study Information (R8.1) — mounted under /studies
# ---------------------------------------------------------------------------

study_information_router = APIRouter(prefix="/studies", tags=["study-info"])


@study_information_router.get(
    "/{study_id}/study-information",
    response_model=StudyInformation,
)
async def get_study_information(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
) -> StudyInformation:
    """Operational Study Information summary (R8.1). Permission: study.read."""
    return await study_info_service.get_study_information(session, study_id)


@study_information_router.get(
    "/{study_id}/status-configuration",
    response_model=StatusConfiguration,
)
async def get_status_configuration(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
) -> StatusConfiguration:
    """Status Configuration — current status + reachable statuses (R8.1)."""
    return await study_info_service.get_status_configuration(session, study_id)


@study_information_router.get(
    "/{study_id}/id-configuration",
    response_model=IdConfiguration,
)
async def get_id_configuration(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
) -> IdConfiguration:
    """ID Configuration — design-dependent id formats (R8.1, R8.14)."""
    return await study_info_service.get_id_configuration(session, study_id)


# ---------------------------------------------------------------------------
# CRF Version management (R8.2) — mounted under /studies and /design-versions
# ---------------------------------------------------------------------------

crf_version_router = APIRouter(prefix="/studies", tags=["crf-version"])


@crf_version_router.get(
    "/{study_id}/crf-version-history",
    response_model=CrfVersionHistory,
)
async def get_version_history(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
) -> CrfVersionHistory:
    """CRF Version History for a study (R8.2). Permission: study.read."""
    return await study_info_service.get_version_history(session, study_id)


design_version_router = APIRouter(prefix="/design-versions", tags=["crf-version"])


@design_version_router.get(
    "/{design_version_id}/edit-check-testing-cases",
    response_model=EditCheckTestingCases,
)
async def get_edit_check_testing_cases(
    design_version_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
) -> EditCheckTestingCases:
    """Edit Check Testing Case list for a design version (R8.2, R8.14)."""
    return await study_info_service.get_edit_check_testing_cases(
        session, design_version_id
    )


@design_version_router.get(
    "/{design_version_id}/access-control",
    response_model=AccessControl,
)
async def get_access_control(
    design_version_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
) -> AccessControl:
    """Access Control matrix for a design version (R8.2, R8.14)."""
    return await study_info_service.get_access_control(session, design_version_id)


# ---------------------------------------------------------------------------
# Version Upgrade (R8.3, R8.15) — transactional rebind to a newer design
# ---------------------------------------------------------------------------


@crf_version_router.post(
    "/{study_id}/subjects/{subject_id}/version-upgrade",
    response_model=VersionUpgradeResult,
)
async def upgrade_subject_version(
    study_id: UUID,
    subject_id: UUID,
    body: VersionUpgradeRequest,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.update"))],
) -> VersionUpgradeResult:
    """Rebind a Subject's Operational_Records to a newer Published_Design.

    Transactional (R8.3, R8.15): on success all affected records are rebound and
    the upgrade is audited; on failure the records stay on their prior design
    version, the failed attempt is audited, and an error is returned.

    Permission: subject.update
    """
    result = await version_upgrade_service.upgrade_subject(
        session,
        subject_id=subject_id,
        target_design_version_id=body.target_design_version_id,
        actor_id=current_user.id,
    )
    return VersionUpgradeResult.model_validate(result)


@crf_version_router.post(
    "/{study_id}/sites/{site_id}/version-upgrade",
    response_model=VersionUpgradeResult,
)
async def upgrade_site_version(
    study_id: UUID,
    site_id: UUID,
    body: VersionUpgradeRequest,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.update"))],
) -> VersionUpgradeResult:
    """Rebind every Subject of a Site to a newer Published_Design.

    Transactional (R8.3, R8.15): on success all affected records of the site's
    subjects are rebound and the upgrade is audited; on failure no subject of
    the site is rebound, the failed attempt is audited, and an error is returned.

    Permission: subject.update
    """
    result = await version_upgrade_service.upgrade_site(
        session,
        site_id=site_id,
        study_id=study_id,
        target_design_version_id=body.target_design_version_id,
        actor_id=current_user.id,
    )
    return VersionUpgradeResult.model_validate(result)


__all__ = [
    "crf_version_router",
    "design_version_router",
    "study_information_router",
]
