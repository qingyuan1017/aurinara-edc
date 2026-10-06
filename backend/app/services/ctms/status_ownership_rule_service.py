"""Shared ownership-rule compilation and projection minimization service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module, ensure_utc, utc_now
from app.core.exceptions import ConflictError, ValidationError
from app.models.ctms.ownership import (
    OwnershipRuleStatus,
    ProjectionType,
    StatusOwnershipRule,
)
from app.schemas.ctms.ownership import (
    PROHIBITED_PROJECTION_TOKENS,
    ProjectionFieldType,
    ProjectionValidationResult,
    StatusOwnershipRuleCreate,
)

# These contracts are the only default fields that may cross the module
# boundary. Custom rules must still use one of the supported scalar types.
DEFAULT_TYPED_ALLOWLISTS: dict[ProjectionType, dict[str, Any]] = {
    ProjectionType.SUBJECT_STATUS: {
        "subject_id": ProjectionFieldType.UUID.value,
        "approved_pseudonym": ProjectionFieldType.STRING.value,
        "approved_reference": ProjectionFieldType.STRING.value,
        "status": ProjectionFieldType.STRING.value,
        "milestone_date": ProjectionFieldType.DATETIME.value,
        "source_version": ProjectionFieldType.STRING.value,
        "rule_version": ProjectionFieldType.INTEGER.value,
    },
    ProjectionType.QUERY_SUMMARY: {
        "query_id": ProjectionFieldType.UUID.value,
        "query_type": ProjectionFieldType.STRING.value,
        "study_id": ProjectionFieldType.UUID.value,
        "site_id": ProjectionFieldType.UUID.value,
        "subject_id": ProjectionFieldType.UUID.value,
        "approved_pseudonym": ProjectionFieldType.STRING.value,
        "form_reference": ProjectionFieldType.STRING.value,
        "visit_reference": ProjectionFieldType.STRING.value,
        "opened_at": ProjectionFieldType.DATETIME.value,
        "resolved_at": ProjectionFieldType.DATETIME.value,
        "status": ProjectionFieldType.STRING.value,
        "summary": ProjectionFieldType.STRING.value,
    },
    ProjectionType.DATA_QUALITY_SIGNAL: {
        "study_id": ProjectionFieldType.UUID.value,
        "site_id": ProjectionFieldType.UUID.value,
        "signal_type": ProjectionFieldType.STRING.value,
        "value": ProjectionFieldType.NUMBER.value,
        "numerator": ProjectionFieldType.INTEGER.value,
        "denominator": ProjectionFieldType.INTEGER.value,
        "source_watermark": ProjectionFieldType.STRING.value,
        "calculated_at": ProjectionFieldType.DATETIME.value,
    },
    ProjectionType.COORDINATED_TRANSITION: {
        "entity_id": ProjectionFieldType.UUID.value,
        "status": ProjectionFieldType.STRING.value,
        "source_version": ProjectionFieldType.STRING.value,
    },
}


@dataclass(frozen=True, slots=True)
class CompiledOwnershipRule:
    """Immutable runtime representation used at both coordination boundaries."""

    entity_type: str
    field_path: str
    authoritative_module: Module
    writable_module: Module
    projection_target: Module | None
    projection_type: ProjectionType | None
    allowed_transitions: dict[str, tuple[str, ...]]
    typed_allowlist: dict[str, Any]
    version: int
    effective_from: datetime
    effective_to: datetime | None
    status: OwnershipRuleStatus

    def is_effective(self, at: datetime | None = None) -> bool:
        moment = ensure_utc(at or utc_now())
        return (
            self.status is OwnershipRuleStatus.ACTIVE
            and self.effective_from <= moment
            and (self.effective_to is None or moment < self.effective_to)
        )


class StatusOwnershipRuleService:
    """Persist, resolve, and compile one authoritative ownership policy."""

    def __init__(self) -> None:
        self._runtime_rules: dict[tuple[str, str], CompiledOwnershipRule] = {}

    # ------------------------------------------------------------------
    # Rule compilation and validation
    # ------------------------------------------------------------------

    @staticmethod
    def _rule_values(rule: StatusOwnershipRule | Mapping[str, Any]) -> Mapping[str, Any]:
        if isinstance(rule, Mapping):
            return rule
        return {
            "entity_type": rule.entity_type,
            "field_path": rule.field_path,
            "authoritative_module": rule.authoritative_module,
            "writable_module": rule.writable_module,
            "projection_target": rule.projection_target,
            "projection_type": rule.projection_type,
            "allowed_transitions": rule.allowed_transitions,
            "typed_allowlist": getattr(rule, "allowlist_json", getattr(rule, "typed_allowlist", {})),
            "version": rule.version,
            "effective_from": rule.effective_from,
            "effective_to": rule.effective_to,
            "status": rule.status,
        }

    @staticmethod
    def _module(value: Module | str) -> Module:
        try:
            return value if isinstance(value, Module) else Module(str(value))
        except ValueError as exc:
            raise ValidationError(
                "Ownership rule contains an unknown module",
                {"reason": "INVALID_OWNERSHIP_MODULE"},
            ) from exc

    @staticmethod
    def _projection_type(value: ProjectionType | str | None) -> ProjectionType | None:
        if value is None:
            return None
        try:
            return value if isinstance(value, ProjectionType) else ProjectionType(str(value))
        except ValueError as exc:
            raise ValidationError(
                "Ownership rule contains an unknown projection type",
                {"reason": "INVALID_PROJECTION_TYPE"},
            ) from exc

    @classmethod
    def _compile_allowlist(
        cls, projection_type: ProjectionType | None, allowlist: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        selected = dict(allowlist or DEFAULT_TYPED_ALLOWLISTS.get(projection_type, {}))
        compiled: dict[str, Any] = {}
        for path, declaration in selected.items():
            if not isinstance(path, str) or not path.strip():
                raise ValidationError(
                    "Projection allowlist field paths must be non-empty strings",
                    {"reason": "INVALID_PROJECTION_ALLOWLIST"},
                )
            normalized_path = path.strip()
            if any(token in normalized_path.lower().replace("-", "_") for token in PROHIBITED_PROJECTION_TOKENS):
                raise ValidationError(
                    "Projection allowlist contains a prohibited field",
                    {"reason": "PROJECTION_FIELD_NOT_ALLOWED", "field": normalized_path},
                )
            if isinstance(declaration, Mapping):
                field_type = declaration.get("type")
                if field_type is None:
                    raise ValidationError(
                        "Projection field type is required",
                        {"reason": "INVALID_PROJECTION_FIELD_TYPE", "field": normalized_path},
                    )
                normalized = dict(declaration)
                normalized["type"] = str(field_type)
            else:
                normalized = str(declaration)
            allowed_types = {item.value for item in ProjectionFieldType}
            field_type = normalized["type"] if isinstance(normalized, Mapping) else normalized
            if field_type not in allowed_types:
                raise ValidationError(
                    "Projection field type is not supported",
                    {"reason": "INVALID_PROJECTION_FIELD_TYPE", "field": normalized_path},
                )
            compiled[normalized_path] = normalized
        return compiled

    @classmethod
    def compile_rule(cls, rule: StatusOwnershipRule | Mapping[str, Any]) -> CompiledOwnershipRule:
        values = cls._rule_values(rule)
        entity_type = str(values["entity_type"]).strip()
        field_path = str(values["field_path"]).strip()
        if not entity_type or not field_path:
            raise ValidationError("Ownership rule names must not be blank", {"reason": "INVALID_OWNERSHIP_RULE"})
        authoritative = cls._module(values["authoritative_module"])
        writable = cls._module(values["writable_module"])
        target = cls._module(values["projection_target"]) if values.get("projection_target") else None
        if writable is not authoritative:
            raise ConflictError(
                "A field must have one authoritative writable module",
                {"reason": "CONFLICTING_OWNERSHIP_RULE"},
            )
        if target is authoritative:
            raise ConflictError(
                "A projection target cannot be its authoritative module",
                {"reason": "CONFLICTING_OWNERSHIP_RULE"},
            )
        projection_type = cls._projection_type(values.get("projection_type"))
        effective_from = values.get("effective_from") or utc_now()
        effective_to = values.get("effective_to")
        try:
            effective_from = ensure_utc(effective_from)
            effective_to = ensure_utc(effective_to) if effective_to else None
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Ownership-rule effective timestamps must be timezone-aware UTC values",
                {"reason": "INVALID_EFFECTIVE_INTERVAL"},
            ) from exc
        if effective_to is not None and effective_to <= effective_from:
            raise ValidationError("Ownership-rule effective interval is invalid", {"reason": "INVALID_EFFECTIVE_INTERVAL"})
        status = values.get("status", OwnershipRuleStatus.ACTIVE)
        try:
            status = status if isinstance(status, OwnershipRuleStatus) else OwnershipRuleStatus(str(status))
        except ValueError as exc:
            raise ValidationError("Ownership-rule status is invalid", {"reason": "INVALID_RULE_STATUS"}) from exc
        transitions = values.get("allowed_transitions") or {}
        if not isinstance(transitions, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value)
            for key, value in transitions.items()
        ):
            raise ValidationError("Allowed transitions must be string lists", {"reason": "INVALID_ALLOWED_TRANSITIONS"})
        return CompiledOwnershipRule(
            entity_type=entity_type,
            field_path=field_path,
            authoritative_module=authoritative,
            writable_module=writable,
            projection_target=target,
            projection_type=projection_type,
            allowed_transitions={str(key): tuple(value) for key, value in transitions.items()},
            typed_allowlist=cls._compile_allowlist(projection_type, values.get("typed_allowlist", values.get("allowlist_json"))),
            version=int(values.get("version", 1)),
            effective_from=effective_from,
            effective_to=effective_to,
            status=status,
        )

    @classmethod
    def default_allowlist(cls, projection_type: ProjectionType | str) -> dict[str, Any]:
        """Return a copy of a built-in schema contract."""

        kind = cls._projection_type(projection_type)
        return dict(DEFAULT_TYPED_ALLOWLISTS.get(kind, {}))

    # ------------------------------------------------------------------
    # Typed projection validation
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, Mapping):
                flattened.update(StatusOwnershipRuleService._flatten(child, path))
            else:
                flattened[path] = child
        return flattened

    @staticmethod
    def _type_name(declaration: Any) -> str:
        return str(declaration.get("type")) if isinstance(declaration, Mapping) else str(declaration)

    @classmethod
    def _coerce(cls, value: Any, declaration: Any, field: str) -> Any:
        if value is None:
            return None
        field_type = cls._type_name(declaration)
        if field_type == ProjectionFieldType.UUID.value:
            try:
                return str(value if isinstance(value, UUID) else UUID(str(value)))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValidationError("Projection field has an invalid UUID", {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": field}) from exc
        if field_type == ProjectionFieldType.STRING.value:
            if not isinstance(value, str):
                raise ValidationError("Projection field has an invalid type", {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": field})
            return value
        if field_type == ProjectionFieldType.INTEGER.value:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValidationError("Projection field has an invalid type", {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": field})
            return value
        if field_type == ProjectionFieldType.NUMBER.value:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError("Projection field has an invalid type", {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": field})
            return value
        if field_type == ProjectionFieldType.BOOLEAN.value:
            if not isinstance(value, bool):
                raise ValidationError("Projection field has an invalid type", {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": field})
            return value
        if field_type == ProjectionFieldType.DATETIME.value:
            if isinstance(value, datetime):
                return ensure_utc(value).isoformat()
            if isinstance(value, str):
                try:
                    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00"))).isoformat()
                except ValueError as exc:
                    raise ValidationError("Projection field has an invalid timestamp", {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": field}) from exc
            raise ValidationError("Projection field has an invalid timestamp", {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": field})
        if field_type == ProjectionFieldType.ENUM.value:
            choices = declaration.get("values", []) if isinstance(declaration, Mapping) else []
            if not isinstance(value, str) or (choices and value not in choices):
                raise ValidationError("Projection field has an invalid enum value", {"reason": "PROJECTION_FIELD_TYPE_INVALID", "field": field})
            return value
        raise ValidationError("Projection field type is not supported", {"reason": "INVALID_PROJECTION_FIELD_TYPE", "field": field})

    @classmethod
    def validate_payload(
        cls,
        rule: CompiledOwnershipRule | StatusOwnershipRule | Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> ProjectionValidationResult:
        """Validate and minimize one source payload against a compiled rule."""

        compiled = rule if isinstance(rule, CompiledOwnershipRule) else cls.compile_rule(rule)
        if not isinstance(payload, Mapping):
            raise ValidationError("Projection payload must be an object", {"reason": "PROJECTION_PAYLOAD_INVALID"})
        flattened = cls._flatten(payload)
        prohibited = [
            path
            for path in flattened
            if any(token in path.lower().replace("-", "_") for token in PROHIBITED_PROJECTION_TOKENS)
        ]
        unknown = sorted(set(flattened) - set(compiled.typed_allowlist))
        rejected = tuple(sorted(set(prohibited) | set(unknown)))
        fingerprint = cls.fingerprint(payload)
        if rejected:
            raise ValidationError(
                "Projection payload contains fields outside its typed allowlist",
                {
                    "reason": "PROJECTION_FIELD_NOT_ALLOWED",
                    "rejected_field_count": len(rejected),
                    "payload_fingerprint": fingerprint,
                },
            )
        minimized = {path: cls._coerce(value, compiled.typed_allowlist[path], path) for path, value in flattened.items()}
        output: dict[str, Any] = {}
        for path, value in minimized.items():
            cursor = output
            parts = path.split(".")
            for part in parts[:-1]:
                cursor = cursor.setdefault(part, {})
            cursor[parts[-1]] = value
        return ProjectionValidationResult(accepted=True, payload=output, fingerprint=cls.fingerprint(output))

    validate_projection = validate_payload
    validate_allowlisted_payload = validate_payload

    @staticmethod
    def fingerprint(payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Persistence and current-version resolution
    # ------------------------------------------------------------------

    async def create_rule(
        self,
        session: AsyncSession,
        data: StatusOwnershipRuleCreate,
        actor_id: UUID | None,
        *,
        correlation_id: str | None = None,
    ) -> StatusOwnershipRule:
        """Persist a validated version, rejecting overlapping active rules."""

        compiled = self.compile_rule(data.model_dump())
        rows = await self._matching_rows(session, compiled.entity_type, compiled.field_path)
        self._reject_overlap(rows, compiled)
        rule = StatusOwnershipRule(
            entity_type=compiled.entity_type,
            field_path=compiled.field_path,
            authoritative_module=compiled.authoritative_module.value,
            writable_module=compiled.writable_module.value,
            projection_target=compiled.projection_target.value if compiled.projection_target else None,
            projection_type=compiled.projection_type.value if compiled.projection_type else None,
            allowed_transitions={key: list(value) for key, value in compiled.allowed_transitions.items()},
            allowlist_json=compiled.typed_allowlist,
            version=compiled.version,
            effective_from=compiled.effective_from,
            effective_to=compiled.effective_to,
            status=compiled.status,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation_id or str(uuid4()),
        )
        session.add(rule)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="status_ownership_rule",
            entity_id=rule.id,
            action="create",
            module=Module.CTMS,
            actor_id=actor_id,
            correlation_id=rule.correlation_id,
            changed_fields=["authoritative_module", "writable_module", "projection_target", "typed_allowlist", "version", "effective_interval", "status"],
        )
        return rule

    async def activate_rule(
        self, session: AsyncSession, rule: StatusOwnershipRule, actor_id: UUID | None, *, correlation_id: str | None = None
    ) -> StatusOwnershipRule:
        """Activate a version only when it does not overlap another active version."""

        compiled = self.compile_rule(rule)
        rows = await self._matching_rows(session, rule.entity_type, rule.field_path)
        self._reject_overlap([row for row in rows if row.id != rule.id], compiled)
        rule.status = OwnershipRuleStatus.ACTIVE
        rule.updated_by = actor_id
        rule.updated_at = utc_now()
        await session.flush()
        await audit_service.record(
            session,
            entity_type="status_ownership_rule",
            entity_id=rule.id,
            action="activate",
            module=Module.CTMS,
            actor_id=actor_id,
            correlation_id=correlation_id or rule.correlation_id,
            changed_fields=["status"],
        )
        return rule

    async def retire_rule(
        self, session: AsyncSession, rule: StatusOwnershipRule, actor_id: UUID | None, *, reason: str, correlation_id: str | None = None
    ) -> StatusOwnershipRule:
        if not reason or not reason.strip():
            raise ValidationError("Retirement reason is required", {"reason": "REASON_REQUIRED"})
        rule.status = OwnershipRuleStatus.RETIRED
        rule.retired_at = utc_now()
        rule.retired_by = actor_id
        rule.retirement_reason = reason.strip()
        rule.updated_by = actor_id
        rule.updated_at = rule.retired_at
        await session.flush()
        await audit_service.record(
            session,
            entity_type="status_ownership_rule",
            entity_id=rule.id,
            action="retire",
            module=Module.CTMS,
            actor_id=actor_id,
            correlation_id=correlation_id or rule.correlation_id,
            reason=reason.strip(),
            changed_fields=["status", "retired_at", "retired_by", "retirement_reason"],
        )
        return rule

    async def current_rule(
        self, session: AsyncSession, entity_type: str, field_path: str, *, at: datetime | None = None
    ) -> StatusOwnershipRule | None:
        rows = await self._matching_rows(session, entity_type, field_path)
        moment = ensure_utc(at or utc_now())
        candidates = [
            row for row in rows
            if str(getattr(row, "status", "")) in {OwnershipRuleStatus.ACTIVE.value, OwnershipRuleStatus.ACTIVE}
            and row.effective_from <= moment
            and (row.effective_to is None or moment < row.effective_to)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.version, reverse=True)
        if len(candidates) > 1 and candidates[0].version == candidates[1].version:
            raise ConflictError(
                "More than one current ownership rule applies",
                {"reason": "AMBIGUOUS_OWNERSHIP_RULE", "entity_type": entity_type, "field_path": field_path},
            )
        return candidates[0]

    async def resolve_current_rule(self, *args: Any, **kwargs: Any) -> StatusOwnershipRule | None:
        """Explicit alias used by coordination consumers."""

        return await self.current_rule(*args, **kwargs)

    get_current_rule = current_rule

    async def _matching_rows(self, session: AsyncSession, entity_type: str, field_path: str) -> list[StatusOwnershipRule]:
        result = await session.execute(
            select(StatusOwnershipRule).where(
                StatusOwnershipRule.entity_type == entity_type,
                StatusOwnershipRule.field_path == field_path,
            )
        )
        return [row for row in result.scalars().all() if row.entity_type == entity_type and row.field_path == field_path]

    @staticmethod
    def _reject_overlap(rows: list[StatusOwnershipRule], candidate: CompiledOwnershipRule) -> None:
        for row in rows:
            row_status = str(row.status)
            if row_status not in {OwnershipRuleStatus.ACTIVE.value, OwnershipRuleStatus.ACTIVE}:
                continue
            existing_from = ensure_utc(row.effective_from)
            existing_to = ensure_utc(row.effective_to) if row.effective_to else None
            overlaps = existing_from < (candidate.effective_to or datetime.max.replace(tzinfo=UTC)) and (
                existing_to is None or existing_to > candidate.effective_from
            )
            if overlaps:
                raise ConflictError(
                    "An active ownership rule already covers this field and interval",
                    {"reason": "AMBIGUOUS_OWNERSHIP_RULE", "entity_type": candidate.entity_type, "field_path": candidate.field_path},
                )

    # ------------------------------------------------------------------
    # Runtime integration for services that accept policy before persistence
    # ------------------------------------------------------------------

    def register_runtime_rule(self, key: str, rule: Any) -> CompiledOwnershipRule:
        """Register an in-process rule for command acceptance before DB lookup."""

        compiled = self.compile_rule(
            {
                "entity_type": "Subject",
                "field_path": key,
                "authoritative_module": getattr(rule, "authoritative_module", Module.EDC),
                "writable_module": getattr(rule, "writable_module", Module.EDC),
                "projection_target": getattr(rule, "projection_target", Module.CTMS),
                "projection_type": ProjectionType.SUBJECT_STATUS,
                "allowed_transitions": {},
                "typed_allowlist": DEFAULT_TYPED_ALLOWLISTS[ProjectionType.SUBJECT_STATUS],
                "version": getattr(rule, "rule_version", 1),
                "effective_from": utc_now(),
                "status": OwnershipRuleStatus.ACTIVE if getattr(rule, "active", True) else OwnershipRuleStatus.RETIRED,
            }
        )
        self._runtime_rules[("Subject", key)] = compiled
        return compiled

    def runtime_rule(self, entity_type: str, field_path: str) -> CompiledOwnershipRule | None:
        rule = self._runtime_rules.get((entity_type, field_path))
        return rule if rule and rule.is_effective() else None


status_ownership_rule_service = StatusOwnershipRuleService()

__all__ = [
    "DEFAULT_TYPED_ALLOWLISTS",
    "CompiledOwnershipRule",
    "StatusOwnershipRuleService",
    "status_ownership_rule_service",
]
