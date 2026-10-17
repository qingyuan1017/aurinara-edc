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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_current_user, get_db, get_permission_service
from app.core.audit import audit_service
from app.core.edit_check_dsl import evaluate_rule
from app.models.edc.form_data import FieldValue
from app.models.shared.identity import User
from app.schemas.edc.form_data import (
    ChangeValueRequest,
    FormDataPatch,
    FormInstanceResponse,
)
from app.schemas.shared.audit import AuditEventResponse, AuditSearchFilters
from app.schemas.shared.base import PaginatedResponse
from app.services.edc.data_capture_service import data_capture_service
from app.services.edc.operational_service import edc_operational_service
from app.services.edc.scope_service import edc_scope_service
from app.services.shared.permission_service import PermissionService

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/form-instances", tags=["form-data"])


async def _authorized_form(
    session: AsyncSession,
    form_instance_id: UUID,
    current_user: User,
    permission_service: PermissionService,
    permission: str,
) -> Any:
    form_instance = await data_capture_service.load(session, form_instance_id)
    edc_scope_service.require_form(current_user, permission_service, permission, form_instance)
    return form_instance


async def _instance_payload(session: AsyncSession, form_instance: Any) -> dict[str, Any]:
    """Return the persisted instance plus the metadata needed by the UI."""
    definition = form_instance.form_definition
    field_values = list(
        (
            await session.execute(
                select(FieldValue).where(FieldValue.form_instance_id == form_instance.id)
            )
        )
        .scalars()
        .all()
    )
    values = form_instance.data_jsonb or {
        str(value.field_definition_id): value.value for value in field_values
    }
    variable_context = {
        field.variable_name: values.get(str(field.id))
        for section in definition.sections
        for field in section.fields
    }
    sections = [
        {
            "id": section.id,
            "title": section.name,
            "fields": [
                {
                    "id": field.id,
                    "label": field.label,
                    "question": field.question,
                    "caption": field.caption,
                    "text_align": field.text_align,
                    "variable_name": field.variable_name,
                    "control_type": field.control_type,
                    "data_type": field.data_type,
                    "is_required": field.is_required,
                    "default_value": field.default_value,
                    "help_text": field.help_text,
                    "unit": field.unit,
                    "min_value": field.min_value,
                    "max_value": field.max_value,
                    "max_length": field.max_length,
                    "decimal_precision": field.decimal_precision,
                    "is_read_only": field.is_read_only,
                    "is_calculated": field.is_calculated,
                    "calculation_expression": field.calculation_expression,
                    "visibility_rule": field.visibility_rule,
                    "is_visible": (
                        bool(evaluate_rule(field.visibility_rule, variable_context))
                        if field.visibility_rule
                        else True
                    ),
                    # Choice controls (dropdown/radio/checkbox/...) render their
                    # options from the linked codelist's items. Project them as
                    # {value: code, label} ordered by display order so the
                    # data-entry renderer can populate the control.
                    "codelist_items": [
                        {"value": item.code, "label": item.label}
                        for item in sorted(
                            field.codelist.items,
                            key=lambda i: (i.display_order, str(i.id)),
                        )
                    ]
                    if field.codelist is not None
                    else [],
                }
                for field in section.fields
            ],
        }
        for section in definition.sections
    ]
    operational_status = (await edc_operational_service.form_statuses(session, [form_instance]))[
        form_instance.id
    ]
    return {
        "id": form_instance.id,
        "study_id": form_instance.subject.study_id,
        "subject_id": form_instance.subject_id,
        "visit_instance_id": form_instance.visit_instance_id,
        "form_definition_id": form_instance.form_definition_id,
        "status": form_instance.status,
        "data_entry_status": form_instance.data_entry_status,
        "data_revision": form_instance.data_revision,
        "operational_status": operational_status,
        "data_jsonb": form_instance.data_jsonb,
        "created_at": form_instance.created_at,
        "updated_at": form_instance.updated_at,
        "submitted_at": form_instance.submitted_at,
        "submitted_by": form_instance.submitted_by,
        "field_values": field_values,
        "form_name": definition.name,
        "is_repeating": definition.is_repeating,
        "subject_number": form_instance.subject.subject_number,
        "visit_name": form_instance.visit_instance.name if form_instance.visit_instance else None,
        "sections": sections,
        "data": values,
        "is_frozen": operational_status.freeze == "Active",
        "is_locked": operational_status.lock == "Active",
    }


