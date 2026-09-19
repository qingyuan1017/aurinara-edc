"""Persistence, minimization, and read-only access for CTMS projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module, ensure_utc, utc_now
from app.core.exceptions import ConflictError, ValidationError
from app.core.metrics import get_metrics
from app.models.ctms.ownership import ProjectionType, StatusOwnershipRule
from app.models.ctms.projection import CTMSOperationalProjection, ProjectionStatus
from app.repositories.ctms.projection_repository import projection_repository
from app.schemas.ctms.projection import ProjectionResponse
from app.services.ctms_ownership_guard import assert_ctms_command_safe
from app.services.status_ownership_rule_service import (
    CompiledOwnershipRule,
    StatusOwnershipRuleService,
    status_ownership_rule_service,
)


@dataclass(frozen=True, slots=True)
class ProjectionApplyResult:
    """Outcome of applying one source snapshot to a projection read model."""

    projection: CTMSOperationalProjection
    applied: bool
    stale: bool = False
    rejected: bool = False
    skipped: bool = False
    conflict: bool = False
    reason: str | None = None
    current_version: str | None = None

    @property
    def read_only(self) -> bool:
        return True

    @property
    def outcome(self) -> str:
        """Return the durable coordination outcome for this application."""

        if self.rejected:
            return "rejected"
        if self.conflict:
            return "conflict"
        if self.skipped:
            return "skipped"
        if self.applied:
            return "succeeded"
        return "unchanged"


class CTMSProjectionService:
    """Own projection persistence while preserving source-module authority."""

    def __init__(self, *, repository=projection_repository, rule_service: StatusOwnershipRuleService | None = None) -> None:
        self.repository = repository
        self.rule_service = rule_service or status_ownership_rule_service

    # ------------------------------------------------------------------
    # Safe deterministic helpers
    # ------------------------------------------------------------------

    @staticmethod
    def record_update(*, lag_seconds: float = 0.0) -> None:
        """Record freshness metrics without retaining source or payload values."""

        get_metrics().record_ctms_projection(lag_seconds)

    @staticmethod
    def field_fingerprint(fields: list[str] | tuple[str, ...] | set[str]) -> str:
        """Hash only normalized field paths, never rejected values."""

        return StatusOwnershipRuleService.fingerprint({"fields": sorted(set(fields))})

    @staticmethod
    def _source_version(value: str | int) -> str:
        value = str(value).strip()
        if not value:
            raise ValidationError(
                "Projection source version is required",
                {"reason": "PROJECTION_SOURCE_VERSION_REQUIRED"},
            )
        return value[:128]

    @staticmethod
    def _compare_versions(left: str, right: str) -> int:
        """Compare numeric versions numerically and opaque versions stably."""

        try:
            left_number, right_number = int(left), int(right)
        except ValueError:
            return (left > right) - (left < right)
        return (left_number > right_number) - (left_number < right_number)

    @classmethod
    def _compare_source_order(
        cls,
        *,
        source_sequence: int | None,
        source_version: str,
        source_timestamp: datetime,
        current: CTMSOperationalProjection,
    ) -> int:
        """Compare an incoming source snapshot with the current target.

        A producer sequence is authoritative when both sides provide one. The
        source version is the fallback ordering key, and timestamps only break
        ties. This prevents a delayed event with a newer wall-clock timestamp
        from replacing a newer source sequence.
        """

        current_sequence = getattr(current, "source_sequence", None)
        if source_sequence is not None and current_sequence is not None and source_sequence != current_sequence:
            return (source_sequence > current_sequence) - (source_sequence < current_sequence)
        version_order = cls._compare_versions(source_version, current.source_version)
        if version_order:
            return version_order
        incoming_timestamp = ensure_utc(source_timestamp)
        current_timestamp = ensure_utc(current.source_timestamp)
        return (incoming_timestamp > current_timestamp) - (incoming_timestamp < current_timestamp)

    @staticmethod
    def source_order_key(event: Any) -> tuple[Any, ...]:
        """Build the stable ordering key shared by coordination consumers."""

        def value(name: str, default: Any = None) -> Any:
            if isinstance(event, Mapping):
                return event.get(name, default)
            return getattr(event, name, default)

        sequence = value("source_sequence")
        version = str(value("source_version", ""))
        try:
            version_key: tuple[int, Any] = (0, int(version))
        except (TypeError, ValueError):
            version_key = (1, version)
        return (
            str(value("source_module", value("module", ""))),
            str(value("entity_type", value("aggregate_type", ""))),
            str(value("source_record_id", value("aggregate_id", ""))),
            sequence is None,
            sequence if sequence is not None else 0,
            version_key,
            str(value("event_id", value("id", ""))),
        )

    @classmethod
    def order_events(cls, events: Any) -> list[Any]:
        """Return events in deterministic per-entity source order."""

        return sorted(list(events), key=cls.source_order_key)

    order_source_events = order_events

    @staticmethod
    def _projection_type(
        projection_type: ProjectionType | str | None,
        rule: CompiledOwnershipRule,
    ) -> ProjectionType:
        selected = projection_type or rule.projection_type
        if selected is None:
            raise ValidationError(
                "Projection type is required",
                {"reason": "PROJECTION_TYPE_REQUIRED"},
            )
        try:
            return selected if isinstance(selected, ProjectionType) else ProjectionType(str(selected))
        except ValueError as exc:
            raise ValidationError(
                "Projection type is not supported",
                {"reason": "INVALID_PROJECTION_TYPE"},
            ) from exc

    @staticmethod
    def _canonical_reference(value: UUID | str | None) -> UUID | None:
        if value is None:
            return None
        try:
            return value if isinstance(value, UUID) else UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Projection canonical references must be UUIDs",
                {"reason": "INVALID_CANONICAL_REFERENCE"},
            ) from exc

    @classmethod
    def _is_stale(
        cls,
        current: CTMSOperationalProjection,
        *,
        source_sequence: int | None,
        source_version: str,
        source_timestamp: datetime,
    ) -> bool:
        return cls._compare_source_order(
            source_sequence=source_sequence,
            source_version=source_version,
            source_timestamp=source_timestamp,
            current=current,
        ) < 0

    @staticmethod
    def _is_same_source(
        current: CTMSOperationalProjection,
        *,
        source_sequence: int | None,
        source_version: str,
        source_timestamp: datetime,
        fingerprint: str,
    ) -> bool:
        return (
            getattr(current, "source_sequence", None) == source_sequence
            and current.source_version == source_version
            and ensure_utc(current.source_timestamp) == source_timestamp
            and current.payload_fingerprint == fingerprint
        )

    @staticmethod
    def _metadata(
        *,
        source_module: Module | str,
        source_record_id: UUID,
        source_version: str | int,
        source_sequence: int | None,
        source_timestamp: datetime,
        rule_version: int,
        correlation_id: str,
        projected_at: datetime | None,
        projection_type: ProjectionType,
        study_id: UUID | None,
        site_id: UUID | None,
        subject_id: UUID | None,
        visit_instance_id: UUID | None,
        query_id: UUID | None,
        rebuild_generation: UUID | None,
        payload: dict[str, Any],
        status: ProjectionStatus,
        rejected_fields_fingerprint: str | None = None,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        try:
            module = source_module if isinstance(source_module, Module) else Module(str(source_module))
        except ValueError as exc:
            raise ValidationError(
                "Projection source module is not supported",
                {"reason": "INVALID_SOURCE_MODULE"},
            ) from exc
        if not correlation_id or not correlation_id.strip():
            raise ValidationError(
                "Projection correlation identifier is required",
                {"reason": "CORRELATION_ID_REQUIRED"},
            )
        if source_sequence is not None and source_sequence < 0:
            raise ValidationError(
                "Projection source sequence must not be negative",
                {"reason": "INVALID_SOURCE_SEQUENCE"},
            )
        return {
            "projection_type": projection_type.value,
            "source_module": module.value,
            "source_record_id": CTMSProjectionService._canonical_reference(source_record_id),
            "study_id": study_id,
            "site_id": site_id,
            "subject_id": subject_id,
            "visit_instance_id": visit_instance_id,
            "query_id": query_id,
            "source_version": CTMSProjectionService._source_version(source_version),
            "source_sequence": source_sequence,
            "source_timestamp": ensure_utc(source_timestamp),
            "rule_version": rule_version,
            "correlation_id": correlation_id.strip()[:128],
            "projected_at": ensure_utc(projected_at or utc_now()),
            "payload_json": payload,
            "payload_fingerprint": StatusOwnershipRuleService.fingerprint(payload),
            "rejected_fields_fingerprint": rejected_fields_fingerprint,
            "rejection_reason": rejection_reason,
            "status": status,
            "rebuild_generation": rebuild_generation,
        }

    # ------------------------------------------------------------------
    # Validation and persistence
    # ------------------------------------------------------------------

    def validate_payload(
        self,
        rule: CompiledOwnershipRule | StatusOwnershipRule | Mapping[str, Any],
        payload: Mapping[str, Any],
    ):
        """Return the typed allowlisted payload or raise a sanitized error."""

        # This guard rejects clinical values/objects before minimization. The
        # ownership service then rejects all other unknown fields and coerces
        # approved scalar fields to their canonical representation.
        assert_ctms_command_safe(payload, operation="project_projection")
        return self.rule_service.validate_payload(rule, payload)

    validate_projection = validate_payload
    build_allowlisted_payload = validate_payload

    async def apply_projection(
        self,
        session: AsyncSession,
        *,
        rule: CompiledOwnershipRule | StatusOwnershipRule | Mapping[str, Any],
        projection_type: ProjectionType | str | None = None,
        source_module: Module | str,
        source_record_id: UUID,
        payload: Mapping[str, Any],
        source_version: str | int,
        source_timestamp: datetime,
        source_sequence: int | None = None,
        rule_version: int | None = None,
        correlation_id: str,
        study_id: UUID | str | None = None,
        site_id: UUID | str | None = None,
        subject_id: UUID | str | None = None,
        visit_instance_id: UUID | str | None = None,
        query_id: UUID | str | None = None,
        projected_at: datetime | None = None,
        rebuild_generation: UUID | None = None,
        actor_id: UUID | None = None,
        worker_id: str | None = None,
    ) -> ProjectionApplyResult:
        """Validate and upsert a projection without mutating its source record."""

        compiled = rule if isinstance(rule, CompiledOwnershipRule) else self.rule_service.compile_rule(rule)
        kind = self._projection_type(projection_type, compiled)
        if compiled.projection_target is not None and compiled.projection_target is not Module.CTMS:
            raise ConflictError(
                "The CTMS projection rule targets a different module",
                {"reason": "PROJECTION_TARGET_NOT_CTMS"},
            )
        normalized_source_version = self._source_version(source_version)
        if source_sequence is not None:
            if isinstance(source_sequence, bool) or not isinstance(source_sequence, int) or source_sequence < 0:
                raise ValidationError(
                    "Projection source sequence must be a non-negative integer",
                    {"reason": "INVALID_SOURCE_SEQUENCE"},
                )
            normalized_source_sequence = source_sequence
        else:
            normalized_source_sequence = None
        try:
            normalized_timestamp = ensure_utc(source_timestamp)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Projection source timestamp must be timezone-aware UTC",
                {"reason": "INVALID_SOURCE_TIMESTAMP"},
            ) from exc
        canonical = {
            name: self._canonical_reference(value)
            for name, value in {
                "study_id": study_id,
                "site_id": site_id,
                "subject_id": subject_id,
                "visit_instance_id": visit_instance_id,
                "query_id": query_id,
            }.items()
        }

        try:
            validation = self.validate_payload(compiled, payload)
        except (ValidationError, ConflictError) as exc:
            # Persist a rejected state only when no current row would be
            # overwritten. Values never enter the row; only field names hash.
            existing = await self.repository.get(
                session,
                projection_type=kind.value,
                source_module=(source_module.value if isinstance(source_module, Module) else str(source_module)),
                source_record_id=source_record_id,
            )
            rejected_fields = exc.details.get("rejected_fields", ())
            if not rejected_fields:
                rejected_fields = tuple(sorted(str(key) for key in payload))
            rejection_fingerprint = self.field_fingerprint(tuple(rejected_fields))
            if existing is None:
                metadata = self._metadata(
                    source_module=source_module,
                    source_record_id=source_record_id,
                    source_version=normalized_source_version,
                    source_sequence=normalized_source_sequence,
                    source_timestamp=normalized_timestamp,
                    rule_version=rule_version or compiled.version,
                    correlation_id=correlation_id,
                    projected_at=projected_at,
                    projection_type=kind,
                    study_id=canonical["study_id"],
                    site_id=canonical["site_id"],
                    subject_id=canonical["subject_id"],
                    visit_instance_id=canonical["visit_instance_id"],
                    query_id=canonical["query_id"],
                    rebuild_generation=rebuild_generation,
                    payload={},
                    status=ProjectionStatus.REJECTED,
                    rejected_fields_fingerprint=rejection_fingerprint,
                    rejection_reason=str(exc.details.get("reason", "PROJECTION_FIELD_NOT_ALLOWED")),
                )
                rejected = await self.repository.add(session, CTMSOperationalProjection(**metadata))
                await audit_service.record(
                    session,
                    entity_type="ctms_operational_projection",
                    entity_id=rejected.id,
                    action="reject",
                    module=Module.CTMS,
                    actor_id=actor_id,
                    actor_kind="worker" if worker_id else "user",
                    worker_id=worker_id,
                    correlation_id=correlation_id,
                    source_module=source_module,
                    target_module=Module.CTMS,
                    source_record_id=source_record_id,
                    target_record_id=rejected.id,
                    study_id=canonical["study_id"],
                    site_id=canonical["site_id"],
                    subject_id=canonical["subject_id"],
                    changed_fields=["status", "rejected_fields_fingerprint"],
                    reason="PROJECTION_FIELD_NOT_ALLOWED",
                )
                return ProjectionApplyResult(rejected, applied=False, rejected=True, reason="PROJECTION_FIELD_NOT_ALLOWED")
            return ProjectionApplyResult(
                existing,
                applied=False,
                rejected=True,
                reason="PROJECTION_FIELD_NOT_ALLOWED",
            )

        existing = await self.repository.get(
            session,
            projection_type=kind.value,
            source_module=(source_module.value if isinstance(source_module, Module) else str(source_module)),
            source_record_id=source_record_id,
        )
        if existing is not None:
            if self._is_stale(
                existing,
                source_sequence=normalized_source_sequence,
                source_version=normalized_source_version,
                source_timestamp=normalized_timestamp,
            ):
                return ProjectionApplyResult(
                    existing,
                    applied=False,
                    stale=True,
                    conflict=True,
                    reason=(
                        "OUT_OF_ORDER_EVENT"
                        if normalized_source_sequence is not None
                        and getattr(existing, "source_sequence", None) is not None
                        and normalized_source_sequence < existing.source_sequence
                        else "STALE_PROJECTION"
                    ),
                    current_version=existing.source_version,
                )
            if self._is_same_source(
                existing,
                source_sequence=normalized_source_sequence,
                source_version=normalized_source_version,
                source_timestamp=normalized_timestamp,
                fingerprint=validation.fingerprint,
            ) and existing.rule_version == (rule_version or compiled.version) and str(existing.status) in {
                ProjectionStatus.CURRENT.value,
                str(ProjectionStatus.CURRENT),
            }:
                return ProjectionApplyResult(
                    existing,
                    applied=False,
                    skipped=True,
                    reason="PROJECTION_CURRENT",
                    current_version=existing.source_version,
                )

        metadata = self._metadata(
            source_module=source_module,
            source_record_id=source_record_id,
            source_version=normalized_source_version,
            source_sequence=normalized_source_sequence,
            source_timestamp=normalized_timestamp,
            rule_version=rule_version or compiled.version,
            correlation_id=correlation_id,
            projected_at=projected_at,
            projection_type=kind,
            study_id=canonical["study_id"],
            site_id=canonical["site_id"],
            subject_id=canonical["subject_id"],
            visit_instance_id=canonical["visit_instance_id"],
            query_id=canonical["query_id"],
            rebuild_generation=rebuild_generation,
            payload=validation.payload,
            status=ProjectionStatus.CURRENT,
        )
        if existing is None:
            projection = await self.repository.add(session, CTMSOperationalProjection(**metadata))
            action = "create"
        else:
            # Refreshes may omit rebuild metadata or canonical scope fields;
            # never erase target metadata while accepting a newer source.
            for name in (
                "source_sequence",
                "rebuild_generation",
                "study_id",
                "site_id",
                "subject_id",
                "visit_instance_id",
                "query_id",
            ):
                if metadata.get(name) is None:
                    metadata[name] = getattr(existing, name)
            for name, value in metadata.items():
                setattr(existing, name, value)
            await session.flush()
            projection = existing
            action = "refresh"

        await audit_service.record(
            session,
            entity_type="ctms_operational_projection",
            entity_id=projection.id,
            action=action,
            module=Module.CTMS,
            actor_id=actor_id,
            actor_kind="worker" if worker_id else "user",
            worker_id=worker_id,
            correlation_id=correlation_id,
            source_module=source_module,
            target_module=Module.CTMS,
            source_record_id=source_record_id,
            target_record_id=projection.id,
            study_id=canonical["study_id"],
            site_id=canonical["site_id"],
            subject_id=canonical["subject_id"],
            changed_fields=["payload_json", "payload_fingerprint", "source_version", "rule_version", "status"],
        )
        self.record_update(lag_seconds=max(0.0, (utc_now() - normalized_timestamp).total_seconds()))
        return ProjectionApplyResult(
            projection,
            applied=True,
            current_version=projection.source_version,
        )

    # Explicit names used by workers and service consumers.
    upsert_projection = apply_projection
    persist_projection = apply_projection
    refresh = apply_projection

    async def create_projection(self, session: AsyncSession, **kwargs: Any) -> CTMSOperationalProjection:
        result = await self.apply_projection(session, **kwargs)
        if result.rejected:
            raise ValidationError(
                "Projection was rejected by its field allowlist",
                {"reason": result.reason or "PROJECTION_FIELD_NOT_ALLOWED"},
            )
        if result.stale:
            raise ConflictError(
                "Projection source is older than the current projection",
                {"reason": "STALE_PROJECTION"},
            )
        return result.projection

    # ------------------------------------------------------------------
    # Consumer read-only access
    # ------------------------------------------------------------------

    async def get_projection(self, session: AsyncSession, projection_id: UUID) -> ProjectionResponse | None:
        projection = await self.repository.get_by_id(session, projection_id)
        return ProjectionResponse.model_validate(projection) if projection is not None else None

    async def read_projection(self, session: AsyncSession, projection_id: UUID) -> ProjectionResponse | None:
        return await self.get_projection(session, projection_id)

    async def list_projections(self, session: AsyncSession, **filters: Any) -> list[ProjectionResponse]:
        rows = await self.repository.list(session, **filters)
        return [ProjectionResponse.model_validate(row) for row in rows]

    @staticmethod
    def consumer_can_mutate_source(*, projection: CTMSOperationalProjection | ProjectionResponse, operation: str) -> bool:
        """Projected data is never authorization to mutate EDC Clinical_Data."""

        assert_ctms_command_safe({}, operation=operation)
        return False

    @staticmethod
    def assert_consumer_read_only(operation: str) -> None:
        """Fail closed if a consumer attempts a clinical or projection write."""

        assert_ctms_command_safe({}, operation=operation)
        raise ConflictError(
            "CTMS projections are read-only consumer views",
            {"reason": "PROJECTION_READ_ONLY"},
        )


ctms_projection_service = CTMSProjectionService()

__all__ = [
    "CTMSProjectionService",
    "ProjectionApplyResult",
    "ctms_projection_service",
]
