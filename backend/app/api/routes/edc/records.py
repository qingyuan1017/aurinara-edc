"""Routes for repeating Form_Record lifecycle operations.

The handlers validate input, enforce the form-enter permission and object scope,
then delegate all clinical mutations to RepeatingRecordService. The injected
session owns the transaction, so each service audit event commits atomically
with its corresponding row change.

Satisfies Requirements 11.1-11.4 and 21.1.

Endpoints:
  - POST   /form-instances/{form_instance_id}/records  add a row
  - PATCH  /records/{record_id}                        edit a row
  - DELETE /records/{record_id}                        soft-delete a row
  - POST   /records/{record_id}/restore                restore a row
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import PaginationParams, get_current_user, get_db, get_permission_service
from app.api.pagination import paginate
from app.core.exceptions import NotFoundError
from app.models.edc.form_data import FormInstance
from app.models.edc.form_record import FormRecord
from app.models.shared.identity import User
from app.schemas.edc.form_record import (
    FormRecordCreate,
    FormRecordDelete,
    FormRecordResponse,
    FormRecordRestore,
    FormRecordUpdate,
)
from app.schemas.shared.base import PaginatedResponse
from app.services.edc.data_capture_service import data_capture_service
from app.services.edc.repeating_record_service import repeating_record_service
from app.services.shared.permission_service import PermissionService

DbSession = Annotated[AsyncSession, Depends(get_db)]

form_instance_records_router = APIRouter(prefix="/form-instances", tags=["records"])
router = APIRouter(prefix="/records", tags=["records"])


@form_instance_records_router.get(
    "/{form_instance_id}/records",
    response_model=PaginatedResponse[FormRecordResponse],
)
async def list_records(
    form_instance_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
    pagination: Annotated[PaginationParams, Depends()],
    include_deleted: bool = False,
) -> PaginatedResponse[FormRecordResponse]:
    form_instance = await data_capture_service.load(session, form_instance_id)
    _assert_form_access(current_user, form_instance, permission_service, permission="form.read")
    statement = select(FormRecord).where(FormRecord.form_instance_id == form_instance_id)
    if not include_deleted:
        statement = statement.where(FormRecord.deleted_at.is_(None))
    result = await paginate(session, statement.order_by(FormRecord.sequence_number), pagination)
    return PaginatedResponse[FormRecordResponse](
        items=[FormRecordResponse.model_validate(record) for record in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


def _assert_form_access(
    current_user: User,
    form_instance: FormInstance,
    permission_service: PermissionService,
    *,
    permission: str = "form.enter",
) -> None:
    """Apply the requested permission to the form's actual study/site scope."""
    subject = form_instance.subject
    permission_service.require(
        current_user,
        permission,
        study_id=subject.study_id,
        site_id=subject.site_id,
    )


async def _get_record(session: AsyncSession, record_id: UUID) -> FormRecord:
    """Load a record and its subject scope, or return the standard 404 error."""
    result = await session.execute(
        select(FormRecord)
        .where(FormRecord.id == record_id)
        .options(selectinload(FormRecord.form_instance).selectinload(FormInstance.subject))
    )
    record = result.scalars().first()
    if record is None:
        raise NotFoundError(
            message="Form record not found",
            details={"record_id": str(record_id)},
        )
    return record


@form_instance_records_router.post(
    "/{form_instance_id}/records",
    response_model=FormRecordResponse,
    status_code=201,
)
async def add_record(
    form_instance_id: UUID,
    body: FormRecordCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> FormRecordResponse:
    """Add a row with the next monotonic sequence number."""
    form_instance = await data_capture_service.load(session, form_instance_id)
    _assert_form_access(current_user, form_instance, permission_service)
    record = await repeating_record_service.add_record(
        session=session,
        form_instance=form_instance,
        values=body.values,
        actor_id=current_user.id,
        reason=body.reason,
    )
    return FormRecordResponse.model_validate(record)


@router.patch("/{record_id}", response_model=FormRecordResponse)
async def edit_record(
    record_id: UUID,
    body: FormRecordUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> FormRecordResponse:
    """Replace an active row's values and write an audit event."""
    record = await _get_record(session, record_id)
    _assert_form_access(current_user, record.form_instance, permission_service)
    updated = await repeating_record_service.edit_record(
        session=session,
        record=record,
        values=body.values,
        actor_id=current_user.id,
        reason=body.reason,
    )
    return FormRecordResponse.model_validate(updated)


@router.delete("/{record_id}", response_model=FormRecordResponse)
async def delete_record(
    record_id: UUID,
    body: FormRecordDelete,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> FormRecordResponse:
    """Soft-delete a row while retaining its data and deletion metadata."""
    record = await _get_record(session, record_id)
    _assert_form_access(current_user, record.form_instance, permission_service)
    deleted = await repeating_record_service.soft_delete(
        session=session,
        record=record,
        reason=body.reason,
        actor_id=current_user.id,
    )
    return FormRecordResponse.model_validate(deleted)


@router.post("/{record_id}/restore", response_model=FormRecordResponse)
async def restore_record(
    record_id: UUID,
    body: FormRecordRestore,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> FormRecordResponse:
    """Restore a soft-deleted row and clear its deletion metadata."""
    record = await _get_record(session, record_id)
    _assert_form_access(current_user, record.form_instance, permission_service)
    restored = await repeating_record_service.restore(
        session=session,
        record=record,
        actor_id=current_user.id,
        reason=body.reason,
    )
    return FormRecordResponse.model_validate(restored)
