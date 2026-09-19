"""CTMS monitoring service.

This service owns operational monitoring plans and activities.  Protocol visit
definitions, visit instances, casebooks, and clinical data remain EDC-owned;
``edc_visit_instance_id`` is resolved as a stable, read-only reference only.
Methods use the caller's session and never commit, so monitoring data, audit,
status history, and outbox records share one transaction.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.ctms import ensure_utc, utc_now
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.request_context import get_actor, get_correlation_id
from app.models.ctms.monitoring import (
    MonitoringActivity,
    MonitoringActivityScheduleHistory,
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringPlan,
    MonitoringPlanStatus,
    MonitoringPlanVersion,
    MonitoringPlanVersionStatus,
)
from app.models.identity import User, UserStatus
from app.models.subject import Subject
from app.models.visit import VisitInstance
from app.services.ctms_atomicity_service import ctms_atomicity_service
from app.services.ctms_identity_service import CanonicalIdentityResolver
from app.services.ctms_ownership_guard import assert_ctms_command_safe
from app.services.notification_service import notification_service
from app.services.permission_service import PermissionService

_PLAN_VERSION_FIELDS = {
    "objectives",
    "activity_types",
    "frequency",
    "frequency_value",
    "frequency_unit",
    "cadence",
    "responsibilities",
    "scope",
    "completion_criteria",
    "risk_level",
    "risk_strategy",
    "monitoring_strategy",
    "risk_threshold",
    "thresholds",
}
_ACTIVITY_FIELDS = {
    "activity_type",
    "planned_date",
    "assigned_cra_id",
    "site_id",
    "edc_visit_instance_id",
    "issue_id",
    "issue_reference",
    "escalation_id",
    "escalation_reference",
}


def _mapping(value: Mapping[str, Any] | Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dict(dump(exclude_unset=True))
    raise ValidationError("CTMS monitoring payload must be a mapping")


def _uuid(value: UUID | str, field: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a canonical UUID", {"field": field}) from exc


def _actor_id(actor: Any | None = None, actor_id: UUID | None = None) -> UUID:
    value = actor_id
    if value is None and actor is not None:
        value = getattr(actor, "user_id", None) or getattr(actor, "id", None)
    if value is None:
        value = get_actor()
    if value is None:
        raise ValidationError("An actor is required for a monitoring mutation")
    return _uuid(value, "actor_id")


def _correlation(value: UUID | str | None, actor: Any | None = None) -> str:
    if value is not None:
        return str(value)
    return str(getattr(actor, "correlation_id", None) or get_correlation_id() or uuid4().hex)


def _correlation_uuid(value: UUID | str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return uuid5(NAMESPACE_URL, str(value))


def _timestamp(value: datetime | date | str | None, field: str = "timestamp") -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError(f"{field} must be an ISO timestamp") from exc
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min, tzinfo=UTC)
    try:
        return ensure_utc(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must include timezone information") from exc


def _stored_utc(value: datetime) -> datetime:
    """Normalize ORM-loaded timestamps (SQLite drops tzinfo) back to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return ensure_utc(value)


def _required_reason(reason: str | None, message: str = "A non-empty reason is required") -> str:
    if reason is None or not reason.strip():
        raise ValidationError(message)
    return reason.strip()


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _evidence(value: Mapping[str, Any] | str | None) -> dict[str, Any]:
    if value is None:
        raise ValidationError("Completion evidence is required")
    if isinstance(value, str):
        reference = value.strip()
        if not reference:
            raise ValidationError("Completion evidence is required")
        return {"reference": reference}
    if not isinstance(value, Mapping) or not value:
        raise ValidationError("Completion evidence is required")
    result = dict(value)
    if not any(str(result.get(key, "")).strip() for key in ("reference", "evidence_reference", "uri", "id")):
        # Structured evidence is allowed, but must not be an empty object.
        result["reference"] = json.dumps(result, sort_keys=True, separators=(",", ":"))
    return result


