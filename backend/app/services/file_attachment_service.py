"""File_Attachment_Service — audited file storage linked to clinical objects.

File bytes are kept behind the object-storage abstraction in
``app.core.storage``.  The database row is the retained source of metadata and
soft-delete state.  The service never commits: metadata and Audit_Events use
the caller's transaction, matching the rest of the service layer.

Satisfies Requirements 27.1-27.5 and 18.4.
"""

from __future__ import annotations

import inspect
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.config import get_settings
from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.request_context import get_correlation_id
from app.core.storage import ObjectStorage, get_object_storage
from app.models.file_attachment import (
    FileAttachment,
    FileAttachmentModule,
    FileAttachmentObjectType,
)
from app.models.form_data import FieldValue, FormInstance
from app.models.form_metadata import FieldDefinition
from app.models.site import Site
from app.models.study import Study, StudyVersion
from app.models.subject import Subject
from app.models.visit import VisitInstance
from app.services.lock_service import LockService, lock_service
from app.services.permission_service import PermissionService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParentContext:
    """Normalized parent reference and denormalized authorization scope."""

    object_type: FileAttachmentObjectType
    object_id: UUID
    study_id: UUID
    site_id: UUID | None
    subject_id: UUID | None
    parent: Any


class FileAttachmentService:
    """Store and audit attachments for supported clinical object types."""

    _READ_PERMISSIONS: ClassVar[dict[FileAttachmentObjectType, str]] = {
        FileAttachmentObjectType.field: "form.read",
        FileAttachmentObjectType.form: "form.read",
        FileAttachmentObjectType.visit: "subject.read",
        FileAttachmentObjectType.subject: "subject.read",
        FileAttachmentObjectType.site: "site.read",
        FileAttachmentObjectType.study: "study.read",
    }
    _OPERATIONAL_PARENT_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "operational",
            "operational_study",
            "operational_site",
            "study_plan",
            "enrollment_target",
            "milestone",
            "activation_action",
            "monitoring_plan",
            "monitoring_activity",
            "task",
            "contact",
            "operational_task",
            "operational_contact",
        }
    )
    _CLINICAL_PARENT_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "field",
            "form",
            "visit",
            "subject",
            "site",
            "study",
            "query",
            "clinical_attachment",
            "clinical_export",
        }
    )
    _OPERATIONAL_WRITE_PERMISSIONS: ClassVar[dict[str, str]] = {
        "operational_study": "ctms.operational-study-management",
        "study_plan": "ctms.operational-study-management",
        "operational_site": "ctms.operational-site-management",
        "activation_action": "ctms.operational-site-management",
        "monitoring_plan": "ctms.monitoring-activity-management",
        "monitoring_activity": "ctms.monitoring-activity-management",
        "enrollment_target": "ctms.enrollment-management",
        "milestone": "ctms.enrollment-management",
        "task": "ctms.operational-study-management",
        "operational_task": "ctms.operational-study-management",
        "contact": "ctms.operational-study-management",
        "operational_contact": "ctms.operational-study-management",
        "operational": "ctms.operational-study-management",
    }

    def __init__(
        self,
        storage: ObjectStorage | None = None,
        permission_service: PermissionService | None = None,
        lock_service_instance: LockService | None = None,
    ) -> None:
        self.storage = storage or get_object_storage()
        self.permission_service = permission_service or PermissionService()
        self.lock_service = lock_service_instance or lock_service

    async def upload(
        self,
        session: AsyncSession,
        parent: Any,
        file: Any,
        actor_id: UUID,
        *,
        user: Any | None = None,
        object_type: FileAttachmentObjectType | str | None = None,
        object_id: UUID | None = None,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        subject_id: UUID | None = None,
    ) -> FileAttachment:
        """Upload bytes, persist metadata, and record an ``upload`` audit event.

        ``parent`` may be a loaded clinical model or an ID paired with
        ``object_type``.  ``file`` may be raw bytes, a synchronous file-like
        object, or FastAPI's async ``UploadFile``.
        """
        context = await self._resolve_parent(
            session,
            parent,
            object_type=object_type,
            object_id=object_id,
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
        )
        if user is not None:
            self.permission_service.require(
                user,
                "file.upload",
                study_id=context.study_id,
                site_id=context.site_id,
            )

        blocked = await self.lock_service.is_modification_blocked(
            session,
            context.parent,
            object_type=context.object_type.value,
            object_id=context.object_id,
        )
        if blocked:
            raise ConflictError(
                message="The parent clinical object is frozen or locked",
                details={
                    "code": "OBJECT_LOCKED",
                    "object_type": context.object_type.value,
                    "object_id": str(context.object_id),
                },
            )

        content, filename, content_type = await self._read_file(file)
        max_size = get_settings().max_attachment_size_bytes
        if len(content) > max_size:
            raise ValidationError(
                message="Attachment exceeds the configured size limit",
                details={"size_bytes": len(content), "max_size_bytes": max_size},
            )

        attachment_id = uuid.uuid4()
        storage_key = f"files/{context.study_id}/{attachment_id}/{filename}"
        # The object is written before the metadata row so a storage failure
        # cannot leave a committed attachment row without file bytes.  The
        # caller's transaction still controls the metadata/audit commit.
        await self.storage.put(storage_key, content, content_type)

        attachment = FileAttachment(
            id=attachment_id,
            object_type=context.object_type.value,
            object_id=context.object_id,
            study_id=context.study_id,
            site_id=context.site_id,
            subject_id=context.subject_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            storage_key=storage_key,
            uploaded_by=actor_id,
            uploaded_at=datetime.now(UTC),
        )
        session.add(attachment)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="file_attachment",
            entity_id=attachment.id,
            action="upload",
            study_id=attachment.study_id,
            site_id=attachment.site_id,
            subject_id=attachment.subject_id,
            actor_id=actor_id,
            new_value=(
                f"object_type={attachment.object_type}, object_id={attachment.object_id}, "
                f"filename={attachment.filename}, size_bytes={attachment.size_bytes}, "
                f"storage_key={attachment.storage_key}"
            ),
        )
        logger.info(
            "File attachment uploaded: id=%s parent=%s:%s actor=%s",
            attachment.id,
            attachment.object_type,
            attachment.object_id,
            actor_id,
        )
        return attachment

    async def upload_operational(
        self,
        session: AsyncSession,
        *,
        parent_type: str,
        parent_id: UUID,
        study_id: UUID,
        file: Any,
        actor_id: UUID,
        site_id: UUID | None = None,
        user: Any | None = None,
        retention_until: datetime | None = None,
        correlation_id: str | None = None,
    ) -> FileAttachment:
        """Upload a CTMS-owned attachment using the shared object store.

        The parent is an operational CTMS reference, never an EDC object. The
        metadata row is written in the caller's transaction together with its
        CTMS audit event; object bytes are namespaced by generated UUID and a
        safe extension so user-controlled filenames cannot escape the store.
        """
        normalized_parent = self._normalize_operational_parent_type(parent_type)
        if retention_until is not None:
            retention_until = self._ensure_utc_retention(retention_until)
        if correlation_id is None:
            correlation_id = get_correlation_id()

        if user is not None:
            self.permission_service.require(
                user,
                self._OPERATIONAL_WRITE_PERMISSIONS[normalized_parent],
                study_id=study_id,
                site_id=site_id,
            )

        content, filename, content_type = await self._read_file(file)
        self._validate_operational_file(content, content_type)
        attachment_id = uuid.uuid4()
        # Do not put the submitted name in the key. The UUID namespace and a
        # short validated extension make traversal and key injection impossible.
        extension = self._safe_extension(filename)
        storage_key = f"ctms-files/{study_id}/{attachment_id}{extension}"
        await self.storage.put(storage_key, content, content_type)
        attachment = FileAttachment(
            id=attachment_id,
            module=FileAttachmentModule.CTMS.value,
            attachment_type="Operational_Attachment",
            object_type=FileAttachmentObjectType.operational.value,
            object_id=parent_id,
            study_id=study_id,
            site_id=site_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            storage_key=storage_key,
            uploaded_by=actor_id,
            uploaded_at=datetime.now(UTC),
            correlation_id=correlation_id,
            retention_until=retention_until,
        )
        session.add(attachment)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="operational_attachment",
            entity_id=attachment.id,
            action="upload",
            module=Module.CTMS,
            actor_id=actor_id,
            correlation_id=correlation_id,
            scope={"study_id": study_id, "site_id": site_id},
            changed_fields=["storage_key", "retention_until", "correlation_id"],
            study_id=study_id,
            site_id=site_id,
            new_value=(
                "attachment_type=Operational_Attachment, "
                f"parent_type={normalized_parent}, size_bytes={len(content)}"
            ),
        )
        return attachment

    @classmethod
    def _normalize_operational_parent_type(cls, parent_type: str) -> str:
        normalized = str(parent_type).strip().replace("-", "_").lower()
        if normalized in cls._CLINICAL_PARENT_TYPES or normalized not in cls._OPERATIONAL_PARENT_TYPES:
            raise ValidationError(
                message="Operational attachments require a CTMS-owned parent",
                details={"parent_type": normalized},
            )
        return normalized

    @staticmethod
    def _ensure_utc_retention(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValidationError(
                message="Attachment retention timestamp must include a timezone",
                details={},
            )
        return value.astimezone(UTC)

    @staticmethod
    def _safe_extension(filename: str) -> str:
        suffix = filename.rsplit(".", 1)[-1] if "." in filename else ""
        suffix = re.sub(r"[^a-zA-Z0-9]", "", suffix.lower())
        return f".{suffix}" if suffix else ""

    @classmethod
    def _validate_operational_file(cls, content: bytes, content_type: str) -> None:
        settings = get_settings()
        if len(content) > settings.max_attachment_size_bytes:
            raise ValidationError(
                message="Attachment exceeds the configured size limit",
                details={
                    "size_bytes": len(content),
                    "max_size_bytes": settings.max_attachment_size_bytes,
                },
            )
        normalized_type = content_type.split(";", 1)[0].strip().lower()
        allowed = {
            item.strip().lower()
            for item in settings.operational_attachment_allowed_mime_types.split(",")
            if item.strip()
        }
        if not normalized_type or normalized_type not in allowed:
            raise ValidationError(
                message="Attachment MIME type is not permitted for CTMS operational content",
                details={"content_type": normalized_type, "allowed_types": sorted(allowed)},
            )

    @staticmethod
    def _assert_attachment_ownership(attachment: FileAttachment) -> None:
        is_ctms = attachment.module == FileAttachmentModule.CTMS.value
        is_operational = attachment.attachment_type == "Operational_Attachment"
        if is_ctms != is_operational or (
            is_ctms and attachment.object_type != FileAttachmentObjectType.operational.value
        ):
            raise ConflictError(
                message="Attachment ownership metadata is invalid",
                details={"code": "ATTACHMENT_OWNERSHIP_INVALID"},
            )

    async def download(
        self,
        session: AsyncSession,
        attachment: FileAttachment | UUID,
        user: Any,
        *,
        correlation_id: str | None = None,
    ) -> bytes:
        """Return attachment bytes only when the parent is readable.

        Both the specific parent read permission and object scope are checked;
        a caller cannot download merely because it knows an attachment UUID.
        """
        attachment = await self._resolve_attachment(session, attachment)
        self._assert_attachment_ownership(attachment)
        if attachment.deleted_at is not None or attachment.archived_at is not None:
            raise NotFoundError(
                message="File attachment not found",
                details={"attachment_id": str(attachment.id)},
            )

        object_type = FileAttachmentObjectType(attachment.object_type)
        if attachment.module == FileAttachmentModule.CTMS.value:
            permission = "ctms.operational-data-read"
        else:
            permission = self._READ_PERMISSIONS[object_type]
        self.permission_service.require(
            user,
            permission,
            study_id=attachment.study_id,
            site_id=attachment.site_id,
        )
        self.permission_service.assert_object_access(user, attachment)

        try:
            content = await self.storage.get(attachment.storage_key)
        except FileNotFoundError as exc:
            raise NotFoundError(
                message="Attachment content not found",
                details={"attachment_id": str(attachment.id)},
            ) from exc

        await audit_service.record(
            session,
            entity_type=(
                "operational_attachment"
                if attachment.module == FileAttachmentModule.CTMS.value
                else "file_attachment"
            ),
            entity_id=attachment.id,
            action="download",
            module=attachment.module,
            actor_id=getattr(user, "id", None),
            correlation_id=correlation_id or getattr(user, "correlation_id", None) or get_correlation_id(),
            scope={"study_id": attachment.study_id, "site_id": attachment.site_id},
            changed_fields=[],
            study_id=attachment.study_id,
            site_id=attachment.site_id,
            subject_id=attachment.subject_id,
            new_value=f"storage_key={attachment.storage_key}",
        )
        logger.info(
            "File attachment downloaded: id=%s actor=%s",
            attachment.id,
            getattr(user, "id", None),
        )
        return content

    async def soft_delete(
        self,
        session: AsyncSession,
        attachment: FileAttachment | UUID,
        reason: str,
        actor_id: UUID,
        *,
        user: Any | None = None,
        correlation_id: str | None = None,
    ) -> FileAttachment:
        """Soft-delete metadata while retaining the row and stored object."""
        attachment = await self._resolve_attachment(session, attachment)
        self._assert_attachment_ownership(attachment)
        if not reason or not reason.strip():
            raise ValidationError(
                message="A deletion reason is required",
                details={"attachment_id": str(attachment.id)},
            )
        if attachment.deleted_at is not None:
            raise ConflictError(
                message="File attachment is already deleted",
                details={"attachment_id": str(attachment.id)},
            )
        if user is not None:
            permission = (
                "ctms.operational-study-management"
                if attachment.module == FileAttachmentModule.CTMS.value
                else "file.upload"
            )
            self.permission_service.require(
                user,
                permission,
                study_id=attachment.study_id,
                site_id=attachment.site_id,
            )
            self.permission_service.assert_object_access(user, attachment)

        deleted_at = datetime.now(UTC)
        attachment.deleted_at = deleted_at
        attachment.deleted_by = actor_id
        attachment.delete_reason = reason.strip()
        attachment.retention_state = "soft_deleted"
        await session.flush()
        await audit_service.record(
            session,
            entity_type=(
                "operational_attachment"
                if attachment.module == FileAttachmentModule.CTMS.value
                else "file_attachment"
            ),
            entity_id=attachment.id,
            action="delete",
            module=attachment.module,
            correlation_id=correlation_id or getattr(user, "correlation_id", None) or get_correlation_id(),
            scope={"study_id": attachment.study_id, "site_id": attachment.site_id},
            changed_fields=["deleted_at", "deleted_by", "delete_reason"],
            study_id=attachment.study_id,
            site_id=attachment.site_id,
            subject_id=attachment.subject_id,
            actor_id=actor_id,
            reason=attachment.delete_reason,
            old_value="deleted_at=None",
            new_value=(
                f"deleted_at={deleted_at.isoformat()}, deleted_by={actor_id}, "
                f"delete_reason={attachment.delete_reason}"
            ),
        )
        logger.info(
            "File attachment soft-deleted: id=%s actor=%s reason=%s",
            attachment.id,
            actor_id,
            attachment.delete_reason,
        )
        return attachment

    async def restore(
        self,
        session: AsyncSession,
        attachment: FileAttachment | UUID,
        actor_id: UUID,
        *,
        reason: str | None = None,
        user: Any | None = None,
        correlation_id: str | None = None,
    ) -> FileAttachment:
        """Restore retained metadata without changing content ownership."""
        attachment = await self._resolve_attachment(session, attachment)
        self._assert_attachment_ownership(attachment)
        if attachment.deleted_at is None and attachment.archived_at is None:
            raise ConflictError(
                message="File attachment is not deleted or archived",
                details={"attachment_id": str(attachment.id)},
            )
        if reason is None or not reason.strip():
            raise ValidationError(
                message="A restore reason is required",
                details={"attachment_id": str(attachment.id)},
            )
        if user is not None:
            permission = (
                "ctms.operational-study-management"
                if attachment.module == FileAttachmentModule.CTMS.value
                else "file.upload"
            )
            self.permission_service.require(
                user, permission, study_id=attachment.study_id, site_id=attachment.site_id
            )
            self.permission_service.assert_object_access(user, attachment)
        attachment.deleted_at = None
        attachment.deleted_by = None
        attachment.delete_reason = None
        attachment.archived_at = None
        attachment.archived_by = None
        attachment.archive_reason = None
        attachment.retention_state = "active"
        attachment.restored_at = datetime.now(UTC)
        attachment.restored_by = actor_id
        await session.flush()
        await audit_service.record(
            session,
            entity_type=(
                "operational_attachment"
                if attachment.module == FileAttachmentModule.CTMS.value
                else "file_attachment"
            ),
            entity_id=attachment.id,
            action="restore",
            module=attachment.module,
            actor_id=actor_id,
            correlation_id=correlation_id or get_correlation_id(),
            scope={"study_id": attachment.study_id, "site_id": attachment.site_id},
            changed_fields=["deleted_at", "deleted_by", "delete_reason", "restored_at", "restored_by", "retention_state"],
            study_id=attachment.study_id,
            site_id=attachment.site_id,
            reason=reason.strip(),
        )
        return attachment

    async def archive(
        self,
        session: AsyncSession,
        attachment: FileAttachment | UUID,
        reason: str,
        actor_id: UUID,
        *,
        user: Any | None = None,
        correlation_id: str | None = None,
        now: datetime | None = None,
    ) -> FileAttachment:
        """Mark an attachment archived after its configured retention point."""
        attachment = await self._resolve_attachment(session, attachment)
        self._assert_attachment_ownership(attachment)
        if not reason or not reason.strip():
            raise ValidationError(message="An archive reason is required", details={})
        current_time = self._ensure_utc_retention(now or datetime.now(UTC))
        if attachment.retention_until and current_time < attachment.retention_until:
            raise ConflictError(
                message="Attachment retention period has not elapsed",
                details={"retention_until": attachment.retention_until.isoformat()},
            )
        if attachment.archived_at is not None:
            raise ConflictError(message="File attachment is already archived", details={})
        if user is not None:
            permission = (
                "ctms.operational-study-management"
                if attachment.module == FileAttachmentModule.CTMS.value
                else "file.upload"
            )
            self.permission_service.require(user, permission, study_id=attachment.study_id, site_id=attachment.site_id)
            self.permission_service.assert_object_access(user, attachment)
        attachment.archived_at = current_time
        attachment.archived_by = actor_id
        attachment.archive_reason = reason.strip()
        attachment.retention_state = "archived"
        await session.flush()
        await audit_service.record(
            session,
            entity_type="operational_attachment" if attachment.module == FileAttachmentModule.CTMS.value else "file_attachment",
            entity_id=attachment.id,
            action="archive",
            module=attachment.module,
            actor_id=actor_id,
            correlation_id=correlation_id or get_correlation_id(),
            scope={"study_id": attachment.study_id, "site_id": attachment.site_id},
            changed_fields=["archived_at", "archived_by", "archive_reason"],
            study_id=attachment.study_id,
            site_id=attachment.site_id,
            reason=attachment.archive_reason,
        )
        return attachment

    async def purge(
        self,
        session: AsyncSession,
        attachment: FileAttachment | UUID,
        actor_id: UUID,
        *,
        user: Any | None = None,
        correlation_id: str | None = None,
        now: datetime | None = None,
    ) -> FileAttachment:
        """Physically remove bytes only after archive and retention checks.

        Metadata is intentionally retained for audit/traceability; this method
        only removes the object-store content after authorization and policy
        validation, and therefore cannot cascade into EDC clinical records.
        """
        attachment = await self._resolve_attachment(session, attachment)
        self._assert_attachment_ownership(attachment)
        current_time = self._ensure_utc_retention(now or datetime.now(UTC))
        if attachment.archived_at is None:
            raise ConflictError(message="Attachment must be archived before purge", details={})
        if attachment.retention_until and current_time < attachment.retention_until:
            raise ConflictError(
                message="Attachment retention period has not elapsed",
                details={"retention_until": attachment.retention_until.isoformat()},
            )
        if user is not None:
            permission = (
                "ctms.operational-study-management"
                if attachment.module == FileAttachmentModule.CTMS.value
                else "file.upload"
            )
            self.permission_service.require(user, permission, study_id=attachment.study_id, site_id=attachment.site_id)
            self.permission_service.assert_object_access(user, attachment)
        await self.storage.delete(attachment.storage_key)
        await audit_service.record(
            session,
            entity_type="operational_attachment" if attachment.module == FileAttachmentModule.CTMS.value else "file_attachment",
            entity_id=attachment.id,
            action="purge",
            module=attachment.module,
            actor_id=actor_id,
            correlation_id=correlation_id or get_correlation_id(),
            scope={"study_id": attachment.study_id, "site_id": attachment.site_id},
            changed_fields=["storage_key"],
            study_id=attachment.study_id,
            site_id=attachment.site_id,
        )
        return attachment

    async def _resolve_attachment(
        self, session: AsyncSession, attachment: FileAttachment | UUID
    ) -> FileAttachment:
        if isinstance(attachment, UUID):
            result = await session.execute(
                select(FileAttachment).where(FileAttachment.id == attachment)
            )
            resolved = result.scalars().first()
        else:
            resolved = attachment
        if resolved is None:
            raise NotFoundError(
                message="File attachment not found",
                details={"attachment_id": str(attachment)},
            )
        return resolved

    async def _resolve_parent(
        self,
        session: AsyncSession,
        parent: Any,
        *,
        object_type: FileAttachmentObjectType | str | None,
        object_id: UUID | None,
        study_id: UUID | None,
        site_id: UUID | None,
        subject_id: UUID | None,
    ) -> _ParentContext:
        normalized_type = self._normalize_object_type(parent, object_type)
        resolved_parent = parent
        resolved_id = object_id or (
            parent if isinstance(parent, UUID) else getattr(parent, "id", None)
        )
        if resolved_parent is None or isinstance(resolved_parent, UUID):
            if resolved_id is None:
                raise ValidationError(
                    message="A parent object id is required",
                    details={"object_type": normalized_type.value},
                )
            model = self._model_for_type(normalized_type)
            result = await session.execute(select(model).where(model.id == resolved_id))
            resolved_parent = result.scalars().first()
            if resolved_parent is None:
                raise NotFoundError(
                    message="Parent clinical object not found",
                    details={
                        "object_type": normalized_type.value,
                        "object_id": str(resolved_id),
                    },
                )
        if resolved_id is None:
            raise ValidationError(
                message="A parent object id is required",
                details={"object_type": normalized_type.value},
            )

        derived_study, derived_site, derived_subject = await self._derive_scope(
            session, normalized_type, resolved_parent
        )
        final_study = study_id or derived_study
        if normalized_type is FileAttachmentObjectType.study and final_study is None:
            final_study = UUID(str(resolved_id))
        if final_study is None:
            raise ValidationError(
                message="Parent object is not linked to a study",
                details={"object_type": normalized_type.value},
            )
        return _ParentContext(
            object_type=normalized_type,
            object_id=UUID(str(resolved_id)),
            study_id=UUID(str(final_study)),
            site_id=site_id or derived_site,
            subject_id=subject_id or derived_subject,
            parent=resolved_parent,
        )

    async def _derive_scope(
        self,
        session: AsyncSession,
        object_type: FileAttachmentObjectType,
        parent: Any,
    ) -> tuple[UUID | None, UUID | None, UUID | None]:
        direct_study = getattr(parent, "study_id", None)
        direct_site = getattr(parent, "site_id", None)
        direct_subject = getattr(parent, "subject_id", None)
        if object_type is FileAttachmentObjectType.study:
            return UUID(str(parent.id)), None, None
        if (
            object_type
            in {
                FileAttachmentObjectType.site,
                FileAttachmentObjectType.subject,
            }
            and direct_study is not None
        ):
            return (
                UUID(str(direct_study)),
                UUID(str(direct_site)) if direct_site else None,
                UUID(str(direct_subject)) if direct_subject else None,
            )
        if object_type is FileAttachmentObjectType.visit:
            subject = getattr(parent, "subject", None)
            if subject is None and direct_subject is not None:
                subject = await self._load_by_id(session, Subject, direct_subject)
            return self._scope_from_subject(subject)
        if object_type is FileAttachmentObjectType.form:
            subject = getattr(parent, "subject", None)
            if subject is None and direct_subject is not None:
                subject = await self._load_by_id(session, Subject, direct_subject)
            if subject is not None:
                return self._scope_from_subject(subject)
            definition = getattr(parent, "form_definition", None)
            if definition is not None:
                version = getattr(definition, "study_version", None)
                if version is None and getattr(definition, "study_version_id", None):
                    version = await self._load_by_id(
                        session, StudyVersion, definition.study_version_id
                    )
                if version is not None:
                    return UUID(str(version.study_id)), None, None
        if object_type is FileAttachmentObjectType.field:
            if isinstance(parent, FieldValue):
                form = getattr(parent, "form_instance", None)
                if form is None:
                    form = await self._load_by_id(session, FormInstance, parent.form_instance_id)
                if form is not None:
                    subject = getattr(form, "subject", None)
                    if subject is None:
                        subject = await self._load_by_id(session, Subject, form.subject_id)
                    return self._scope_from_subject(subject)
            section = getattr(parent, "form_section", None)
            if section is not None:
                definition = getattr(section, "form_definition", None)
                if definition is not None:
                    version = getattr(definition, "study_version", None)
                    if version is None:
                        version = await self._load_by_id(
                            session, StudyVersion, definition.study_version_id
                        )
                    if version is not None:
                        return UUID(str(version.study_id)), None, None
        return (
            UUID(str(direct_study)) if direct_study else None,
            UUID(str(direct_site)) if direct_site else None,
            UUID(str(direct_subject)) if direct_subject else None,
        )

    @staticmethod
    def _scope_from_subject(subject: Any) -> tuple[UUID, UUID, UUID]:
        if subject is None or not getattr(subject, "study_id", None):
            raise ValidationError(
                message="Parent clinical object is not linked to a subject and study",
                details={},
            )
        return (
            UUID(str(subject.study_id)),
            UUID(str(subject.site_id)),
            UUID(str(subject.id)),
        )

    @staticmethod
    async def _load_by_id(session: AsyncSession, model: Any, entity_id: UUID) -> Any | None:
        result = await session.execute(select(model).where(model.id == entity_id))
        return result.scalars().first()

    @staticmethod
    def _model_for_type(object_type: FileAttachmentObjectType) -> Any:
        return {
            FileAttachmentObjectType.field: FieldDefinition,
            FileAttachmentObjectType.form: FormInstance,
            FileAttachmentObjectType.visit: VisitInstance,
            FileAttachmentObjectType.subject: Subject,
            FileAttachmentObjectType.site: Site,
            FileAttachmentObjectType.study: Study,
        }[object_type]

    @staticmethod
    def _normalize_object_type(
        parent: Any, object_type: FileAttachmentObjectType | str | None
    ) -> FileAttachmentObjectType:
        value = (
            object_type.value if isinstance(object_type, FileAttachmentObjectType) else object_type
        )
        if value is None:
            value = {
                "FieldDefinition": "field",
                "FieldValue": "field",
                "FormInstance": "form",
                "FormDefinition": "form",
                "VisitInstance": "visit",
                "Subject": "subject",
                "Site": "site",
                "Study": "study",
            }.get(parent.__class__.__name__)
        try:
            return FileAttachmentObjectType(str(value))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                message="Invalid attachment parent object type",
                details={"object_type": value},
            ) from exc

    @staticmethod
    async def _read_file(file: Any) -> tuple[bytes, str, str]:
        filename = getattr(file, "filename", None) or getattr(file, "name", None)
        content_type = getattr(file, "content_type", None) or "application/octet-stream"
        if isinstance(file, (bytes, bytearray, memoryview)):
            content = bytes(file)
        elif hasattr(file, "read"):
            content = file.read()
            if inspect.isawaitable(content):
                content = await content
            content = bytes(content)
        else:
            raise ValidationError(
                message="Attachment content must be bytes or a readable file",
                details={"value_type": type(file).__name__},
            )
        safe_filename = unicodedata.normalize("NFKC", str(filename or "attachment"))
        safe_filename = re.sub(r"[\x00-\x1f\x7f]", "", safe_filename)
        safe_filename = safe_filename.replace("/", "_").replace("\\", "_").strip()
        if not safe_filename or safe_filename in {".", ".."}:
            raise ValidationError(message="Attachment filename is required", details={})
        if len(safe_filename) > 255:
            raise ValidationError(
                message="Attachment filename is too long",
                details={"max_length": 255},
            )
        normalized_content_type = str(content_type).split(";", 1)[0].strip().lower()
        return content, safe_filename, normalized_content_type


file_attachment_service = FileAttachmentService()
