"""Configured PV_Safety_Module retention, archival, and soft-deletion controls.

Retention is deliberately implemented as updates to PV-owned/shared metadata; it
never issues deletes against EDC clinical tables, CTMS operational tables, or
their attachments, and it never physically removes PV Safety_Data or a related
Audit_Event.  PV records are retained for at least seven years (Requirement
20.3); this service applies logical archival/soft-deletion only after the
configured retention floor has elapsed, and every action appends an immutable
actor/time/reason ledger row plus one PV safety Audit_Event.

Design references:
  * design goal 8 "Soft-delete retention": PV safety records are never physically
    removed; deletion actor, timestamp, and reason remain attributable.
  * design "Migration and integrity plan" step 6: retention jobs soft-delete/
    archive PV records per policy without cascading into EDC clinical or CTMS
    operational records or their audit history.
  * Requirement 17.2 (Soft_Deletion), 17.3 (UTC timestamps), 20.3 (retention/
    backup/restore), 20.5 (regulated-change actor/timestamp/reason retention).
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
from app.core.exceptions import ConflictError, ValidationError
from app.core.pv import Module, ensure_utc, utc_now
from app.models.audit import AuditEvent
from app.models.export import Export
from app.models.file_attachment import FileAttachment
from app.models.notification import Notification
from app.models.pv import (
    AdverseEventRecord,
    CaseNarrative,
    CaseVersion,
    CausalityAssessment,
    CodingDictionaryVersion,
    CoordinationRef,
    EdcAeProjection,
    ExpectednessAssessment,
    MedDraCoding,
    NarrativeVersion,
    PVRetentionAction,
    ReconciliationDiscrepancy,
    ReconciliationRun,
    RegulatoryClock,
    RegulatoryReport,
    ReportabilityRule,
    SafetyCase,
    SeriousnessAssessment,
    SeverityGrade,
    WhoDrugCoding,
)


class RetentionMode(StrEnum):
    """How a configured PV retention policy disposes of a matched record."""

    ARCHIVE = "archive"
    SOFT_DELETE = "soft_delete"
    PROTECTED = "protected"


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """One independently configurable PV retention rule."""

    resource: str
    days: int
    mode: RetentionMode = RetentionMode.ARCHIVE
    timestamp_field: str = "created_at"

    def cutoff(self, now: datetime) -> datetime:
        return ensure_utc(now) - timedelta(days=self.days)


@dataclass(frozen=True, slots=True)
class RetentionRunResult:
    """Sanitized retention-job counts; no safety payloads are returned."""

    archived: int = 0
    soft_deleted: int = 0
    protected: int = 0
    skipped: int = 0

    @property
    def processed(self) -> int:
        return self.archived + self.soft_deleted + self.protected


# PV Safety_Data models grouped by policy so a retention run cannot accidentally
# reach an EDC clinical or CTMS operational model.  Each entry names the PV table
# and the timestamp column used to test the retention cutoff.
_SAFETY_DATA_MODELS: tuple[tuple[str, type[Any], str], ...] = (
    ("safety_case", SafetyCase, "created_at"),
    ("adverse_event_record", AdverseEventRecord, "created_at"),
    ("case_version", CaseVersion, "created_at"),
    ("seriousness_assessment", SeriousnessAssessment, "created_at"),
    ("causality_assessment", CausalityAssessment, "created_at"),
    ("expectedness_assessment", ExpectednessAssessment, "created_at"),
    ("severity_grade", SeverityGrade, "created_at"),
    ("meddra_coding", MedDraCoding, "created_at"),
    ("whodrug_coding", WhoDrugCoding, "created_at"),
    ("coding_dictionary_version", CodingDictionaryVersion, "created_at"),
    ("case_narrative", CaseNarrative, "created_at"),
    ("narrative_version", NarrativeVersion, "created_at"),
    ("regulatory_report", RegulatoryReport, "created_at"),
    ("regulatory_clock", RegulatoryClock, "created_at"),
    ("reportability_rule", ReportabilityRule, "created_at"),
    ("reconciliation_run", ReconciliationRun, "created_at"),
    ("reconciliation_discrepancy", ReconciliationDiscrepancy, "created_at"),
)

# PV-owned read-only projection read models.  These are metadata about EDC
# adverse events, not EDC clinical records themselves; archiving them never
# touches EDC state.
_PROJECTION_MODELS: tuple[tuple[str, type[Any], str], ...] = (
    ("edc_ae_projection", EdcAeProjection, "projected_at"),
    ("coordination_ref", CoordinationRef, "processed_at"),
)


def _actor(actor_id: UUID | str | None) -> UUID:
    if actor_id is None:
        raise ValidationError(message="A retention actor is required", details={})
    try:
        return actor_id if isinstance(actor_id, UUID) else UUID(str(actor_id))
    except (TypeError, ValueError) as exc:
        raise ValidationError(message="Retention actor must be a UUID", details={}) from exc


def _reason(reason: str | None) -> str:
    if reason is None or not str(reason).strip():
        raise ValidationError(message="A non-empty retention reason is required", details={})
    return str(reason).strip()[:4000]


def _settings_days(settings: Settings, name: str) -> int:
    override = getattr(settings, name, None)
    return int(override if override is not None else settings.pv_retention_days)


class PVRetentionService:
    """Apply configured lifecycle policy only to PV-owned records."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def policies(self) -> tuple[RetentionPolicy, ...]:
        """Return every configured PV retention job, including protected records."""

        return (
            RetentionPolicy("safety_data", _settings_days(self.settings, "pv_safety_case_retention_days")),
            RetentionPolicy("assessments", _settings_days(self.settings, "pv_assessment_retention_days")),
            RetentionPolicy("coding", _settings_days(self.settings, "pv_coding_retention_days")),
            RetentionPolicy("narratives", _settings_days(self.settings, "pv_narrative_retention_days")),
            RetentionPolicy("regulatory", _settings_days(self.settings, "pv_regulatory_retention_days")),
            RetentionPolicy("reconciliation", _settings_days(self.settings, "pv_reconciliation_retention_days")),
            RetentionPolicy("projections", _settings_days(self.settings, "pv_projection_retention_days")),
            RetentionPolicy(
                "attachments",
                _settings_days(self.settings, "pv_attachment_retention_days"),
                RetentionMode.SOFT_DELETE,
                "uploaded_at",
            ),
            RetentionPolicy("notifications", _settings_days(self.settings, "pv_notification_retention_days")),
            RetentionPolicy("exports", _settings_days(self.settings, "pv_export_retention_days")),
            RetentionPolicy(
                "audit",
                _settings_days(self.settings, "pv_audit_retention_days"),
                RetentionMode.PROTECTED,
                "timestamp",
            ),
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
        """Append the immutable ledger row and one PV safety Audit_Event."""

        entity_id = getattr(record, "id", None)
        if entity_id is None:
            raise ValidationError(message="Retention target has no identifier", details={})
        resolved_correlation = correlation_id or (str(getattr(record, "correlation_id", "")) or None)
        session.add(
            PVRetentionAction(
                entity_type=resource,
                entity_id=entity_id,
                action=action,
                actor_id=actor_id,
                occurred_at=occurred_at,
                reason=reason,
                correlation_id=resolved_correlation,
                module=Module.PV.value,
            )
        )
        await session.flush()
        await audit_service.record(
            session,
            entity_type=resource,
            entity_id=entity_id,
            action=action,
            module=Module.PV,
            actor_kind="worker" if action.startswith("retention_") else "user",
            actor_id=actor_id,
            correlation_id=resolved_correlation,
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
        """Archive a PV record while retaining its row and references."""

        actor = _actor(actor_id)
        why = _reason(reason)
        timestamp = ensure_utc(now or utc_now())
        if getattr(record, "retention_state", "active") == "archived":
            raise ConflictError(message="Retention record is already archived", details={"reason": "ALREADY_ARCHIVED"})
        self._set(record, "retention_state", "archived")
        self._set(record, "archived_at", timestamp)
        self._set(record, "archived_by", actor)
        self._set(record, "retention_reason", why)
        if isinstance(record, Notification):
            record.status = "Archived"
        await session.flush()
        await self._ledger(
            session,
            record,
            resource=resource or record.__tablename__,
            action="retention_archive",
            actor_id=actor,
            occurred_at=timestamp,
            reason=why,
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
        """Soft-delete a PV/shared record without deleting storage or parents."""

        actor = _actor(actor_id)
        why = _reason(reason)
        timestamp = ensure_utc(now or utc_now())
        if not hasattr(record, "deleted_at"):
            raise ValidationError(message="Retention target does not support soft deletion", details={})
        if getattr(record, "deleted_at", None) is not None:
            raise ConflictError(message="Retention record is already soft-deleted", details={"reason": "ALREADY_DELETED"})
        record.deleted_at = timestamp
        self._set(record, "deleted_by", actor)
        self._set(record, "deletion_reason", why)
        self._set(record, "delete_reason", why)
        self._set(record, "retention_state", "soft_deleted")
        await session.flush()
        await self._ledger(
            session,
            record,
            resource=resource or record.__tablename__,
            action="retention_soft_delete",
            actor_id=actor,
            occurred_at=timestamp,
            reason=why,
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
        """Restore a retained PV record and preserve the restore decision."""

        actor = _actor(actor_id)
        why = _reason(reason)
        timestamp = ensure_utc(now or utc_now())
        archived = getattr(record, "archived_at", None) is not None
        deleted = getattr(record, "deleted_at", None) is not None
        if not archived and not deleted:
            raise ConflictError(message="Retention record is not archived or deleted", details={"reason": "NOT_RETAINED"})
        self._set(record, "retention_state", "active")
        self._set(record, "archived_at", None)
        self._set(record, "archived_by", None)
        self._set(record, "retention_reason", None)
        self._set(record, "deleted_at", None)
        self._set(record, "deleted_by", None)
        self._set(record, "deletion_reason", None)
        self._set(record, "delete_reason", None)
        await session.flush()
        await self._ledger(
            session,
            record,
            resource=resource or record.__tablename__,
            action="retention_restore",
            actor_id=actor,
            occurred_at=timestamp,
            reason=why,
        )
        return record

    async def _query_candidates(
        self,
        session: AsyncSession,
        model: type[Any],
        policy: RetentionPolicy,
        now: datetime,
        *,
        pv_module_only: bool = False,
    ) -> list[Any]:
        timestamp = getattr(model, policy.timestamp_field, None)
        if timestamp is None:
            return []
        statement = select(model).where(timestamp <= policy.cutoff(now))
        if hasattr(model, "retention_state"):
            statement = statement.where(model.retention_state == "active")
        if hasattr(model, "deleted_at"):
            statement = statement.where(model.deleted_at.is_(None))
        if pv_module_only and hasattr(model, "module"):
            statement = statement.where(model.module == Module.PV.value)
        return list(
            (await session.scalars(statement.limit(self.settings.pv_retention_batch_size))).all()
        )

    async def run(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID | str,
        reason: str,
        now: datetime | None = None,
    ) -> RetentionRunResult:
        """Run every configured PV policy in one caller-controlled transaction."""

        actor = _actor(actor_id)
        why = _reason(reason)
        timestamp = ensure_utc(now or utc_now())
        counts = {"archived": 0, "soft_deleted": 0, "protected": 0, "skipped": 0}
        policies = {policy.resource: policy for policy in self.policies()}

        # PV Safety_Data and PV read-only projections are archived (never
        # physically deleted).  Each group uses its own resource policy days.
        group_map = {
            "safety_case": "safety_data",
            "adverse_event_record": "safety_data",
            "case_version": "safety_data",
            "seriousness_assessment": "assessments",
            "causality_assessment": "assessments",
            "expectedness_assessment": "assessments",
            "severity_grade": "assessments",
            "meddra_coding": "coding",
            "whodrug_coding": "coding",
            "coding_dictionary_version": "coding",
            "case_narrative": "narratives",
            "narrative_version": "narratives",
            "regulatory_report": "regulatory",
            "regulatory_clock": "regulatory",
            "reportability_rule": "regulatory",
            "reconciliation_run": "reconciliation",
            "reconciliation_discrepancy": "reconciliation",
        }
        for resource, model, timestamp_field in _SAFETY_DATA_MODELS:
            policy = policies[group_map[resource]]
            candidate_policy = RetentionPolicy(resource, policy.days, RetentionMode.ARCHIVE, timestamp_field)
            for record in await self._query_candidates(session, model, candidate_policy, timestamp):
                await self.archive(session, record, actor_id=actor, reason=why, now=timestamp, resource=resource)
                counts["archived"] += 1

        projection_policy = policies["projections"]
        for resource, model, timestamp_field in _PROJECTION_MODELS:
            candidate_policy = RetentionPolicy(resource, projection_policy.days, RetentionMode.ARCHIVE, timestamp_field)
            for record in await self._query_candidates(session, model, candidate_policy, timestamp):
                await self.archive(session, record, actor_id=actor, reason=why, now=timestamp, resource=resource)
                counts["archived"] += 1

        # Shared primitives (attachments/exports/notifications) are only touched
        # for PV-owned rows; a missing/other module discriminator is skipped so
        # CTMS/EDC rows are never reached.
        shared_map: tuple[tuple[str, type[Any], str], ...] = (
            ("attachments", FileAttachment, "uploaded_at"),
            ("exports", Export, "created_at"),
            ("notifications", Notification, "created_at"),
        )
        for resource, model, timestamp_field in shared_map:
            policy = policies[resource]
            candidate_policy = RetentionPolicy(resource, policy.days, policy.mode, timestamp_field)
            for record in await self._query_candidates(
                session, model, candidate_policy, timestamp, pv_module_only=True
            ):
                if getattr(record, "module", None) != Module.PV.value:
                    counts["skipped"] += 1
                    continue
                if policy.mode is RetentionMode.SOFT_DELETE:
                    await self.soft_delete(session, record, actor_id=actor, reason=why, now=timestamp, resource=resource)
                    counts["soft_deleted"] += 1
                else:
                    await self.archive(session, record, actor_id=actor, reason=why, now=timestamp, resource=resource)
                    counts["archived"] += 1

        # PV Audit_Events are append-only and are never modified or physically
        # deleted.  Counting them makes protection observable without violating
        # their immutability contract or touching EDC/CTMS audit history.
        audit_policy = policies["audit"]
        statement = (
            select(AuditEvent)
            .where(AuditEvent.timestamp <= audit_policy.cutoff(timestamp))
            .where(AuditEvent.module == Module.PV.value)
            .limit(self.settings.pv_retention_batch_size)
        )
        counts["protected"] += len((await session.scalars(statement)).all())

        return RetentionRunResult(**counts)


pv_retention_service = PVRetentionService()

__all__ = [
    "PVRetentionService",
    "RetentionMode",
    "RetentionPolicy",
    "RetentionRunResult",
    "pv_retention_service",
]
