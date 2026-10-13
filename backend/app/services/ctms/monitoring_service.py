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
    MonitoringActionItem,
    MonitoringActivity,
    MonitoringActivityScheduleHistory,
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringChecklistResult,
    MonitoringFinding,
    MonitoringFindingStatus,
    MonitoringPlan,
    MonitoringPlanStatus,
    MonitoringPlanVersion,
    MonitoringPlanVersionStatus,
    MonitoringReportStatus,
    MonitoringRule,
    MonitoringVisitActivity,
    MonitoringVisitModality,
    MonitoringVisitReport,
)
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitInstance
from app.models.shared.identity import User, UserStatus
from app.services.ctms.ctms_atomicity_service import ctms_atomicity_service
from app.services.ctms.ctms_identity_service import CanonicalIdentityResolver
from app.services.ctms.ctms_ownership_guard import assert_ctms_command_safe
from app.services.shared.notification_service import notification_service
from app.services.shared.permission_service import PermissionService

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
    "modality",
}

_RULE_FIELDS = {
    "visit_type",
    "frequency_value",
    "frequency_unit",
    "trigger",
    "allowed_modalities",
    "expected_duration_hours",
    "required_activities",
    "report_due_days",
    "sort_order",
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
    if not any(
        str(result.get(key, "")).strip() for key in ("reference", "evidence_reference", "uri", "id")
    ):
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
        unknown = (
            set(values)
            - _PLAN_VERSION_FIELDS
            - {
                "correlation_id",
                "amendment_reason",
                "visit_rules",
            }
        )
        if unknown:
            raise ValidationError(
                "Unknown monitoring plan version field", {"field": sorted(unknown)[0]}
            )
        data = {field: values[field] for field in _PLAN_VERSION_FIELDS if field in values}
        data.setdefault("activity_types", [])
        if not data["activity_types"] and values.get("visit_rules"):
            data["activity_types"] = [
                _enum_value(_mapping(rule).get("visit_type", "")) for rule in values["visit_rules"]
            ]
        data.setdefault("responsibilities", {})
        data.setdefault("scope", {})
        data.setdefault("thresholds", {})
        allowed_types = {item.value for item in MonitoringActivityType}
        invalid = set(data["activity_types"] or []) - allowed_types
        if invalid:
            raise ValidationError(
                "Unsupported monitoring activity type", {"activity_type": sorted(invalid)[0]}
            )
        return data

    @staticmethod
    def _rule_data(value: Mapping[str, Any] | Any, *, sort_order: int) -> dict[str, Any]:
        data = _mapping(value)
        unknown = set(data) - _RULE_FIELDS
        if unknown:
            raise ValidationError("Unknown monitoring rule field", {"field": sorted(unknown)[0]})
        visit_type = _enum_value(data.get("visit_type", ""))
        if visit_type not in {item.value for item in MonitoringActivityType}:
            raise ValidationError("Unsupported monitoring visit type", {"visit_type": visit_type})
        modalities = [_enum_value(item) for item in data.get("allowed_modalities", [])]
        invalid_modalities = set(modalities) - {item.value for item in MonitoringVisitModality}
        if invalid_modalities:
            raise ValidationError(
                "Unsupported monitoring visit modality",
                {"modality": sorted(invalid_modalities)[0]},
            )
        required = []
        for index, activity in enumerate(data.get("required_activities", [])):
            if isinstance(activity, Mapping):
                label = str(activity.get("requirement") or activity.get("label") or "").strip()
                key = str(activity.get("key") or f"activity-{index + 1}")
                reference = activity.get("plan_reference")
            else:
                label = str(activity).strip()
                key = f"activity-{index + 1}"
                reference = None
            if not label:
                raise ValidationError("Monitoring rule activities must not be blank")
            required.append({"key": key, "requirement": label, "plan_reference": reference})
        return {
            "visit_type": visit_type,
            "frequency_value": data.get("frequency_value"),
            "frequency_unit": data.get("frequency_unit"),
            "trigger": data.get("trigger"),
            "allowed_modalities": modalities,
            "expected_duration_hours": data.get("expected_duration_hours"),
            "required_activities": required,
            "report_due_days": data.get("report_due_days", 10),
            "sort_order": data.get("sort_order", sort_order),
        }

    async def _add_rules(
        self,
        session: AsyncSession,
        version: MonitoringPlanVersion,
        values: list[Any],
    ) -> None:
        for index, raw in enumerate(values):
            session.add(
                MonitoringRule(
                    plan_version_id=version.id,
                    **self._rule_data(raw, sort_order=index),
                )
            )
        await session.flush()

    async def _resolve_plan(
        self, session: AsyncSession, plan: MonitoringPlan | UUID | str
    ) -> MonitoringPlan:
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
            raise NotFoundError(
                "Monitoring plan version was not found", {"plan_version_id": str(version_id)}
            )
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
            raise NotFoundError(
                "Monitoring activity was not found", {"activity_id": str(activity_id)}
            )
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
        scope = type(
            "MonitoringScope", (), {"study_id": canonical_study_id, "site_id": canonical_site_id}
        )()
        self._check_scope(user, scope)
        name = str(values.get("name") or "").strip()
        if not name:
            raise ValidationError("Monitoring plan name is required")
        unknown = (
            set(values)
            - {"name", "description", "site_id", "correlation_id", "version"}
            - _PLAN_VERSION_FIELDS
        )
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
            version_values = {
                field: values[field] for field in _PLAN_VERSION_FIELDS if field in values
            }
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
        await self._add_rules(session, version, list(version_values.get("visit_rules") or []))
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
            raise ConflictError(
                "Published monitoring plans are immutable; amend by creating a new draft"
            )
        unknown = set(values) - {"name", "description", "correlation_id"}
        if unknown:
            raise ValidationError("Unknown monitoring plan field", {"field": sorted(unknown)[0]})
        changed = [
            field
            for field in ("name", "description")
            if field in values and getattr(resolved, field) != values[field]
        ]
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
        resolved_version = (
            await self._resolve_version(session, version) if version is not None else None
        )
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
            payload={
                "plan_id": resolved_plan.id,
                "version_number": resolved_version.version_number,
            },
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
        version_data = {field: getattr(current, field) for field in _PLAN_VERSION_FIELDS}
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
        if "visit_rules" in values:
            await self._add_rules(session, version, list(values.get("visit_rules") or []))
        else:
            current_rules = list(
                (
                    await session.execute(
                        select(MonitoringRule)
                        .where(MonitoringRule.plan_version_id == current.id)
                        .order_by(MonitoringRule.sort_order)
                    )
                )
                .scalars()
                .all()
            )
            await self._add_rules(
                session,
                version,
                [{field: getattr(rule, field) for field in _RULE_FIELDS} for rule in current_rules],
            )
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
        self,
        session: AsyncSession,
        plan: MonitoringPlan | UUID | str,
        *,
        published_only: bool = False,
    ) -> list[MonitoringPlanVersion]:
        resolved_plan = await self._resolve_plan(session, plan)
        query = select(MonitoringPlanVersion).where(
            MonitoringPlanVersion.plan_id == resolved_plan.id
        )
        if published_only:
            query = query.where(
                MonitoringPlanVersion.status == MonitoringPlanVersionStatus.PUBLISHED.value
            )
        query = query.order_by(MonitoringPlanVersion.version_number.asc())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_published_versions(
        self, session: AsyncSession, plan: MonitoringPlan | UUID | str
    ) -> list[MonitoringPlanVersion]:
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
        if (
            resolved_plan.status != MonitoringPlanStatus.PUBLISHED.value
            or resolved_plan.current_version_id is None
        ):
            raise ConflictError("Activities require a published monitoring plan")
        unknown = set(values) - _ACTIVITY_FIELDS - {"correlation_id", "reason"}
        if unknown:
            raise ValidationError(
                "Unknown monitoring activity field", {"field": sorted(unknown)[0]}
            )
        study_id = resolved_plan.study_id
        site_value = values.get("site_id", resolved_plan.site_id)
        _, site_id = await self._canonical_study_site(session, study_id, site_value)
        kind = _enum_value(activity_type or values.get("activity_type") or "")
        if kind not in {item.value for item in MonitoringActivityType}:
            raise ValidationError("Unsupported monitoring activity type", {"activity_type": kind})
        scheduled_at = _timestamp(planned_date or values.get("planned_date"), "planned_date")
        if scheduled_at is None:
            raise ValidationError("planned_date is required")
        modality = _enum_value(values.get("modality") or MonitoringVisitModality.ON_SITE.value)
        if modality not in {item.value for item in MonitoringVisitModality}:
            raise ValidationError("Unsupported monitoring visit modality", {"modality": modality})
        rule = (
            (
                await session.execute(
                    select(MonitoringRule).where(
                        MonitoringRule.plan_version_id == resolved_plan.current_version_id,
                        MonitoringRule.visit_type == kind,
                    )
                )
            )
            .scalars()
            .first()
        )
        if rule is not None and rule.allowed_modalities and modality not in rule.allowed_modalities:
            raise ValidationError(
                "Visit modality is not permitted by the approved monitoring plan",
                {"modality": modality, "visit_type": kind},
            )
        actor_uuid = _actor_id(actor, actor_id)
        cra_value = assigned_cra_id or values.get("assigned_cra_id")
        cra_id = (
            await self._active_cra(
                session, cra_value, study_id=study_id, site_id=site_id, user=user
            )
            if cra_value
            else None
        )
        visit_value = edc_visit_instance_id or values.get("edc_visit_instance_id")
        visit_id = (
            await self._canonical_visit(session, visit_value, study_id=study_id, site_id=site_id)
            if visit_value
            else None
        )
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)
        activity = MonitoringActivity(
            plan_version_id=resolved_plan.current_version_id,
            study_id=study_id,
            site_id=site_id,
            activity_type=kind,
            modality=modality,
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
        activity.visit_code = f"MV-{scheduled_at.year}-{str(activity.id).split('-')[0].upper()}"
        if rule is not None:
            for index, required in enumerate(rule.required_activities):
                item = required if isinstance(required, Mapping) else {"requirement": required}
                requirement = str(item.get("requirement") or "").strip()
                if not requirement:
                    continue
                session.add(
                    MonitoringVisitActivity(
                        visit_id=activity.id,
                        rule_id=rule.id,
                        study_id=activity.study_id,
                        site_id=activity.site_id,
                        requirement_key=str(item.get("key") or f"activity-{index + 1}"),
                        requirement=requirement,
                        plan_reference=item.get("plan_reference"),
                        result=MonitoringChecklistResult.PENDING.value,
                        sort_order=index,
                        created_by=actor_uuid,
                        updated_by=actor_uuid,
                        correlation_id=correlation,
                        created_at=utc_now(),
                        updated_at=utc_now(),
                    )
                )
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
            changed_fields=[
                "plan_version_id",
                "activity_type",
                "modality",
                "planned_date",
                "assigned_cra_id",
                "edc_visit_instance_id",
            ],
            status=activity.status,
            payload={
                "plan_id": resolved_plan.id,
                "activity_id": activity.id,
                "edc_visit_instance_id": visit_id,
            },
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
        cra_id = await self._active_cra(
            session,
            assigned_cra_id,
            study_id=resolved.study_id,
            site_id=resolved.site_id,
            user=user,
        )
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
        if resolved.status in {
            MonitoringActivityStatus.COMPLETED.value,
            MonitoringActivityStatus.CANCELLED.value,
        }:
            raise ConflictError(
                "Completed or cancelled monitoring activities cannot be rescheduled"
            )
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

    async def start_activity(
        self,
        session: AsyncSession,
        activity: MonitoringActivity | UUID | str,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringActivity:
        resolved = await self._resolve_activity(session, activity)
        self._check_scope(user, resolved)
        if resolved.status not in {
            MonitoringActivityStatus.PLANNED.value,
            MonitoringActivityStatus.SCHEDULED.value,
            MonitoringActivityStatus.RESCHEDULED.value,
            MonitoringActivityStatus.OVERDUE.value,
        }:
            raise ConflictError("Only an active monitoring visit can be started")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        previous = resolved.status
        resolved.status = MonitoringActivityStatus.IN_PROGRESS.value
        resolved.actual_start_at = utc_now()
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
            action="start",
            changed_fields=["status", "actual_start_at"],
            previous_status=previous,
            status=resolved.status,
            payload={"plan_version_id": resolved.plan_version_id},
        )
        return resolved

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
        if resolved.status in {
            MonitoringActivityStatus.COMPLETED.value,
            MonitoringActivityStatus.CANCELLED.value,
        }:
            raise ConflictError("Only active monitoring activities can be completed")
        checklist = await self.list_checklist(session, resolved)
        pending = [
            item.requirement_key
            for item in checklist
            if item.result == MonitoringChecklistResult.PENDING.value
        ]
        if pending:
            raise ConflictError(
                "All monitoring checklist items must be documented before completion",
                {"pending_requirements": pending},
            )
        completion_evidence = _evidence(evidence)
        assert_ctms_command_safe(
            {"evidence": completion_evidence, "notes": notes},
            operation="complete_monitoring_activity",
        )
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        resolved.status = MonitoringActivityStatus.COMPLETED.value
        resolved.completion_evidence = completion_evidence
        resolved.completion_notes = notes
        resolved.completed_by = actor_uuid
        resolved.completed_at = utc_now()
        resolved.actual_start_at = resolved.actual_start_at or resolved.completed_at
        resolved.actual_end_at = resolved.completed_at
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
            changed_fields=[
                "status",
                "completion_evidence",
                "completion_notes",
                "completed_by",
                "completed_at",
                "actual_start_at",
                "actual_end_at",
            ],
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
        if resolved.status in {
            MonitoringActivityStatus.COMPLETED.value,
            MonitoringActivityStatus.CANCELLED.value,
        }:
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

    async def list_checklist(
        self, session: AsyncSession, visit: MonitoringActivity | UUID | str
    ) -> list[MonitoringVisitActivity]:
        resolved = await self._resolve_activity(session, visit)
        result = await session.execute(
            select(MonitoringVisitActivity)
            .where(MonitoringVisitActivity.visit_id == resolved.id)
            .order_by(MonitoringVisitActivity.sort_order, MonitoringVisitActivity.created_at)
        )
        return list(result.scalars().all())

    async def add_checklist_item(
        self,
        session: AsyncSession,
        visit: MonitoringActivity | UUID | str,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringVisitActivity:
        resolved = await self._resolve_activity(session, visit)
        self._check_scope(user, resolved)
        if resolved.status in {
            MonitoringActivityStatus.COMPLETED.value,
            MonitoringActivityStatus.CANCELLED.value,
        }:
            raise ConflictError("Checklist requirements cannot be added to a closed visit")
        values = _mapping(payload)
        requirement = str(values.get("requirement") or "").strip()
        key = str(values.get("requirement_key") or "").strip()
        if not requirement or not key:
            raise ValidationError("Checklist requirement and key are required")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        item = MonitoringVisitActivity(
            visit_id=resolved.id,
            study_id=resolved.study_id,
            site_id=resolved.site_id,
            requirement_key=key,
            requirement=requirement,
            plan_reference=values.get("plan_reference"),
            result=MonitoringChecklistResult.PENDING.value,
            sort_order=int(values.get("sort_order", 0)),
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=correlation,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(item)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_visit_activity",
            entity_id=item.id,
            study_id=item.study_id,
            site_id=item.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["requirement_key", "requirement", "plan_reference"],
            status=item.result,
            payload={"visit_id": resolved.id},
        )
        return item

    async def update_checklist_item(
        self,
        session: AsyncSession,
        item_id: UUID | str,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringVisitActivity:
        item = await session.get(MonitoringVisitActivity, _uuid(item_id, "checklist_item_id"))
        if item is None or item.deleted_at is not None:
            raise NotFoundError("Monitoring checklist item was not found")
        self._check_scope(user, item)
        visit = await self._resolve_activity(session, item.visit_id)
        if visit.status in {
            MonitoringActivityStatus.COMPLETED.value,
            MonitoringActivityStatus.CANCELLED.value,
        }:
            raise ConflictError("Checklist results cannot be changed after visit closure")
        values = _mapping(payload)
        allowed = {
            "result",
            "review_details",
            "observations",
            "subject_reference",
            "record_reference",
            "evidence_references",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValidationError("Unknown checklist result field", {"field": sorted(unknown)[0]})
        result = _enum_value(values.get("result") or item.result)
        if result not in {choice.value for choice in MonitoringChecklistResult}:
            raise ValidationError("Unsupported checklist result", {"result": result})
        if (
            result == MonitoringChecklistResult.NOT_APPLICABLE.value
            and not str(values.get("review_details") or "").strip()
        ):
            raise ValidationError("Not Applicable requires review details")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        previous = item.result
        for field in allowed - {"result"}:
            if field in values:
                setattr(item, field, values[field])
        item.result = result
        item.completed_at = None if result == MonitoringChecklistResult.PENDING.value else utc_now()
        item.completed_by = (
            None if result == MonitoringChecklistResult.PENDING.value else actor_uuid
        )
        item.updated_by = actor_uuid
        item.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_visit_activity",
            entity_id=item.id,
            study_id=item.study_id,
            site_id=item.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="record_result",
            changed_fields=sorted(values),
            previous_status=previous,
            status=item.result,
            payload={"visit_id": item.visit_id},
        )
        return item

    async def list_reports(
        self, session: AsyncSession, visit: MonitoringActivity | UUID | str
    ) -> list[MonitoringVisitReport]:
        resolved = await self._resolve_activity(session, visit)
        result = await session.execute(
            select(MonitoringVisitReport)
            .where(MonitoringVisitReport.visit_id == resolved.id)
            .order_by(MonitoringVisitReport.version_number)
        )
        return list(result.scalars().all())

    async def create_report(
        self,
        session: AsyncSession,
        visit: MonitoringActivity | UUID | str,
        payload: Mapping[str, Any] | Any | None = None,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringVisitReport:
        resolved = await self._resolve_activity(session, visit)
        self._check_scope(user, resolved)
        if resolved.status == MonitoringActivityStatus.CANCELLED.value:
            raise ConflictError("A report cannot be created for a cancelled visit")
        existing = await self.list_reports(session, resolved)
        if existing and existing[-1].status != MonitoringReportStatus.FINALIZED.value:
            raise ConflictError("The visit already has an active monitoring report")
        values = _mapping(payload)
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        previous = existing[-1] if existing else None
        report = MonitoringVisitReport(
            visit_id=resolved.id,
            previous_report_id=previous.id if previous else None,
            version_number=(previous.version_number + 1) if previous else 1,
            study_id=resolved.study_id,
            site_id=resolved.site_id,
            status=MonitoringReportStatus.DRAFT.value,
            content=dict(values.get("content") or (previous.content if previous else {})),
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=correlation,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(report)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_visit_report",
            entity_id=report.id,
            study_id=report.study_id,
            site_id=report.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["visit_id", "version_number", "content"],
            status=report.status,
            payload={"visit_id": report.visit_id, "version_number": report.version_number},
        )
        return report

    async def update_report(
        self,
        session: AsyncSession,
        report_id: UUID | str,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringVisitReport:
        report = await session.get(MonitoringVisitReport, _uuid(report_id, "report_id"))
        if report is None or report.deleted_at is not None:
            raise NotFoundError("Monitoring visit report was not found")
        self._check_scope(user, report)
        if report.status not in {
            MonitoringReportStatus.DRAFT.value,
            MonitoringReportStatus.REVISION_REQUIRED.value,
        }:
            raise ConflictError("Only draft or revision-required reports can be edited")
        values = _mapping(payload)
        if "content" not in values:
            raise ValidationError("Structured report content is required")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        report.content = dict(values["content"])
        report.updated_by = actor_uuid
        report.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_visit_report",
            entity_id=report.id,
            study_id=report.study_id,
            site_id=report.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="update",
            changed_fields=["content"],
            status=report.status,
            payload={"visit_id": report.visit_id},
        )
        return report

    async def transition_report(
        self,
        session: AsyncSession,
        report_id: UUID | str,
        action: str,
        *,
        comments: str | None = None,
        document_reference: str | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringVisitReport:
        report = await session.get(MonitoringVisitReport, _uuid(report_id, "report_id"))
        if report is None or report.deleted_at is not None:
            raise NotFoundError("Monitoring visit report was not found")
        self._check_scope(user, report)
        normalized = action.strip().lower().replace("-", "_").replace(" ", "_")
        transitions = {
            "submit": (
                {
                    MonitoringReportStatus.DRAFT.value,
                    MonitoringReportStatus.REVISION_REQUIRED.value,
                },
                MonitoringReportStatus.SUBMITTED.value,
            ),
            "start_review": (
                {MonitoringReportStatus.SUBMITTED.value},
                MonitoringReportStatus.UNDER_REVIEW.value,
            ),
            "request_revision": (
                {MonitoringReportStatus.UNDER_REVIEW.value},
                MonitoringReportStatus.REVISION_REQUIRED.value,
            ),
            "approve": (
                {MonitoringReportStatus.UNDER_REVIEW.value},
                MonitoringReportStatus.APPROVED.value,
            ),
            "finalize": (
                {MonitoringReportStatus.APPROVED.value},
                MonitoringReportStatus.FINALIZED.value,
            ),
        }
        if normalized not in transitions:
            raise ValidationError("Unsupported monitoring report action", {"action": action})
        allowed, target = transitions[normalized]
        if report.status not in allowed:
            raise ConflictError(
                "Monitoring report transition is not allowed",
                {"status": report.status, "action": normalized},
            )
        if normalized == "request_revision" and not str(comments or "").strip():
            raise ValidationError("Reviewer comments are required when requesting revision")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        previous = report.status
        now = utc_now()
        report.status = target
        report.reviewer_comments = comments if comments is not None else report.reviewer_comments
        if normalized == "submit":
            report.submitted_at, report.submitted_by = now, actor_uuid
        elif normalized in {"start_review", "request_revision"}:
            report.reviewed_at, report.reviewed_by = now, actor_uuid
        elif normalized == "approve":
            report.approved_at, report.approved_by = now, actor_uuid
        elif normalized == "finalize":
            # Build the controlled snapshot before the single finalizing flush;
            # otherwise an autoflush would make the newly-finalized row
            # immutable before its snapshot fields are populated.
            with session.no_autoflush:
                visit = await self._resolve_activity(session, report.visit_id)
                if visit.status != MonitoringActivityStatus.COMPLETED.value:
                    raise ConflictError(
                        "A monitoring report can be finalized only after the visit is completed"
                    )
                checklist = await self.list_checklist(session, report.visit_id)
                findings = list(
                    (
                        await session.execute(
                            select(MonitoringFinding).where(
                                MonitoringFinding.visit_id == report.visit_id
                            )
                        )
                    ).scalars()
                )
            report.finalized_at, report.finalized_by = now, actor_uuid
            report.document_reference = document_reference
            report.controlled_snapshot = {
                "report_id": str(report.id),
                "version_number": report.version_number,
                "finalized_at": now.isoformat().replace("+00:00", "Z"),
                "finalized_by": str(actor_uuid),
                "content": report.content,
                "checklist": [
                    {
                        "requirement": item.requirement,
                        "result": item.result,
                        "observations": item.observations,
                        "completed_by": str(item.completed_by) if item.completed_by else None,
                    }
                    for item in checklist
                ],
                "findings": [
                    {"finding_code": item.finding_code, "status": item.status} for item in findings
                ],
            }
        report.updated_by = actor_uuid
        report.updated_at = now
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_visit_report",
            entity_id=report.id,
            study_id=report.study_id,
            site_id=report.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action=normalized,
            changed_fields=["status"],
            previous_status=previous,
            status=report.status,
            reason=comments,
            payload={"visit_id": report.visit_id, "version_number": report.version_number},
        )
        return report

    async def create_finding(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | str,
        payload: Mapping[str, Any] | Any,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringFinding:
        values = _mapping(payload)
        canonical_study_id, canonical_site_id = await self._canonical_study_site(
            session, study_id, values.get("site_id")
        )
        visit = None
        if values.get("visit_id"):
            visit = await self._resolve_activity(session, values["visit_id"])
            if visit.study_id != canonical_study_id or (
                canonical_site_id is not None and visit.site_id != canonical_site_id
            ):
                raise ConflictError("Finding source visit is outside the requested scope")
            canonical_site_id = canonical_site_id or visit.site_id
        report_id = values.get("report_id")
        if report_id:
            report = await session.get(MonitoringVisitReport, _uuid(report_id, "report_id"))
            if report is None or report.study_id != canonical_study_id:
                raise ConflictError("Finding source report is outside the requested scope")
            if canonical_site_id is not None and report.site_id != canonical_site_id:
                raise ConflictError("Finding source report is outside the requested site scope")
            canonical_site_id = canonical_site_id or report.site_id
            if visit and report.visit_id != visit.id:
                raise ConflictError("Finding report and visit do not match")
        scope = type(
            "MonitoringScope", (), {"study_id": canonical_study_id, "site_id": canonical_site_id}
        )()
        self._check_scope(user, scope)
        category = str(values.get("category") or "").strip()
        description = str(values.get("description") or "").strip()
        if not category or not description:
            raise ValidationError("Finding category and description are required")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        finding_uuid = uuid4()
        finding = MonitoringFinding(
            id=finding_uuid,
            finding_code=f"FIND-{str(finding_uuid).split('-')[0].upper()}",
            study_id=canonical_study_id,
            site_id=canonical_site_id,
            visit_id=visit.id if visit else None,
            report_id=_uuid(report_id, "report_id") if report_id else None,
            category=category,
            severity=_enum_value(values.get("severity")),
            description=description,
            responsible_party=values.get("responsible_party"),
            owner_id=values.get("owner_id"),
            due_date=_timestamp(values.get("due_date"), "due_date"),
            status=MonitoringFindingStatus.OPEN.value,
            capa_required=bool(values.get("capa_required", False)),
            capa_reference=values.get("capa_reference"),
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=correlation,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(finding)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_finding",
            entity_id=finding.id,
            study_id=finding.study_id,
            site_id=finding.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["category", "severity", "description", "due_date", "capa_required"],
            status=finding.status,
            payload={"finding_code": finding.finding_code, "visit_id": finding.visit_id},
        )
        return finding

    async def transition_finding(
        self,
        session: AsyncSession,
        finding_id: UUID | str,
        status: MonitoringFindingStatus | str,
        *,
        reason: str,
        resolution: str | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringFinding:
        finding = await session.get(MonitoringFinding, _uuid(finding_id, "finding_id"))
        if finding is None or finding.deleted_at is not None:
            raise NotFoundError("Monitoring finding was not found")
        self._check_scope(user, finding)
        target = _enum_value(status)
        transitions = {
            MonitoringFindingStatus.OPEN.value: {
                MonitoringFindingStatus.ACTION_ASSIGNED.value,
                MonitoringFindingStatus.IN_PROGRESS.value,
                MonitoringFindingStatus.CANCELLED.value,
            },
            MonitoringFindingStatus.ACTION_ASSIGNED.value: {
                MonitoringFindingStatus.IN_PROGRESS.value,
                MonitoringFindingStatus.CANCELLED.value,
            },
            MonitoringFindingStatus.IN_PROGRESS.value: {
                MonitoringFindingStatus.PENDING_VERIFICATION.value,
                MonitoringFindingStatus.CANCELLED.value,
            },
            MonitoringFindingStatus.PENDING_VERIFICATION.value: {
                MonitoringFindingStatus.CLOSED.value,
                MonitoringFindingStatus.IN_PROGRESS.value,
            },
            MonitoringFindingStatus.CLOSED.value: {MonitoringFindingStatus.OPEN.value},
            MonitoringFindingStatus.CANCELLED.value: {MonitoringFindingStatus.OPEN.value},
        }
        if target not in transitions.get(finding.status, set()):
            raise ConflictError(
                "Monitoring finding transition is not allowed",
                {"status": finding.status, "target": target},
            )
        transition_reason = _required_reason(reason)
        if target == MonitoringFindingStatus.CLOSED.value and not str(resolution or "").strip():
            raise ValidationError("Resolution is required to close a monitoring finding")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        previous = finding.status
        finding.status = target
        finding.resolution = resolution if resolution is not None else finding.resolution
        if target == MonitoringFindingStatus.CLOSED.value:
            finding.verified_by = actor_uuid
            finding.verified_at = utc_now()
            finding.closed_at = utc_now()
            finding.closure_reason = transition_reason
        elif target == MonitoringFindingStatus.OPEN.value:
            finding.verified_by = None
            finding.verified_at = None
            finding.closed_at = None
            finding.closure_reason = transition_reason
        elif target == MonitoringFindingStatus.CANCELLED.value:
            finding.closure_reason = transition_reason
        finding.updated_by = actor_uuid
        finding.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_finding",
            entity_id=finding.id,
            study_id=finding.study_id,
            site_id=finding.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="transition",
            changed_fields=["status", "resolution", "verified_by", "verified_at"],
            previous_status=previous,
            status=finding.status,
            reason=transition_reason,
            payload={"finding_code": finding.finding_code},
        )
        return finding

    async def create_action_item(
        self,
        session: AsyncSession,
        finding_id: UUID | str,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringActionItem:
        finding = await session.get(MonitoringFinding, _uuid(finding_id, "finding_id"))
        if finding is None or finding.deleted_at is not None:
            raise NotFoundError("Monitoring finding was not found")
        self._check_scope(user, finding)
        if finding.status in {
            MonitoringFindingStatus.CLOSED.value,
            MonitoringFindingStatus.CANCELLED.value,
        }:
            raise ConflictError("Actions cannot be added to a closed finding")
        values = _mapping(payload)
        title = str(values.get("title") or "").strip()
        if not title:
            raise ValidationError("Action title is required")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        action = MonitoringActionItem(
            finding_id=finding.id,
            study_id=finding.study_id,
            site_id=finding.site_id,
            title=title,
            description=values.get("description"),
            owner_id=values.get("owner_id"),
            responsible_party=values.get("responsible_party"),
            due_date=_timestamp(values.get("due_date"), "due_date"),
            status="Open",
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=correlation,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(action)
        if finding.status == MonitoringFindingStatus.OPEN.value:
            finding.status = MonitoringFindingStatus.ACTION_ASSIGNED.value
            finding.updated_by = actor_uuid
            finding.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_action_item",
            entity_id=action.id,
            study_id=action.study_id,
            site_id=action.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["title", "owner_id", "responsible_party", "due_date"],
            status=action.status,
            payload={"finding_id": finding.id},
        )
        return action

    async def complete_action_item(
        self,
        session: AsyncSession,
        action_id: UUID | str,
        evidence: Mapping[str, Any] | str,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        user: Any | None = None,
        correlation_id: UUID | str | None = None,
    ) -> MonitoringActionItem:
        action = await session.get(MonitoringActionItem, _uuid(action_id, "action_id"))
        if action is None or action.deleted_at is not None:
            raise NotFoundError("Monitoring action item was not found")
        self._check_scope(user, action)
        if action.status == "Completed":
            raise ConflictError("Monitoring action is already completed")
        actor_uuid = _actor_id(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        action.status = "Completed"
        action.completion_evidence = _evidence(evidence)
        action.completed_at = utc_now()
        action.completed_by = actor_uuid
        action.updated_by = actor_uuid
        action.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="monitoring_action_item",
            entity_id=action.id,
            study_id=action.study_id,
            site_id=action.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="complete",
            changed_fields=["status", "completion_evidence", "completed_at", "completed_by"],
            previous_status="Open",
            status=action.status,
            payload={"finding_id": action.finding_id},
        )
        return action


monitoring_service = MonitoringService()

__all__ = ["MonitoringService", "monitoring_service"]
