"""PV Safety_Attachment service using the shared file primitives.

PV owns Safety_Attachments and their safety access/content semantics, but it
reuses the platform's shared file primitives rather than forking them:

* object bytes live behind ``app.core.storage.ObjectStorage`` (the same
  local/S3 abstraction used by EDC/CTMS attachments);
* metadata and soft-delete/retention state live on the shared
  ``file_attachments`` table (``app.models.file_attachment.FileAttachment``),
  tagged ``module="PV"`` and ``attachment_type="Safety_Attachment"`` so PV
  content stays separate from EDC Clinical_Attachments and CTMS
  Operational_Attachments;
* every completed upload/download/deletion records exactly one PV safety
  Audit_Event through :mod:`pv_shared_integration` /
  :mod:`pv_atomicity_service`, so no completed attachment action persists
  without its Audit_Event.

The service receives an ``AsyncSession`` from the route or worker and never
commits or opens an independent session; the shared unit of work owns the
commit/rollback boundary. Because the object bytes are written before the
metadata row and audit event are flushed, a storage failure rolls back with no
persisted metadata, and an audit/commit failure rolls back the metadata while
leaving only an orphaned object that no metadata references.

Satisfies Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.pv import ActorContext, utc_now
from app.models.file_attachment import (
    FileAttachment,
    FileAttachmentModule,
    FileAttachmentObjectType,
)
from app.models.pv.safety_case import CaseState, SafetyCase
from app.services.file_attachment_service import FileAttachmentService
from app.services.permission_service import PermissionService
from app.services.pv_ownership_guard import assert_pv_command_safe
from app.services.pv_shared_integration import (
    PVSharedIntegrationService,
    pv_shared_integration_service,
)

logger = logging.getLogger(__name__)

# A Safety_Attachment file must be non-empty and no larger than 100 MB
# (Requirement 15.1). PV enforces its own bound rather than the shared
# ``max_attachment_size_bytes`` setting, whose platform default differs.
_MAX_SAFETY_ATTACHMENT_BYTES = 100 * 1024 * 1024

# PV permissions reused from the safety-case namespace. Uploading and deleting a
# Safety_Attachment is a case mutation (``safety_case.enter``); downloading
# requires read access to the parent Safety_Case (``safety_case.read``). No new
# permission code or migration is introduced.
_UPLOAD_PERMISSION = "safety_case.enter"
_DELETE_PERMISSION = "safety_case.enter"
_READ_PERMISSION = "safety_case.read"

# The PV module value and safety attachment tag written to the shared row.
_PV_MODULE = FileAttachmentModule.PV.value
_SAFETY_ATTACHMENT_TYPE = "Safety_Attachment"
_SAFETY_OBJECT_TYPE = FileAttachmentObjectType.safety.value


class SafetyAttachmentService:
    """Store, authorize, and audit PV Safety_Attachments.

    A Safety_Attachment always links to a parent Safety_Case (or a safety source
    record owned by that case). The PV_Safety_Module never owns or mutates an EDC
    Clinical_Attachment or a CTMS Operational_Attachment; commands are guarded so
    a PV operation that targets another module's attachment is rejected before
    any state change (Requirement 15.6).
    """

    def __init__(
        self,
        *,
        storage: Any = None,
        permission_service: PermissionService | None = None,
        integration: PVSharedIntegrationService | None = None,
    ) -> None:
        # Reuse the shared object-storage backend used by every module.
        self._storage = storage or FileAttachmentService().storage
        self._permission_service = permission_service or PermissionService()
        self._integration = integration or pv_shared_integration_service

    # ------------------------------------------------------------------
    # Upload (Requirements 15.1, 15.4, 15.5, 15.6, 15.7)
    # ------------------------------------------------------------------

    async def upload(
        self,
        session: AsyncSession,
        *,
        case_id: UUID,
        file: Any,
        actor: ActorContext,
        user: Any | None = None,
    ) -> FileAttachment:
        """Store a non-empty file (<=100 MB) as a Safety_Attachment.

        The parent Safety_Case must exist and must not be Closed. An empty or
        oversized file is rejected before any object is written or metadata is
        persisted, and if object storage is unavailable the upload is rejected
        with no persisted metadata and no partial file (Requirements 15.1, 15.5,
        15.7). On success the metadata row and its single PV safety Audit_Event
        are staged on the caller's transaction so they commit or roll back
        together (Requirement 15.4).
        """

        # A PV upload must never target an EDC/CTMS attachment (Requirement 15.6).
        assert_pv_command_safe(operation="upload_safety_attachment")

        case = await self._require_open_case(session, case_id)
        if user is not None:
            self._permission_service.require(
                user,
                _UPLOAD_PERMISSION,
                study_id=case.study_id,
                site_id=case.site_id,
            )

        content, filename, content_type = await FileAttachmentService._read_file(file)
        # Validate size bounds before touching object storage so a rejected
        # upload stores nothing and persists no metadata (Requirement 15.1).
        if len(content) == 0:
            raise ValidationError(
                message="A Safety_Attachment file must not be empty",
                details={"reason": "EMPTY_ATTACHMENT", "size_bytes": 0},
            )
        if len(content) > _MAX_SAFETY_ATTACHMENT_BYTES:
            raise ValidationError(
                message="Safety_Attachment exceeds the 100 MB size limit",
                details={
                    "reason": "ATTACHMENT_TOO_LARGE",
                    "size_bytes": len(content),
                    "max_size_bytes": _MAX_SAFETY_ATTACHMENT_BYTES,
                },
            )

        attachment_id = uuid.uuid4()
        storage_key = f"pv-safety-files/{case.study_id}/{attachment_id}/{filename}"
        # Write bytes before persisting metadata: a storage failure therefore
        # leaves no metadata row and no partial reference (Requirement 15.7).
        try:
            await self._storage.put(storage_key, content, content_type)
        except Exception as exc:
            logger.warning(
                "Safety_Attachment upload failed: object storage unavailable case=%s",
                case_id,
            )
            raise ServiceUnavailableError(
                message="Object storage is unavailable for the Safety_Attachment upload",
                details={"reason": "OBJECT_STORAGE_UNAVAILABLE"},
            ) from exc

        attachment = FileAttachment(
            id=attachment_id,
            module=_PV_MODULE,
            attachment_type=_SAFETY_ATTACHMENT_TYPE,
            object_type=_SAFETY_OBJECT_TYPE,
            object_id=case.id,
            study_id=case.study_id,
            site_id=case.site_id,
            subject_id=case.subject_reference,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            storage_key=storage_key,
            uploaded_by=actor.user_id,
            correlation_id=actor.correlation_id,
        )
        session.add(attachment)
        await session.flush()

        await self._integration.record_attachment_action(
            session,
            attachment_id=attachment.id,
            action="upload",
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            case_id=case.id,
        )
        logger.info(
            "Safety_Attachment uploaded: id=%s case=%s actor=%s",
            attachment.id,
            case.id,
            actor.user_id,
        )
        return attachment

    # ------------------------------------------------------------------
    # Download (Requirements 15.2, 15.4)
    # ------------------------------------------------------------------

    async def download(
        self,
        session: AsyncSession,
        *,
        attachment_id: UUID,
        actor: ActorContext,
        user: Any | None = None,
    ) -> bytes:
        """Return attachment bytes only with read access to the parent case.

        Access is granted only when the caller has read access to the parent
        Safety_Case; otherwise the request is rejected without revealing file
        content (Requirement 15.2). A soft-deleted attachment is not downloadable
        through normal access (Requirement 15.3). A completed download records
        one PV safety Audit_Event (Requirement 15.4).
        """

        attachment = await self._require_pv_attachment(session, attachment_id)
        if attachment.deleted_at is not None:
            raise NotFoundError(
                message="Safety_Attachment is not available",
                details={"reason": "ATTACHMENT_DELETED", "attachment_id": str(attachment_id)},
            )

        case = await self._require_case(session, attachment.object_id)
        if user is not None:
            self._permission_service.require(
                user,
                _READ_PERMISSION,
                study_id=case.study_id,
                site_id=case.site_id,
            )
            self._permission_service.assert_object_access(user, case)

        try:
            content = await self._storage.get(attachment.storage_key)
        except FileNotFoundError as exc:
            raise NotFoundError(
                message="Safety_Attachment content is not available",
                details={"reason": "CONTENT_NOT_FOUND", "attachment_id": str(attachment_id)},
            ) from exc

        await self._integration.record_attachment_action(
            session,
            attachment_id=attachment.id,
            action="download",
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            case_id=case.id,
        )
        logger.info(
            "Safety_Attachment downloaded: id=%s case=%s actor=%s",
            attachment.id,
            case.id,
            actor.user_id,
        )
        return content

    # ------------------------------------------------------------------
    # Soft deletion (Requirements 15.3, 15.4)
    # ------------------------------------------------------------------

    async def soft_delete(
        self,
        session: AsyncSession,
        *,
        attachment_id: UUID,
        reason: str,
        actor: ActorContext,
        user: Any | None = None,
    ) -> FileAttachment:
        """Soft-delete a Safety_Attachment, retaining metadata and the reason.

        Soft_Deletion retains the metadata row and the deletion reason and
        prevents subsequent downloads through normal attachment access; the
        stored object bytes are retained for audit/retention. A completed
        deletion records one PV safety Audit_Event (Requirements 15.3, 15.4).
        """

        cleaned_reason = reason.strip() if isinstance(reason, str) else ""
        if not cleaned_reason:
            raise ValidationError(
                message="A deletion reason is required for a Safety_Attachment",
                details={"reason": "MISSING_DELETE_REASON", "attachment_id": str(attachment_id)},
            )

        attachment = await self._require_pv_attachment(session, attachment_id)
        if attachment.deleted_at is not None:
            raise ConflictError(
                message="Safety_Attachment is already deleted",
                details={"reason": "ALREADY_DELETED", "attachment_id": str(attachment_id)},
            )

        case = await self._require_case(session, attachment.object_id)
        if user is not None:
            self._permission_service.require(
                user,
                _DELETE_PERMISSION,
                study_id=case.study_id,
                site_id=case.site_id,
            )
            self._permission_service.assert_object_access(user, case)

        attachment.deleted_at = utc_now()
        attachment.deleted_by = actor.user_id
        attachment.delete_reason = cleaned_reason
        attachment.retention_state = "soft_deleted"
        session.add(attachment)
        await session.flush()

        await self._integration.record_attachment_action(
            session,
            attachment_id=attachment.id,
            action="delete",
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            case_id=case.id,
            reason=cleaned_reason,
        )
        logger.info(
            "Safety_Attachment soft-deleted: id=%s case=%s actor=%s",
            attachment.id,
            case.id,
            actor.user_id,
        )
        return attachment

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _require_case(self, session: AsyncSession, case_id: UUID) -> SafetyCase:
        statement = select(SafetyCase).where(
            SafetyCase.id == case_id, SafetyCase.deleted_at.is_(None)
        )
        result = await session.execute(statement)
        case = result.scalar_one_or_none()
        if case is None:
            raise NotFoundError(
                message="Parent Safety_Case was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_case"},
            )
        return case

    async def _require_open_case(self, session: AsyncSession, case_id: UUID) -> SafetyCase:
        case = await self._require_case(session, case_id)
        if case.lifecycle_state == CaseState.CLOSED.value:
            # While the parent Safety_Case is Closed, reject new uploads and
            # preserve existing attachment state (Requirement 15.5).
            raise ConflictError(
                message="New Safety_Attachment uploads are rejected while the case is Closed",
                details={"reason": "CASE_CLOSED", "case_id": str(case_id)},
            )
        return case

    async def _require_pv_attachment(
        self, session: AsyncSession, attachment_id: UUID
    ) -> FileAttachment:
        statement = select(FileAttachment).where(FileAttachment.id == attachment_id)
        result = await session.execute(statement)
        attachment = result.scalar_one_or_none()
        if attachment is None:
            raise NotFoundError(
                message="Safety_Attachment was not found",
                details={"reason": "RECORD_NOT_FOUND", "attachment_id": str(attachment_id)},
            )
        # A PV operation must not target an EDC Clinical_Attachment or CTMS
        # Operational_Attachment; reject without changing that module's state
        # (Requirement 15.6).
        if (
            attachment.module != _PV_MODULE
            or attachment.attachment_type != _SAFETY_ATTACHMENT_TYPE
        ):
            raise ConflictError(
                message="Attachment is not owned by the PV_Safety_Module",
                details={
                    "reason": "NON_PV_ATTACHMENT",
                    "module": attachment.module,
                    "attachment_type": attachment.attachment_type,
                },
            )
        return attachment


safety_attachment_service = SafetyAttachmentService()

__all__ = ["SafetyAttachmentService", "safety_attachment_service"]
