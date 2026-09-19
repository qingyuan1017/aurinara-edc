"""CTMS operational study service.

The service owns operational planning records while preserving the canonical
EDC ``Study`` and all ``StudyVersion``/clinical configuration records as
read-only references. Methods use the caller's session and never commit, so the
aggregate, status history, audit event, and outbox row are atomic.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import Any, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ctms import ensure_utc, utc_now
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.request_context import get_actor, get_correlation_id
from app.models.ctms.operational_study import (
    DashboardQuery,
    EnrollmentPlan,
    EnrollmentPlanStatus,
    OperationalMilestoneStatus,
    OperationalStudy,
    OperationalStudyStatus,
    ReadinessCriterion,
    ReadinessCriterionStatus,
    ReportQuery,
    StudyOperationalMilestone,
    StudyPlan,
    StudyPlanStatus,
)
from app.models.study import Study
from app.services.ctms_atomicity_service import ctms_atomicity_service
from app.services.ctms_identity_service import CanonicalIdentityResolver
from app.services.ctms_ownership_guard import assert_ctms_command_safe

T = TypeVar("T")

_STUDY_TRANSITIONS: dict[str, set[str]] = {
    OperationalStudyStatus.DRAFT.value: {OperationalStudyStatus.PLANNING.value},
    OperationalStudyStatus.PLANNING.value: {OperationalStudyStatus.READY.value, OperationalStudyStatus.SUSPENDED.value},
    OperationalStudyStatus.READY.value: {OperationalStudyStatus.ACTIVE.value, OperationalStudyStatus.PLANNING.value, OperationalStudyStatus.SUSPENDED.value},
    OperationalStudyStatus.ACTIVE.value: {
        OperationalStudyStatus.ENROLLMENT_CLOSED.value,
        OperationalStudyStatus.SUSPENDED.value,
        OperationalStudyStatus.CLOSED.value,
    },
    OperationalStudyStatus.ENROLLMENT_CLOSED.value: {
        OperationalStudyStatus.SUSPENDED.value,
        OperationalStudyStatus.CLOSED.value,
    },
    OperationalStudyStatus.SUSPENDED.value: {
        OperationalStudyStatus.PLANNING.value,
        OperationalStudyStatus.READY.value,
        OperationalStudyStatus.ACTIVE.value,
        OperationalStudyStatus.ENROLLMENT_CLOSED.value,
        OperationalStudyStatus.CLOSED.value,
    },
    OperationalStudyStatus.CLOSED.value: set(),
}

_PROFILE_FIELDS = {
    "operational_owner_id",
    "sponsor",
    "phase",
    "therapeutic_area",
    "indication",
    "planning_metadata",
    "readiness_criteria",
}


def _mapping(value: Mapping[str, Any] | Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump(exclude_unset=True))
    raise ValidationError("CTMS study payload must be a mapping")


def _uuid(value: UUID | str, field: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a canonical UUID", {"field": field}) from exc


def _actor(actor: Any | None, actor_id: UUID | None) -> UUID:
    value = actor_id
    if value is None and actor is not None:
        value = getattr(actor, "user_id", None) or getattr(actor, "id", None)
    if value is None:
        value = get_actor()
    if value is None:
        raise ValidationError("An actor is required for an operational study mutation")
    return _uuid(value, "actor_id")


def _correlation(value: UUID | str | None, actor: Any | None = None) -> str:
    if value is not None:
        return str(value)
    return str(getattr(actor, "correlation_id", None) or get_correlation_id() or uuid4().hex)


def _correlation_uuid(value: UUID | str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        return uuid5(NAMESPACE_URL, str(value))


def _reason(reason: str | None) -> str:
    if reason is None or not reason.strip():
        raise ValidationError("A non-empty reason is required for this operational change")
    return reason.strip()


def _timestamp(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min, tzinfo=UTC)
    return ensure_utc(value)


def _normalize_loaded_timestamps(record: OperationalStudy) -> OperationalStudy:
    """Normalize SQLite-reloaded timestamps to the shared UTC API contract."""

    for field in ("created_at", "updated_at", "archived_at", "deleted_at"):
        value = getattr(record, field, None)
        if isinstance(value, datetime) and value.tzinfo is None:
            setattr(record, field, value.replace(tzinfo=UTC))
    return record


def _value_status(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


class OperationalStudyService:
    """Manage CTMS operational study profiles and planning records."""

    async def _canonical_study(self, session: AsyncSession, study_id: UUID | str) -> Study:
        canonical_id = _uuid(study_id, "study_id")
        identity = await CanonicalIdentityResolver(session).resolve_study(canonical_id)
        result = await session.execute(select(Study).where(Study.id == identity.id, Study.deleted_at.is_(None)))
        study = result.scalars().first()
        if study is None:  # Defensive for repository/session fakes.
            raise NotFoundError("Canonical EDC Study reference was not found", {"study_id": str(canonical_id)})
        return study

    async def get_profile(self, session: AsyncSession, study_id: UUID | str) -> OperationalStudy:
        canonical_id = _uuid(study_id, "study_id")
        result = await session.execute(
            select(OperationalStudy).where(
                or_(OperationalStudy.id == canonical_id, OperationalStudy.study_id == canonical_id),
                OperationalStudy.deleted_at.is_(None),
            )
        )
        profile = result.scalars().first()
        if profile is None:
            raise NotFoundError("Operational study profile was not found", {"study_id": str(canonical_id)})
        return _normalize_loaded_timestamps(profile)

    async def create_profile(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | str,
        payload: Mapping[str, Any] | Any | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> OperationalStudy:
        values = _mapping(payload)
        assert_ctms_command_safe(values, operation="create_operational_study_profile")
        actor_uuid = _actor(actor, actor_id)
        study = await self._canonical_study(session, study_id)
        existing = await session.execute(
            select(OperationalStudy).where(
                OperationalStudy.study_id == study.id,
                OperationalStudy.deleted_at.is_(None),
            )
        )
        if existing.scalars().first() is not None:
            raise ConflictError("An operational study profile already exists", {"study_id": str(study.id), "reason": "DUPLICATE_RECORD"})
        status = _value_status(values.get("status", OperationalStudyStatus.DRAFT))
        if status not in _STUDY_TRANSITIONS:
            raise ValidationError("Invalid operational study status", {"status": status})
        unknown = set(values) - _PROFILE_FIELDS - {"status", "correlation_id"}
        if unknown:
            raise ValidationError("Unknown operational study profile field", {"field": sorted(unknown)[0]})
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)
        profile = OperationalStudy(
            study_id=study.id,
            operational_owner_id=values.get("operational_owner_id"),
            sponsor=values.get("sponsor"),
            phase=values.get("phase"),
            therapeutic_area=values.get("therapeutic_area"),
            indication=values.get("indication"),
            planning_metadata=dict(values.get("planning_metadata") or {}),
            readiness_criteria=dict(values.get("readiness_criteria") or {}),
            status=status,
            retention_state="active",
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(profile)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="operational_study",
            entity_id=profile.id,
            study_id=profile.study_id,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["study_id", *_PROFILE_FIELDS, "status"],
            status=status,
            payload={"study_id": profile.study_id, "status": status},
        )
        return profile

    # Public aliases keep the service name explicit for API and worker callers.
    create_operational_study = create_profile
    create_study_profile = create_profile

    async def update_profile(
        self,
        session: AsyncSession,
        profile: OperationalStudy | UUID,
        changes: Mapping[str, Any] | Any,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
        reason: str | None = None,
    ) -> OperationalStudy:
        values = _mapping(changes)
        assert_ctms_command_safe(values, operation="update_operational_study_profile")
        actor_uuid = _actor(actor, actor_id)
        if isinstance(profile, UUID):
            profile = await self.get_profile(session, profile)
        unknown = set(values) - _PROFILE_FIELDS - {"correlation_id"}
        if unknown:
            raise ValidationError("Unknown operational study profile field", {"field": sorted(unknown)[0]})
        changed = [field for field in _PROFILE_FIELDS if field in values and getattr(profile, field) != values[field]]
        if not changed:
            return profile
        # Updates to an Active profile require an explicit reason for traceability.
        change_reason = _reason(reason) if profile.status == OperationalStudyStatus.ACTIVE.value else reason.strip() if reason and reason.strip() else None
        for field in changed:
            setattr(profile, field, dict(values[field] or {}) if field in {"planning_metadata", "readiness_criteria"} else values[field])
        profile.updated_by = actor_uuid
        profile.updated_at = utc_now()
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="operational_study",
            entity_id=profile.id,
            study_id=profile.study_id,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="update",
            changed_fields=changed,
            reason=change_reason,
            payload={"study_id": profile.study_id, "changed_fields": changed},
        )
        return profile

    update_operational_study = update_profile

    async def transition_status(
        self,
        session: AsyncSession,
        profile: OperationalStudy | UUID,
        target_status: OperationalStudyStatus | str,
        reason: str | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> OperationalStudy:
        actor_uuid = _actor(actor, actor_id)
        if isinstance(profile, UUID):
            profile = await self.get_profile(session, profile)
        current = _value_status(profile.status)
        target = _value_status(target_status)
        if target == current:
            return profile
        if target not in _STUDY_TRANSITIONS.get(current, set()):
            raise ConflictError(
                f"Invalid operational study transition from '{current}' to '{target}'",
                {"reason": "INVALID_TRANSITION", "current_status": current, "target_status": target},
            )
        change_reason = _reason(reason)
        correlation = _correlation(correlation_id, actor)
        profile.status = target
        profile.updated_by = actor_uuid
        profile.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="operational_study",
            entity_id=profile.id,
            study_id=profile.study_id,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="status_transition",
            changed_fields=["status"],
            previous_status=current,
            status=target,
            reason=change_reason,
            payload={"study_id": profile.study_id, "status": target},
        )
        return profile

    transition_operational_status = transition_status

    async def archive_study(
        self,
        session: AsyncSession,
        profile: OperationalStudy | UUID,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        reason: str | None = None,
        correlation_id: UUID | str | None = None,
    ) -> OperationalStudy:
        actor_uuid = _actor(actor, actor_id)
        change_reason = _reason(reason)
        if isinstance(profile, UUID):
            profile = await self.get_profile(session, profile)
        if profile.retention_state == "archived":
            return profile
        correlation = _correlation(correlation_id, actor)
        profile.retention_state = "archived"
        profile.archived_at = utc_now()
        profile.archived_by = actor_uuid
        profile.retention_reason = change_reason
        profile.updated_by = actor_uuid
        profile.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="operational_study",
            entity_id=profile.id,
            study_id=profile.study_id,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="archive",
            changed_fields=["retention_state", "archived_at", "archived_by", "retention_reason"],
            reason=change_reason,
            event_type="operational_study_archived",
            payload={"study_id": profile.study_id, "retention_state": "archived"},
        )
        return profile

    archive = archive_study

    async def _create_scoped(
        self,
        session: AsyncSession,
        model: type[T],
        *,
        entity_type: str,
        study_id: UUID | str,
        payload: Mapping[str, Any] | Any | None,
        actor: Any | None,
        actor_id: UUID | None,
        correlation_id: UUID | str | None,
        required_fields: set[str],
        fields: set[str],
        defaults: Mapping[str, Any] | None = None,
    ) -> T:
        values = _mapping(payload)
        assert_ctms_command_safe(values, operation=f"create_{entity_type}")
        actor_uuid = _actor(actor, actor_id)
        study = await self._canonical_study(session, study_id)
        unknown = set(values) - fields - {"correlation_id"}
        if unknown:
            raise ValidationError(f"Unknown {entity_type} field", {"field": sorted(unknown)[0]})
        missing = [field for field in required_fields if not values.get(field)]
        if missing:
            raise ValidationError(f"{entity_type} requires {missing[0]}", {"field": missing[0]})
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)
        data = dict(defaults or {})
        data.update({field: values[field] for field in fields if field in values})
        data.update(
            study_id=study.id,
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        record = model(**data)
        session.add(record)
        await session.flush()
        status = getattr(record, "status", None)
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type=entity_type,
            entity_id=record.id,
            study_id=study.id,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=sorted(fields & set(values)),
            status=_value_status(status) if status is not None else None,
            payload={"study_id": study.id},
        )
        return record

    async def create_study_plan(self, session: AsyncSession, *, study_id: UUID | str, payload: Mapping[str, Any] | Any | None = None, actor: Any | None = None, actor_id: UUID | None = None, correlation_id: UUID | str | None = None) -> StudyPlan:
        return await self._create_scoped(session, StudyPlan, entity_type="study_plan", study_id=study_id, payload=payload, actor=actor, actor_id=actor_id, correlation_id=correlation_id, required_fields={"title"}, fields={"title", "objective", "planning_scope", "owner_id", "status"}, defaults={"planning_scope": {}, "status": StudyPlanStatus.DRAFT.value})

    async def create_enrollment_plan(self, session: AsyncSession, *, study_id: UUID | str, payload: Mapping[str, Any] | Any | None = None, actor: Any | None = None, actor_id: UUID | None = None, correlation_id: UUID | str | None = None) -> EnrollmentPlan:
        return await self._create_scoped(session, EnrollmentPlan, entity_type="enrollment_plan", study_id=study_id, payload=payload, actor=actor, actor_id=actor_id, correlation_id=correlation_id, required_fields={"title"}, fields={"title", "target_quantity", "planning_period_start", "planning_period_end", "planning_scope", "owner_id", "status"}, defaults={"planning_scope": {}, "status": EnrollmentPlanStatus.DRAFT.value})

    async def create_readiness_criterion(self, session: AsyncSession, *, study_id: UUID | str, payload: Mapping[str, Any] | Any | None = None, actor: Any | None = None, actor_id: UUID | None = None, correlation_id: UUID | str | None = None) -> ReadinessCriterion:
        return await self._create_scoped(session, ReadinessCriterion, entity_type="readiness_criterion", study_id=study_id, payload=payload, actor=actor, actor_id=actor_id, correlation_id=correlation_id, required_fields={"name"}, fields={"name", "description", "status", "required", "due_at", "completed_at", "completed_by", "evidence_reference"}, defaults={"status": ReadinessCriterionStatus.OPEN.value, "required": True})

    async def create_operational_milestone(self, session: AsyncSession, *, study_id: UUID | str, payload: Mapping[str, Any] | Any | None = None, actor: Any | None = None, actor_id: UUID | None = None, correlation_id: UUID | str | None = None) -> StudyOperationalMilestone:
        return await self._create_scoped(session, StudyOperationalMilestone, entity_type="study_milestone", study_id=study_id, payload=payload, actor=actor, actor_id=actor_id, correlation_id=correlation_id, required_fields={"title", "milestone_type"}, fields={"title", "milestone_type", "planned_at", "completed_at", "owner_id", "notes", "status"}, defaults={"status": OperationalMilestoneStatus.PLANNED.value})

    async def create_dashboard_query(self, session: AsyncSession, *, study_id: UUID | str, payload: Mapping[str, Any] | Any | None = None, actor: Any | None = None, actor_id: UUID | None = None, correlation_id: UUID | str | None = None) -> DashboardQuery:
        return await self._create_scoped(session, DashboardQuery, entity_type="dashboard_query", study_id=study_id, payload=payload, actor=actor, actor_id=actor_id, correlation_id=correlation_id, required_fields={"name"}, fields={"name", "query_definition", "owner_id", "status"}, defaults={"query_definition": {}, "status": "Active"})

    async def create_report_query(self, session: AsyncSession, *, study_id: UUID | str, payload: Mapping[str, Any] | Any | None = None, actor: Any | None = None, actor_id: UUID | None = None, correlation_id: UUID | str | None = None) -> ReportQuery:
        return await self._create_scoped(session, ReportQuery, entity_type="report_query", study_id=study_id, payload=payload, actor=actor, actor_id=actor_id, correlation_id=correlation_id, required_fields={"name"}, fields={"name", "query_definition", "owner_id", "status"}, defaults={"query_definition": {}, "status": "Active"})

    create_plan = create_study_plan
    create_enrollment = create_enrollment_plan
    create_readiness_criterion = create_readiness_criterion
    create_milestone = create_operational_milestone


operational_study_service = OperationalStudyService()

__all__ = ["OperationalStudyService", "operational_study_service"]
