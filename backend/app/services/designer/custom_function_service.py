"""Lifecycle and execution orchestration for custom Python functions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.designer.custom_function import (
    CustomFunctionDefinition,
    CustomFunctionExecution,
    CustomFunctionExecutionStatus,
    CustomFunctionVersion,
    CustomFunctionVersionStatus,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.schemas.designer.custom_function import (
    CustomFunctionCreate,
    CustomFunctionExecuteRequest,
    CustomFunctionExecutionResponse,
    CustomFunctionVersionCreate,
)
from app.services.designer.custom_function_runtime import (
    CustomFunctionRuntimeClient,
    custom_function_runtime_client,
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class CustomFunctionService:
    def __init__(self, runtime: CustomFunctionRuntimeClient | None = None) -> None:
        self.runtime = runtime or custom_function_runtime_client

    @staticmethod
    def _source_hash(source_code: str) -> str:
        return hashlib.sha256(source_code.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_draft(study_version: StudyVersion) -> None:
        if study_version.status != StudyVersionStatus.draft:
            raise BusinessRuleError("Custom functions can only be authored in a draft design")

    async def list_definitions(
        self, session: AsyncSession, study_version_id: UUID
    ) -> list[CustomFunctionDefinition]:
        result = await session.execute(
            select(CustomFunctionDefinition)
            .where(CustomFunctionDefinition.study_version_id == study_version_id)
            .options(selectinload(CustomFunctionDefinition.versions))
            .order_by(CustomFunctionDefinition.name)
        )
        return list(result.scalars().unique().all())

    async def get_definition(
        self, session: AsyncSession, definition_id: UUID
    ) -> CustomFunctionDefinition:
        result = await session.execute(
            select(CustomFunctionDefinition)
            .where(CustomFunctionDefinition.id == definition_id)
            .options(selectinload(CustomFunctionDefinition.versions))
        )
        definition = result.scalars().first()
        if definition is None:
            raise NotFoundError("Custom function not found")
        return definition

    async def get_version(
        self, session: AsyncSession, version_id: UUID
    ) -> tuple[CustomFunctionVersion, CustomFunctionDefinition, StudyVersion]:
        result = await session.execute(
            select(CustomFunctionVersion)
            .where(CustomFunctionVersion.id == version_id)
            .options(selectinload(CustomFunctionVersion.definition))
        )
        version = result.scalars().first()
        if version is None:
            raise NotFoundError("Custom function version not found")
        definition = version.definition
        study_version = await session.get(StudyVersion, definition.study_version_id)
        if study_version is None:
            raise NotFoundError("Study version not found")
        return version, definition, study_version

    async def create_definition(
        self,
        session: AsyncSession,
        study_version: StudyVersion,
        body: CustomFunctionCreate,
        *,
        actor_id: UUID,
    ) -> CustomFunctionDefinition:
        self._require_draft(study_version)
        existing = await session.scalar(
            select(CustomFunctionDefinition.id).where(
                CustomFunctionDefinition.study_version_id == study_version.id,
                func.lower(CustomFunctionDefinition.name) == body.name.lower(),
            )
        )
        if existing is not None:
            raise ConflictError("A custom function with this name already exists")
        definition = CustomFunctionDefinition(
            study_version_id=study_version.id,
            name=body.name,
            description=body.description,
            created_by=actor_id,
        )
        version = self._new_version(definition, 1, body, actor_id)
        session.add_all([definition, version])
        await session.flush()
        await audit_service.record(
            session,
            entity_type="custom_function_version",
            entity_id=version.id,
            action="create",
            module=Module.DESIGNER,
            actor_id=actor_id,
            study_id=study_version.study_id,
            changed_fields=["name", "source_sha256", "entrypoint"],
            scope={"study_version_id": study_version.id},
        )
        await session.refresh(definition, attribute_names=["versions"])
        return definition

    async def create_version(
        self,
        session: AsyncSession,
        definition: CustomFunctionDefinition,
        study_version: StudyVersion,
        body: CustomFunctionVersionCreate,
        *,
        actor_id: UUID,
    ) -> CustomFunctionVersion:
        self._require_draft(study_version)
        number = (
            int(
                await session.scalar(
                    select(func.coalesce(func.max(CustomFunctionVersion.version_number), 0)).where(
                        CustomFunctionVersion.definition_id == definition.id
                    )
                )
                or 0
            )
            + 1
        )
        version = self._new_version(definition, number, body, actor_id)
        session.add(version)
        await session.flush()
        await self._audit(session, version, study_version, "create", actor_id)
        return version

    @staticmethod
    def _new_version(
        definition: CustomFunctionDefinition,
        version_number: int,
        body: CustomFunctionCreate | CustomFunctionVersionCreate,
        actor_id: UUID,
    ) -> CustomFunctionVersion:
        return CustomFunctionVersion(
            definition=definition,
            version_number=version_number,
            language="python",
            source_code=body.source_code,
            source_sha256=CustomFunctionService._source_hash(body.source_code),
            entrypoint=body.entrypoint,
            input_schema=body.input_schema,
            output_schema=body.output_schema,
            status=CustomFunctionVersionStatus.draft,
            created_by=actor_id,
        )

    async def submit(
        self,
        session: AsyncSession,
        version: CustomFunctionVersion,
        study_version: StudyVersion,
        actor_id: UUID,
    ) -> CustomFunctionVersion:
        self._require_draft(study_version)
        if version.status != CustomFunctionVersionStatus.draft:
            raise BusinessRuleError("Only a draft custom function version can be submitted")
        version.status = CustomFunctionVersionStatus.pending_approval
        version.submitted_by = actor_id
        version.submitted_at = datetime.now(UTC)
        await session.flush()
        await self._audit(session, version, study_version, "submit", actor_id)
        return version

    async def approve(
        self,
        session: AsyncSession,
        version: CustomFunctionVersion,
        study_version: StudyVersion,
        actor_id: UUID,
    ) -> CustomFunctionVersion:
        self._require_draft(study_version)
        if version.status != CustomFunctionVersionStatus.pending_approval:
            raise BusinessRuleError("Only a pending custom function version can be approved")
        if actor_id in {version.created_by, version.submitted_by}:
            raise BusinessRuleError(
                "The custom function approver must be different from its author and submitter",
                details={"reason": "CUSTOM_FUNCTION_MAKER_CHECKER_REQUIRED"},
            )
        version.status = CustomFunctionVersionStatus.approved
        version.approved_by = actor_id
        version.approved_at = datetime.now(UTC)
        version.rejection_reason = None
        await session.flush()
        await self._audit(session, version, study_version, "approve", actor_id)
        return version

    async def reject(
        self,
        session: AsyncSession,
        version: CustomFunctionVersion,
        study_version: StudyVersion,
        actor_id: UUID,
        reason: str,
    ) -> CustomFunctionVersion:
        self._require_draft(study_version)
        if version.status != CustomFunctionVersionStatus.pending_approval:
            raise BusinessRuleError("Only a pending custom function version can be rejected")
        version.status = CustomFunctionVersionStatus.rejected
        version.rejection_reason = reason
        await session.flush()
        await self._audit(session, version, study_version, "reject", actor_id, reason=reason)
        return version

    async def activate(
        self,
        session: AsyncSession,
        version: CustomFunctionVersion,
        study_version: StudyVersion,
        actor_id: UUID,
    ) -> CustomFunctionVersion:
        self._require_draft(study_version)
        if version.status != CustomFunctionVersionStatus.approved:
            raise BusinessRuleError("Only an approved custom function version can be activated")
        active_versions = list(
            (
                await session.execute(
                    select(CustomFunctionVersion).where(
                        CustomFunctionVersion.definition_id == version.definition_id,
                        CustomFunctionVersion.status == CustomFunctionVersionStatus.active,
                    )
                )
            ).scalars()
        )
        now = datetime.now(UTC)
        for active in active_versions:
            active.status = CustomFunctionVersionStatus.retired
            active.retired_at = now
        version.status = CustomFunctionVersionStatus.active
        version.activated_at = now
        await session.flush()
        await self._audit(session, version, study_version, "activate", actor_id)
        return version

    async def retire(
        self,
        session: AsyncSession,
        version: CustomFunctionVersion,
        study_version: StudyVersion,
        actor_id: UUID,
    ) -> CustomFunctionVersion:
        if version.status != CustomFunctionVersionStatus.active:
            raise BusinessRuleError("Only an active custom function version can be retired")
        version.status = CustomFunctionVersionStatus.retired
        version.retired_at = datetime.now(UTC)
        await session.flush()
        await self._audit(session, version, study_version, "retire", actor_id)
        return version

    async def disable(
        self,
        session: AsyncSession,
        version: CustomFunctionVersion,
        study_version: StudyVersion,
        actor_id: UUID,
    ) -> CustomFunctionVersion:
        if version.status not in {
            CustomFunctionVersionStatus.approved,
            CustomFunctionVersionStatus.active,
        }:
            raise BusinessRuleError(
                "Only an approved or active custom function version can be disabled"
            )
        version.status = CustomFunctionVersionStatus.disabled
        version.retired_at = datetime.now(UTC)
        await session.flush()
        await self._audit(session, version, study_version, "disable", actor_id)
        return version

    async def execute(
        self,
        session: AsyncSession,
        version: CustomFunctionVersion,
        study_version: StudyVersion,
        body: CustomFunctionExecuteRequest,
        *,
        actor_id: UUID,
    ) -> CustomFunctionExecutionResponse:
        if version.status != CustomFunctionVersionStatus.active:
            raise BusinessRuleError("Only an active custom function version can be executed")
        if self._source_hash(version.source_code) != version.source_sha256:
            raise ConflictError(
                "Custom function source integrity check failed",
                details={"reason": "CUSTOM_FUNCTION_SOURCE_HASH_MISMATCH"},
            )
        inputs_hash = _canonical_hash(body.inputs)
        runtime_result = await self.runtime.execute(
            function_version_id=str(version.id),
            source_code=version.source_code,
            source_sha256=version.source_sha256,
            entrypoint=version.entrypoint,
            inputs=body.inputs,
            input_schema=version.input_schema,
            output_schema=version.output_schema,
        )
        output_value = {"result": runtime_result.result, "commands": runtime_result.commands}
        execution = CustomFunctionExecution(
            function_version_id=version.id,
            study_id=study_version.study_id,
            invoked_by=actor_id,
            status=CustomFunctionExecutionStatus(runtime_result.status),
            input_sha256=inputs_hash,
            output_sha256=(
                _canonical_hash(output_value) if runtime_result.status == "succeeded" else None
            ),
            runtime_execution_id=runtime_result.runtime_execution_id,
            duration_ms=runtime_result.duration_ms,
            error_code=runtime_result.error_code,
            completed_at=datetime.now(UTC),
        )
        session.add(execution)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="custom_function_execution",
            entity_id=execution.id,
            action=runtime_result.status,
            module=Module.DESIGNER,
            actor_id=actor_id,
            study_id=study_version.study_id,
            changed_fields=["status", "input_sha256", "output_sha256"],
            scope={
                "study_version_id": study_version.id,
                "custom_function_version_id": version.id,
            },
        )
        return CustomFunctionExecutionResponse(
            execution_id=execution.id,
            runtime_execution_id=runtime_result.runtime_execution_id,
            status=runtime_result.status,  # type: ignore[arg-type]
            result=runtime_result.result,
            commands=runtime_result.commands,
            error_code=runtime_result.error_code,
            duration_ms=runtime_result.duration_ms,
        )

    @staticmethod
    async def _audit(
        session: AsyncSession,
        version: CustomFunctionVersion,
        study_version: StudyVersion,
        action: str,
        actor_id: UUID,
        *,
        reason: str | None = None,
    ) -> None:
        await audit_service.record(
            session,
            entity_type="custom_function_version",
            entity_id=version.id,
            action=action,
            module=Module.DESIGNER,
            actor_id=actor_id,
            study_id=study_version.study_id,
            changed_fields=["status"],
            reason=reason,
            scope={"study_version_id": study_version.id},
        )


custom_function_service = CustomFunctionService()

__all__ = ["CustomFunctionService", "custom_function_service"]
