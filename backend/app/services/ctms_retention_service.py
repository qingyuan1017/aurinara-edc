"""Configured CTMS retention, archival, and soft-deletion controls.

Retention is deliberately implemented as updates to CTMS-owned/shared metadata;
it never issues deletes against EDC clinical tables or their attachments.  Audit
events, completed coordination logs, and retention-action history are immutable
and therefore remain protected records rather than being physically purged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.config import Settings, get_settings
from app.core.ctms import Module, ensure_utc, utc_now
from app.core.exceptions import ConflictError, ValidationError
from app.models.audit import AuditEvent
from app.models.ctms import (
    ActivationAction,
    CoordinationEvent,
    CoordinationEventLog,
    CTMSCoordinationConflict,
    CTMSFailedEvent,
    CTMSRetentionAction,
    DashboardQuery,
    EnrollmentPlan,
    EnrollmentTarget,
    MonitoringActivity,
    MonitoringPlan,
    MonitoringPlanVersion,
    OperationalContact,
    OperationalMilestone,
    OperationalSite,
    OperationalStudy,
    OperationalTask,
    ReadinessCriterion,
    ReportQuery,
    StudyOperationalMilestone,
    StudyPlan,
    TaskEscalation,
)
from app.models.ctms.coordination import CTMSEventAttempt, CTMSOutbox
from app.models.ctms.projection import CTMSOperationalProjection, ProjectionStatus
from app.models.export import Export
from app.models.file_attachment import FileAttachment
from app.models.notification import Notification


class RetentionMode(StrEnum):
    ARCHIVE = "archive"
    SOFT_DELETE = "soft_delete"
    PROTECTED = "protected"


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """One independently configurable CTMS retention rule."""

    resource: str
    days: int
    mode: RetentionMode = RetentionMode.ARCHIVE
    timestamp_field: str = "created_at"

    def cutoff(self, now: datetime) -> datetime:
        return ensure_utc(now) - timedelta(days=self.days)


@dataclass(frozen=True, slots=True)
class RetentionRunResult:
    """Sanitized retention-job counts; no payloads are returned."""

    archived: int = 0
    soft_deleted: int = 0
    protected: int = 0
    skipped: int = 0

    @property
    def processed(self) -> int:
        return self.archived + self.soft_deleted + self.protected


# CTMS operational records use the same archive metadata but are independently
# selected so a retention run cannot accidentally reach an EDC model.
_OPERATIONAL_MODELS: tuple[tuple[str, type[Any]], ...] = (
    ("operational_study", OperationalStudy),
    ("study_plan", StudyPlan),
    ("enrollment_plan", EnrollmentPlan),
    ("readiness_criterion", ReadinessCriterion),
    ("study_milestone", StudyOperationalMilestone),
    ("report_query", ReportQuery),
    ("dashboard_query", DashboardQuery),
    ("operational_site", OperationalSite),
    ("activation_action", ActivationAction),
    ("enrollment_target", EnrollmentTarget),
    ("operational_milestone", OperationalMilestone),
    ("monitoring_plan", MonitoringPlan),
    ("monitoring_plan_version", MonitoringPlanVersion),
    ("monitoring_activity", MonitoringActivity),
    ("operational_task", OperationalTask),
    ("operational_contact", OperationalContact),
    ("task_escalation", TaskEscalation),
)


def _actor(actor_id: UUID | str | None) -> UUID:
    if actor_id is None:
        raise ValidationError("A retention actor is required")
    try:
        return actor_id if isinstance(actor_id, UUID) else UUID(str(actor_id))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Retention actor must be a UUID") from exc


def _reason(reason: str | None) -> str:
    if reason is None or not str(reason).strip():
        raise ValidationError("A non-empty retention reason is required")
    return str(reason).strip()[:255]


def _settings_days(settings: Settings, name: str) -> int:
    override = getattr(settings, name, None)
    return int(override if override is not None else settings.retention_days)


class CTMSRetentionService:
    """Apply configured lifecycle policy only to CTMS-owned records."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def policies(self) -> tuple[RetentionPolicy, ...]:
        """Return all configured jobs, including protected immutable records."""
        operational_days = _settings_days(self.settings, "ctms_operational_retention_days")
        return (
            RetentionPolicy("operational_data", operational_days),
            RetentionPolicy("projections", _settings_days(self.settings, "ctms_projection_retention_days")),
            RetentionPolicy("event_attempts", _settings_days(self.settings, "ctms_event_attempt_retention_days")),
            RetentionPolicy("event_logs", _settings_days(self.settings, "ctms_event_log_retention_days"), RetentionMode.PROTECTED, "completed_at"),
            RetentionPolicy("failed_events", _settings_days(self.settings, "ctms_failed_event_retention_days")),
            RetentionPolicy("conflicts", _settings_days(self.settings, "ctms_conflict_retention_days")),
            RetentionPolicy("exports", _settings_days(self.settings, "ctms_export_retention_days")),
            RetentionPolicy("attachments", _settings_days(self.settings, "ctms_attachment_retention_days"), RetentionMode.SOFT_DELETE, "uploaded_at"),
            RetentionPolicy("notifications", _settings_days(self.settings, "ctms_notification_retention_days"), RetentionMode.ARCHIVE),
            RetentionPolicy("audit", _settings_days(self.settings, "ctms_audit_retention_days"), RetentionMode.PROTECTED, "timestamp"),
        )

    @staticmethod
    def _set(record: Any, name: str, value: Any) -> bool:
        if hasattr(record, name):
            setattr(record, name, value)
            return True
        return False

    async def _ledger(
        self,
        session: AsyncSession,
        record: Any,
        *,
        resource: str,
        action: str,
        actor_id: UUID,
        occurred_at: datetime,
        reason: str,
        correlation_id: str | None = None,
    ) -> None:
        entity_id = getattr(record, "id", None)
        if entity_id is None:
            raise ValidationError("Retention target has no identifier")
        session.add(
            CTMSRetentionAction(
                entity_type=resource,
                entity_id=entity_id,
                action=action,
                actor_id=actor_id,
                occurred_at=occurred_at,
                reason=reason,
                correlation_id=correlation_id or str(getattr(record, "correlation_id", "")) or None,
                module=Module.CTMS.value,
            )
        )
        await session.flush()
        await audit_service.record(
            session,
            entity_type=resource,
            entity_id=entity_id,
            action=action,
            module=Module.CTMS,
            actor_id=actor_id,
            actor_kind="worker" if action.startswith("retention_") else "user",
            correlation_id=correlation_id or str(getattr(record, "correlation_id", "")) or None,
            study_id=getattr(record, "study_id", None),
            site_id=getattr(record, "site_id", None),
            changed_fields=["retention_state", "archived_at", "deleted_at"],
            reason=reason,
        )

    async def archive(
        self,
        session: AsyncSession,
        record: Any,
        *,
        actor_id: UUID | str,
        reason: str,
        now: datetime | None = None,
        resource: str | None = None,
    ) -> Any:
        """Archive a record while retaining its row and references."""
        actor = _actor(actor_id)
        why = _reason(reason)
        timestamp = ensure_utc(now or utc_now())
        if getattr(record, "retention_state", "active") == "archived":
            raise ConflictError("Retention record is already archived", {"reason": "ALREADY_ARCHIVED"})
        self._set(record, "retention_state", "archived")
        self._set(record, "archived_at", timestamp)
        self._set(record, "archived_by", actor)
        self._set(record, "retention_reason", why)
        self._set(record, "archive_reason", why)
        if isinstance(record, Notification):
            record.status = "Archived"
        if isinstance(record, CTMSOperationalProjection):
            record.status = ProjectionStatus.ARCHIVED
        await session.flush()
        await self._ledger(
            session, record, resource=resource or record.__tablename__, action="retention_archive",
            actor_id=actor, occurred_at=timestamp, reason=why,
        )
        return record

    async def soft_delete(
        self,
        session: AsyncSession,
        record: Any,
        *,
        actor_id: UUID | str,
        reason: str,
        now: datetime | None = None,
        resource: str | None = None,
    ) -> Any:
        """Soft-delete a CTMS/shared record without deleting storage or parents."""
        actor = _actor(actor_id)
        why = _reason(reason)
        timestamp = ensure_utc(now or utc_now())
        if getattr(record, "deleted_at", None) is not None:
            raise ConflictError("Retention record is already soft-deleted", {"reason": "ALREADY_DELETED"})
        if not hasattr(record, "deleted_at"):
            raise ValidationError("Retention target does not support soft deletion")
        record.deleted_at = timestamp
        self._set(record, "deleted_by", actor)
        self._set(record, "deletion_reason", why)
        self._set(record, "delete_reason", why)
        self._set(record, "retention_state", "soft_deleted")
        await session.flush()
        await self._ledger(
            session, record, resource=resource or record.__tablename__, action="retention_soft_delete",
            actor_id=actor, occurred_at=timestamp, reason=why,
        )
        return record

    async def restore(
        self,
        session: AsyncSession,
        record: Any,
        *,
        actor_id: UUID | str,
        reason: str,
        now: datetime | None = None,
        resource: str | None = None,
    ) -> Any:
        """Restore a retained record and preserve the restore decision in history."""
        actor = _actor(actor_id)
        why = _reason(reason)
        timestamp = ensure_utc(now or utc_now())
        archived = getattr(record, "archived_at", None) is not None
        deleted = getattr(record, "deleted_at", None) is not None
        if not archived and not deleted:
            raise ConflictError("Retention record is not archived or deleted", {"reason": "NOT_RETAINED"})
        self._set(record, "retention_state", "active")
        self._set(record, "archived_at", None)
        self._set(record, "archived_by", None)
        self._set(record, "retention_reason", None)
        self._set(record, "archive_reason", None)
        self._set(record, "deleted_at", None)
        self._set(record, "deleted_by", None)
        self._set(record, "deletion_reason", None)
        self._set(record, "delete_reason", None)
        if isinstance(record, CTMSOperationalProjection):
            record.status = ProjectionStatus.CURRENT
        await session.flush()
        await self._ledger(
            session, record, resource=resource or record.__tablename__, action="retention_restore",
            actor_id=actor, occurred_at=timestamp, reason=why,
        )
        return record

    async def _query_candidates(
        self, session: AsyncSession, model: type[Any], policy: RetentionPolicy, now: datetime
    ) -> list[Any]:
        timestamp = getattr(model, policy.timestamp_field, None)
        if timestamp is None:
            return []
        statement = select(model).where(timestamp <= policy.cutoff(now))
        if hasattr(model, "retention_state"):
            statement = statement.where(model.retention_state == "active")
        if hasattr(model, "deleted_at"):
            statement = statement.where(model.deleted_at.is_(None))
        if hasattr(model, "module"):
            statement = statement.where(model.module == Module.CTMS.value)
        return list((await session.scalars(statement.limit(self.settings.ctms_retention_batch_size))).all())

    async def run(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID | str,
        reason: str,
        now: datetime | None = None,
    ) -> RetentionRunResult:
        """Run every configured policy in one caller-controlled transaction."""
        actor = _actor(actor_id)
        why = _reason(reason)
        timestamp = ensure_utc(now or utc_now())
        counts = {"archived": 0, "soft_deleted": 0, "protected": 0, "skipped": 0}
        policies = {policy.resource: policy for policy in self.policies()}

        for resource, model in _OPERATIONAL_MODELS:
            policy = policies["operational_data"]
            for record in await self._query_candidates(session, model, policy, timestamp):
                await self.archive(session, record, actor_id=actor, reason=why, now=timestamp, resource=resource)
                counts["archived"] += 1

        model_policies: tuple[tuple[str, type[Any], str], ...] = (
            ("projections", CTMSOperationalProjection, "projected_at"),
            ("event_attempts", CTMSEventAttempt, "started_at"),
            ("failed_events", CTMSFailedEvent, "created_at"),
            ("conflicts", CTMSCoordinationConflict, "created_at"),
            ("exports", Export, "created_at"),
            ("attachments", FileAttachment, "uploaded_at"),
            ("notifications", Notification, "created_at"),
        )
        for resource, model, timestamp_field in model_policies:
            policy = policies[resource]
            candidate_policy = RetentionPolicy(resource, policy.days, policy.mode, timestamp_field)
            for record in await self._query_candidates(session, model, candidate_policy, timestamp):
                if resource == "attachments" and getattr(record, "module", None) != Module.CTMS.value:
                    counts["skipped"] += 1
                    continue
                if resource in {"exports", "notifications"} and getattr(record, "module", None) != Module.CTMS.value:
                    counts["skipped"] += 1
                    continue
                if policy.mode is RetentionMode.SOFT_DELETE:
                    await self.soft_delete(session, record, actor_id=actor, reason=why, now=timestamp, resource=resource)
                    counts["soft_deleted"] += 1
                else:
                    await self.archive(session, record, actor_id=actor, reason=why, now=timestamp, resource=resource)
                    counts["archived"] += 1

        # Completed logs and CTMS audit rows are intentionally not modified or
        # physically deleted. Counting them makes protection observable without
        # violating their append-only contract or touching EDC audit history.
        for resource, model, timestamp_field in (("event_logs", CoordinationEventLog, "completed_at"), ("audit", AuditEvent, "timestamp")):
            policy = policies[resource]
            statement = select(model).where(getattr(model, timestamp_field) <= policy.cutoff(timestamp)).limit(self.settings.ctms_retention_batch_size)
            if resource == "audit":
                statement = statement.where(model.module == Module.CTMS.value)
            counts["protected"] += len((await session.scalars(statement)).all())

        # Event rows/outbox rows are operational coordination state. Failed
        # events are archived, but their immutable completed logs remain above.
        event_policy = policies["failed_events"]
        for model in (CoordinationEvent, CTMSOutbox):
            candidates = await self._query_candidates(session, model, RetentionPolicy("failed_events", event_policy.days, RetentionMode.ARCHIVE, "processed_at"), timestamp)
            for record in candidates:
                if getattr(record, "status", "").lower() not in {"failed", "conflict"}:
                    continue
                await self.archive(session, record, actor_id=actor, reason=why, now=timestamp, resource="failed_events")
                counts["archived"] += 1

        return RetentionRunResult(**counts)


ctms_retention_service = CTMSRetentionService()

__all__ = ["CTMSRetentionService", "RetentionMode", "RetentionPolicy", "RetentionRunResult", "ctms_retention_service"]
