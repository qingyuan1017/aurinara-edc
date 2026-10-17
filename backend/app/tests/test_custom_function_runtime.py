"""Governance and fail-closed tests for custom Python functions."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.database import Base
from app.core.exceptions import BusinessRuleError, ServiceUnavailableError, ValidationError
from app.core.permissions import DESIGNER_PERMISSION_CODES, PERMISSION_CODES
from app.models.designer.custom_function import (
    CustomFunctionExecution,
    CustomFunctionVersionStatus,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.edc.study import Study, StudyStatus
from app.models.shared.audit import AuditEvent
from app.models.shared.identity import User, UserStatus
from app.schemas.designer.custom_function import (
    CustomFunctionCreate,
    CustomFunctionExecuteRequest,
)
from app.services.designer.custom_function_runtime import (
    CustomFunctionRuntimeClient,
    RuntimeResult,
)
from app.services.designer.custom_function_service import CustomFunctionService
from app.services.designer.design_clone_service import DesignCloneService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class SuccessfulRuntime:
    async def execute(self, **_kwargs) -> RuntimeResult:
        return RuntimeResult(
            runtime_execution_id="sandbox-1",
            status="succeeded",
            result={"score": 3},
            commands=[{"type": "show", "item_oid": "ITEM.AEOUT"}],
            error_code=None,
            duration_ms=7,
        )


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_scope(session: AsyncSession):
    author = User(
        email=f"author-{uuid4()}@example.test",
        first_name="Function",
        last_name="Author",
        status=UserStatus.active,
    )
    approver = User(
        email=f"approver-{uuid4()}@example.test",
        first_name="Function",
        last_name="Approver",
        status=UserStatus.active,
    )
    session.add_all([author, approver])
    await session.flush()
    study = Study(
        study_code=f"CF-{uuid4().hex[:8]}",
        title="Custom Function Study",
        status=StudyStatus.draft,
        created_by=author.id,
    )
    session.add(study)
    await session.flush()
    design = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
    )
    session.add(design)
    await session.flush()
    return author, approver, design


async def test_custom_function_requires_maker_checker_and_records_hashed_execution():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            author, approver, design = await _seed_scope(session)
            service = CustomFunctionService(runtime=SuccessfulRuntime())  # type: ignore[arg-type]
            definition = await service.create_definition(
                session,
                design,
                CustomFunctionCreate(
                    name="derive_score",
                    source_code="def main(inputs):\n    return {'score': inputs['a'] + 1}\n",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                ),
                actor_id=author.id,
            )
            version = definition.versions[0]
            await service.submit(session, version, design, author.id)

            with pytest.raises(BusinessRuleError, match="approver must be different"):
                await service.approve(session, version, design, author.id)

            await service.approve(session, version, design, approver.id)
            await service.activate(session, version, design, approver.id)
            response = await service.execute(
                session,
                version,
                design,
                CustomFunctionExecuteRequest(inputs={"a": 2}),
                actor_id=author.id,
            )

            assert version.status == CustomFunctionVersionStatus.active
            assert response.result == {"score": 3}
            execution = (await session.execute(select(CustomFunctionExecution))).scalar_one()
            assert execution.input_sha256 != ""
            assert execution.output_sha256 != ""
            assert len(execution.input_sha256) == 64
            audit_events = list((await session.execute(select(AuditEvent))).scalars())
            serialized = json.dumps(
                [
                    {
                        "old": event.old_value,
                        "new": event.new_value,
                        "reason": event.reason,
                    }
                    for event in audit_events
                ]
            )
            assert "def main" not in serialized
            assert '"a": 2' not in serialized
    finally:
        await engine.dispose()


async def test_runtime_disabled_fails_closed_without_local_execution():
    client = CustomFunctionRuntimeClient(Settings(custom_function_runtime_enabled=False))
    with pytest.raises(ServiceUnavailableError) as caught:
        await client.execute(
            function_version_id=str(uuid4()),
            source_code="raise RuntimeError('must not run here')",
            source_sha256="0" * 64,
            entrypoint="main",
            inputs={},
            input_schema={},
            output_schema={},
        )
    assert caught.value.details["reason"] == "CUSTOM_FUNCTION_RUNTIME_DISABLED"


async def test_persisted_source_fields_are_immutable():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            author, _, design = await _seed_scope(session)
            definition = await CustomFunctionService().create_definition(
                session,
                design,
                CustomFunctionCreate(
                    name="immutable_source",
                    source_code="def main(inputs):\n    return inputs\n",
                ),
                actor_id=author.id,
            )
            await session.commit()
            definition.versions[0].source_code = "def main(inputs):\n    return {}\n"
            with pytest.raises(ValueError, match="source versions are immutable"):
                await session.flush()
            await session.rollback()
    finally:
        await engine.dispose()


async def test_amendment_clone_preserves_approved_function_version_without_executions():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            author, approver, source_design = await _seed_scope(session)
            service = CustomFunctionService()
            definition = await service.create_definition(
                session,
                source_design,
                CustomFunctionCreate(
                    name="clone_me",
                    source_code="def main(inputs):\n    return inputs\n",
                ),
                actor_id=author.id,
            )
            version = definition.versions[0]
            await service.submit(session, version, source_design, author.id)
            await service.approve(session, version, source_design, approver.id)
            await service.activate(session, version, source_design, approver.id)
            source_design.status = StudyVersionStatus.published
            target_design = StudyVersion(
                study_id=source_design.study_id,
                version_number="2.0",
                status=StudyVersionStatus.draft,
                amended_from_version_id=source_design.id,
            )
            session.add(target_design)
            await session.flush()

            counts = await DesignCloneService().clone_version(
                session,
                source_version_id=source_design.id,
                target_version_id=target_design.id,
            )

            cloned = (
                await session.execute(
                    select(CustomFunctionExecution.function_version_id).where(
                        CustomFunctionExecution.study_id == source_design.study_id
                    )
                )
            ).all()
            definitions = await service.list_definitions(session, target_design.id)
            assert counts["custom_functions"] == 1
            assert counts["custom_function_versions"] == 1
            assert len(definitions) == 1
            assert definitions[0].versions[0].source_sha256 == version.source_sha256
            assert definitions[0].versions[0].status == CustomFunctionVersionStatus.active
            assert cloned == []
    finally:
        await engine.dispose()


async def test_runtime_rejects_non_allowlisted_commands():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "execution_id": "sandbox-2",
                "status": "succeeded",
                "result": None,
                "commands": [{"type": "run_sql", "statement": "DELETE FROM subjects"}],
                "duration_ms": 1,
            },
        )

    settings = Settings(
        custom_function_runtime_enabled=True,
        custom_function_runtime_url="https://runtime.test",
    )
    client = CustomFunctionRuntimeClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(ValidationError) as caught:
        await client.execute(
            function_version_id=str(uuid4()),
            source_code="def main(inputs): return inputs",
            source_sha256="0" * 64,
            entrypoint="main",
            inputs={},
            input_schema={},
            output_schema={},
        )
    assert caught.value.details["reason"] == "CUSTOM_FUNCTION_COMMAND_NOT_ALLOWED"


def test_custom_function_permissions_are_designer_scoped():
    expected = {
        "designer.custom_function.author",
        "designer.custom_function.approve",
        "designer.custom_function.execute",
    }
    assert expected <= PERMISSION_CODES
    assert expected <= DESIGNER_PERMISSION_CODES
