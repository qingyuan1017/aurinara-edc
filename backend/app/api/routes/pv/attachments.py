"""PV safety attachment routes on shared file primitives.

Thin, authenticated handlers under ``/api/v1/pv`` that delegate to the
``Safety_Attachment_Service``. The service enforces the 100 MB/non-empty bound,
the Closed-case upload guard, parent-case read access on download, and
Soft_Deletion on delete, recording one PV safety Audit_Event per completed
action. A Safety_Attachment always links to a parent Safety_Case; no route
targets an EDC Clinical_Attachment or a CTMS Operational_Attachment.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_pv_permission
from app.api.routes.pv._common import build_actor
from app.core.exceptions import NotFoundError
from app.models.file_attachment import FileAttachment
from app.models.identity import User
from app.schemas.pv.resources import (
    SafetyAttachmentDeleteRequest,
    SafetyAttachmentResponse,
)
from app.services.safety_attachment_service import safety_attachment_service

router = APIRouter(tags=["pv-attachments"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
# Uploading/deleting a Safety_Attachment is a case mutation; downloading needs
# read access to the parent Safety_Case. Object-level access is enforced in the
# service against the resolved parent case.
UploadGuard = Annotated[User, Depends(require_pv_permission("safety_case.enter"))]
ReadGuard = Annotated[User, Depends(require_pv_permission("safety_case.read"))]


@router.post(
    "/cases/{case_id}/attachments",
    response_model=SafetyAttachmentResponse,
    status_code=201,
)
async def upload_attachment(
    case_id: UUID,
    session: DbSession,
    current_user: UploadGuard,
    file: Annotated[UploadFile, File(description="Safety attachment content")],
) -> SafetyAttachmentResponse:
    """Store a non-empty file (<=100 MB) as a Safety_Attachment for a case."""

    attachment = await safety_attachment_service.upload(
        session,
        case_id=case_id,
        file=file,
        actor=build_actor(current_user),
        user=current_user,
    )
    return SafetyAttachmentResponse.model_validate(attachment)


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
) -> Response:
    """Download a Safety_Attachment after parent-case read access is verified."""

    content = await safety_attachment_service.download(
        session,
        attachment_id=attachment_id,
        actor=build_actor(current_user),
        user=current_user,
    )
    attachment = await session.get(FileAttachment, attachment_id)
    if attachment is None:  # pragma: no cover - download already resolved it
        raise NotFoundError(
            message="Safety_Attachment was not found",
            details={"reason": "RECORD_NOT_FOUND", "attachment_id": str(attachment_id)},
        )
    filename = quote(attachment.filename, safe="")
    return Response(
        content=content,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{attachment.filename}"; '
                f"filename*=UTF-8''{filename}"
            )
        },
    )


@router.delete("/attachments/{attachment_id}", response_model=SafetyAttachmentResponse)
async def delete_attachment(
    attachment_id: UUID,
    body: SafetyAttachmentDeleteRequest,
    session: DbSession,
    current_user: UploadGuard,
) -> SafetyAttachmentResponse:
    """Soft-delete a Safety_Attachment, retaining metadata and the reason."""

    attachment = await safety_attachment_service.soft_delete(
        session,
        attachment_id=attachment_id,
        reason=body.reason,
        actor=build_actor(current_user),
        user=current_user,
    )
    return SafetyAttachmentResponse.model_validate(attachment)
