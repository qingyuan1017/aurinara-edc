"""Edit-check definition and runtime evaluation routes.

The routes keep authorization and study-version ownership server-side while
 delegating validation, persistence, and evaluation to ``EditCheckService``.
Satisfies Requirements 12.1, 12.4, 12.5, and 21.1.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_permission_service
from app.core.exceptions import NotFoundError
from app.models.edit_check import EditCheck, ValidationResult
from app.models.form_data import FormInstance
from app.models.form_metadata import FormDefinition
from app.models.identity import User
from app.models.study import StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.schemas.edit_check import (
    EditCheckCreate,
    EditCheckResponse,
    EditCheckRunRequest,
    EditCheckRunResponse,
    EditCheckTestRequest,
    EditCheckTestResponse,
    EditCheckUpdate,
    ValidationResultResponse,
)
from app.services.edit_check_service import edit_check_service
from app.services.permission_service import PermissionService
from app.services.study_service import study_service

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
PermissionSvc = Annotated[PermissionService, Depends(get_permission_service)]

study_router = APIRouter(prefix="/studies", tags=["edit-checks"])
router = APIRouter(prefix="/edit-checks", tags=["edit-checks"])


async def _get_version(
    session: AsyncSession,
    study_id: UUID,
    study_version_id: UUID | None = None,
    *,
    draft_only: bool = True,
) -> StudyVersion:
    """Load a version owned by the requested study, never by ID alone."""
    conditions = [StudyVersion.study_id == study_id]
    if study_version_id is not None:
        conditions.append(StudyVersion.id == study_version_id)
    elif draft_only:
        conditions.append(StudyVersion.status == StudyVersionStatus.draft)

    result = await session.execute(
        select(StudyVersion)
        .where(*conditions)
        .order_by(StudyVersion.created_at.desc())
        .limit(1)
    )
    version = result.scalars().first()
    if version is None:
        message = "Study version not found" if study_version_id else "No draft study version found for this study"
        raise NotFoundError(
            message,
            details={
                "study_id": str(study_id),
                **({"study_version_id": str(study_version_id)} if study_version_id else {}),
            },
        )
    return version


async def _get_check_version(
    session: AsyncSession, edit_check_id: UUID
) -> tuple[EditCheck, StudyVersion]:
    """Load an edit check and its owning version for object authorization."""
    edit_check = await edit_check_service.get_edit_check(session, edit_check_id)
    version = await session.get(StudyVersion, edit_check.study_version_id)
    if version is None:
        raise NotFoundError(
            "Study version not found",
            details={"study_version_id": str(edit_check.study_version_id)},
        )
    return edit_check, version


def _require_access(
    current_user: User,
    permission_service: PermissionService,
    study_id: UUID,
) -> None:
    """Enforce the permission against the owning study, not just globally."""
    permission_service.require(current_user, "editcheck.configure", study_id=study_id)


@study_router.get(
    "/{study_id}/edit-checks", response_model=list[EditCheckResponse]
)
async def list_edit_checks(
    study_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    study_version_id: Annotated[
        UUID | None,
        Query(description="Specific study version; defaults to the latest draft."),
    ] = None,
) -> list[EditCheckResponse]:
    """List edit checks for a study version within the caller's study scope."""
    await study_service.get_study(session, study_id)
    _require_access(current_user, permission_service, study_id)
    version = await _get_version(session, study_id, study_version_id)
    checks = await edit_check_service.list_edit_checks(session, version.id)
    return [EditCheckResponse.model_validate(check) for check in checks]


@study_router.post(
    "/{study_id}/edit-checks",
    response_model=EditCheckResponse,
    status_code=201,
)
async def create_edit_check(
    study_id: UUID,
    body: EditCheckCreate,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    study_version_id: Annotated[
        UUID | None,
        Query(description="Target draft version; defaults to the latest draft."),
    ] = None,
) -> EditCheckResponse:
    """Create a validated edit check on a mutable study version."""
    await study_service.get_study(session, study_id)
    _require_access(current_user, permission_service, study_id)
    version = await _get_version(session, study_id, study_version_id)
    check = await edit_check_service.create_edit_check(
        session, version, body, actor_id=current_user.id
    )
    return EditCheckResponse.model_validate(check)


@router.get("/{edit_check_id}", response_model=EditCheckResponse)
async def get_edit_check(
    edit_check_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> EditCheckResponse:
    """Get an edit check after checking its owning study scope."""
    check, version = await _get_check_version(session, edit_check_id)
    _require_access(current_user, permission_service, version.study_id)
    return EditCheckResponse.model_validate(check)


@router.patch("/{edit_check_id}", response_model=EditCheckResponse)
async def update_edit_check(
    edit_check_id: UUID,
    body: EditCheckUpdate,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> EditCheckResponse:
    """Update a rule only while its owning study version is mutable."""
    check, version = await _get_check_version(session, edit_check_id)
    _require_access(current_user, permission_service, version.study_id)
    updated = await edit_check_service.update_edit_check(
        session, version, check, body, actor_id=current_user.id
    )
    return EditCheckResponse.model_validate(updated)


@router.post("/{edit_check_id}/test", response_model=EditCheckTestResponse)
async def test_edit_check(
    edit_check_id: UUID,
    body: EditCheckTestRequest,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> EditCheckTestResponse:
    """Evaluate sample data without creating clinical or validation records."""
    check, version = await _get_check_version(session, edit_check_id)
    _require_access(current_user, permission_service, version.study_id)
    outcome = edit_check_service.test(check.rule_json, body.sample_data)
    return EditCheckTestResponse(
        edit_check_id=check.id,
        outcome=outcome,
        matched=outcome,
        passed=not outcome,
        persisted=False,
    )


@study_router.post(
    "/{study_id}/edit-checks/run",
    response_model=EditCheckRunResponse,
)
async def run_edit_checks(
    study_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    body: EditCheckRunRequest | None = None,
) -> EditCheckRunResponse:
    """Evaluate active checks against selected or all study form instances."""
    await study_service.get_study(session, study_id)
    _require_access(current_user, permission_service, study_id)
    request = body or EditCheckRunRequest()
    version = await _get_version(
        session, study_id, request.study_version_id, draft_only=False
    )

    requested_ids = set(request.form_instance_ids)
    if request.form_instance_id is not None:
        requested_ids.add(request.form_instance_id)

    statement = (
        select(FormInstance)
        .join(Subject, Subject.id == FormInstance.subject_id)
        .join(FormDefinition, FormDefinition.id == FormInstance.form_definition_id)
        .where(
            Subject.study_id == study_id,
            FormDefinition.study_version_id == version.id,
        )
    )
    if requested_ids:
        statement = statement.where(FormInstance.id.in_(requested_ids))

    form_instances = list((await session.execute(statement)).scalars().all())
    if requested_ids and len(form_instances) != len(requested_ids):
        found_ids = {form.id for form in form_instances}
        missing = sorted(str(form_id) for form_id in requested_ids - found_ids)
        raise NotFoundError(
            "One or more form instances were not found in the study version",
            details={"form_instance_ids": missing},
        )

    results: list[ValidationResult] = []
    for form_instance in form_instances:
        results.extend(
            await edit_check_service.evaluate_form_instance(
                session, form_instance, actor_id=current_user.id
            )
        )

    return EditCheckRunResponse(
        study_id=study_id,
        study_version_id=version.id,
        evaluated_form_instances=len(form_instances),
        failed_checks=len(results),
        results=[ValidationResultResponse.model_validate(result) for result in results],
    )


__all__ = ["router", "study_router"]
