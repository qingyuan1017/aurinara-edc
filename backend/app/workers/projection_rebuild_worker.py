"""Scope-limited, source-preserving CTMS projection rebuild worker."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ctms import Module, ensure_utc, utc_now
from app.core.exceptions import ValidationError
from app.models.ctms.enrollment import OperationalMilestone
from app.models.ctms.ownership import OwnershipRuleStatus, ProjectionType
from app.models.ctms.projection_rebuild import (
    CTMSProjectionRebuildState,
    ProjectionRebuildStatus,
)
from app.models.query import Query
from app.models.subject import Subject
from app.repositories.ctms.projection_rebuild_repository import (
    ProjectionRebuildRepository,
    projection_rebuild_repository,
)
from app.services.ctms_projection_service import CTMSProjectionService, ctms_projection_service
from app.services.status_ownership_rule_service import (
    CompiledOwnershipRule,
    StatusOwnershipRuleService,
    status_ownership_rule_service,
)

WORKER_NAME = "ctms-projection-rebuild"


@dataclass(frozen=True, slots=True)
class AuthoritativeRecordSnapshot:
    """The non-mutating source contract consumed by a rebuild.

    ``payload`` is read from an authoritative service and is never persisted by
    the rebuild state.  The projection service applies the active typed
    allowlist before any payload reaches the projection table.
    """

    source_record_id: UUID
    source_module: Module
    source_version: str
    source_timestamp: datetime
    payload: Mapping[str, Any]
    study_id: UUID
    site_id: UUID | None = None
    subject_id: UUID | None = None
    visit_instance_id: UUID | None = None
    query_id: UUID | None = None
    source_sequence: int | None = None


class AuthoritativeSourceReader(Protocol):
    """Reader interface implemented by source services or deterministic fakes."""

    async def list_records(
        self,
        session: AsyncSession,
        *,
        projection_type: ProjectionType,
        source_module: Module,
        study_id: UUID,
        site_id: UUID | None,
    ) -> Iterable[AuthoritativeRecordSnapshot]: ...


class SQLAlchemyAuthoritativeSourceReader:
    """Read approved source records from EDC/CTMS tables in stable ID order."""

    @staticmethod
    def _timestamp(record: Any) -> datetime:
        return ensure_utc(getattr(record, "updated_at", None) or record.created_at)

    @staticmethod
    def _version(record: Any) -> str:
        return SQLAlchemyAuthoritativeSourceReader._timestamp(record).isoformat()

    async def list_records(
        self,
        session: AsyncSession,
        *,
        projection_type: ProjectionType,
        source_module: Module,
        study_id: UUID,
        site_id: UUID | None,
    ) -> list[AuthoritativeRecordSnapshot]:
        if projection_type is ProjectionType.SUBJECT_STATUS:
            if source_module is Module.CTMS:
                statement = select(OperationalMilestone).where(
                    OperationalMilestone.study_id == study_id,
                    OperationalMilestone.deleted_at.is_(None),
                )
                if site_id is not None:
                    statement = statement.where(OperationalMilestone.site_id == site_id)
                rows = list((await session.scalars(statement.order_by(OperationalMilestone.id.asc()))).all())
                return [
                    AuthoritativeRecordSnapshot(
                        source_record_id=row.id,
                        source_module=Module.CTMS,
                        source_version=self._version(row),
                        source_timestamp=self._timestamp(row),
                        study_id=row.study_id,
                        site_id=row.site_id,
                        subject_id=row.subject_id,
                        payload={
                            "subject_id": row.subject_id,
                            "approved_pseudonym": row.approved_pseudonym,
                            "approved_reference": row.approved_reference,
                            "status": str(row.status),
                            "milestone_date": row.milestone_date,
                            "source_version": self._version(row),
                        },
                    )
                    for row in rows
                ]

            statement = select(Subject).where(
                Subject.study_id == study_id,
                Subject.deleted_at.is_(None),
            )
            if site_id is not None:
                statement = statement.where(Subject.site_id == site_id)
            rows = list((await session.scalars(statement.order_by(Subject.id.asc()))).all())
            return [
                AuthoritativeRecordSnapshot(
                    source_record_id=row.id,
                    source_module=Module.EDC,
                    source_version=self._version(row),
                    source_timestamp=self._timestamp(row),
                    study_id=row.study_id,
                    site_id=row.site_id,
                    subject_id=row.id,
                    payload={
                        "subject_id": row.id,
                        "approved_reference": row.subject_number,
                        "status": str(row.status),
                        "source_version": self._version(row),
                    },
                )
                for row in rows
            ]

        if projection_type is ProjectionType.QUERY_SUMMARY:
            if source_module is not Module.EDC:
                return []
            statement = select(Query).where(Query.study_id == study_id)
            if site_id is not None:
                statement = statement.where(Query.site_id == site_id)
            rows = list((await session.scalars(statement.order_by(Query.id.asc()))).all())
            return [
                AuthoritativeRecordSnapshot(
                    source_record_id=row.id,
                    source_module=Module.EDC,
                    source_version=self._version(row),
                    source_timestamp=self._timestamp(row),
                    study_id=row.study_id,
                    site_id=row.site_id,
                    subject_id=row.subject_id,
                    query_id=row.id,
                    payload={
                        "query_id": row.id,
                        "query_type": row.query_type,
                        "study_id": row.study_id,
                        "site_id": row.site_id,
                        "subject_id": row.subject_id,
                        "status": str(row.status),
                        "opened_at": row.created_at,
                        "resolved_at": row.closed_at,
                        "summary": row.text,
                    },
                )
                for row in rows
            ]

        raise ValidationError(
            "No authoritative source reader is configured for this projection type",
            {"reason": "PROJECTION_SOURCE_NOT_CONFIGURED"},
        )


@dataclass(frozen=True, slots=True)
class ProjectionRebuildResult:
    """Sanitized outcome of a completed rebuild generation."""

    state: CTMSProjectionRebuildState
    projections: tuple[Any, ...]

    @property
    def generation(self) -> UUID:
        return self.state.generation

    @property
    def watermark(self) -> dict[str, object | None]:
        return self.state.watermark


class ProjectionRebuildWorker:
    """Rebuild only a scoped CTMS read model from authoritative source rows."""

    _rule_keys: ClassVar[dict[ProjectionType, tuple[str, str]]] = {
        ProjectionType.SUBJECT_STATUS: ("Subject", "status"),
        ProjectionType.QUERY_SUMMARY: ("Query", "status"),
        ProjectionType.DATA_QUALITY_SIGNAL: ("DataQualitySignal", "signal"),
        ProjectionType.COORDINATED_TRANSITION: ("CoordinatedTransition", "status"),
    }

    def __init__(
        self,
        *,
        source_reader: AuthoritativeSourceReader | None = None,
        projection_service: CTMSProjectionService | None = None,
        state_repository: ProjectionRebuildRepository | None = None,
        rule_service: StatusOwnershipRuleService | None = None,
        worker_id: str = WORKER_NAME,
    ) -> None:
        self.source_reader = source_reader or SQLAlchemyAuthoritativeSourceReader()
        self.projection_service = projection_service or ctms_projection_service
        self.state_repository = state_repository or projection_rebuild_repository
        self.rule_service = rule_service or status_ownership_rule_service
        self.worker_id = worker_id[:128]

    @staticmethod
    def _normalize_projection_type(value: ProjectionType | str) -> ProjectionType:
        try:
            return value if isinstance(value, ProjectionType) else ProjectionType(str(value))
        except ValueError as exc:
            raise ValidationError(
                "Projection type is not supported",
                {"reason": "INVALID_PROJECTION_TYPE"},
            ) from exc

    @staticmethod
    def _normalize_scope(study_id: UUID | str, site_id: UUID | str | None) -> tuple[UUID, UUID | None]:
        try:
            normalized_study = study_id if isinstance(study_id, UUID) else UUID(str(study_id))
            normalized_site = None if site_id is None else (
                site_id if isinstance(site_id, UUID) else UUID(str(site_id))
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Projection rebuild scope identifiers must be UUIDs",
                {"reason": "INVALID_REBUILD_SCOPE"},
            ) from exc
        return normalized_study, normalized_site

    @staticmethod
    def _normalize_source_module(value: Module | str) -> Module:
        try:
            return value if isinstance(value, Module) else Module(str(value))
        except ValueError as exc:
            raise ValidationError(
                "Projection source module is not supported",
                {"reason": "INVALID_SOURCE_MODULE"},
            ) from exc

    @staticmethod
    def _version_key(value: str) -> tuple[int, object]:
        try:
            return (0, int(value))
        except (TypeError, ValueError):
            return (1, str(value))

    @classmethod
    def _record_sort_key(cls, record: AuthoritativeRecordSnapshot) -> tuple[str, str, str]:
        """Sort by canonical scope and ID, independent of source query order."""

        return (str(record.study_id), str(record.site_id or ""), str(record.source_record_id))

    @classmethod
    def _watermark_key(cls, record: AuthoritativeRecordSnapshot) -> tuple[datetime, tuple[int, object], str]:
        return (
            ensure_utc(record.source_timestamp),
            cls._version_key(record.source_version),
            str(record.source_record_id),
        )

    async def _resolve_rule(
        self,
        session: AsyncSession,
        projection_type: ProjectionType,
        rule: CompiledOwnershipRule | Mapping[str, Any] | None,
    ) -> CompiledOwnershipRule:
        if rule is not None:
            compiled = rule if isinstance(rule, CompiledOwnershipRule) else self.rule_service.compile_rule(rule)
        else:
            entity_type, field_path = self._rule_keys[projection_type]
            current = await self.rule_service.current_rule(session, entity_type, field_path)
            if current is None:
                raise ValidationError(
                    "No active projection allowlist is configured",
                    {"reason": "ACTIVE_PROJECTION_RULE_REQUIRED"},
                )
            compiled = self.rule_service.compile_rule(current)
        if compiled.status is not OwnershipRuleStatus.ACTIVE or not compiled.is_effective():
            raise ValidationError(
                "Projection rebuild requires an active allowlist",
                {"reason": "ACTIVE_PROJECTION_RULE_REQUIRED"},
            )
        return compiled

    async def _read_records(
        self,
        session: AsyncSession,
        *,
        projection_type: ProjectionType,
        source_module: Module,
        study_id: UUID,
        site_id: UUID | None,
    ) -> list[AuthoritativeRecordSnapshot]:
        records = await self.source_reader.list_records(
            session,
            projection_type=projection_type,
            source_module=source_module,
            study_id=study_id,
            site_id=site_id,
        )
        normalized = [
            record
            for record in records
            if record.study_id == study_id
            and (site_id is None or record.site_id == site_id)
            and (record.source_module.value if isinstance(record.source_module, Module) else str(record.source_module))
            == source_module.value
        ]
        normalized.sort(key=self._record_sort_key)
        return normalized

    async def rebuild(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | str,
        projection_type: ProjectionType | str,
        source_module: Module | str,
        rule: CompiledOwnershipRule | Mapping[str, Any] | None = None,
        site_id: UUID | str | None = None,
        generation: UUID | None = None,
        correlation_id: str | None = None,
        worker_id: str | None = None,
    ) -> ProjectionRebuildResult:
        """Run one deterministic scoped rebuild and record its watermark.

        The caller owns the transaction.  No outbox or reverse coordination
        event is created; only projection rows and rebuild-state metadata are
        written.  Source records and their audit history are never attached to
        the session for mutation.
        """

        normalized_study, normalized_site = self._normalize_scope(study_id, site_id)
        kind = self._normalize_projection_type(projection_type)
        module = self._normalize_source_module(source_module)
        compiled = await self._resolve_rule(session, kind, rule)
        run_generation = generation or uuid4()
        run_correlation = (correlation_id or f"projection-rebuild:{run_generation}").strip()[:128]
        if not run_correlation:
            raise ValidationError(
                "Projection rebuild correlation identifier is required",
                {"reason": "CORRELATION_ID_REQUIRED"},
            )
        run_worker = (worker_id or self.worker_id).strip()[:128]
        started_at = utc_now()
        state = CTMSProjectionRebuildState(
            generation=run_generation,
            projection_type=kind.value,
            source_module=module.value,
            scope_study_id=normalized_study,
            scope_site_id=normalized_site,
            rule_version=compiled.version,
            status=ProjectionRebuildStatus.RUNNING,
            records_seen=0,
            records_applied=0,
            records_rejected=0,
            records_stale=0,
            correlation_id=run_correlation,
            worker_id=run_worker,
            started_at=started_at,
        )
        await self.state_repository.add(session, state)

        records = await self._read_records(
            session,
            projection_type=kind,
            source_module=module,
            study_id=normalized_study,
            site_id=normalized_site,
        )
        projections: list[Any] = []
        watermark_record: AuthoritativeRecordSnapshot | None = None
        for record in records:
            result = await self.projection_service.apply_projection(
                session,
                rule=compiled,
                projection_type=kind,
                source_module=record.source_module,
                source_record_id=record.source_record_id,
                payload=record.payload,
                source_version=record.source_version,
                source_timestamp=record.source_timestamp,
                source_sequence=record.source_sequence,
                rule_version=compiled.version,
                correlation_id=run_correlation,
                study_id=record.study_id,
                site_id=record.site_id,
                subject_id=record.subject_id,
                visit_instance_id=record.visit_instance_id,
                query_id=record.query_id,
                projected_at=started_at,
                rebuild_generation=run_generation,
                worker_id=run_worker,
            )
            # A current row is intentionally not rewritten by the projection
            # service, but its generation watermark still identifies this run.
            if not result.applied and not result.rejected and not result.stale:
                result.projection.rebuild_generation = run_generation
                await session.flush()
            projections.append(result.projection)
            state.records_seen += 1
            if result.applied:
                state.records_applied += 1
            if result.rejected:
                state.records_rejected += 1
            if result.stale:
                state.records_stale += 1
            if watermark_record is None or self._watermark_key(record) > self._watermark_key(watermark_record):
                watermark_record = record

        state.status = ProjectionRebuildStatus.COMPLETED
        state.completed_at = utc_now()
        if watermark_record is not None:
            state.watermark_version = str(watermark_record.source_version)[:128]
            state.watermark_timestamp = ensure_utc(watermark_record.source_timestamp)
            state.watermark_record_id = watermark_record.source_record_id
        await session.flush()
        return ProjectionRebuildResult(state=state, projections=tuple(projections))

    run = rebuild


projection_rebuild_worker = ProjectionRebuildWorker()

__all__ = [
    "WORKER_NAME",
    "AuthoritativeRecordSnapshot",
    "AuthoritativeSourceReader",
    "ProjectionRebuildResult",
    "ProjectionRebuildWorker",
    "SQLAlchemyAuthoritativeSourceReader",
    "projection_rebuild_worker",
]