class MonitoringService:
    """Manage CTMS monitoring plans and operational monitoring activities."""

    def __init__(self, permission_service: PermissionService | None = None) -> None:
        self.permission_service = permission_service or PermissionService()

    async def _canonical_study_site(
        self,
        session: AsyncSession,
        study_id: UUID | str,
        site_id: UUID | str | None = None,
    ) -> tuple[UUID, UUID | None]:
        study = await CanonicalIdentityResolver(session).resolve_study(study_id)
        canonical_study_id = study.id
        if site_id is None:
            return canonical_study_id, None
        site = await CanonicalIdentityResolver(session).resolve_site(
            site_id, study_id=canonical_study_id
        )
        return canonical_study_id, site.id

    async def _canonical_visit(
        self,
        session: AsyncSession,
        visit_id: UUID | str,
        *,
        study_id: UUID,
        site_id: UUID | None,
    ) -> UUID:
        # Resolve by stable ID through the shared identity service first.  It
        # rejects display names and unknown/deleted records without mutation.
        visit_identity = await CanonicalIdentityResolver(session).resolve_visit_instance(visit_id)
        statement = (
            select(VisitInstance)
            .join(Subject, Subject.id == VisitInstance.subject_id)
            .where(
                VisitInstance.id == visit_identity.id,
                Subject.deleted_at.is_(None),
                Subject.study_id == study_id,
            )
        )
        if site_id is not None:
            statement = statement.where(Subject.site_id == site_id)
        result = await session.execute(statement)
        if result.scalars().first() is None:
            raise ConflictError(
                "Canonical EDC Visit_Instance is outside the monitoring scope",
                {"reason": "REFERENCE_SCOPE_MISMATCH"},
            )
        return visit_identity.id

    def _check_scope(self, user: Any | None, record: Any) -> None:
        """Apply the shared object-scope check when a hydrated user is supplied."""
        if user is None:
            return
        # Service callers that pass only actor_id do not have authorization
        # context. HTTP callers pass the hydrated current user and therefore
        # receive the same Permission_Service object check as other CTMS APIs.
        if hasattr(user, "user_roles"):
            self.permission_service.assert_object_access(user, record)

    async def _active_cra(
        self,
        session: AsyncSession,
        cra_id: UUID | str,
        *,
        study_id: UUID,
        site_id: UUID | None,
        user: Any | None = None,
    ) -> UUID:
        canonical_id = _uuid(cra_id, "assigned_cra_id")
        result = await session.execute(select(User).where(User.id == canonical_id))
        cra = result.scalars().first()
        if cra is None or cra.status in (UserStatus.inactive, UserStatus.inactive.value):
            raise ValidationError("Assigned CRA must be an active user")
        scope_record = type("MonitoringScope", (), {"study_id": study_id, "site_id": site_id})()
        self._check_scope(user, scope_record)
        return canonical_id

    @staticmethod
    def _version_data(values: Mapping[str, Any]) -> dict[str, Any]:
        unknown = set(values) - _PLAN_VERSION_FIELDS - {"correlation_id", "amendment_reason"}
        if unknown:
            raise ValidationError("Unknown monitoring plan version field", {"field": sorted(unknown)[0]})
        data = {field: values[field] for field in _PLAN_VERSION_FIELDS if field in values}
        data.setdefault("activity_types", [])
        data.setdefault("responsibilities", {})
        data.setdefault("scope", {})
        data.setdefault("thresholds", {})
        allowed_types = {item.value for item in MonitoringActivityType}
        invalid = set(data["activity_types"] or []) - allowed_types
        if invalid:
            raise ValidationError("Unsupported monitoring activity type", {"activity_type": sorted(invalid)[0]})
        return data

    async def _resolve_plan(self, session: AsyncSession, plan: MonitoringPlan | UUID | str) -> MonitoringPlan:
        if isinstance(plan, MonitoringPlan):
            return plan
        plan_id = _uuid(plan, "plan_id")
        result = await session.execute(
            select(MonitoringPlan)
            .options(selectinload(MonitoringPlan.versions))
            .where(MonitoringPlan.id == plan_id, MonitoringPlan.deleted_at.is_(None))
        )
        resolved = result.scalars().first()
        if resolved is None:
            raise NotFoundError("Monitoring plan was not found", {"plan_id": str(plan_id)})
        return resolved

    async def _resolve_version(
        self, session: AsyncSession, version: MonitoringPlanVersion | UUID | str
    ) -> MonitoringPlanVersion:
        if isinstance(version, MonitoringPlanVersion):
            return version
        version_id = _uuid(version, "plan_version_id")
        result = await session.execute(
            select(MonitoringPlanVersion).where(MonitoringPlanVersion.id == version_id)
        )
        resolved = result.scalars().first()
        if resolved is None:
            raise NotFoundError("Monitoring plan version was not found", {"plan_version_id": str(version_id)})
        return resolved

    async def _resolve_activity(
        self, session: AsyncSession, activity: MonitoringActivity | UUID | str
    ) -> MonitoringActivity:
        if isinstance(activity, MonitoringActivity):
            return activity
        activity_id = _uuid(activity, "activity_id")
        result = await session.execute(
            select(MonitoringActivity).where(
                MonitoringActivity.id == activity_id,
                MonitoringActivity.deleted_at.is_(None),
            )
        )
        resolved = result.scalars().first()
        if resolved is None:
            raise NotFoundError("Monitoring activity was not found", {"activity_id": str(activity_id)})
        return resolved

    async def create_plan(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | str,
        payload: Mapping[str, Any] | Any | None = None,
        site_id: UUID | str | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringPlan:
        values = _mapping(payload)
        assert_ctms_command_safe(values, operation="create_monitoring_plan")
        actor_uuid = _actor_id(actor, actor_id)
        canonical_study_id, canonical_site_id = await self._canonical_study_site(
            session, study_id, site_id or values.get("site_id")
        )
        scope = type("MonitoringScope", (), {"study_id": canonical_study_id, "site_id": canonical_site_id})()
        self._check_scope(user, scope)
        name = str(values.get("name") or "").strip()
        if not name:
            raise ValidationError("Monitoring plan name is required")
        unknown = set(values) - {"name", "description", "site_id", "correlation_id", "version"} - _PLAN_VERSION_FIELDS
        if unknown:
            raise ValidationError("Unknown monitoring plan field", {"field": sorted(unknown)[0]})
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)
        plan = MonitoringPlan(
            study_id=canonical_study_id,
            site_id=canonical_site_id,
            name=name,
            description=values.get("description"),
            status=MonitoringPlanStatus.DRAFT.value,
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=correlation,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(plan)
        await session.flush()
        version_values = _mapping(values.get("version"))
        if not version_values:
            version_values = {field: values[field] for field in _PLAN_VERSION_FIELDS if field in values}
        version_data = self._version_data(version_values)
        version = MonitoringPlanVersion(
            plan_id=plan.id,
            study_id=canonical_study_id,
            site_id=canonical_site_id,
            version_number=1,
            status=MonitoringPlanVersionStatus.DRAFT.value,
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=correlation,
            created_at=utc_now(),
            updated_at=utc_now(),
            **version_data,
        )
        session.add(version)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_plan",
            entity_id=plan.id,
            study_id=plan.study_id,
            site_id=plan.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["study_id", "site_id", "name", "description"],
            status=plan.status,
            payload={"study_id": plan.study_id, "site_id": plan.site_id, "version_id": version.id},
        )
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_plan_version",
            entity_id=version.id,
            study_id=version.study_id,
            site_id=version.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=sorted(version_data),
            status=version.status,
            payload={"plan_id": plan.id, "version_number": version.version_number},
        )
        return plan

    create_monitoring_plan = create_plan

    async def update_plan(
        self,
        session: AsyncSession,
        plan: MonitoringPlan | UUID | str,
        changes: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        reason: str | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringPlan:
        values = _mapping(changes)
        assert_ctms_command_safe(values, operation="update_monitoring_plan")
        resolved = await self._resolve_plan(session, plan)
        self._check_scope(user, resolved)
        if resolved.status == MonitoringPlanStatus.PUBLISHED.value:
            raise ConflictError("Published monitoring plans are immutable; amend by creating a new draft")
        unknown = set(values) - {"name", "description", "correlation_id"}
        if unknown:
            raise ValidationError("Unknown monitoring plan field", {"field": sorted(unknown)[0]})
        changed = [field for field in ("name", "description") if field in values and getattr(resolved, field) != values[field]]
        if not changed:
            return resolved
        if "name" in changed and not str(values["name"]).strip():
            raise ValidationError("Monitoring plan name is required")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)
        for field in changed:
            setattr(resolved, field, values[field])
        resolved.updated_by = actor_uuid
        resolved.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_plan",
            entity_id=resolved.id,
            study_id=resolved.study_id,
            site_id=resolved.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="update",
            changed_fields=changed,
            reason=reason.strip() if reason and reason.strip() else None,
            payload={"plan_id": resolved.id, "changed_fields": changed},
        )
        return resolved

    async def publish_plan(
        self,
        session: AsyncSession,
        plan: MonitoringPlan | UUID | str,
        *,
        version: MonitoringPlanVersion | UUID | str | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringPlanVersion:
        resolved_plan = await self._resolve_plan(session, plan)
        self._check_scope(user, resolved_plan)
        if resolved_plan.status == MonitoringPlanStatus.ARCHIVED.value:
            raise ConflictError("Archived monitoring plans cannot be published")
        resolved_version = await self._resolve_version(session, version) if version is not None else None
        if resolved_version is None:
            version_result = await session.execute(
                select(MonitoringPlanVersion).where(
                    MonitoringPlanVersion.plan_id == resolved_plan.id,
                    MonitoringPlanVersion.status == MonitoringPlanVersionStatus.DRAFT.value,
                )
            )
            drafts = list(version_result.scalars().all())
            if not drafts:
                raise ConflictError("Monitoring plan has no draft version to publish")
            resolved_version = max(drafts, key=lambda item: item.version_number)
        if resolved_version.plan_id != resolved_plan.id:
            raise ConflictError("Monitoring plan version does not belong to this plan")
        if resolved_version.status != MonitoringPlanVersionStatus.DRAFT.value:
            raise ConflictError("Only a draft monitoring plan version can be published")
        if not resolved_version.activity_types:
            raise ValidationError("A monitoring plan must define at least one activity type")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        resolved_version.status = MonitoringPlanVersionStatus.PUBLISHED.value
        resolved_version.published_by = actor_uuid
        resolved_version.published_at = utc_now()
        resolved_version.updated_by = actor_uuid
        resolved_version.updated_at = utc_now()
        resolved_plan.current_version_id = resolved_version.id
        resolved_plan.status = MonitoringPlanStatus.PUBLISHED.value
        resolved_plan.updated_by = actor_uuid
        resolved_plan.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_plan_version",
            entity_id=resolved_version.id,
            study_id=resolved_version.study_id,
            site_id=resolved_version.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="publish",
            changed_fields=["status", "published_by", "published_at"],
            previous_status=MonitoringPlanVersionStatus.DRAFT.value,
            status=resolved_version.status,
            payload={"plan_id": resolved_plan.id, "version_number": resolved_version.version_number},
        )
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_plan",
            entity_id=resolved_plan.id,
            study_id=resolved_plan.study_id,
            site_id=resolved_plan.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="publish",
            changed_fields=["status", "current_version_id"],
            previous_status=MonitoringPlanStatus.DRAFT.value,
            status=resolved_plan.status,
            payload={"version_id": resolved_version.id},
        )
        return resolved_version

    publish = publish_plan
    publish_version = publish_plan

    async def amend_plan(
        self,
        session: AsyncSession,
        plan: MonitoringPlan | UUID | str,
        changes: Mapping[str, Any] | Any | None = None,
        *,
        reason: str | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringPlanVersion:
        resolved_plan = await self._resolve_plan(session, plan)
        self._check_scope(user, resolved_plan)
        if resolved_plan.status != MonitoringPlanStatus.PUBLISHED.value:
            raise ConflictError("Only a published monitoring plan can be amended")
        amendment_reason = _required_reason(reason, "An amendment reason is required")
        version_result = await session.execute(
            select(MonitoringPlanVersion).where(MonitoringPlanVersion.plan_id == resolved_plan.id)
        )
        versions = list(version_result.scalars().all())
        current = next((v for v in versions if v.id == resolved_plan.current_version_id), None)
        if current is None:
            raise NotFoundError("Current published monitoring plan version was not found")
        values = _mapping(changes)
        assert_ctms_command_safe(values, operation="amend_monitoring_plan")
        version_data = {
            field: getattr(current, field)
            for field in _PLAN_VERSION_FIELDS
        }
        version_data.update(self._version_data(values))
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        version = MonitoringPlanVersion(
            plan_id=resolved_plan.id,
            study_id=resolved_plan.study_id,
            site_id=resolved_plan.site_id,
            version_number=max(v.version_number for v in versions) + 1,
            status=MonitoringPlanVersionStatus.DRAFT.value,
            amendment_reason=amendment_reason,
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=correlation,
            created_at=utc_now(),
            updated_at=utc_now(),
            **version_data,
        )
        session.add(version)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_plan_version",
            entity_id=version.id,
            study_id=version.study_id,
            site_id=version.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="amend",
            changed_fields=sorted(set(values) | {"version_number", "amendment_reason"}),
            reason=amendment_reason,
            status=version.status,
            payload={"plan_id": resolved_plan.id, "version_number": version.version_number},
        )
        return version

    amend = amend_plan
    amend_version = amend_plan

    async def list_versions(
        self, session: AsyncSession, plan: MonitoringPlan | UUID | str, *, published_only: bool = False
    ) -> list[MonitoringPlanVersion]:
        resolved_plan = await self._resolve_plan(session, plan)
        query = select(MonitoringPlanVersion).where(MonitoringPlanVersion.plan_id == resolved_plan.id)
        if published_only:
            query = query.where(MonitoringPlanVersion.status == MonitoringPlanVersionStatus.PUBLISHED.value)
        query = query.order_by(MonitoringPlanVersion.version_number.asc())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_published_versions(self, session: AsyncSession, plan: MonitoringPlan | UUID | str) -> list[MonitoringPlanVersion]:
        return await self.list_versions(session, plan, published_only=True)

    async def archive_plan(
        self,
        session: AsyncSession,
        plan: MonitoringPlan | UUID | str,
        *,
        reason: str,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringPlan:
        resolved = await self._resolve_plan(session, plan)
        self._check_scope(user, resolved)
        if resolved.status == MonitoringPlanStatus.ARCHIVED.value:
            return resolved
        actor_uuid = _actor_id(actor, actor_id)
        archive_reason = _required_reason(reason)
        correlation = _correlation(correlation_id, actor)
        previous = resolved.status
        resolved.status = MonitoringPlanStatus.ARCHIVED.value
        resolved.retention_state = "archived"
        resolved.archived_at = utc_now()
        resolved.archived_by = actor_uuid
        resolved.retention_reason = archive_reason
        resolved.updated_by = actor_uuid
        resolved.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_plan",
            entity_id=resolved.id,
            study_id=resolved.study_id,
            site_id=resolved.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="archive",
            changed_fields=["status", "retention_state", "archived_at", "archived_by"],
            previous_status=previous,
            status=resolved.status,
            reason=archive_reason,
            payload={"plan_id": resolved.id},
        )
        return resolved

    archive = archive_plan

    async def schedule_activity(
        self,
        session: AsyncSession,
        *,
        plan: MonitoringPlan | UUID | str,
        payload: Mapping[str, Any] | Any | None = None,
        activity_type: MonitoringActivityType | str | None = None,
        planned_date: datetime | date | str | None = None,
        assigned_cra_id: UUID | str | None = None,
        edc_visit_instance_id: UUID | str | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringActivity:
        values = _mapping(payload)
        assert_ctms_command_safe(values, operation="schedule_monitoring_activity")
        resolved_plan = await self._resolve_plan(session, plan)
        self._check_scope(user, resolved_plan)
        if resolved_plan.status != MonitoringPlanStatus.PUBLISHED.value or resolved_plan.current_version_id is None:
            raise ConflictError("Activities require a published monitoring plan")
        unknown = set(values) - _ACTIVITY_FIELDS - {"correlation_id", "reason"}
        if unknown:
            raise ValidationError("Unknown monitoring activity field", {"field": sorted(unknown)[0]})
        study_id = resolved_plan.study_id
        site_value = values.get("site_id", resolved_plan.site_id)
        _, site_id = await self._canonical_study_site(session, study_id, site_value)
        kind = _enum_value(activity_type or values.get("activity_type") or "")
        if kind not in {item.value for item in MonitoringActivityType}:
            raise ValidationError("Unsupported monitoring activity type", {"activity_type": kind})
        scheduled_at = _timestamp(planned_date or values.get("planned_date"), "planned_date")
        if scheduled_at is None:
            raise ValidationError("planned_date is required")
        actor_uuid = _actor_id(actor, actor_id)
        cra_value = assigned_cra_id or values.get("assigned_cra_id")
        cra_id = await self._active_cra(session, cra_value, study_id=study_id, site_id=site_id, user=user) if cra_value else None
        visit_value = edc_visit_instance_id or values.get("edc_visit_instance_id")
        visit_id = await self._canonical_visit(session, visit_value, study_id=study_id, site_id=site_id) if visit_value else None
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)
        activity = MonitoringActivity(
            plan_version_id=resolved_plan.current_version_id,
            study_id=study_id,
            site_id=site_id,
            activity_type=kind,
            planned_date=scheduled_at,
            assigned_cra_id=cra_id,
            status=MonitoringActivityStatus.SCHEDULED.value,
            edc_visit_instance_id=visit_id,
            issue_id=values.get("issue_id"),
            issue_reference=values.get("issue_reference"),
            escalation_id=values.get("escalation_id"),
            escalation_reference=values.get("escalation_reference"),
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=correlation,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(activity)
        await session.flush()
        history = MonitoringActivityScheduleHistory(
            activity_id=activity.id,
            previous_planned_date=None,
            planned_date=scheduled_at,
            reason=str(values.get("reason") or "Initial schedule"),
            changed_by=actor_uuid,
            correlation_id=correlation,
            changed_at=utc_now(),
        )
        session.add(history)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_activity",
            entity_id=activity.id,
            study_id=study_id,
            site_id=site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="schedule",
            changed_fields=["plan_version_id", "activity_type", "planned_date", "assigned_cra_id", "edc_visit_instance_id"],
            status=activity.status,
            payload={"plan_id": resolved_plan.id, "activity_id": activity.id, "edc_visit_instance_id": visit_id},
        )
        if activity.assigned_cra_id is not None:
            await notification_service.on_monitoring_assigned(
                session, activity, correlation_id=correlation
            )
        return activity

    schedule = schedule_activity
    create_activity = schedule_activity

    async def assign_activity(
        self,
        session: AsyncSession,
        activity: MonitoringActivity | UUID | str,
        assigned_cra_id: UUID | str,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringActivity:
        resolved = await self._resolve_activity(session, activity)
        cra_id = await self._active_cra(session, assigned_cra_id, study_id=resolved.study_id, site_id=resolved.site_id, user=user)
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        if resolved.assigned_cra_id == cra_id:
            return resolved
        resolved.assigned_cra_id = cra_id
        resolved.updated_by = actor_uuid
        resolved.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_activity",
            entity_id=resolved.id,
            study_id=resolved.study_id,
            site_id=resolved.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="assign",
            changed_fields=["assigned_cra_id"],
            status=resolved.status,
            payload={"assigned_cra_id": cra_id},
        )
        await notification_service.on_monitoring_assigned(
            session, resolved, correlation_id=correlation
        )
        return resolved

    async def reschedule_activity(
        self,
        session: AsyncSession,
        activity: MonitoringActivity | UUID | str,
        planned_date: datetime | date | str,
        reason: str | None = None,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringActivity:
        resolved = await self._resolve_activity(session, activity)
        self._check_scope(user, resolved)
        if resolved.status in {MonitoringActivityStatus.COMPLETED.value, MonitoringActivityStatus.CANCELLED.value}:
            raise ConflictError("Completed or cancelled monitoring activities cannot be rescheduled")
        new_date = _timestamp(planned_date, "planned_date")
        assert new_date is not None
        change_reason = _required_reason(reason, "A rescheduling reason is required")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        previous_date = _stored_utc(resolved.planned_date)
        resolved.planned_date = new_date
        resolved.status = MonitoringActivityStatus.RESCHEDULED.value
        resolved.updated_by = actor_uuid
        resolved.updated_at = utc_now()
        history = MonitoringActivityScheduleHistory(
            activity_id=resolved.id,
            previous_planned_date=previous_date,
            planned_date=new_date,
            reason=change_reason,
            changed_by=actor_uuid,
            correlation_id=correlation,
            changed_at=utc_now(),
        )
        session.add(history)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_activity",
            entity_id=resolved.id,
            study_id=resolved.study_id,
            site_id=resolved.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="reschedule",
            changed_fields=["planned_date", "status"],
            previous_status=MonitoringActivityStatus.SCHEDULED.value,
            status=resolved.status,
            reason=change_reason,
            payload={"previous_planned_date": previous_date, "planned_date": new_date},
        )
        await notification_service.on_monitoring_rescheduled(
            session,
            resolved,
            previous_planned_date=previous_date,
            correlation_id=correlation,
        )
        return resolved

    reschedule = reschedule_activity

    async def process_overdue_activities(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> int:
        """Mark due activities overdue and notify scoped CTMS recipients once."""
        timestamp = _stored_utc(now or utc_now())
        result = await session.execute(select(MonitoringActivity))
        activities = list(result.scalars().all())
        changed = 0
        for activity in activities:
            if activity.status in {
                MonitoringActivityStatus.COMPLETED.value,
                MonitoringActivityStatus.CANCELLED.value,
                MonitoringActivityStatus.OVERDUE.value,
            }:
                continue
            if _stored_utc(activity.planned_date) > timestamp:
                continue
            activity.status = MonitoringActivityStatus.OVERDUE.value
            activity.updated_at = timestamp
            await session.flush()
            await notification_service.on_monitoring_overdue(
                session, activity, correlation_id=str(activity.correlation_id)
            )
            changed += 1
        return changed

    mark_overdue = process_overdue_activities

    async def complete_activity(
        self,
        session: AsyncSession,
        activity: MonitoringActivity | UUID | str,
        evidence: Mapping[str, Any] | str | None = None,
        notes: str | None = None,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringActivity:
        resolved = await self._resolve_activity(session, activity)
        self._check_scope(user, resolved)
        if resolved.status in {MonitoringActivityStatus.COMPLETED.value, MonitoringActivityStatus.CANCELLED.value}:
            raise ConflictError("Only active monitoring activities can be completed")
        completion_evidence = _evidence(evidence)
        assert_ctms_command_safe({"evidence": completion_evidence, "notes": notes}, operation="complete_monitoring_activity")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        resolved.status = MonitoringActivityStatus.COMPLETED.value
        resolved.completion_evidence = completion_evidence
        resolved.completion_notes = notes
        resolved.completed_by = actor_uuid
        resolved.completed_at = utc_now()
        resolved.updated_by = actor_uuid
        resolved.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_activity",
            entity_id=resolved.id,
            study_id=resolved.study_id,
            site_id=resolved.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="complete",
            changed_fields=["status", "completion_evidence", "completion_notes", "completed_by", "completed_at"],
            previous_status=MonitoringActivityStatus.SCHEDULED.value,
            status=resolved.status,
            payload={"edc_visit_instance_id": resolved.edc_visit_instance_id},
        )
        return resolved

    complete = complete_activity

    async def cancel_activity(
        self,
        session: AsyncSession,
        activity: MonitoringActivity | UUID | str,
        reason: str | None = None,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringActivity:
        resolved = await self._resolve_activity(session, activity)
        self._check_scope(user, resolved)
        if resolved.status in {MonitoringActivityStatus.COMPLETED.value, MonitoringActivityStatus.CANCELLED.value}:
            raise ConflictError("Completed or cancelled monitoring activities cannot be cancelled")
        cancellation_reason = _required_reason(reason, "A cancellation reason is required")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        resolved.status = MonitoringActivityStatus.CANCELLED.value
        resolved.cancellation_reason = cancellation_reason
        resolved.cancelled_by = actor_uuid
        resolved.cancelled_at = utc_now()
        resolved.updated_by = actor_uuid
        resolved.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_activity",
            entity_id=resolved.id,
            study_id=resolved.study_id,
            site_id=resolved.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="cancel",
            changed_fields=["status", "cancellation_reason", "cancelled_by", "cancelled_at"],
            status=resolved.status,
            reason=cancellation_reason,
            payload={"edc_visit_instance_id": resolved.edc_visit_instance_id},
        )
        return resolved

    cancel = cancel_activity


monitoring_service = MonitoringService()

__all__ = ["MonitoringService", "monitoring_service"]
