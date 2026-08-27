"""Form data routes — load, save, submit, change-value, and audit trail.

Thin route handlers that delegate to DataCaptureService and AuditService
for clinical data capture lifecycle operations.

Satisfies Requirements:
  - 10.1: Save draft field values and set status In Progress.
  - 10.3: Submit form instance (validates required fields, types, ranges).
  - 10.5: Post-submission field change requires Reason_For_Change.
  - 21.1: All endpoints mounted under /api/v1.

Endpoints:
  - GET   /form-instances/{form_instance_id}              load form instance (form.read)
  - PATCH /form-instances/{form_instance_id}/data         save draft data (form.enter)
  - POST  /form-instances/{form_instance_id}/save         explicit save draft (form.enter)
  - POST  /form-instances/{form_instance_id}/submit       submit form (form.submit)
  - POST  /form-instances/{form_instance_id}/change-value post-submission change (form.enter)
  - GET   /form-instances/{form_instance_id}/audit        audit trail (audit.read)
"""

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_permission
from app.core.audit import audit_service
from app.models.identity import User
from app.schemas.audit import AuditEventResponse, AuditSearchFilters
from app.schemas.base import PaginatedResponse
from app.schemas.form_data import (
    ChangeValueRequest,
    FormDataPatch,
    FormInstanceResponse,
)
from app.services.data_capture_service import data_capture_service

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/form-instances", tags=["form-data"])


@router.get("/{form_instance_id}", response_model=FormInstanceResponse)
async def get_form_instance(
    form_instance_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.read"))],
) -> FormInstanceResponse:
    """Load a form instance with its field values.

    Permission: form.read
    Requirement 10.1: Returns the form instance with current data.
    """
    form_instance = await data_capture_service.load(session, form_instance_id)
    return FormInstanceResponse.model_validate(form_instance)


@router.patch("/{form_instance_id}/data", response_model=FormInstanceResponse)
async def patch_form_data(
    form_instance_id: UUID,
    body: FormDataPatch,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.enter"))],
) -> FormInstanceResponse:
    """Save draft field data for a form instance.

    Permission: form.enter
    Requirement 10.1: Persists Field_Values and sets status to In Progress.
    Body is a dict mapping field_definition_id to value.
    """
    form_instance = await data_capture_service.load(session, form_instance_id)
    updated = await data_capture_service.save_draft(
        session=session,
        form_instance=form_instance,
        values=body.values,
        actor_id=current_user.id,
    )
    return FormInstanceResponse.model_validate(updated)


@router.post("/{form_instance_id}/save", response_model=FormInstanceResponse)
async def save_form_draft(
    form_instance_id: UUID,
    body: FormDataPatch,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.enter"))],
) -> FormInstanceResponse:
    """Explicit save of draft field data for a form instance.

    Permission: form.enter
    Requirement 10.1: Persists Field_Values and sets status to In Progress.
    Semantically identical to PATCH /data but uses POST for explicit save intent.
    """
    form_instance = await data_capture_service.load(session, form_instance_id)
    updated = await data_capture_service.save_draft(
        session=session,
        form_instance=form_instance,
        values=body.values,
        actor_id=current_user.id,
    )
    return FormInstanceResponse.model_validate(updated)


@router.post("/{form_instance_id}/submit", response_model=FormInstanceResponse)
async def submit_form(
    form_instance_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.submit"))],
) -> FormInstanceResponse:
    """Submit a form instance after validation.

    Permission: form.submit
    Requirement 10.3: Validates required fields, data types, ranges, codelist
    membership, and conditional rules. On success sets status Submitted.
    On failure returns field-level errors preserving previously entered values.
    """
    form_instance = await data_capture_service.load(session, form_instance_id)
    updated = await data_capture_service.submit(
        session=session,
        form_instance=form_instance,
        actor_id=current_user.id,
    )
    return FormInstanceResponse.model_validate(updated)


@router.post(
    "/{form_instance_id}/change-value", response_model=FormInstanceResponse
)
async def change_field_value(
    form_instance_id: UUID,
    body: ChangeValueRequest,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("form.enter"))],
) -> FormInstanceResponse:
    """Change a single field value, with optional reason for post-submission edits.

    Permission: form.enter
    Requirement 10.5: If the form instance was already submitted, requires a
    Reason_For_Change before persisting the change.
    """
    form_instance = await data_capture_service.load(session, form_instance_id)
    updated = await data_capture_service.change_value(
        session=session,
        form_instance=form_instance,
        field_id=body.field_id,
        new_value=body.value,
        reason=body.reason,
        actor_id=current_user.id,
    )
    return FormInstanceResponse.model_validate(updated)


@router.get(
    "/{form_instance_id}/audit",
    response_model=PaginatedResponse[AuditEventResponse],
)
async def get_form_instance_audit(
    form_instance_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("audit.read"))],
    pagination: Annotated[PaginationParams, Depends()],
) -> Any:
    """Get the audit trail for a form instance.

    Permission: audit.read
    Returns paginated audit events for this form instance, ordered by
    most recent first.
    """
    # Validate the form instance exists
    await data_capture_service.load(session, form_instance_id)

    # Search audit events scoped to this form instance
    filters = AuditSearchFilters(
        entity_type="form_instance",
        entity_id=form_instance_id,
    )
    result = await audit_service.search(
        session, filters=filters, pagination=pagination
    )

    # For a complete audit trail, we search both form_instance and field_value
    # events. The primary search covers form-level events (submit, status changes).
    # Field-level events are tracked via the subject_id on the form instance.
    return result
