"""PV safety assessment routes (seriousness, causality, expectedness, severity).

Thin, authenticated handlers under ``/api/v1/pv`` that delegate to the
``Assessment_Service``. The service owns validation (a serious determination
requires a criterion), the Closed-case guard, and the atomic Safety_Data + PV
safety Audit_Event transaction boundary. No route mutates an EDC clinical or
CTMS operational record.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_pv_permission
from app.api.routes.pv._common import build_actor
from app.models.identity import User
from app.schemas.pv.resources import (
    AssessmentResponse,
    CausalityRequest,
    ExpectednessRequest,
    SeriousnessRequest,
    SeverityRequest,
)
from app.services.assessment_service import assessment_service

router = APIRouter(tags=["pv-assessments"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
RecordGuard = Annotated[User, Depends(require_pv_permission("safety_assessment.record"))]


@router.post(
    "/adverse-events/{ae_id}/seriousness",
    response_model=AssessmentResponse,
    status_code=201,
)
async def record_seriousness(
    ae_id: UUID,
    body: SeriousnessRequest,
    session: DbSession,
    current_user: RecordGuard,
) -> AssessmentResponse:
    """Record a Seriousness_Assessment for an Adverse_Event_Record."""

    assessment = await assessment_service.record_seriousness(
        session,
        ae_id=ae_id,
        serious=body.serious,
        criteria=frozenset(criterion.value for criterion in body.criteria),
        actor=build_actor(current_user),
    )
    return AssessmentResponse.model_validate(assessment)


@router.post(
    "/adverse-events/{ae_id}/causality",
    response_model=AssessmentResponse,
    status_code=201,
)
async def record_causality(
    ae_id: UUID,
    body: CausalityRequest,
    session: DbSession,
    current_user: RecordGuard,
) -> AssessmentResponse:
    """Record a Causality_Assessment for an Adverse_Event_Record."""

    assessment = await assessment_service.record_causality(
        session,
        ae_id=ae_id,
        suspect_product=body.suspect_product,
        category=body.category,
        actor=build_actor(current_user),
    )
    return AssessmentResponse.model_validate(assessment)


@router.post(
    "/adverse-events/{ae_id}/expectedness",
    response_model=AssessmentResponse,
    status_code=201,
)
async def record_expectedness(
    ae_id: UUID,
    body: ExpectednessRequest,
    session: DbSession,
    current_user: RecordGuard,
) -> AssessmentResponse:
    """Record an Expectedness_Assessment for an Adverse_Event_Record."""

    assessment = await assessment_service.record_expectedness(
        session,
        ae_id=ae_id,
        expected=body.expected,
        reference_safety_information=body.reference_safety_information,
        actor=build_actor(current_user),
    )
    return AssessmentResponse.model_validate(assessment)


@router.post(
    "/adverse-events/{ae_id}/severity",
    response_model=AssessmentResponse,
    status_code=201,
)
async def record_severity(
    ae_id: UUID,
    body: SeverityRequest,
    session: DbSession,
    current_user: RecordGuard,
) -> AssessmentResponse:
    """Record a Severity_Grade for an Adverse_Event_Record."""

    assessment = await assessment_service.record_severity(
        session,
        ae_id=ae_id,
        grade=body.grade,
        actor=build_actor(current_user),
    )
    return AssessmentResponse.model_validate(assessment)
