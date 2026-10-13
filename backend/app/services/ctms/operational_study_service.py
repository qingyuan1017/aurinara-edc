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
    ProjectScopeLevel,
    ReadinessCriterion,
    ReadinessCriterionStatus,
    ReportQuery,
    StudyOperationalMilestone,
    StudyPlan,
    StudyPlanStatus,
)
from app.models.ctms.reference_data import CTMSReferenceValue, ReferenceCategory
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.identity import Role, User, UserRole, UserStatus
from app.services.ctms.ctms_atomicity_service import ctms_atomicity_service
from app.services.ctms.ctms_identity_service import CanonicalIdentityResolver
from app.services.ctms.ctms_ownership_guard import assert_ctms_command_safe
from app.services.ctms.reference_data_service import resolve_reference_value

T = TypeVar("T")

_STUDY_TRANSITIONS: dict[str, set[str]] = {
    OperationalStudyStatus.DRAFT.value: {OperationalStudyStatus.PLANNING.value},
    OperationalStudyStatus.PLANNING.value: {
        OperationalStudyStatus.READY.value,
        OperationalStudyStatus.SUSPENDED.value,
    },
    OperationalStudyStatus.READY.value: {
        OperationalStudyStatus.ACTIVE.value,
        OperationalStudyStatus.PLANNING.value,
        OperationalStudyStatus.SUSPENDED.value,
    },
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
    "phase",
    "study_type",
    "main_purpose",
    "therapeutic_area",
    "program",
    "indication",
    "study_description",
    "investigational_product",
    "blind_method",
    "randomized",
    "expected_subject_count",
    "language",
    "expected_site_count",
    "construction_period",
    "planned_start_date",
    "planned_end_date",
    "actual_start_date",
    "actual_end_date",
    "study_currency",
    "exchange_date",
    "query_expected_days",
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


def _date_value(value: date | str | None, field: str) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO calendar date", {"field": field}) from exc


def _normalize_loaded_timestamps(record: OperationalStudy) -> OperationalStudy:
    """Normalize SQLite-reloaded timestamps to the shared UTC API contract."""

    for field in ("created_at", "updated_at", "archived_at", "deleted_at"):
        value = getattr(record, field, None)
        if isinstance(value, datetime) and value.tzinfo is None:
            setattr(record, field, value.replace(tzinfo=UTC))
    return record


def _value_status(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


class OperationalStudyService:
    """Manage CTMS operational study profiles and planning records."""

    async def _canonical_study(self, session: AsyncSession, study_id: UUID | str) -> Study:
        canonical_id = _uuid(study_id, "study_id")
        identity = await CanonicalIdentityResolver(session).resolve_study(canonical_id)
        result = await session.execute(
            select(Study).where(Study.id == identity.id, Study.deleted_at.is_(None))
        )
        study = result.scalars().first()
        if study is None:  # Defensive for repository/session fakes.
            raise NotFoundError(
                "Canonical platform Study reference was not found", {"study_id": str(canonical_id)}
            )
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
            raise NotFoundError(
                "Operational study profile was not found", {"study_id": str(canonical_id)}
            )
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
            raise ConflictError(
                "An operational study profile already exists",
                {"study_id": str(study.id), "reason": "DUPLICATE_RECORD"},
            )
        status = _value_status(values.get("status", OperationalStudyStatus.DRAFT))
        if status not in _STUDY_TRANSITIONS:
            raise ValidationError("Invalid operational study status", {"status": status})
        unknown = set(values) - _PROFILE_FIELDS - {"status", "correlation_id"}
        if unknown:
            raise ValidationError(
                "Unknown operational study profile field", {"field": sorted(unknown)[0]}
            )
        values["therapeutic_area"] = await resolve_reference_value(
            session,
            ReferenceCategory.THERAPEUTIC_AREA,
            values.get("therapeutic_area"),
            field="therapeutic_area",
        )
        values["indication"] = await resolve_reference_value(
            session,
            ReferenceCategory.INDICATION,
            values.get("indication"),
            field="indication",
        )
        planned_start = _date_value(values.get("planned_start_date"), "planned_start_date")
        planned_end = _date_value(values.get("planned_end_date"), "planned_end_date")
        if planned_start and planned_end and planned_end < planned_start:
            raise ValidationError(
                "Planned end date must be on or after planned start date",
                {"field": "planned_end_date"},
            )
        actual_start = _date_value(values.get("actual_start_date"), "actual_start_date")
        actual_end = _date_value(values.get("actual_end_date"), "actual_end_date")
        if actual_start and actual_end and actual_end < actual_start:
            raise ValidationError(
                "Actual end date must be on or after actual start date",
                {"field": "actual_end_date"},
            )
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)
        profile = OperationalStudy(
            study_id=study.id,
            study=study,
            operational_owner_id=values.get("operational_owner_id"),
            phase=values.get("phase"),
            study_type=values.get("study_type"),
            main_purpose=values.get("main_purpose"),
            therapeutic_area=values.get("therapeutic_area"),
            program=values.get("program"),
            indication=values.get("indication"),
            study_description=values.get("study_description"),
            investigational_product=values.get("investigational_product"),
            blind_method=values.get("blind_method"),
            randomized=values.get("randomized"),
            expected_subject_count=values.get("expected_subject_count"),
            language=values.get("language"),
            expected_site_count=values.get("expected_site_count"),
            construction_period=values.get("construction_period"),
            planned_start_date=planned_start,
            planned_end_date=planned_end,
            actual_start_date=actual_start,
            actual_end_date=actual_end,
            study_currency=(
                str(values["study_currency"]).upper()
                if values.get("study_currency") is not None
                else None
            ),
            exchange_date=_date_value(values.get("exchange_date"), "exchange_date"),
            query_expected_days=values.get("query_expected_days"),
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
            raise ValidationError(
                "Unknown operational study profile field", {"field": sorted(unknown)[0]}
            )
        if "therapeutic_area" in values:
            values["therapeutic_area"] = await resolve_reference_value(
                session,
                ReferenceCategory.THERAPEUTIC_AREA,
                values["therapeutic_area"],
                field="therapeutic_area",
            )
        if "indication" in values:
            values["indication"] = await resolve_reference_value(
                session,
                ReferenceCategory.INDICATION,
                values["indication"],
                field="indication",
            )
        for field in (
            "planned_start_date",
            "planned_end_date",
            "actual_start_date",
            "actual_end_date",
            "exchange_date",
        ):
            if field in values:
                values[field] = _date_value(values[field], field)
        if "study_currency" in values and values["study_currency"] is not None:
            values["study_currency"] = str(values["study_currency"]).upper()
        changed = [
            field
            for field in _PROFILE_FIELDS
            if field in values and getattr(profile, field) != values[field]
        ]
        if not changed:
            return profile
        planned_start = values.get("planned_start_date", profile.planned_start_date)
        planned_end = values.get("planned_end_date", profile.planned_end_date)
        if planned_start and planned_end and planned_end < planned_start:
            raise ValidationError(
                "Planned end date must be on or after planned start date",
                {"field": "planned_end_date"},
            )
        actual_start = values.get("actual_start_date", profile.actual_start_date)
        actual_end = values.get("actual_end_date", profile.actual_end_date)
        if actual_start and actual_end and actual_end < actual_start:
            raise ValidationError(
                "Actual end date must be on or after actual start date",
                {"field": "actual_end_date"},
            )
        # Updates to an Active profile require an explicit reason for traceability.
        change_reason = (
            _reason(reason)
            if profile.status == OperationalStudyStatus.ACTIVE.value
            else reason.strip()
            if reason and reason.strip()
            else None
        )
        for field in changed:
            setattr(
                profile,
                field,
                dict(values[field] or {})
                if field in {"planning_metadata", "readiness_criteria"}
                else values[field],
            )
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
                {
                    "reason": "INVALID_TRANSITION",
                    "current_status": current,
                    "target_status": target,
                },
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

    async def _prepare_project_scope(
        self,
        session: AsyncSession,
        study_id: UUID,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        scope_level = _enum_value(values.get("scope_level", ProjectScopeLevel.STUDY.value))
        if scope_level not in {level.value for level in ProjectScopeLevel}:
            raise ValidationError("Invalid project scope level", {"field": "scope_level"})
        values["scope_level"] = scope_level
        if scope_level == ProjectScopeLevel.STUDY.value:
            values["country_code"] = None
            values["site_id"] = None
        elif scope_level == ProjectScopeLevel.COUNTRY.value:
            values["site_id"] = None
            values["country_code"] = await resolve_reference_value(
                session,
                ReferenceCategory.COUNTRY,
                values.get("country_code"),
                field="country_code",
            )
        else:
            values["country_code"] = None
            site_id = values.get("site_id")
            if site_id is not None:
                site = await session.scalar(
                    select(Site).where(
                        Site.id == site_id,
                        Site.study_id == study_id,
                        Site.deleted_at.is_(None),
                    )
                )
                if site is None:
                    raise ValidationError(
                        "Site is not part of the selected study", {"field": "site_id"}
                    )
        return values

    async def _validate_activity_assignment(
        self, session: AsyncSession, study_id: UUID, values: dict[str, Any]
    ) -> None:
        role_id = values.get("assignee_role_id")
        if role_id is not None and await session.get(Role, role_id) is None:
            raise ValidationError("Assigned role was not found", {"field": "assignee_role_id"})
        user_id = values.get("assignee_user_id")
        if user_id is not None:
            user = await session.get(User, user_id)
            if user is None or _enum_value(user.status) != UserStatus.active.value:
                raise ValidationError("Assigned user must be active", {"field": "assignee_user_id"})
            assignment = await session.scalar(
                select(UserRole).where(
                    UserRole.user_id == user_id,
                    or_(UserRole.study_id == study_id, UserRole.study_id.is_(None)),
                    *([UserRole.role_id == role_id] if role_id is not None else []),
                )
            )
            if assignment is None:
                raise ValidationError(
                    "Assigned user is not available in this study scope",
                    {"field": "assignee_user_id"},
                )
        milestone_id = values.get("milestone_id")
        if milestone_id is None:
            return
        milestone = await session.get(StudyOperationalMilestone, milestone_id)
        if milestone is None or milestone.study_id != study_id or milestone.deleted_at is not None:
            raise ValidationError(
                "Milestone is not part of the selected study", {"field": "milestone_id"}
            )
        scope = values.get("scope_level", ProjectScopeLevel.STUDY.value)
        if (
            scope != milestone.scope_level
            or values.get("country_code") != milestone.country_code
            or values.get("site_id") != milestone.site_id
        ):
            raise ValidationError(
                "Master activity scope must match its milestone scope",
                {"field": "milestone_id", "reason": "SCOPE_MISMATCH"},
            )

    async def create_study_plan(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | str,
        payload: Mapping[str, Any] | Any | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> StudyPlan:
        values = await self._prepare_project_scope(
            session, _uuid(study_id, "study_id"), _mapping(payload)
        )
        requested_status = values.get("status")
        if requested_status is None and callable(getattr(session, "scalar", None)):
            requested_status = await session.scalar(
                select(CTMSReferenceValue.code)
                .where(
                    CTMSReferenceValue.category == ReferenceCategory.PROJECT_STATUS.value,
                    CTMSReferenceValue.active.is_(True),
                )
                .order_by(CTMSReferenceValue.sort_order, CTMSReferenceValue.label)
                .limit(1)
            )
        values["status"] = await resolve_reference_value(
            session,
            ReferenceCategory.PROJECT_STATUS,
            requested_status or StudyPlanStatus.DRAFT.value,
            field="status",
        )
        values["start_at"] = _timestamp(values.get("start_at"))
        values["due_at"] = _timestamp(values.get("due_at"))
        if values["start_at"] and values["due_at"] and values["due_at"] < values["start_at"]:
            raise ValidationError("Due date must be on or after start date", {"field": "due_at"})
        await self._validate_activity_assignment(session, _uuid(study_id, "study_id"), values)
        return await self._create_scoped(
            session,
            StudyPlan,
            entity_type="study_plan",
            study_id=study_id,
            payload=values,
            actor=actor,
            actor_id=actor_id,
            correlation_id=correlation_id,
            required_fields={"title"},
            fields={
                "title",
                "objective",
                "milestone_id",
                "scope_level",
                "country_code",
                "site_id",
                "planning_scope",
                "owner_id",
                "assignee_role_id",
                "assignee_user_id",
                "start_at",
                "due_at",
                "status",
            },
            defaults={"planning_scope": {}, "status": StudyPlanStatus.DRAFT.value},
        )

    async def create_enrollment_plan(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | str,
        payload: Mapping[str, Any] | Any | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> EnrollmentPlan:
        return await self._create_scoped(
            session,
            EnrollmentPlan,
            entity_type="enrollment_plan",
            study_id=study_id,
            payload=payload,
            actor=actor,
            actor_id=actor_id,
            correlation_id=correlation_id,
            required_fields={"title"},
            fields={
                "title",
                "target_quantity",
                "planning_period_start",
                "planning_period_end",
                "planning_scope",
                "owner_id",
                "status",
            },
            defaults={"planning_scope": {}, "status": EnrollmentPlanStatus.DRAFT.value},
        )

    async def create_readiness_criterion(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | str,
        payload: Mapping[str, Any] | Any | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> ReadinessCriterion:
        return await self._create_scoped(
            session,
            ReadinessCriterion,
            entity_type="readiness_criterion",
            study_id=study_id,
            payload=payload,
            actor=actor,
            actor_id=actor_id,
            correlation_id=correlation_id,
            required_fields={"name"},
            fields={
                "name",
                "description",
                "status",
                "required",
                "due_at",
                "completed_at",
                "completed_by",
                "evidence_reference",
            },
            defaults={"status": ReadinessCriterionStatus.OPEN.value, "required": True},
        )

    async def create_operational_milestone(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | str,
        payload: Mapping[str, Any] | Any | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> StudyOperationalMilestone:
        values = await self._prepare_project_scope(
            session, _uuid(study_id, "study_id"), _mapping(payload)
        )
        values["milestone_type"] = await resolve_reference_value(
            session,
            ReferenceCategory.MILESTONE_TYPE,
            values.get("milestone_type"),
            field="milestone_type",
        )
        values["planned_at"] = _timestamp(values.get("planned_at"))
        values["completed_at"] = _timestamp(values.get("completed_at"))
        return await self._create_scoped(
            session,
            StudyOperationalMilestone,
            entity_type="study_milestone",
            study_id=study_id,
            payload=values,
            actor=actor,
            actor_id=actor_id,
            correlation_id=correlation_id,
            required_fields={"title", "milestone_type"},
            fields={
                "title",
                "description",
                "milestone_type",
                "scope_level",
                "country_code",
                "site_id",
                "planned_at",
                "completed_at",
                "owner_id",
                "notes",
                "status",
            },
            defaults={"status": OperationalMilestoneStatus.PLANNED.value},
        )

    async def _update_project_record(
        self,
        session: AsyncSession,
        record: StudyPlan | StudyOperationalMilestone,
        values: dict[str, Any],
        *,
        actor: Any,
        reason: str,
        entity_type: str,
        allowed_fields: set[str],
        correlation_id: UUID | str | None,
    ):
        actor_uuid = _actor(actor, None)
        change_reason = _reason(reason)
        changed: list[str] = []
        for field in allowed_fields:
            if field in values and getattr(record, field) != values[field]:
                setattr(record, field, values[field])
                changed.append(field)
        if not changed:
            return record
        correlation = _correlation(correlation_id, actor)
        record.updated_by = actor_uuid
        record.updated_at = utc_now()
        record.correlation_id = _correlation_uuid(correlation)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type=entity_type,
            entity_id=record.id,
            study_id=record.study_id,
            site_id=record.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="update",
            changed_fields=changed,
            status=_value_status(record.status),
            reason=change_reason,
            payload={"study_id": record.study_id},
        )
        return record

    async def update_study_plan(
        self,
        session: AsyncSession,
        plan_id: UUID,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any,
        correlation_id: UUID | str | None = None,
    ) -> StudyPlan:
        plan = await session.get(StudyPlan, plan_id)
        if plan is None or plan.deleted_at is not None:
            raise NotFoundError("Master activity was not found", {"plan_id": str(plan_id)})
        values = _mapping(payload)
        reason = values.pop("reason", None)
        if "status" in values:
            values["status"] = await resolve_reference_value(
                session,
                ReferenceCategory.PROJECT_STATUS,
                values["status"],
                field="status",
            )
        combined = {
            "scope_level": values.get("scope_level", plan.scope_level),
            "country_code": values.get("country_code", plan.country_code),
            "site_id": values.get("site_id", plan.site_id),
            "milestone_id": values.get("milestone_id", plan.milestone_id),
            "assignee_role_id": values.get("assignee_role_id", plan.assignee_role_id),
            "assignee_user_id": values.get("assignee_user_id", plan.assignee_user_id),
        }
        combined = await self._prepare_project_scope(session, plan.study_id, combined)
        await self._validate_activity_assignment(session, plan.study_id, combined)
        values.update({key: combined[key] for key in ("scope_level", "country_code", "site_id")})
        if "start_at" in values:
            values["start_at"] = _timestamp(values["start_at"])
        if "due_at" in values:
            values["due_at"] = _timestamp(values["due_at"])
        next_start = values.get("start_at", plan.start_at)
        next_due = values.get("due_at", plan.due_at)
        if next_start and next_due and next_due < next_start:
            raise ValidationError("Due date must be on or after start date", {"field": "due_at"})
        return await self._update_project_record(
            session,
            plan,
            values,
            actor=actor,
            reason=reason,
            entity_type="study_plan",
            allowed_fields={
                "title",
                "objective",
                "milestone_id",
                "scope_level",
                "country_code",
                "site_id",
                "assignee_role_id",
                "assignee_user_id",
                "start_at",
                "due_at",
                "status",
            },
            correlation_id=correlation_id,
        )

    async def update_operational_milestone(
        self,
        session: AsyncSession,
        milestone_id: UUID,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any,
        correlation_id: UUID | str | None = None,
    ) -> StudyOperationalMilestone:
        milestone = await session.get(StudyOperationalMilestone, milestone_id)
        if milestone is None or milestone.deleted_at is not None:
            raise NotFoundError(
                "Project milestone was not found", {"milestone_id": str(milestone_id)}
            )
        values = _mapping(payload)
        reason = values.pop("reason", None)
        combined = await self._prepare_project_scope(
            session,
            milestone.study_id,
            {
                "scope_level": values.get("scope_level", milestone.scope_level),
                "country_code": values.get("country_code", milestone.country_code),
                "site_id": values.get("site_id", milestone.site_id),
            },
        )
        values.update(combined)
        linked_activities = list(
            await session.scalars(select(StudyPlan).where(StudyPlan.milestone_id == milestone.id))
        )
        if any(
            activity.scope_level != combined["scope_level"]
            or activity.country_code != combined["country_code"]
            or activity.site_id != combined["site_id"]
            for activity in linked_activities
        ):
            raise ValidationError(
                "Milestone scope cannot differ from its linked master activities",
                {"field": "scope_level", "reason": "LINKED_ACTIVITY_SCOPE_MISMATCH"},
            )
        if "milestone_type" in values:
            values["milestone_type"] = await resolve_reference_value(
                session,
                ReferenceCategory.MILESTONE_TYPE,
                values["milestone_type"],
                field="milestone_type",
            )
        for field in ("planned_at", "completed_at"):
            if field in values:
                values[field] = _timestamp(values[field])
        return await self._update_project_record(
            session,
            milestone,
            values,
            actor=actor,
            reason=reason,
            entity_type="study_milestone",
            allowed_fields={
                "title",
                "description",
                "milestone_type",
                "scope_level",
                "country_code",
                "site_id",
                "planned_at",
                "completed_at",
                "owner_id",
                "notes",
                "status",
            },
            correlation_id=correlation_id,
        )

    async def create_dashboard_query(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | str,
        payload: Mapping[str, Any] | Any | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> DashboardQuery:
        return await self._create_scoped(
            session,
            DashboardQuery,
            entity_type="dashboard_query",
            study_id=study_id,
            payload=payload,
            actor=actor,
            actor_id=actor_id,
            correlation_id=correlation_id,
            required_fields={"name"},
            fields={"name", "query_definition", "owner_id", "status"},
            defaults={"query_definition": {}, "status": "Active"},
        )

    async def create_report_query(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | str,
        payload: Mapping[str, Any] | Any | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> ReportQuery:
        return await self._create_scoped(
            session,
            ReportQuery,
            entity_type="report_query",
            study_id=study_id,
            payload=payload,
            actor=actor,
            actor_id=actor_id,
            correlation_id=correlation_id,
            required_fields={"name"},
            fields={"name", "query_definition", "owner_id", "status"},
            defaults={"query_definition": {}, "status": "Active"},
        )

    create_plan = create_study_plan
    create_enrollment = create_enrollment_plan
    create_readiness_criterion = create_readiness_criterion
    create_milestone = create_operational_milestone


operational_study_service = OperationalStudyService()

__all__ = ["OperationalStudyService", "operational_study_service"]
