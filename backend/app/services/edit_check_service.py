"""Edit_Check_Engine definition, test, and runtime evaluation service.

Rules remain a constrained JSON DSL.  Runtime evaluation builds a read-only
mapping from the form instance, persists failed validation results in the
caller's transaction, and delegates query-severity matches to Query_Service.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.edit_check_dsl import evaluate_rule, validate_rule
from app.core.exceptions import NotFoundError
from app.models.edit_check import EditCheck, ValidationResult
from app.models.form_data import FieldValue, FormInstance
from app.models.form_metadata import (
    CodelistItem,
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.query import QueryTargetType, QueryType
from app.models.study import StudyVersion
from app.repositories.edit_check_repository import EditCheckRepository
from app.schemas.edit_check import EditCheckCreate, EditCheckUpdate
from app.services.query_service import QueryService
from app.services.query_service import query_service as default_query_service
from app.services.study_version_service import study_version_service

logger = logging.getLogger(__name__)

# Public module-level alias retained for callers/tests that replace the query
# service integration point.
query_service = default_query_service

_SEVERITIES = frozenset({"info", "warning", "error", "query"})


class EditCheckService:
    """Persist, test, and evaluate versioned declarative edit checks."""

    def __init__(
        self,
        repository: EditCheckRepository | None = None,
        query_service_instance: QueryService | None = None,
        query_service: QueryService | None = None,
    ) -> None:
        self.repository = repository or EditCheckRepository()
        # Accept both a descriptive keyword and the shorter keyword used by
        # callers that inject a fake service in unit/integration tests.
        self.query_service = query_service_instance or query_service or globals()["query_service"]

    @staticmethod
    def validate_rule(rule: Any) -> dict[str, Any]:
        """Validate a rule before it is handed to SQLAlchemy."""
        return validate_rule(rule)

    @staticmethod
    def evaluate(rule: Any, sample_data: Mapping[str, Any] | None = None) -> bool:
        """Safely evaluate a rule without writing clinical data.

        This is retained as the synchronous low-level API from task 19.2.
        Use :meth:`test` for the explicit test-without-persist contract and
        :meth:`evaluate_form_instance` for runtime persistence.
        """
        if isinstance(rule, EditCheck):
            rule = rule.rule_json
        return evaluate_rule(rule, sample_data)

    @staticmethod
    def test(rule: Any, sample_data: Mapping[str, Any] | None = None) -> bool:
        """Return the rule outcome against sample data without any DB writes.

        ``sample_data`` is intentionally passed directly to the safe DSL
        evaluator; no FormInstance, FieldValue, ValidationResult, or Query is
        created as a side effect.
        """
        return EditCheckService.evaluate(rule, sample_data)

    async def seed_example_edit_checks(
        self,
        session: AsyncSession,
        version: StudyVersion,
        actor_id: UUID,
    ) -> list[EditCheck]:
        """Seed the standard examples using this service instance."""
        from app.services.edit_check_examples import seed_example_edit_checks

        return await seed_example_edit_checks(
            session,
            version,
            actor_id,
            service=self,
        )

    async def evaluate_edit_check(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        edit_check: EditCheck,
        actor_id: UUID | None = None,
        *,
        sample_data: Mapping[str, Any] | None = None,
        persist: bool = True,
    ) -> ValidationResult | None:
        """Evaluate one check for a form and persist a failed result.

        The caller owns the transaction.  When a query-severity rule matches,
        a system Query is created in that same transaction and linked to the
        Form_Instance, which is one of the Query_Service's allowed targets.
        """
        context = dict(sample_data) if sample_data is not None else await self._form_context(
            session, form_instance
        )
        if not evaluate_rule(edit_check.rule_json, context):
            return None

        severity = self._severity(edit_check.severity)
        message = edit_check.description or f"Edit check '{edit_check.name}' failed"
        field_id = self._first_matching_field_id(edit_check.rule_json, context)
        result = ValidationResult(
            edit_check_id=edit_check.id,
            form_instance_id=form_instance.id,
            severity=severity,
            outcome="failed",
            field_definition_id=field_id,
            message=message,
        )

        if not persist:
            return result

        session.add(result)
        await session.flush()
        study_id, site_id, subject_id = await self._scope(session, form_instance)
        await audit_service.record(
            session,
            entity_type="validation_result",
            entity_id=result.id,
            action="create",
            study_id=study_id,
            site_id=site_id,
            subject_id=subject_id,
            actor_id=actor_id,
            field_name=str(field_id) if field_id else None,
            new_value=json.dumps(
                {"edit_check_id": str(edit_check.id), "severity": severity, "outcome": "failed"},
                sort_keys=True,
            ),
        )

        if severity == "query":
            await self.query_service.create_query(
                session,
                study_id=study_id,
                site_id=site_id,
                subject_id=subject_id,
                target_type=QueryTargetType.form_instance,
                target_id=form_instance.id,
                text=message,
                actor_id=actor_id,
                query_type=QueryType.system,
            )
        return result

    async def evaluate_form_instance(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        actor_id: UUID | None = None,
        edit_checks: list[EditCheck] | None = None,
        *,
        sample_data: Mapping[str, Any] | None = None,
        persist: bool = True,
    ) -> list[ValidationResult]:
        """Evaluate active checks for a form instance and return failures.

        If checks are not supplied, they are loaded from the study version that
        owns the form definition.  Only active checks are evaluated.  Results
        and generated system queries use the caller's transaction.
        """
        if edit_checks is None:
            version_id = await self._study_version_id(session, form_instance)
            edit_checks = await self.repository.list_for_version(session, version_id)

        results: list[ValidationResult] = []
        for edit_check in edit_checks:
            if not edit_check.is_active:
                continue
            result = await self.evaluate_edit_check(
                session,
                form_instance,
                edit_check,
                actor_id,
                sample_data=sample_data,
                persist=persist,
            )
            if result is not None:
                results.append(result)
        return results

    # Alias matching the design's runtime verb while preserving the task 19.2
    # synchronous ``evaluate(rule, sample_data)`` API.
    evaluate_runtime = evaluate_form_instance

    async def create_edit_check(
        self,
        session: AsyncSession,
        version: StudyVersion,
        data: EditCheckCreate | Mapping[str, Any],
        actor_id: UUID,
    ) -> EditCheck:
        """Create a rule only after draft-version and DSL validation succeed."""
        study_version_service.guard_mutable(version)
        payload = data.model_dump() if isinstance(data, EditCheckCreate) else dict(data)
        canonical_rule = validate_rule(payload["rule_json"])
        severity = self._severity(payload["severity"])

        edit_check = EditCheck(
            study_version_id=version.id,
            name=payload["name"],
            description=payload.get("description"),
            rule_json=canonical_rule,
            severity=severity,
            is_active=payload.get("is_active", True),
        )
        await self.repository.add(session, edit_check)
        await audit_service.record(
            session,
            entity_type="edit_check",
            entity_id=edit_check.id,
            action="create",
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=json.dumps(canonical_rule, sort_keys=True),
        )
        logger.info(
            "Edit check created: id=%s version_id=%s actor=%s",
            edit_check.id,
            version.id,
            actor_id,
        )
        return edit_check

    async def update_edit_check(
        self,
        session: AsyncSession,
        version: StudyVersion,
        edit_check: EditCheck,
        data: EditCheckUpdate | Mapping[str, Any],
        actor_id: UUID,
    ) -> EditCheck:
        """Update a draft rule, validating a replacement rule before mutation."""
        study_version_service.guard_mutable(version)
        changes = data.model_dump(exclude_unset=True) if isinstance(data, EditCheckUpdate) else dict(data)
        if "rule_json" in changes:
            changes["rule_json"] = validate_rule(changes["rule_json"])
        if "severity" in changes:
            changes["severity"] = self._severity(changes["severity"])

        old_values = {key: getattr(edit_check, key) for key in changes}
        for key, value in changes.items():
            setattr(edit_check, key, value)
        edit_check.updated_at = datetime.now(UTC)
        await self.repository.flush(session)
        await audit_service.record(
            session,
            entity_type="edit_check",
            entity_id=edit_check.id,
            action="update",
            study_id=version.study_id,
            actor_id=actor_id,
            old_value=json.dumps(old_values, default=str, sort_keys=True),
            new_value=json.dumps(changes, default=str, sort_keys=True),
        )
        return edit_check

    async def get_edit_check(self, session: AsyncSession, edit_check_id: UUID) -> EditCheck:
        edit_check = await self.repository.get(session, edit_check_id)
        if edit_check is None:
            raise NotFoundError(
                "Edit check not found", details={"edit_check_id": str(edit_check_id)}
            )
        return edit_check

    async def list_edit_checks(self, session: AsyncSession, study_version_id: UUID) -> list[EditCheck]:
        return await self.repository.list_for_version(session, study_version_id)

    @staticmethod
    def _severity(value: Any) -> str:
        value = getattr(value, "value", value)
        if value not in _SEVERITIES:
            raise ValueError(f"Unsupported edit-check severity: {value!r}")
        return str(value)

    async def _study_version_id(self, session: AsyncSession, form_instance: FormInstance) -> UUID:
        form_definition = getattr(form_instance, "form_definition", None)
        version_id = getattr(form_definition, "study_version_id", None)
        if version_id is not None:
            return version_id
        version_id = getattr(form_instance, "study_version_id", None)
        if version_id is not None:
            return version_id
        result = await session.execute(
            select(FormDefinition.study_version_id).where(
                FormDefinition.id == form_instance.form_definition_id
            )
        )
        version_id = result.scalar_one_or_none()
        if version_id is None:
            raise NotFoundError(
                "Form definition not found",
                details={"form_definition_id": str(form_instance.form_definition_id)},
            )
        return version_id

    async def _form_context(
        self, session: AsyncSession, form_instance: FormInstance
    ) -> dict[str, Any]:
        """Build a variable-name context and add lab range pseudo-fields."""
        context: dict[str, Any] = {}
        if isinstance(form_instance.data_jsonb, Mapping):
            context.update(form_instance.data_jsonb)

        field_values = list(getattr(form_instance, "field_values", None) or [])
        if not field_values:
            value_result = await session.execute(
                select(FieldValue).where(FieldValue.form_instance_id == form_instance.id)
            )
            field_values = list(value_result.scalars().all())

        definitions_result = await session.execute(
            select(FieldDefinition)
            .join(FormSection, FieldDefinition.form_section_id == FormSection.id)
            .where(FormSection.form_definition_id == form_instance.form_definition_id)
        )
        definitions = list(definitions_result.scalars().all())
        by_id = {field.id: field for field in definitions}
        for field_value in field_values:
            field = getattr(field_value, "field_definition", None) or by_id.get(
                field_value.field_definition_id
            )
            if field is None:
                continue
            value = self._parse_value(field_value.value, field.data_type)
            context[field.variable_name] = value
            context[str(field.id)] = value

        for field in definitions:
            variable = field.variable_name
            value = context.get(variable)
            if isinstance(value, Mapping):
                context.setdefault(variable, dict(value))
                for suffix in ("normal_low", "normal_high"):
                    if suffix in value:
                        context[f"{variable}.{suffix}"] = value[suffix]
            ranges = await self._reference_range(session, field, value)
            if ranges is not None:
                low, high = ranges
                context[f"{variable}.normal_low"] = low
                context[f"{variable}.normal_high"] = high
        return context

    async def _reference_range(
        self, session: AsyncSession, field: FieldDefinition, value: Any
    ) -> tuple[Any, Any] | None:
        if field.codelist_id is None:
            return None
        items = list(getattr(getattr(field, "codelist", None), "items", None) or [])
        if not items:
            result = await session.execute(
                select(CodelistItem).where(CodelistItem.codelist_id == field.codelist_id)
            )
            items = list(result.scalars().all())
        if not items:
            return None
        match = next((item for item in items if str(item.code) == str(value)), None)
        if match is None and len(items) == 1:
            match = items[0]
        if match is None or (match.normal_low is None and match.normal_high is None):
            return None
        return match.normal_low, match.normal_high

    async def _scope(
        self, session: AsyncSession, form_instance: FormInstance
    ) -> tuple[UUID | None, UUID | None, UUID | None]:
        subject = getattr(form_instance, "subject", None)
        if subject is None:
            from app.models.subject import Subject

            subject = await session.get(Subject, form_instance.subject_id)
        if subject is None:
            return None, None, form_instance.subject_id
        return subject.study_id, subject.site_id, form_instance.subject_id

    @staticmethod
    def _parse_value(value: Any, data_type: str | None) -> Any:
        if value is None or not data_type:
            return value
        kind = data_type.lower()
        try:
            if kind == "integer":
                return int(value)
            if kind in {"decimal", "float", "number"}:
                return Decimal(str(value))
            if kind == "boolean":
                if isinstance(value, bool):
                    return value
                return str(value).lower() in {"true", "1", "yes"}
        except (TypeError, ValueError, InvalidOperation):
            return value
        return value

    @staticmethod
    def _first_matching_field_id(rule: Any, context: Mapping[str, Any]) -> UUID | None:
        """Return a UUID field key when a rule references one directly."""
        if isinstance(rule, Mapping):
            for key in ("and", "or"):
                for child in rule.get(key, []):
                    match = EditCheckService._first_matching_field_id(child, context)
                    if match:
                        return match
            if "not" in rule:
                return EditCheckService._first_matching_field_id(rule["not"], context)
            field = rule.get("field")
            try:
                candidate = context.get(field) if isinstance(field, str) else None
                return UUID(field) if isinstance(field, str) and field in context and candidate is not None else None
            except (ValueError, TypeError):
                return None
        return None


async def seed_example_edit_checks(
    session: AsyncSession,
    version: StudyVersion,
    actor_id: UUID,
) -> list[EditCheck]:
    """Seed the standard five declarative edit-check examples.

    The implementation lives beside the other seed definitions while this
    compatibility wrapper keeps the public Edit_Check_Engine entry point easy
    to discover.
    """
    from app.services.edit_check_examples import seed_example_edit_checks as seed_examples

    return await seed_examples(session, version, actor_id)


edit_check_service = EditCheckService()

__all__ = ["EditCheckService", "edit_check_service", "seed_example_edit_checks"]
