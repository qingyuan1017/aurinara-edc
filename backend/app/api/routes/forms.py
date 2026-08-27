"""Form, section, and field routes — eCRF metadata configuration.

Satisfies Requirements:
  - 9.1: CRUD for form definitions within a study version.
  - 9.2: Create sections and fields within forms.
  - 21.1: All endpoints mounted under /api/v1.

Endpoints:
  - GET   /studies/{study_id}/forms         list form definitions (form.read)
  - POST  /studies/{study_id}/forms         create form definition (form.configure)
  - GET   /forms/{form_id}                  get form definition with sections/fields (form.read)
  - PATCH /forms/{form_id}                  update form definition (form.configure)
  - DELETE /forms/{form_id}                 delete form definition (form.configure)
  - POST  /forms/{form_id}/sections         create section (form.configure)
  - POST  /forms/{form_id}/fields           create field (form.configure)
  - PATCH /fields/{field_id}                update field (form.configure)
  - DELETE /fields/{field_id}               delete field (form.configure)
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.core.exceptions import NotFoundError, ValidationError
from app.models.identity import User
from app.models.study import StudyVersion, StudyVersionStatus
from app.schemas.form_metadata import (
    FieldDefinitionCreate,
    FieldDefinitionResponse,
    FieldDefinitionUpdate,
    FormDefinitionCreate,
    FormDefinitionResponse,
    FormDefinitionUpdate,
    FormSectionCreate,
    FormSectionResponse,
)
from app.services.form_metadata_service import form_metadata_service
from app.services.study_service import study_service

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Study-scoped form collection (mounted at /studies)
# ---------------------------------------------------------------------------

study_forms_router = APIRouter(prefix="/studies", tags=["forms"])


async def _get_latest_or_specified_version(
    session: AsyncSession,
    study_id: UUID,
    study_version_id: UUID | None = None,
) -> StudyVersion:
    """Return the specified version, or the latest draft version for the study.

    If no study_version_id is given, find the most recently created draft version.
    Raises NotFoundError if the study has no matching version.
    """
    if study_version_id is not None:
        result = await session.execute(
            select(StudyVersion).where(
                StudyVersion.id == study_version_id,
                StudyVersion.study_id == study_id,
            )
        )
        version = result.scalars().first()
        if version is None:
            raise NotFoundError(
                "Study version not found",
                details={
                    "study_version_id": str(study_version_id),
                    "study_id": str(study_id),
                },
            )
        return version

    # Default: latest draft version
    result = await session.execute(
        select(StudyVersion)
        .where(
            StudyVersion.study_id == study_id,
            StudyVersion.status == StudyVersionStatus.draft,
        )
        .order_by(StudyVersion.created_at.desc())
        .limit(1)
    )
    version = result.scalars().first()
    if version is None:
        raise NotFoundError(
            "No draft study version found for this study",
            details={"study_id": str(study_id)},
        )
    return version


@study_forms_router.get(
    "/{study_id}/forms", response_model=list[FormDefinitionResponse]
)
async def list_forms(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.read"))],
    study_version_id: Annotated[
        UUID | None,
        Query(
            description="Specific study version ID. Defaults to the latest draft version.",
        ),
    ] = None,
) -> list[FormDefinitionResponse]:
    """List form definitions for a study's specified or latest draft version.

    Permission: form.read
    Requirement 9.1: Form definitions within a version.
    """
    # Ensure study exists
    await study_service.get_study(session, study_id)

    version = await _get_latest_or_specified_version(
        session, study_id, study_version_id
    )

    forms = await form_metadata_service.list_forms(session, version.id)
    return [FormDefinitionResponse.model_validate(f) for f in forms]


@study_forms_router.post(
    "/{study_id}/forms", response_model=FormDefinitionResponse, status_code=201
)
async def create_form(
    study_id: UUID,
    body: FormDefinitionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.configure"))],
    study_version_id: Annotated[
        UUID | None,
        Query(
            description="Target study version ID. Defaults to the latest draft version.",
        ),
    ] = None,
) -> FormDefinitionResponse:
    """Create a form definition on a study version.

    Permission: form.configure
    Requirement 9.1: Create form definitions while version is draft.
    """
    # Ensure study exists
    await study_service.get_study(session, study_id)

    version = await _get_latest_or_specified_version(
        session, study_id, study_version_id
    )

    form = await form_metadata_service.create_form(
        session=session,
        version=version,
        data=body,
        actor_id=current_user.id,
    )
    return FormDefinitionResponse.model_validate(form)


# ---------------------------------------------------------------------------
# Single form operations (mounted at /forms)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/forms", tags=["forms"])


@router.get("/{form_id}", response_model=FormDefinitionResponse)
async def get_form(
    form_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.read"))],
) -> FormDefinitionResponse:
    """Get a form definition with sections and fields.

    Permission: form.read
    Requirement 9.1: Retrieve form definition metadata.
    """
    form = await form_metadata_service.get_form(session, form_id)
    return FormDefinitionResponse.model_validate(form)


@router.patch("/{form_id}", response_model=FormDefinitionResponse)
async def update_form(
    form_id: UUID,
    body: FormDefinitionUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.configure"))],
) -> FormDefinitionResponse:
    """Update a form definition (partial PATCH).

    Permission: form.configure
    Requirement 9.1: Edit form definitions while version is draft.
    """
    form = await form_metadata_service.get_form(session, form_id)
    version = form.study_version

    updated = await form_metadata_service.update_form(
        session=session,
        version=version,
        form=form,
        data=body,
        actor_id=current_user.id,
    )
    return FormDefinitionResponse.model_validate(updated)


@router.delete("/{form_id}", status_code=204)
async def delete_form(
    form_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.configure"))],
) -> None:
    """Delete a form definition.

    Permission: form.configure
    Requirement 9.1: Delete form definitions while version is draft.
    """
    form = await form_metadata_service.get_form(session, form_id)
    version = form.study_version

    await form_metadata_service.delete_form(
        session=session,
        version=version,
        form=form,
        actor_id=current_user.id,
    )


@router.post(
    "/{form_id}/sections", response_model=FormSectionResponse, status_code=201
)
async def create_section(
    form_id: UUID,
    body: FormSectionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.configure"))],
) -> FormSectionResponse:
    """Create a section within a form.

    Permission: form.configure
    Requirement 9.2: Create sections within a form definition.
    """
    form = await form_metadata_service.get_form(session, form_id)
    version = form.study_version

    section = await form_metadata_service.create_section(
        session=session,
        version=version,
        form=form,
        data=body,
        actor_id=current_user.id,
    )
    return FormSectionResponse.model_validate(section)


@router.post(
    "/{form_id}/fields", response_model=FieldDefinitionResponse, status_code=201
)
async def create_field(
    form_id: UUID,
    body: FieldDefinitionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.configure"))],
    section_id: Annotated[
        UUID,
        Query(description="The section ID to add the field to."),
    ],
) -> FieldDefinitionResponse:
    """Create a field within a form (specifying target section via query param).

    Permission: form.configure
    Requirement 9.2: Create fields within a form section.
    """
    form = await form_metadata_service.get_form(session, form_id)
    version = form.study_version

    # Validate section belongs to this form
    section = await form_metadata_service.get_section(session, section_id)
    if section.form_definition_id != form.id:
        raise ValidationError(
            "Section does not belong to the specified form",
            details={
                "section_id": str(section_id),
                "form_id": str(form_id),
            },
        )

    field = await form_metadata_service.create_field(
        session=session,
        version=version,
        section=section,
        data=body,
        actor_id=current_user.id,
    )
    return FieldDefinitionResponse.model_validate(field)


# ---------------------------------------------------------------------------
# Single field operations (mounted at /fields)
# ---------------------------------------------------------------------------

fields_router = APIRouter(prefix="/fields", tags=["forms"])


@fields_router.patch("/{field_id}", response_model=FieldDefinitionResponse)
async def update_field(
    field_id: UUID,
    body: FieldDefinitionUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.configure"))],
) -> FieldDefinitionResponse:
    """Update a field definition (partial PATCH).

    Permission: form.configure
    Requirement 9.2: Edit field definitions while version is draft.
    """
    field = await form_metadata_service.get_field(session, field_id)
    section = field.form_section
    form = section.form_definition
    version = form.study_version

    updated = await form_metadata_service.update_field(
        session=session,
        version=version,
        field=field,
        data=body,
        actor_id=current_user.id,
    )
    return FieldDefinitionResponse.model_validate(updated)


@fields_router.delete("/{field_id}", status_code=204)
async def delete_field(
    field_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.configure"))],
) -> None:
    """Delete a field definition.

    Permission: form.configure
    Requirement 9.2: Delete field definitions while version is draft.
    """
    field = await form_metadata_service.get_field(session, field_id)
    section = field.form_section
    form = section.form_definition
    version = form.study_version

    await form_metadata_service.delete_field(
        session=session,
        version=version,
        field=field,
        actor_id=current_user.id,
    )
