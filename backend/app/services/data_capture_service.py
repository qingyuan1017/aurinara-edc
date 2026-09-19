"""Data_Capture_Service — clinical data load, save, submit, change, and mark-NA.

Hybrid storage: every mutation keeps ``form_instances.data_jsonb`` (fast retrieval)
and normalized ``field_values`` rows (per-field audit/query/SDV/review/export)
consistent within the same database transaction.

Satisfies Requirements:
  - 10.1: save_draft persists Field_Values and sets status In Progress.
  - 10.3: submit validates required fields, data types, ranges, codelist,
           conditional rules; sets status Submitted on success.
  - 10.4: On validation failure, returns field-level errors and preserves
           previously entered values.
  - 10.5: Post-submission field changes require a Reason_For_Change.
  - 10.6: mark_not_applicable persists the not-applicable state.
  - 10.7: Rejects modifications when Form_Instance is Frozen or Locked.
  - 10.8: Every Field_Value create/change writes an Audit_Event in the same tx.
  - 21.4: Audit_Event is written in the same transaction as the data change.
  - 23.3: Mutation guards delegate hierarchy checks to Lock_Service.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.form_metadata import CodelistItem, FieldDefinition
from app.services.lock_service import lock_service
from app.services.notification_service import notification_service
from app.services.signature_service import signature_service

logger = logging.getLogger(__name__)

# Statuses that count as "post-submission" — changes require Reason_For_Change.
_POST_SUBMISSION_STATUSES = frozenset({
    FormInstanceStatus.submitted,
    FormInstanceStatus.reviewed,
    FormInstanceStatus.frozen,
    FormInstanceStatus.locked,
    FormInstanceStatus.signed,
})

# Statuses that block any modification (Req 10.7).
_LOCKED_STATUSES = frozenset({
    FormInstanceStatus.frozen,
    FormInstanceStatus.locked,
})


class DataCaptureService:
    """Manages clinical data capture lifecycle for Form_Instances."""

    # ------------------------------------------------------------------
    # load (design: return form instance with its field values)
    # ------------------------------------------------------------------

    async def load(
        self,
        session: AsyncSession,
        form_instance_id: UUID,
    ) -> FormInstance:
        """Load a Form_Instance with its field values.

        Args:
            session: Active async database session.
            form_instance_id: UUID of the form instance.

        Returns:
            The FormInstance (eagerly loaded with field_values via relationship).

        Raises:
            NotFoundError: If the form instance does not exist.
        """
        result = await session.execute(
            select(FormInstance).where(FormInstance.id == form_instance_id)
        )
        form_instance = result.scalars().first()
        if form_instance is None:
            raise NotFoundError(
                message="Form instance not found",
                details={"form_instance_id": str(form_instance_id)},
            )
        return form_instance

    # ------------------------------------------------------------------
    # save_draft (Req 10.1)
    # ------------------------------------------------------------------

    async def save_draft(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        values: dict[str, Any],
        actor_id: UUID,
    ) -> FormInstance:
        """Persist field values as a draft and set status to In Progress.

        Upserts each field value (creates new or updates existing), keeps
        data_jsonb consistent, and writes an Audit_Event for each changed
        field in the same transaction.

        Args:
            session: Active async database session (caller's transaction).
            form_instance: The FormInstance to save into.
            values: A dict mapping field_definition_id (str UUID) to the value.
            actor_id: UUID of the actor performing the save.

        Returns:
            The updated FormInstance.

        Raises:
            BusinessRuleError: If the form is Frozen or Locked (Req 10.7).
        """
        await self._guard_modification(session, form_instance)

        # Check each field target as well as the form so field-level controls
        # block writes even when the form itself remains editable.
        for field_id_str, new_value in values.items():
            field_id = UUID(field_id_str)
            await self._guard_modification(
                session, form_instance, field_id=field_id
            )
            await self._upsert_field_value(
                session,
                form_instance=form_instance,
                field_definition_id=field_id,
                new_value=new_value,
                actor_id=actor_id,
                reason=None,
            )

        # Update status to In Progress (Req 10.1)
        if form_instance.status == FormInstanceStatus.not_started:
            form_instance.status = FormInstanceStatus.in_progress

        # Sync data_jsonb from field_values (Req 23.3)
        await self._sync_data_jsonb(session, form_instance)
        await self._invalidate_signed_form(
            session, form_instance, actor_id=actor_id
        )

        form_instance.updated_at = datetime.now(UTC)
        await session.flush()

        logger.info(
            "Draft saved: form_instance_id=%s field_count=%d actor=%s",
            form_instance.id,
            len(values),
            actor_id,
        )
        return form_instance

    # ------------------------------------------------------------------
    # submit (Req 10.3, 10.4)
    # ------------------------------------------------------------------

    async def submit(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        actor_id: UUID,
    ) -> FormInstance:
        """Validate and submit a Form_Instance.

        Validates required fields, data types, ranges (min/max), codelist
        membership. On success sets status to Submitted. On failure returns
        field-level errors and preserves previously entered values (Req 10.4).

        Args:
            session: Active async database session.
            form_instance: The FormInstance to submit.
            actor_id: UUID of the actor.

        Returns:
            The updated FormInstance with status Submitted.

        Raises:
            ValidationError: With field-level errors if validation fails (Req 10.4).
            BusinessRuleError: If the form is Frozen or Locked.
        """
        await self._guard_modification(session, form_instance)

        # Only allow submission from In Progress or Not Started
        if form_instance.status not in (
            FormInstanceStatus.not_started,
            FormInstanceStatus.in_progress,
        ):
            raise BusinessRuleError(
                message=f"Cannot submit a form in '{form_instance.status}' status",
                details={"current_status": str(form_instance.status)},
            )

        # Get field definitions for this form
        field_definitions = await self._get_field_definitions(session, form_instance)

        # Build a lookup of current field values
        field_value_map = await self._get_field_value_map(session, form_instance)

        # Validate
        errors = await self._validate_submission(
            session, field_definitions, field_value_map
        )

        if errors:
            # Req 10.4: preserve values and return errors
            raise ValidationError(
                message="Submission validation failed",
                details={"field_errors": errors},
            )

        # Validation passed — set status to Submitted
        form_instance.status = FormInstanceStatus.submitted
        form_instance.submitted_at = datetime.now(UTC)
        form_instance.submitted_by = actor_id
        form_instance.updated_at = datetime.now(UTC)
        await session.flush()

        # Write Audit_Event for submission
        await audit_service.record(
            session,
            entity_type="form_instance",
            entity_id=form_instance.id,
            action="submit",
            study_id=None,
            site_id=None,
            subject_id=form_instance.subject_id,
            actor_id=actor_id,
            field_name="status",
            old_value=FormInstanceStatus.in_progress.value,
            new_value=FormInstanceStatus.submitted.value,
        )

        # Notify responsible reviewers only after the submitted state and its
        # audit event have been added to this same transaction.
        await notification_service.on_form_submitted(session, form_instance)

        logger.info(
            "Form submitted: form_instance_id=%s actor=%s",
            form_instance.id,
            actor_id,
        )
        return form_instance

    # ------------------------------------------------------------------
    # change_value (Req 10.5, 10.7)
    # ------------------------------------------------------------------

    async def change_value(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        field_id: UUID,
        new_value: Any,
        reason: str | None,
        actor_id: UUID,
    ) -> FormInstance:
        """Change a single field value, requiring a reason post-submission.

        Args:
            session: Active async database session.
            form_instance: The FormInstance containing the field.
            field_id: The field_definition_id to change.
            new_value: The new value for the field.
            reason: Reason_For_Change (required after submission, Req 10.5).
            actor_id: UUID of the actor.

        Returns:
            The updated FormInstance.

        Raises:
            BusinessRuleError: If Frozen/Locked (Req 10.7).
            ValidationError: If reason is missing for post-submission change (Req 10.5).
        """
        status = FormInstanceStatus(form_instance.status)
        # Validate the reason before hierarchy lookup for editable
        # post-submission forms. Frozen/locked lifecycle states retain their
        # lock error precedence in _guard_modification.
        if (
            status in _POST_SUBMISSION_STATUSES
            and status not in _LOCKED_STATUSES
            and (not reason or not reason.strip())
        ):
            raise ValidationError(
                message="Reason_For_Change is required for post-submission edits",
                details={"field_id": str(field_id)},
            )

        await self._guard_modification(
            session, form_instance, field_id=field_id
        )

        await self._upsert_field_value(
            session,
            form_instance=form_instance,
            field_definition_id=field_id,
            new_value=new_value,
            actor_id=actor_id,
            reason=reason,
        )

        # Sync data_jsonb
        await self._sync_data_jsonb(session, form_instance)
        await self._invalidate_signed_form(
            session, form_instance, actor_id=actor_id, reason=reason
        )
        form_instance.updated_at = datetime.now(UTC)
        await session.flush()

        logger.info(
            "Field value changed: form_instance_id=%s field_id=%s actor=%s reason=%s",
            form_instance.id,
            field_id,
            actor_id,
            reason,
        )
        return form_instance

    # ------------------------------------------------------------------
    # mark_not_applicable (Req 10.6)
    # ------------------------------------------------------------------

    async def mark_not_applicable(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        field_id: UUID,
        actor_id: UUID,
    ) -> FormInstance:
        """Mark a field as not applicable (Req 10.6).

        Args:
            session: Active async database session.
            form_instance: The FormInstance containing the field.
            field_id: The field_definition_id to mark.
            actor_id: UUID of the actor.

        Returns:
            The updated FormInstance.

        Raises:
            BusinessRuleError: If Frozen/Locked.
        """
        await self._guard_modification(
            session, form_instance, field_id=field_id
        )

        # Find or create the FieldValue row
        field_value = await self._get_or_create_field_value(
            session, form_instance, field_id
        )

        old_na = field_value.is_not_applicable
        field_value.is_not_applicable = True
        field_value.updated_at = datetime.now(UTC)
        field_value.updated_by = actor_id
        # Sync data_jsonb
        await self._sync_data_jsonb(session, form_instance)
        await self._invalidate_signed_form(
            session,
            form_instance,
            actor_id=actor_id,
            reason="Field marked not applicable after signature.",
        )
        form_instance.updated_at = datetime.now(UTC)
        await session.flush()

        # Write Audit_Event (Req 10.8)
        await audit_service.record(
            session,
            entity_type="field_value",
            entity_id=field_value.id,
            action="mark_not_applicable",
            subject_id=form_instance.subject_id,
            actor_id=actor_id,
            field_name=str(field_id),
            old_value=str(old_na),
            new_value="True",
        )

        logger.info(
            "Field marked not applicable: form_instance_id=%s field_id=%s actor=%s",
            form_instance.id,
            field_id,
            actor_id,
        )
        return form_instance

    async def _invalidate_signed_form(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        *,
        actor_id: UUID,
        reason: str | None = None,
    ) -> None:
        """Invalidate a form signature after a post-signature data mutation.

        Only the explicit ``Signed`` lifecycle state triggers this lookup. It
        keeps ordinary draft/submission mutations free of signature queries
        while ensuring every edit to an electronically signed form is checked.
        """
        if FormInstanceStatus(form_instance.status) != FormInstanceStatus.signed:
            return
        await signature_service.invalidate_if_changed(
            session,
            form_instance,
            actor_id=actor_id,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Internal: guard modifications (Req 10.7)
    # ------------------------------------------------------------------

    async def _guard_modification(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        *,
        field_id: UUID | None = None,
    ) -> None:
        """Reject modifications blocked by the Lock_Service hierarchy check.

        Form-level mutations use the FormInstance target. Field mutations use a
        lightweight FieldValue context so LockService can resolve the field,
        owning form, visit, subject, site, and study ancestors even when the
        normalized FieldValue row does not exist yet. This same polymorphic
        target contract is the integration point for FileAttachmentService.
        """
        target: Any = form_instance
        status = FormInstanceStatus(form_instance.status)
        # Preserve the lifecycle-state error and avoid hierarchy queries for
        # legacy forms that predate FreezeLock rows.
        if status in _LOCKED_STATUSES:
            raise BusinessRuleError(
                message=f"Cannot modify a {status.value} form instance",
                details={
                    "form_instance_id": str(form_instance.id),
                    "status": status.value,
                },
            )

        object_type: str | None = None
        object_id: UUID | None = None
        if field_id is not None:
            target = FieldValue(
                form_instance_id=form_instance.id,
                field_definition_id=field_id,
            )
            object_type = "field"
            object_id = field_id

        if field_id is None:
            blocked = await lock_service.is_modification_blocked(
                session, target
            )
        else:
            blocked = await lock_service.is_modification_blocked(
                session,
                target,
                object_type=object_type,
                object_id=object_id,
            )
        # Keep the Phase 1 status invariant as a defensive fallback while
        # existing records transition to FreezeLock rows. The hierarchy check
        # above remains authoritative for ancestor controls.
        status = FormInstanceStatus(form_instance.status)
        if not blocked and status not in _LOCKED_STATUSES:
            return

        if status in _LOCKED_STATUSES:
            raise BusinessRuleError(
                message=f"Cannot modify a {status.value} form instance",
                details={
                    "form_instance_id": str(form_instance.id),
                    "status": status.value,
                },
            )

        details = {"form_instance_id": str(form_instance.id)}
        if field_id is not None:
            details["field_id"] = str(field_id)
        raise BusinessRuleError(
            message="Cannot modify a frozen or locked clinical object",
            details=details,
        )

    # ------------------------------------------------------------------
    # Internal: upsert field value with audit
    # ------------------------------------------------------------------

    async def _upsert_field_value(
        self,
        session: AsyncSession,
        *,
        form_instance: FormInstance,
        field_definition_id: UUID,
        new_value: Any,
        actor_id: UUID,
        reason: str | None,
    ) -> FieldValue:
        """Create or update a FieldValue row and write an Audit_Event.

        Args:
            session: Active async database session.
            form_instance: The owning FormInstance.
            field_definition_id: The field to upsert.
            new_value: The value to persist (serialized as string).
            actor_id: Actor UUID.
            reason: Optional Reason_For_Change.

        Returns:
            The upserted FieldValue.
        """
        # Serialize value to string for storage
        serialized = self._serialize_value(new_value)

        # Look up existing FieldValue
        result = await session.execute(
            select(FieldValue).where(
                FieldValue.form_instance_id == form_instance.id,
                FieldValue.field_definition_id == field_definition_id,
            )
        )
        field_value = result.scalars().first()

        if field_value is None:
            # Create new
            field_value = FieldValue(
                form_instance_id=form_instance.id,
                field_definition_id=field_definition_id,
                value=serialized,
                updated_by=actor_id,
            )
            session.add(field_value)
            await session.flush()

            # Audit: create (Req 10.8)
            await audit_service.record(
                session,
                entity_type="field_value",
                entity_id=field_value.id,
                action="create",
                subject_id=form_instance.subject_id,
                actor_id=actor_id,
                field_name=str(field_definition_id),
                old_value=None,
                new_value=serialized,
                reason=reason,
            )
        else:
            # Update existing
            old_value = field_value.value
            if old_value != serialized:
                field_value.value = serialized
                field_value.updated_at = datetime.now(UTC)
                field_value.updated_by = actor_id
                await session.flush()

                # Audit: update (Req 10.8)
                await audit_service.record(
                    session,
                    entity_type="field_value",
                    entity_id=field_value.id,
                    action="update",
                    subject_id=form_instance.subject_id,
                    actor_id=actor_id,
                    field_name=str(field_definition_id),
                    old_value=old_value,
                    new_value=serialized,
                    reason=reason,
                )

        return field_value

    # ------------------------------------------------------------------
    # Internal: sync data_jsonb (Req 23.3)
    # ------------------------------------------------------------------

    async def _sync_data_jsonb(
        self, session: AsyncSession, form_instance: FormInstance
    ) -> None:
        """Rebuild data_jsonb from the current field_values rows.

        Ensures hybrid storage consistency (Req 22.3, 23.3).
        """
        result = await session.execute(
            select(FieldValue).where(
                FieldValue.form_instance_id == form_instance.id
            )
        )
        field_values = result.scalars().all()

        data: dict[str, Any] = {}
        for fv in field_values:
            key = str(fv.field_definition_id)
            if fv.is_not_applicable:
                data[key] = {"value": fv.value, "is_not_applicable": True}
            else:
                data[key] = fv.value

        form_instance.data_jsonb = data

    # ------------------------------------------------------------------
    # Internal: get field definitions for a form instance
    # ------------------------------------------------------------------

    async def _get_field_definitions(
        self, session: AsyncSession, form_instance: FormInstance
    ) -> list[FieldDefinition]:
        """Get all field definitions for the form instance's form definition.

        Traverses form_definition -> sections -> fields.
        """
        from app.models.form_metadata import FormSection

        # Get sections for this form definition
        sections_result = await session.execute(
            select(FormSection).where(
                FormSection.form_definition_id == form_instance.form_definition_id
            )
        )
        sections = sections_result.scalars().all()
        section_ids = [s.id for s in sections]

        if not section_ids:
            return []

        # Get field definitions across all sections
        fields_result = await session.execute(
            select(FieldDefinition).where(
                FieldDefinition.form_section_id.in_(section_ids)
            )
        )
        return list(fields_result.scalars().all())

    # ------------------------------------------------------------------
    # Internal: get field value map
    # ------------------------------------------------------------------

    async def _get_field_value_map(
        self, session: AsyncSession, form_instance: FormInstance
    ) -> dict[UUID, FieldValue]:
        """Return a dict mapping field_definition_id -> FieldValue."""
        result = await session.execute(
            select(FieldValue).where(
                FieldValue.form_instance_id == form_instance.id
            )
        )
        return {fv.field_definition_id: fv for fv in result.scalars().all()}

    # ------------------------------------------------------------------
    # Internal: validate submission (Req 10.3)
    # ------------------------------------------------------------------

    async def _validate_submission(
        self,
        session: AsyncSession,
        field_definitions: list[FieldDefinition],
        field_value_map: dict[UUID, FieldValue],
    ) -> list[dict[str, Any]]:
        """Validate all fields for submission.

        Checks:
          - Required fields are populated (not None/empty and not NA)
          - Data type is correct (integer, decimal, date, etc.)
          - Range (min_value / max_value)
          - Codelist membership

        Returns:
            A list of field-level error dicts. Empty if valid.
        """
        errors: list[dict[str, Any]] = []

        for field_def in field_definitions:
            # Skip read-only and calculated fields for user-input validation
            if field_def.is_read_only or field_def.is_calculated:
                continue

            fv = field_value_map.get(field_def.id)
            value = fv.value if fv else None
            is_na = fv.is_not_applicable if fv else False

            # --- Required check ---
            if (
                field_def.is_required
                and not is_na
                and (value is None or (isinstance(value, str) and not value.strip()))
            ):
                errors.append({
                    "field_id": str(field_def.id),
                    "variable_name": field_def.variable_name,
                    "error": "required",
                    "message": f"Field '{field_def.label}' is required",
                })
                continue  # No further checks if missing

            # Skip further validation if no value or NA
            if is_na or value is None or (isinstance(value, str) and not value.strip()):
                continue

            # --- Data type check ---
            type_error = self._validate_data_type(field_def, value)
            if type_error:
                errors.append({
                    "field_id": str(field_def.id),
                    "variable_name": field_def.variable_name,
                    "error": "data_type",
                    "message": type_error,
                })
                continue

            # --- Range check (min/max) ---
            range_error = self._validate_range(field_def, value)
            if range_error:
                errors.append({
                    "field_id": str(field_def.id),
                    "variable_name": field_def.variable_name,
                    "error": "range",
                    "message": range_error,
                })

            # --- Codelist membership check ---
            if field_def.codelist_id is not None:
                codelist_error = await self._validate_codelist(
                    session, field_def, value
                )
                if codelist_error:
                    errors.append({
                        "field_id": str(field_def.id),
                        "variable_name": field_def.variable_name,
                        "error": "codelist",
                        "message": codelist_error,
                    })

            # --- Regex validation ---
            if field_def.regex_validation:
                regex_error = self._validate_regex(field_def, value)
                if regex_error:
                    errors.append({
                        "field_id": str(field_def.id),
                        "variable_name": field_def.variable_name,
                        "error": "format",
                        "message": regex_error,
                    })

        return errors

    # ------------------------------------------------------------------
    # Internal: type validation
    # ------------------------------------------------------------------

    def _validate_data_type(self, field_def: FieldDefinition, value: str) -> str | None:
        """Validate the value matches the expected data type.

        Returns an error message string or None if valid.
        """
        data_type = field_def.data_type.lower()

        if data_type == "integer":
            try:
                int(value)
            except (ValueError, TypeError):
                return f"Expected integer value for '{field_def.label}'"

        elif data_type == "decimal" or data_type == "float":
            try:
                Decimal(value)
            except (InvalidOperation, ValueError, TypeError):
                return f"Expected decimal value for '{field_def.label}'"

        elif data_type == "date":
            # Accept ISO date format YYYY-MM-DD
            if not self._is_valid_date(value):
                return f"Expected date (YYYY-MM-DD) for '{field_def.label}'"

        elif data_type == "datetime":
            if not self._is_valid_datetime(value):
                return f"Expected datetime (ISO 8601) for '{field_def.label}'"

        elif data_type == "boolean" and value.lower() not in (
            "true", "false", "1", "0", "yes", "no"
        ):
            return f"Expected boolean value for '{field_def.label}'"

        # string and text types always pass
        return None

    # ------------------------------------------------------------------
    # Internal: range validation
    # ------------------------------------------------------------------

    def _validate_range(self, field_def: FieldDefinition, value: str) -> str | None:
        """Validate numeric range constraints (min_value / max_value).

        Returns an error message string or None if valid.
        """
        if field_def.min_value is None and field_def.max_value is None:
            return None

        # Only validate range for numeric types
        try:
            numeric_value = Decimal(value)
        except (InvalidOperation, ValueError, TypeError):
            return None  # Type validation handles this case

        if field_def.min_value is not None and numeric_value < field_def.min_value:
            return (
                f"Value {value} is below minimum {field_def.min_value} "
                f"for '{field_def.label}'"
            )

        if field_def.max_value is not None and numeric_value > field_def.max_value:
            return (
                f"Value {value} is above maximum {field_def.max_value} "
                f"for '{field_def.label}'"
            )

        return None

    # ------------------------------------------------------------------
    # Internal: codelist validation
    # ------------------------------------------------------------------

    async def _validate_codelist(
        self, session: AsyncSession, field_def: FieldDefinition, value: str
    ) -> str | None:
        """Validate codelist membership.

        Returns an error message string or None if the value is a valid code.
        """
        result = await session.execute(
            select(CodelistItem.code).where(
                CodelistItem.codelist_id == field_def.codelist_id
            )
        )
        valid_codes = {row[0] for row in result.all()}

        if value not in valid_codes:
            return (
                f"Value '{value}' is not a valid code for '{field_def.label}'"
            )
        return None

    # ------------------------------------------------------------------
    # Internal: regex validation
    # ------------------------------------------------------------------

    def _validate_regex(self, field_def: FieldDefinition, value: str) -> str | None:
        """Validate value against regex_validation pattern.

        Returns an error message string or None if valid.
        """
        try:
            if not re.fullmatch(field_def.regex_validation, value):  # type: ignore[arg-type]
                return (
                    f"Value '{value}' does not match the required format "
                    f"for '{field_def.label}'"
                )
        except re.error:
            # Invalid regex pattern in the definition — skip validation
            logger.warning(
                "Invalid regex pattern for field %s: %s",
                field_def.id,
                field_def.regex_validation,
            )
        return None

    # ------------------------------------------------------------------
    # Internal: date/datetime helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_valid_date(value: str) -> bool:
        """Check if value is a valid ISO date (YYYY-MM-DD)."""
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_valid_datetime(value: str) -> bool:
        """Check if value is a valid ISO datetime."""
        try:
            datetime.fromisoformat(value)
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Internal: get or create field value
    # ------------------------------------------------------------------

    async def _get_or_create_field_value(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        field_definition_id: UUID,
    ) -> FieldValue:
        """Get an existing FieldValue or create a new empty one."""
        result = await session.execute(
            select(FieldValue).where(
                FieldValue.form_instance_id == form_instance.id,
                FieldValue.field_definition_id == field_definition_id,
            )
        )
        field_value = result.scalars().first()

        if field_value is None:
            field_value = FieldValue(
                form_instance_id=form_instance.id,
                field_definition_id=field_definition_id,
                value=None,
            )
            session.add(field_value)
            await session.flush()

        return field_value

    # ------------------------------------------------------------------
    # Internal: serialize value
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_value(value: Any) -> str | None:
        """Serialize a value to string for storage in the field_values row."""
        if value is None:
            return None
        return str(value)


# Module-level singleton for convenience
data_capture_service = DataCaptureService()
