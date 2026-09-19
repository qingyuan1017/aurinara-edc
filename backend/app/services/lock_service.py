"""Lock_Service — freeze, lock, unlock, and hierarchy blocking.

Freeze/lock state is stored as polymorphic ``FreezeLock`` rows.  The service
keeps all writes in the caller's transaction and records the corresponding
Audit_Event through the shared audit service.

The clinical hierarchy is resolved as:
    field -> form -> visit -> subject -> site -> study

A field may be represented by a ``FieldValue`` (which gives the service the
clinical form/visit context) or by a ``FieldDefinition`` (which gives the
metadata form/study context).
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import NotFoundError, ValidationError
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.lock import FreezeLock, FreezeLockObjectType, FreezeLockType
from app.models.site import Site
from app.models.study import Study, StudyVersion
from app.models.subject import Subject
from app.models.visit import VisitInstance

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Target:
    """A normalized polymorphic lock target."""

    object_type: FreezeLockObjectType
    object_id: UUID


@dataclass(frozen=True)
class _HierarchyRef:
    """A hierarchy node used by ``is_modification_blocked``."""

    object_type: FreezeLockObjectType
    object_id: UUID


class LockService:
    """Apply and remove freeze/lock controls across clinical data."""

    async def freeze(
        self,
        session: AsyncSession,
        target: Any = None,
        actor_id: UUID | None = None,
        *,
        object_type: FreezeLockObjectType | str | None = None,
        object_id: UUID | None = None,
    ) -> FreezeLock:
        """Freeze a field, form, visit, subject, site, or study."""
        return await self._activate(
            session,
            target,
            FreezeLockType.freeze,
            actor_id,
            object_type=object_type,
            object_id=object_id,
        )

    async def lock(
        self,
        session: AsyncSession,
        target: Any = None,
        actor_id: UUID | None = None,
        *,
        object_type: FreezeLockObjectType | str | None = None,
        object_id: UUID | None = None,
    ) -> FreezeLock:
        """Lock a field, form, visit, subject, site, or study."""
        return await self._activate(
            session,
            target,
            FreezeLockType.lock,
            actor_id,
            object_type=object_type,
            object_id=object_id,
        )

    async def unlock(
        self,
        session: AsyncSession,
        target: Any = None,
        reason: str | None = None,
        actor_id: UUID | None = None,
        *,
        lock_type: FreezeLockType | str = FreezeLockType.lock,
        object_type: FreezeLockObjectType | str | None = None,
        object_id: UUID | None = None,
    ) -> FreezeLock:
        """Clear an active lock after recording a mandatory reason.

        ``unlock`` defaults to the hard-lock record.  Passing
        ``lock_type=FreezeLockType.freeze`` (or using ``unfreeze``) supports
        the corresponding freeze-control route without duplicating logic.
        """
        normalized_reason = reason.strip() if isinstance(reason, str) else ""
        if not normalized_reason:
            raise ValidationError(
                message="A reason is required to unlock an object",
                details={"reason": "unlock reason must not be blank"},
            )
        if actor_id is None:
            raise ValidationError(
                message="An actor is required to unlock an object",
                details={},
            )

        target_ref = self._normalize_target(
            target, object_type=object_type, object_id=object_id
        )
        normalized_lock_type = self._normalize_lock_type(lock_type)
        result = await session.execute(
            select(FreezeLock).where(
                FreezeLock.object_type == target_ref.object_type.value,
                FreezeLock.object_id == target_ref.object_id,
                FreezeLock.lock_type == normalized_lock_type.value,
                FreezeLock.is_active.is_(True),
            )
        )
        control = result.scalars().first()
        if control is None:
            raise NotFoundError(
                message="Active freeze/lock not found",
                details={
                    "object_type": target_ref.object_type.value,
                    "object_id": str(target_ref.object_id),
                    "lock_type": normalized_lock_type.value,
                },
            )

        control.is_active = False
        control.unlocked_by = actor_id
        control.unlocked_at = datetime.now(UTC)
        control.unlock_reason = normalized_reason
        await session.flush()

        await self._record_audit(
            session,
            target,
            target_ref,
            action="unlock" if normalized_lock_type == FreezeLockType.lock else "unfreeze",
            actor_id=actor_id,
            old_value=f"{normalized_lock_type.value}:active",
            new_value=f"{normalized_lock_type.value}:inactive",
            reason=normalized_reason,
        )
        logger.info(
            "Clinical control cleared: type=%s object=%s:%s actor=%s",
            normalized_lock_type.value,
            target_ref.object_type.value,
            target_ref.object_id,
            actor_id,
        )
        return control

    async def unfreeze(
        self,
        session: AsyncSession,
        target: Any = None,
        reason: str | None = None,
        actor_id: UUID | None = None,
        *,
        object_type: FreezeLockObjectType | str | None = None,
        object_id: UUID | None = None,
    ) -> FreezeLock:
        """Clear an active freeze, retaining the mandatory removal reason."""
        return await self.unlock(
            session,
            target,
            reason,
            actor_id,
            lock_type=FreezeLockType.freeze,
            object_type=object_type,
            object_id=object_id,
        )

    async def is_modification_blocked(
        self,
        session: AsyncSession,
        field: Any = None,
        *,
        object_type: FreezeLockObjectType | str | None = None,
        object_id: UUID | None = None,
    ) -> bool:
        """Return whether a field or any of its ancestors is frozen or locked.

        The method is intentionally target-polymorphic: DataCaptureService
        passes a form or field context, and FileAttachmentService can pass
        its parent object through the same interface before an upload.

        The method checks both freeze and lock records in one query.  It also
        honors the existing FormInstance lifecycle status so callers remain
        safe while older records are being migrated to FreezeLock rows.
        """
        target = self._normalize_target(
            field, object_type=object_type, object_id=object_id
        )
        refs = await self._hierarchy_refs(session, field, target)
        if not refs:
            refs = [_HierarchyRef(target.object_type, target.object_id)]

        # Form status is an existing Phase 1 protection and should be treated
        # as blocked when the requested target is a form or field in that form.
        if await self._form_status_blocks(session, field, refs):
            return True

        predicates = [
            (FreezeLock.object_type == ref.object_type.value)
            & (FreezeLock.object_id == ref.object_id)
            for ref in refs
        ]
        result = await session.execute(
            select(FreezeLock.id).where(
                FreezeLock.is_active.is_(True),
                or_(*predicates),
            )
        )
        row = result.first()
        if inspect.isawaitable(row):
            row = await row
        return row is not None

    async def _activate(
        self,
        session: AsyncSession,
        target: Any,
        lock_type: FreezeLockType,
        actor_id: UUID | None,
        *,
        object_type: FreezeLockObjectType | str | None,
        object_id: UUID | None,
    ) -> FreezeLock:
        if actor_id is None:
            raise ValidationError(
                message="An actor is required to freeze or lock an object",
                details={},
            )
        target_ref = self._normalize_target(
            target, object_type=object_type, object_id=object_id
        )

        result = await session.execute(
            select(FreezeLock).where(
                FreezeLock.object_type == target_ref.object_type.value,
                FreezeLock.object_id == target_ref.object_id,
                FreezeLock.lock_type == lock_type.value,
                FreezeLock.is_active.is_(True),
            )
        )
        control = result.scalars().first()
        if control is None:
            control = FreezeLock(
                object_type=target_ref.object_type.value,
                object_id=target_ref.object_id,
                lock_type=lock_type.value,
                is_active=True,
                locked_by=actor_id,
                locked_at=datetime.now(UTC),
            )
            session.add(control)
            await session.flush()
        else:
            # Keep one active control per target/type while retaining its
            # original row and avoiding duplicate active blockers.
            control.locked_by = actor_id
            control.locked_at = datetime.now(UTC)
            control.unlocked_by = None
            control.unlocked_at = None
            control.unlock_reason = None
            await session.flush()

        await self._record_audit(
            session,
            target,
            target_ref,
            action=lock_type.value,
            actor_id=actor_id,
            old_value=None,
            new_value=f"{lock_type.value}:active",
        )
        logger.info(
            "Clinical control applied: type=%s object=%s:%s actor=%s",
            lock_type.value,
            target_ref.object_type.value,
            target_ref.object_id,
            actor_id,
        )
        return control

    @staticmethod
    def _normalize_lock_type(lock_type: FreezeLockType | str) -> FreezeLockType:
        try:
            return (
                lock_type
                if isinstance(lock_type, FreezeLockType)
                else FreezeLockType(lock_type)
            )
        except ValueError as exc:
            raise ValidationError(
                message="Invalid freeze/lock type",
                details={"lock_type": str(lock_type)},
            ) from exc

    @staticmethod
    def _normalize_target(
        target: Any,
        *,
        object_type: FreezeLockObjectType | str | None,
        object_id: UUID | None,
    ) -> _Target:
        """Normalize a model instance or explicit type/id pair."""
        explicit_type = object_type.value if isinstance(object_type, FreezeLockObjectType) else object_type
        if explicit_type is not None:
            aliases = {
                "field_definition": FreezeLockObjectType.field.value,
                "field_value": FreezeLockObjectType.field.value,
                "form_definition": FreezeLockObjectType.form.value,
                "form_instance": FreezeLockObjectType.form.value,
                "visit_instance": FreezeLockObjectType.visit.value,
            }
            explicit_type = aliases.get(str(explicit_type), str(explicit_type))
            try:
                normalized_type = FreezeLockObjectType(explicit_type)
            except ValueError as exc:
                raise ValidationError(
                    message="Invalid freeze/lock object type",
                    details={"object_type": explicit_type},
                ) from exc
            resolved_id = object_id or (target if isinstance(target, UUID) else getattr(target, "id", None))
            if resolved_id is None:
                raise ValidationError(
                    message="An object id is required for freeze/lock",
                    details={"object_type": normalized_type.value},
                )
            return _Target(normalized_type, UUID(str(resolved_id)))

        if isinstance(target, FreezeLock):
            return _Target(
                FreezeLockObjectType(target.object_type), UUID(str(target.object_id))
            )
        if isinstance(target, UUID):
            raise ValidationError(
                message="object_type is required when target is an id",
                details={"object_id": str(target)},
            )
        if target is None:
            raise ValidationError(message="A freeze/lock target is required", details={})

        class_name = target.__class__.__name__
        type_by_class = {
            "FieldDefinition": FreezeLockObjectType.field,
            "FieldValue": FreezeLockObjectType.field,
            "FormDefinition": FreezeLockObjectType.form,
            "FormInstance": FreezeLockObjectType.form,
            "VisitInstance": FreezeLockObjectType.visit,
            "Subject": FreezeLockObjectType.subject,
            "Site": FreezeLockObjectType.site,
            "Study": FreezeLockObjectType.study,
        }
        normalized_type = type_by_class.get(class_name)
        resolved_id = getattr(target, "id", None)
        if normalized_type is None or resolved_id is None:
            raise ValidationError(
                message="Unsupported freeze/lock target",
                details={"target_type": class_name},
            )
        return _Target(normalized_type, UUID(str(resolved_id)))

    async def _hierarchy_refs(
        self,
        session: AsyncSession,
        target: Any,
        normalized: _Target,
    ) -> list[_HierarchyRef]:
        """Resolve target and all available ancestors to normalized refs."""
        refs: list[_HierarchyRef] = [
            _HierarchyRef(normalized.object_type, normalized.object_id)
        ]

        if isinstance(target, UUID) or target is None:
            target = await self._load_target(session, normalized)
        if target is None:
            return refs

        if isinstance(target, FieldValue):
            form = await self._load_or_use(
                session, FormInstance, target.form_instance_id
            )
            refs = [
                _HierarchyRef(FreezeLockObjectType.field, target.field_definition_id),
                _HierarchyRef(FreezeLockObjectType.form, target.form_instance_id),
            ]
            if form is not None:
                refs.extend(await self._visit_subject_refs(session, form.visit_instance_id, form.subject_id))
            return refs

        if isinstance(target, FieldDefinition):
            section = await self._load_or_use(session, FormSection, target.form_section_id)
            if section is not None:
                refs.append(_HierarchyRef(FreezeLockObjectType.form, section.form_definition_id))
                form = await self._load_or_use(session, FormDefinition, section.form_definition_id)
                if form is not None:
                    version = await self._load_or_use(session, StudyVersion, form.study_version_id)
                    if version is not None:
                        refs.append(_HierarchyRef(FreezeLockObjectType.study, version.study_id))
            return refs

        if isinstance(target, FormInstance):
            refs.extend(await self._visit_subject_refs(session, target.visit_instance_id, target.subject_id))
            return refs

        if isinstance(target, FormDefinition):
            version = await self._load_or_use(session, StudyVersion, target.study_version_id)
            if version is not None:
                refs.append(_HierarchyRef(FreezeLockObjectType.study, version.study_id))
            return refs

        if isinstance(target, VisitInstance):
            refs.extend(await self._subject_refs(session, target.subject_id))
            return refs

        if isinstance(target, Subject):
            refs.extend(await self._site_study_refs(session, target.site_id, target.study_id))
            return refs

        if isinstance(target, Site):
            refs.append(_HierarchyRef(FreezeLockObjectType.study, target.study_id))
            return refs

        return refs

    async def _visit_subject_refs(
        self,
        session: AsyncSession,
        visit_id: UUID | None,
        subject_id: UUID,
    ) -> list[_HierarchyRef]:
        refs: list[_HierarchyRef] = []
        if visit_id is not None:
            refs.append(_HierarchyRef(FreezeLockObjectType.visit, visit_id))
        refs.extend(await self._subject_refs(session, subject_id))
        return refs

    async def _subject_refs(
        self, session: AsyncSession, subject_id: UUID
    ) -> list[_HierarchyRef]:
        refs = [_HierarchyRef(FreezeLockObjectType.subject, subject_id)]
        subject = await self._load_or_use(session, Subject, subject_id)
        if subject is not None:
            refs.extend(await self._site_study_refs(session, subject.site_id, subject.study_id))
        return refs

    @staticmethod
    async def _site_study_refs(
        session: AsyncSession,
        site_id: UUID | None,
        study_id: UUID | None,
    ) -> list[_HierarchyRef]:
        refs: list[_HierarchyRef] = []
        if site_id is not None:
            refs.append(_HierarchyRef(FreezeLockObjectType.site, site_id))
        if study_id is not None:
            refs.append(_HierarchyRef(FreezeLockObjectType.study, study_id))
        return refs

    async def _form_status_blocks(
        self,
        session: AsyncSession,
        target: Any,
        refs: list[_HierarchyRef],
    ) -> bool:
        form: FormInstance | None = target if isinstance(target, FormInstance) else None
        if isinstance(target, FieldValue):
            form = await self._load_or_use(session, FormInstance, target.form_instance_id)
        return form is not None and FormInstanceStatus(form.status) in {
            FormInstanceStatus.frozen,
            FormInstanceStatus.locked,
        }

    async def _load_target(
        self, session: AsyncSession, target: _Target
    ) -> Any | None:
        model_by_type = {
            FreezeLockObjectType.field: FieldDefinition,
            FreezeLockObjectType.form: FormInstance,
            FreezeLockObjectType.visit: VisitInstance,
            FreezeLockObjectType.subject: Subject,
            FreezeLockObjectType.site: Site,
            FreezeLockObjectType.study: Study,
        }
        return await self._load_or_use(
            session, model_by_type[target.object_type], target.object_id
        )

    @staticmethod
    async def _load_or_use(
        session: AsyncSession, model: Any, entity_id: UUID | None
    ) -> Any | None:
        if entity_id is None:
            return None
        result = await session.execute(select(model).where(model.id == entity_id))
        scalars = result.scalars()
        if inspect.isawaitable(scalars):
            scalars = await scalars
        entity = scalars.first()
        if inspect.isawaitable(entity):
            entity = await entity
        return entity

    async def _record_audit(
        self,
        session: AsyncSession,
        target: Any,
        normalized: _Target,
        *,
        action: str,
        actor_id: UUID,
        old_value: str | None,
        new_value: str | None,
        reason: str | None = None,
    ) -> None:
        study_id = getattr(target, "study_id", None)
        site_id = getattr(target, "site_id", None)
        subject_id = getattr(target, "subject_id", None)
        await audit_service.record(
            session,
            entity_type=normalized.object_type.value,
            entity_id=normalized.object_id,
            action=action,
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            actor_id=actor_id,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )


# Module-level singleton, matching the other backend services.
lock_service = LockService()
