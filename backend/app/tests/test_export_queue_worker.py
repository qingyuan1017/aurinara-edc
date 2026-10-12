"""Tests for the durable EDC export queue runner."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.ctms import Module
from app.models.shared.export import Export, ExportStatus, ExportType
from app.workers.export_queue_worker import claim_next, consume_once, process_next


def _export(*, status: str = ExportStatus.queued) -> Export:
    return Export(
        id=uuid4(),
        study_id=uuid4(),
        module=Module.EDC.value,
        content_owner=Module.EDC.value,
        export_type=ExportType.csv,
        status=status,
        requested_by=uuid4(),
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_claim_next_uses_locked_edc_owned_queue_query() -> None:
    session = AsyncMock()
    job = _export()
    session.scalar.return_value = job

    assert await claim_next(session) is job

    statement = session.scalar.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "exports.status = 'Queued'" in sql
    assert "exports.module = 'EDC'" in sql
    assert "exports.content_owner = 'EDC'" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_process_next_delegates_to_format_worker() -> None:
    session = AsyncMock()
    job = _export()
    session.scalar.return_value = job

    with patch(
        "app.workers.export_queue_worker.run_export",
        new_callable=AsyncMock,
    ) as worker:
        assert await process_next(session) is job

    worker.assert_awaited_once_with(session, job)


@pytest.mark.asyncio
async def test_process_next_retains_failed_job_without_raising() -> None:
    session = AsyncMock()
    job = _export()
    session.scalar.return_value = job

    async def fail(_session, export):
        export.status = ExportStatus.failed
        raise RuntimeError("sensitive database details")

    with patch("app.workers.export_queue_worker.run_export", side_effect=fail):
        assert await process_next(session) is job

    assert job.status == ExportStatus.failed


@pytest.mark.asyncio
async def test_process_next_terminalizes_failure_before_lifecycle_start() -> None:
    session = AsyncMock()
    job = _export()
    session.scalar.return_value = job

    async def start(_session, export):
        export.status = ExportStatus.running

    async def fail(_session, export, *, error_message):
        export.status = ExportStatus.failed
        export.error_message = error_message

    with (
        patch(
            "app.workers.export_queue_worker.run_export",
            new=AsyncMock(side_effect=RuntimeError("sensitive database details")),
        ),
        patch(
            "app.workers.export_queue_worker.export_service.start_export",
            new=AsyncMock(side_effect=start),
        ) as start_export,
        patch(
            "app.workers.export_queue_worker.export_service.fail_export",
            new=AsyncMock(side_effect=fail),
        ) as fail_export,
    ):
        assert await process_next(session) is job

    start_export.assert_awaited_once_with(session, job)
    fail_export.assert_awaited_once()
    assert job.status == ExportStatus.failed
    assert job.error_message == "RuntimeError: request failed"
    assert "sensitive database details" not in job.error_message


@pytest.mark.asyncio
async def test_consume_once_commits_each_job_and_stops_on_empty_queue() -> None:
    sessions = [AsyncMock(), AsyncMock()]
    contexts = []
    for session in sessions:
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=False)
        contexts.append(context)
    session_factory = MagicMock(side_effect=contexts)
    job = _export(status=ExportStatus.completed)

    with patch(
        "app.workers.export_queue_worker.process_next",
        new=AsyncMock(side_effect=[job, None]),
    ):
        processed = await consume_once(max_jobs=5, session_factory=session_factory)

    assert processed == 1
    sessions[0].commit.assert_awaited_once()
    sessions[0].rollback.assert_not_awaited()
    sessions[1].rollback.assert_awaited_once()
    sessions[1].commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_consume_once_rejects_invalid_batch_size() -> None:
    with pytest.raises(ValueError, match="max_jobs must be at least 1"):
        await consume_once(max_jobs=0)