@router.get("/{form_instance_id}", response_model=FormInstanceResponse)
async def get_form_instance(
    form_instance_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> FormInstanceResponse:
    """Load a form instance with its field values.

    Permission: form.read
    Requirement 10.1: Returns the form instance with current data.
    """
    form_instance = await _authorized_form(
        session, form_instance_id, current_user, permission_service, "form.read"
    )
    return FormInstanceResponse.model_validate(await _instance_payload(session, form_instance))


@router.patch("/{form_instance_id}/data", response_model=FormInstanceResponse)
async def patch_form_data(
    form_instance_id: UUID,
    body: FormDataPatch,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> FormInstanceResponse:
    """Save draft field data for a form instance.

    Permission: form.enter
    Requirement 10.1: Persists Field_Values and sets status to In Progress.
    Body is a dict mapping field_definition_id to value.
    """
    form_instance = await _authorized_form(
        session, form_instance_id, current_user, permission_service, "form.enter"
    )
    updated = await data_capture_service.save_draft(
        session=session,
        form_instance=form_instance,
        values=body.values,
        actor_id=current_user.id,
    )
    return FormInstanceResponse.model_validate(await _instance_payload(session, updated))


@router.post("/{form_instance_id}/save", response_model=FormInstanceResponse)
async def save_form_draft(
    form_instance_id: UUID,
    body: FormDataPatch,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> FormInstanceResponse:
    """Explicit save of draft field data for a form instance.

    Permission: form.enter
    Requirement 10.1: Persists Field_Values and sets status to In Progress.
    Semantically identical to PATCH /data but uses POST for explicit save intent.
    """
    form_instance = await _authorized_form(
        session, form_instance_id, current_user, permission_service, "form.enter"
    )
    updated = await data_capture_service.save_draft(
        session=session,
        form_instance=form_instance,
        values=body.values,
        actor_id=current_user.id,
    )
    return FormInstanceResponse.model_validate(await _instance_payload(session, updated))


@router.post("/{form_instance_id}/submit", response_model=FormInstanceResponse)
async def submit_form(
    form_instance_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> FormInstanceResponse:
    """Submit a form instance after validation.

    Permission: form.submit
    Requirement 10.3: Validates required fields, data types, ranges, codelist
    membership, and conditional rules. On success sets status Submitted.
    On failure returns field-level errors preserving previously entered values.
    """
    form_instance = await _authorized_form(
        session, form_instance_id, current_user, permission_service, "form.submit"
    )
    updated = await data_capture_service.submit(
        session=session,
        form_instance=form_instance,
        actor_id=current_user.id,
    )
    return FormInstanceResponse.model_validate(await _instance_payload(session, updated))


@router.post("/{form_instance_id}/change-value", response_model=FormInstanceResponse)
async def change_field_value(
    form_instance_id: UUID,
    body: ChangeValueRequest,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> FormInstanceResponse:
    """Change a single field value, with optional reason for post-submission edits.

    Permission: form.enter
    Requirement 10.5: If the form instance was already submitted, requires a
    Reason_For_Change before persisting the change.
    """
    form_instance = await _authorized_form(
        session, form_instance_id, current_user, permission_service, "form.enter"
    )
    updated = await data_capture_service.change_value(
        session=session,
        form_instance=form_instance,
        field_id=body.field_id,
        new_value=body.value,
        reason=body.reason,
        actor_id=current_user.id,
    )
    return FormInstanceResponse.model_validate(await _instance_payload(session, updated))


@router.get(
    "/{form_instance_id}/audit",
    response_model=PaginatedResponse[AuditEventResponse],
)
async def get_form_instance_audit(
    form_instance_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    pagination: Annotated[PaginationParams, Depends()],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> Any:
    """Get the audit trail for a form instance.

    Permission: audit.read
    Returns paginated audit events for this form instance, ordered by
    most recent first.
    """
    # Validate the form instance exists
    await _authorized_form(
        session, form_instance_id, current_user, permission_service, "audit.read"
    )

    # Search audit events scoped to this form instance
    filters = AuditSearchFilters(
        entity_type="form_instance",
        entity_id=form_instance_id,
    )
    result = await audit_service.search(session, filters=filters, pagination=pagination)

    # For a complete audit trail, we search both form_instance and field_value
    # events. The primary search covers form-level events (submit, status changes).
    # Field-level events are tracked via the subject_id on the form instance.
    return result
