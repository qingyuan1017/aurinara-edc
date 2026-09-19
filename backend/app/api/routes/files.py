"""Routes for uploading, downloading, and soft-deleting file attachments.

The FileAttachmentService owns parent resolution, authorization, lock checks,
storage, metadata persistence, and audit events.  These handlers only parse
HTTP input, delegate to the service, and serialize the result.

Satisfies Requirements 27.1-27.3 and 21.1.

Endpoints:
  - POST   /objects/{object_type}/{object_id}/files  multipart upload
  - GET    /files/{file_id}/download                 authenticated download
  - DELETE /files/{file_id}                          reasoned soft-delete
"""

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.exceptions import NotFoundError
from app.models.file_attachment import FileAttachment
from app.models.identity import User
from app.schemas.file_attachment import FileAttachmentDelete, FileAttachmentResponse
from app.services.file_attachment_service import file_attachment_service

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["files"])


@router.post(
    "/objects/{object_type}/{object_id}/files",
    response_model=FileAttachmentResponse,
    status_code=201,
)
async def upload_file(
    object_type: str,
    object_id: UUID,
    file: Annotated[UploadFile, File(description="Attachment content")],
    session: DbSession,
    current_user: CurrentUser,
) -> FileAttachmentResponse:
    """Upload an attachment linked to the requested clinical parent object."""
    attachment = await file_attachment_service.upload(
        session=session,
        parent=object_id,
        file=file,
        actor_id=current_user.id,
        user=current_user,
        object_type=object_type,
        object_id=object_id,
    )
    return FileAttachmentResponse.model_validate(attachment)


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> Response:
    """Download an attachment after the service verifies parent read access."""
    attachment = await session.get(FileAttachment, file_id)
    if attachment is None:
        raise NotFoundError(
            message="File attachment not found",
            details={"attachment_id": str(file_id)},
        )

    content = await file_attachment_service.download(session, attachment, current_user)
    filename = quote(attachment.filename, safe="")
    return Response(
        content=content,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{attachment.filename}\"; filename*=UTF-8''{filename}"
            )
        },
    )


@router.delete("/files/{file_id}", response_model=FileAttachmentResponse)
async def delete_file(
    file_id: UUID,
    body: FileAttachmentDelete,
    session: DbSession,
    current_user: CurrentUser,
) -> FileAttachmentResponse:
    """Soft-delete an attachment while retaining its metadata and storage bytes."""
    attachment = await file_attachment_service.soft_delete(
        session=session,
        attachment=file_id,
        reason=body.reason,
        actor_id=current_user.id,
        user=current_user,
    )
    return FileAttachmentResponse.model_validate(attachment)


__all__ = ["router"]
