"""Repeating_Record_Service — repeating form row lifecycle management.

The service keeps row mutations and their Audit_Events in the caller's
transaction. Sequence allocation locks the owning FormInstance before reading
the current maximum, so concurrent additions to the same repeating form cannot
reuse a sequence number on PostgreSQL.

Satisfies Requirements:
  - 11.1: Add rows with monotonically increasing sequence numbers.
  - 11.2: Edit rows and write an Audit_Event.
  - 11.3: Soft-delete rows while retaining actor, timestamp, and reason.
  - 11.4: Restore soft-deleted rows and write an Audit_Event.
  - 21.4/23.3: Data and audit writes use the caller's transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, ConflictError, ValidationError
from app.models.form_data import FormInstance
from app.models.form_record import FormRecord

logger = logging.getLogger(__name__)


class RepeatingRecordService:
    """Manage Form_Record rows for repeating Form_Instances."""

    async def add_record(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        values: Mapping[str, Any] | UUID | None = None,
        actor_id: UUID | None = None,
    ) -> FormRecord:
        """Create a row with the next sequence number for a form instance.

        ``values`` is optional because a newly added repeating row may start
        empty.  For compatibility with callers that only provide an actor,
        the third positional argument may be the actor UUID.

        The owning FormInstance is locked before calculating the maximum.  The
        lock is intentionally held by the caller's transaction; this service
        never commits.
        """
        if isinstance(values, UUID) and actor_id is None:
            actor_id = values
            values = None

        # Serialize additions for this form instance.  PostgreSQL's row lock
        # prevents two transactions from observing the same current maximum.
        await session.execute(
            select(FormInstance.id)
            .where(FormInstance.id == form_instance.id)
            .with_for_update()
        )
        max_result = await session.execute(
            select(func.max(FormRecord.sequence_number)).where(
                FormRecord.form_instance_id == form_instance.id
            )
        )
        current_max = max_result.scalar_one_or_none()
        sequence_number = (current_max or 0) + 1

        record = FormRecord(
            form_instance_id=form_instance.id,
            sequence_number=sequence_number,
            data_jsonb=dict(values) if values is not None else None,
            created_at=datetime.now(UTC),
        )
        session.add(record)
        await session.flush()

        study_id, site_id, subject_id = self._scope(form_instance)
        await audit_service.record(
            session,
            entity_type="form_record",
            entity_id=record.id,
            action="create",
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            actor_id=actor_id,
            new_value=f"sequence_number={record.sequence_number}, data={record.data_jsonb}",
        )

        logger.info(
            "Repeating record created: id=%s form_instance_id=%s sequence=%s actor=%s",
            record.id,
            record.form_instance_id,
            record.sequence_number,
            actor_id,
        )
        return record

    async def edit_record(
        self,
        session: AsyncSession,
        record: FormRecord,
        values: Mapping[str, Any],
        actor_id: UUID | None = None,
    ) -> FormRecord:
        """Replace a row's values and record the old and new payloads.

        Soft-deleted rows cannot be edited until they are restored.  The
        restriction prevents a hidden mutation of a retained deleted record.
        """
        self._require_values(values)
        self._guard_not_deleted(record)

        old_values = record.data_jsonb
        record.data_jsonb = dict(values)
        record.updated_at = datetime.now(UTC)
        await session.flush()

        form_instance = getattr(record, "form_instance", None)
        study_id, site_id, subject_id = self._scope(form_instance)
        await audit_service.record(
            session,
            entity_type="form_record",
            entity_id=record.id,
            action="update",
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            actor_id=actor_id,
            old_value=str(old_values) if old_values is not None else None,
            new_value=str(record.data_jsonb),
        )

        logger.info(
            "Repeating record updated: id=%s form_instance_id=%s actor=%s",
            record.id,
            record.form_instance_id,
            actor_id,
        )
        return record

    async def soft_delete(
        self,
        session: AsyncSession,
        record: FormRecord,
        reason: str,
        actor_id: UUID | None = None,
    ) -> FormRecord:
        """Soft-delete a row, retaining its data and deletion metadata."""
        if not reason or not reason.strip():
            raise ValidationError(
                message="A deletion reason is required",
                details={"record_id": str(record.id)},
            )
        if record.deleted_at is not None:
            raise ConflictError(
                message="Form record is already deleted",
                details={"record_id": str(record.id)},
            )

        deleted_at = datetime.now(UTC)
        record.deleted_at = deleted_at
        record.deleted_by = actor_id
        record.deletion_reason = reason
        record.updated_at = deleted_at
        await session.flush()

        form_instance = getattr(record, "form_instance", None)
        study_id, site_id, subject_id = self._scope(form_instance)
        await audit_service.record(
            session,
            entity_type="form_record",
            entity_id=record.id,
            action="delete",
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            actor_id=actor_id,
            reason=reason,
            old_value=(
                f"deleted_at=None, deleted_by=None, deletion_reason=None, "
                f"data={record.data_jsonb}"
            ),
            new_value=(
                f"deleted_at={record.deleted_at.isoformat()}, "
                f"deleted_by={record.deleted_by}, deletion_reason={reason}, "
                f"data={record.data_jsonb}"
            ),
        )

        logger.info(
            "Repeating record soft-deleted: id=%s form_instance_id=%s actor=%s reason=%s",
            record.id,
            record.form_instance_id,
            actor_id,
            reason,
        )
        return record

    async def restore(
        self,
        session: AsyncSession,
        record: FormRecord,
        actor_id: UUID | None = None,
    ) -> FormRecord:
        """Restore a soft-deleted row and clear all deletion metadata."""
        if record.deleted_at is None:
            raise ConflictError(
                message="Form record is not deleted",
                details={"record_id": str(record.id)},
            )

        old_deleted_at = record.deleted_at
        old_deleted_by = record.deleted_by
        old_reason = record.deletion_reason
        record.deleted_at = None
        record.deleted_by = None
        record.deletion_reason = None
        record.updated_at = datetime.now(UTC)
        await session.flush()

        form_instance = getattr(record, "form_instance", None)
        study_id, site_id, subject_id = self._scope(form_instance)
        await audit_service.record(
            session,
            entity_type="form_record",
            entity_id=record.id,
            action="restore",
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            actor_id=actor_id,
            old_value=(
                f"deleted_at={old_deleted_at.isoformat()}, "
                f"deleted_by={old_deleted_by}, deletion_reason={old_reason}"
            ),
            new_value="deleted_at=None, deleted_by=None, deletion_reason=None",
        )

        logger.info(
            "Repeating record restored: id=%s form_instance_id=%s actor=%s",
            record.id,
            record.form_instance_id,
            actor_id,
        )
        return record

    @staticmethod
    def _require_values(values: Mapping[str, Any]) -> None:
        """Reject non-mapping row payloads with a domain validation error."""
        if not isinstance(values, Mapping):
            raise ValidationError(
                message="Record values must be an object",
                details={"value_type": type(values).__name__},
            )

    @staticmethod
    def _guard_not_deleted(record: FormRecord) -> None:
        """Prevent edits while a row is in its soft-deleted state."""
        if record.deleted_at is not None:
            raise BusinessRuleError(
                message="Cannot edit a deleted form record; restore it first",
                details={"record_id": str(record.id)},
            )

    @staticmethod
    def _scope(
        form_instance: FormInstance | None,
    ) -> tuple[UUID | None, UUID | None, UUID | None]:
        """Extract audit scope when the related subject is already loaded."""
        if form_instance is None:
            return None, None, None
        subject = getattr(form_instance, "subject", None)
        return (
            getattr(subject, "study_id", None),
            getattr(subject, "site_id", None),
            getattr(form_instance, "subject_id", None),
        )


# Module-level singleton for consistency with the other services.
repeating_record_service = RepeatingRecordService()
