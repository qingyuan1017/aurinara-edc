"""SDV_Service — source data verification state and progress tracking.

The service stores one current SDV status per supported clinical target.  Status
writes and their audit events use the caller's ``AsyncSession`` and therefore
participate in the same transaction.

Satisfies Requirements:
  - 14.1: Set verification state with actor and timestamp at field/form/visit/
          subject scope.
  - 14.2: Clear verification state.
  - 14.3: Report verified and not-verified progress counts.
  - 14.4: Audit every SDV status mutation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import ValidationError
from app.models.form_data import FieldValue, FormInstance
from app.models.sdv import SDVScopeType, SDVStatus
from app.models.subject import Subject
from app.models.visit import VisitInstance

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SDVTarget:
    """Normalized polymorphic SDV target."""

    scope_type: SDVScopeType
    scope_id: UUID


_SCOPE_ALIASES = {
    "field_definition": SDVScopeType.field,
    "field_value": SDVScopeType.field,
    "form_instance": SDVScopeType.form,
    "visit_instance": SDVScopeType.visit,
}
_TARGET_SCOPE_BY_CLASS = {
    "FieldDefinition": SDVScopeType.field,
    "FieldValue": SDVScopeType.field,
    "FormInstance": SDVScopeType.form,
    "VisitInstance": SDVScopeType.visit,
    "Subject": SDVScopeType.subject,
}


class SDVService:
    """Manage source-data-verification toggles and progress counts."""

    async def set_sdv(
        self,
        session: AsyncSession,
        scope: SDVScopeType | str,
        target: Any,
        actor_id: Any = None,
    ) -> SDVStatus:
        """Mark ``target`` as source-data verified.

        ``target`` may be an ORM object or a UUID.  UUID targets are accepted
        when the explicit ``scope`` identifies their polymorphic type, which
        lets route handlers normalize authorization-checked path parameters
        without manufacturing partial ORM objects.  ``actor_id`` accepts a
        UUID or the authenticated User object used by API dependencies.
        """
        target_ref = self._normalize_target(scope, target)
        actor_uuid, actor_email = self._normalize_actor(actor_id)
        status = await self._get_or_create_status(session, target_ref)
        old_verified = status.is_verified
        changed_at = datetime.now(UTC)

        status.is_verified = True
        status.verified_by = actor_uuid
        status.verified_at = changed_at
        status.updated_at = changed_at
        await session.flush()

        await self._record_audit(
            session,
            target,
            target_ref,
            status,
            action="set_sdv",
            actor_id=actor_uuid,
            actor_email=actor_email,
            old_value=str(old_verified),
            new_value="True",
        )
        logger.info(
            "SDV set: scope=%s target=%s actor=%s",
            target_ref.scope_type.value,
            target_ref.scope_id,
            actor_uuid,
        )
        return status

    async def clear_sdv(
        self,
        session: AsyncSession,
        scope: SDVScopeType | str,
        target: Any,
        actor_id: Any = None,
    ) -> SDVStatus:
        """Clear SDV state for ``target`` and retain the status row.

        The clearing actor is recorded in the Audit_Event.  The status row's
        verifier and verification time describe the current state, so both are
        cleared when the target becomes not verified.  ``actor_id`` may be
        omitted when the request context supplies the actor to AuditService.
        """
        target_ref = self._normalize_target(scope, target)
        actor_uuid, actor_email = self._normalize_actor(actor_id)
        status = await self._get_or_create_status(session, target_ref)
        old_verified = status.is_verified
        changed_at = datetime.now(UTC)

        status.is_verified = False
        status.verified_by = None
        status.verified_at = None
        status.updated_at = changed_at
        await session.flush()

        await self._record_audit(
            session,
            target,
            target_ref,
            status,
            action="clear_sdv",
            actor_id=actor_uuid,
            actor_email=actor_email,
            old_value=str(old_verified),
            new_value="False",
        )
        logger.info(
            "SDV cleared: scope=%s target=%s actor=%s",
            target_ref.scope_type.value,
            target_ref.scope_id,
            actor_uuid,
        )
        return status

    async def progress(
        self,
        session: AsyncSession,
        scope: Any = None,
        *,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        subject_id: UUID | None = None,
        scope_type: SDVScopeType | str | None = None,
    ) -> dict[str, int]:
        """Return verified/not-verified counts for a requested clinical scope.

        A UUID supplied as ``scope`` is treated as a study ID, matching the
        design's ``progress(scope)`` interface and the study progress route.
        ``study_id``, ``site_id``, and ``subject_id`` provide narrower filters.
        ``scope_type`` limits the denominator to fields, forms, visits, or
        subjects.  When no type is supplied, all four supported target types
        are aggregated; targets without an SDV row count as not verified.
        """
        scope_type = self._resolve_progress_scope(scope, scope_type)
        if scope is not None and not isinstance(scope, (SDVScopeType, str)):
            if isinstance(scope, UUID):
                study_id = study_id or scope
            else:
                study_id = study_id or getattr(scope, "study_id", None)
                site_id = site_id or getattr(scope, "site_id", None)
                subject_id = subject_id or getattr(scope, "subject_id", None)
                if isinstance(scope, Subject):
                    subject_id = scope.id
        elif isinstance(scope, UUID):
            study_id = study_id or scope
        elif isinstance(scope, str):
            try:
                self._normalize_scope(scope)
            except ValidationError:
                try:
                    study_id = study_id or UUID(scope)
                except ValueError as exc:
                    raise ValidationError(
                        message="Invalid SDV progress scope",
                        details={"scope": scope},
                    ) from exc

        models = (
            [self._model_for_scope(scope_type)]
            if scope_type is not None
            else [
                FieldValue,
                FormInstance,
                VisitInstance,
                Subject,
            ]
        )
        total_terms = []
        verified_terms = []
        for model in models:
            total, verified = self._count_query(
                model,
                scope_type=self._scope_for_model(model),
                study_id=study_id,
                site_id=site_id,
                subject_id=subject_id,
            )
            total_terms.append(total.scalar_subquery())
            verified_terms.append(verified.scalar_subquery())

        total_expression = total_terms[0]
        verified_expression = verified_terms[0]
        for term in total_terms[1:]:
            total_expression = total_expression + term
        for term in verified_terms[1:]:
            verified_expression = verified_expression + term

        result = await session.execute(
            select(
                total_expression.label("total"),
                verified_expression.label("verified"),
            )
        )
        row = result.one()
        total = int(row.total or 0)
        verified = int(row.verified or 0)
        counts = {"verified": verified, "not_verified": max(total - verified, 0)}
        logger.debug(
            "SDV progress computed: study_id=%s site_id=%s subject_id=%s scope_type=%s counts=%s",
            study_id,
            site_id,
            subject_id,
            scope_type.value if scope_type else None,
            counts,
        )
        return counts

    async def _get_or_create_status(
        self,
        session: AsyncSession,
        target: _SDVTarget,
    ) -> SDVStatus:
        """Fetch the unique status row or create its unverified baseline."""
        result = await session.execute(
            select(SDVStatus).where(
                SDVStatus.scope_type == target.scope_type.value,
                SDVStatus.scope_id == target.scope_id,
            )
        )
        status = result.scalars().first()
        if status is None:
            status = SDVStatus(
                scope_type=target.scope_type.value,
                scope_id=target.scope_id,
                is_verified=False,
            )
            session.add(status)
            await session.flush()
        return status

    def _count_query(
        self,
        model: Any,
        *,
        scope_type: SDVScopeType,
        study_id: UUID | None,
        site_id: UUID | None,
        subject_id: UUID | None,
    ) -> tuple[Any, Any]:
        """Build total and verified count queries for one target type."""
        status_join = (SDVStatus.scope_type == scope_type.value) & (SDVStatus.scope_id == model.id)
        base = select(
            func.count(model.id).label("total"),
            func.count(case((SDVStatus.is_verified.is_(True), model.id), else_=None)).label(
                "verified"
            ),
        ).select_from(model)

        if model is Subject:
            if study_id is not None:
                base = base.where(Subject.study_id == study_id)
            if site_id is not None:
                base = base.where(Subject.site_id == site_id)
            if subject_id is not None:
                base = base.where(Subject.id == subject_id)
        elif model is VisitInstance:
            base = base.join(Subject, VisitInstance.subject_id == Subject.id)
            base = self._subject_filters(base, study_id, site_id, subject_id)
        elif model is FormInstance:
            base = base.join(Subject, FormInstance.subject_id == Subject.id)
            base = self._subject_filters(base, study_id, site_id, subject_id)
        elif model is FieldValue:
            base = base.join(FormInstance, FieldValue.form_instance_id == FormInstance.id)
            base = base.join(Subject, FormInstance.subject_id == Subject.id)
            base = self._subject_filters(base, study_id, site_id, subject_id)

        total = base.outerjoin(SDVStatus, status_join).with_only_columns(
            func.count(model.id).label("total")
        )
        verified = base.outerjoin(SDVStatus, status_join).with_only_columns(
            func.count(case((SDVStatus.is_verified.is_(True), model.id), else_=None)).label(
                "verified"
            )
        )
        return total, verified

    @staticmethod
    def _subject_filters(
        stmt: Any, study_id: UUID | None, site_id: UUID | None, subject_id: UUID | None
    ) -> Any:
        if study_id is not None:
            stmt = stmt.where(Subject.study_id == study_id)
        if site_id is not None:
            stmt = stmt.where(Subject.site_id == site_id)
        if subject_id is not None:
            stmt = stmt.where(Subject.id == subject_id)
        return stmt

    @staticmethod
    def _normalize_target(
        scope: SDVScopeType | str,
        target: Any,
    ) -> _SDVTarget:
        normalized_scope = SDVService._normalize_scope(scope)
        if target is None:
            raise ValidationError(
                message="An SDV target is required",
                details={"scope": normalized_scope.value},
            )
        target_id = target if isinstance(target, UUID) else getattr(target, "id", None)
        if target_id is None:
            raise ValidationError(
                message="An SDV target id is required",
                details={"scope": normalized_scope.value},
            )

        target_scope = _TARGET_SCOPE_BY_CLASS.get(target.__class__.__name__)
        if target_scope is not None and target_scope != normalized_scope:
            raise ValidationError(
                message="SDV scope does not match target type",
                details={
                    "scope": normalized_scope.value,
                    "target_type": target.__class__.__name__,
                },
            )
        try:
            normalized_id = UUID(str(target_id))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                message="An SDV target id must be a UUID",
                details={"target_id": str(target_id)},
            ) from exc
        return _SDVTarget(normalized_scope, normalized_id)

    @staticmethod
    def _normalize_scope(scope: SDVScopeType | str) -> SDVScopeType:
        if isinstance(scope, SDVScopeType):
            return scope
        normalized = _SCOPE_ALIASES.get(str(scope), str(scope))
        try:
            return SDVScopeType(normalized)
        except ValueError as exc:
            raise ValidationError(
                message="Invalid SDV scope",
                details={"scope": str(scope), "allowed": [item.value for item in SDVScopeType]},
            ) from exc

    @staticmethod
    def _resolve_progress_scope(
        scope: Any,
        scope_type: SDVScopeType | str | None,
    ) -> SDVScopeType | None:
        if scope_type is not None:
            return SDVService._normalize_scope(scope_type)
        if isinstance(scope, SDVScopeType):
            return scope
        if isinstance(scope, str):
            try:
                return SDVService._normalize_scope(scope)
            except ValidationError:
                return None
        if scope is not None:
            return _TARGET_SCOPE_BY_CLASS.get(scope.__class__.__name__)
        return None

    @staticmethod
    def _model_for_scope(scope_type: SDVScopeType) -> Any:
        return {
            SDVScopeType.field: FieldValue,
            SDVScopeType.form: FormInstance,
            SDVScopeType.visit: VisitInstance,
            SDVScopeType.subject: Subject,
        }[scope_type]

    @staticmethod
    def _scope_for_model(model: Any) -> SDVScopeType:
        return {
            FieldValue: SDVScopeType.field,
            FormInstance: SDVScopeType.form,
            VisitInstance: SDVScopeType.visit,
            Subject: SDVScopeType.subject,
        }[model]

    @staticmethod
    def _normalize_actor(actor: Any) -> tuple[UUID | None, str | None]:
        if actor is None:
            return None, None
        actor_id = actor if isinstance(actor, UUID) else getattr(actor, "id", actor)
        try:
            normalized_id = UUID(str(actor_id))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                message="An SDV actor id must be a UUID",
                details={"actor_id": str(actor_id)},
            ) from exc
        return normalized_id, getattr(actor, "email", None)

    async def _record_audit(
        self,
        session: AsyncSession,
        target: Any,
        normalized: _SDVTarget,
        status: SDVStatus,
        *,
        action: str,
        actor_id: UUID | None,
        actor_email: str | None,
        old_value: str,
        new_value: str,
    ) -> None:
        study_id, site_id, subject_id = self._audit_scope(target)
        await audit_service.record(
            session,
            entity_type="sdv_status",
            entity_id=status.id,
            action=action,
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            actor_id=actor_id,
            actor_email=actor_email,
            field_name="is_verified",
            old_value=old_value,
            new_value=new_value,
        )

    @staticmethod
    def _audit_scope(target: Any) -> tuple[UUID | None, UUID | None, UUID | None]:
        """Extract already-loaded hierarchy context without async lazy loads."""
        if target is None or isinstance(target, UUID):
            return None, None, None
        study_id = getattr(target, "study_id", None)
        site_id = getattr(target, "site_id", None)
        subject_id = getattr(target, "subject_id", None)

        if isinstance(target, Subject):
            return study_id, site_id, target.id

        subject = target.__dict__.get("subject") if hasattr(target, "__dict__") else None
        if subject is not None:
            study_id = study_id or getattr(subject, "study_id", None)
            site_id = site_id or getattr(subject, "site_id", None)
            subject_id = subject_id or getattr(subject, "id", None)

        if isinstance(target, FieldValue):
            form_instance = target.__dict__.get("form_instance")
            if form_instance is not None:
                return SDVService._audit_scope(form_instance)
        return study_id, site_id, subject_id


sdv_service = SDVService()

__all__ = ["SDVService", "sdv_service"]
