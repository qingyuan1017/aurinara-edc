"""Focused security and contract tests for CTMS task 5.3 exports."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.ctms import Module
from app.core.exceptions import ValidationError
from app.models.export import Export, ExportStatus
from app.schemas.ctms.export import OperationalExportCreate, OperationalExportFilters
from app.services.export_service import ExportService
from app.workers.ctms_export_worker import _row_for, run_ctms_export, serialize_operational_csv


def test_operational_filters_are_strict_and_bounded() -> None:
    request = OperationalExportCreate(
        export_type="json",
        filters={"page": 2, "page_size": 1000, "record_types": ["operational_task"]},
    )
    assert request.filters.page == 2
    assert request.filters.page_size == 1000

    with pytest.raises(PydanticValidationError):
        OperationalExportFilters.model_validate({"page_size": 1001})
    with pytest.raises(PydanticValidationError):
        OperationalExportFilters.model_validate({"clinical_data": True})
    with pytest.raises(PydanticValidationError):
        OperationalExportFilters.model_validate({"projection_types": ["query_summary"]})


def test_operational_row_allowlist_excludes_clinical_and_sensitive_fields() -> None:
    record = MagicMock()
    record.id = uuid4()
    record.study_id = uuid4()
    record.site_id = uuid4()
    record.status = "Open"
    record.title = "Follow up"
    record.description = "Operational description"
    record.query_id = uuid4()
    record.query_summary = "Clinical query text"
    record.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    record.updated_at = record.created_at
    record.correlation_id = uuid4()

    row = _row_for("operational_task", record)
    assert row["title"] == "Follow up"
    assert "description" not in row
    assert "query_id" not in row
    assert "query_summary" not in row
    assert b"Clinical query text" not in serialize_operational_csv([row])


@pytest.mark.asyncio
async def test_create_ctms_export_sets_shared_ctms_content_owner() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    service = ExportService()
    with patch("app.services.export_service.audit_service.record", new_callable=AsyncMock):
        export = await service.create_ctms_export(
            session,
            study_id=uuid4(),
            export_type="csv",
            filters={"page_size": 25},
            actor_id=uuid4(),
        )

    assert export.module == Module.CTMS.value
    assert export.content_owner == Module.CTMS.value
    assert export.export_type == "csv"
    assert export.filters["page_size"] == 25


@pytest.mark.asyncio
async def test_ctms_worker_uses_object_storage_and_shared_lifecycle() -> None:
    export = Export(
        id=uuid4(),
        study_id=uuid4(),
        export_type="json",
        status=ExportStatus.queued,
        module="CTMS",
        content_owner="CTMS",
        filters={"record_types": ["operational_task"]},
        requested_by=uuid4(),
    )
    session = AsyncMock()
    storage = AsyncMock()
    with (
        patch(
            "app.workers.ctms_export_worker.fetch_operational_rows",
            new_callable=AsyncMock,
            return_value=[{"record_type": "operational_task", "status": "Open"}],
        ),
        patch("app.workers.ctms_export_worker.get_object_storage", return_value=storage),
        patch(
            "app.workers.ctms_export_worker.export_service.start_export",
            new_callable=AsyncMock,
        ),
        patch(
            "app.workers.ctms_export_worker.export_service.complete_export",
            new_callable=AsyncMock,
        ) as complete,
        patch("app.workers.ctms_export_worker.audit_service.record", new_callable=AsyncMock),
    ):
        await run_ctms_export(session, export)

    storage.put.assert_awaited_once()
    key, content, content_type = storage.put.await_args.args
    assert key.startswith("local/exports/ctms/")
    assert content_type == "application/json"
    assert b"operational_task" in content
    assert complete.await_args.kwargs["file_path"] == key


def test_edc_content_owner_cannot_be_processed_by_ctms_worker() -> None:
    export = Export(
        id=uuid4(),
        study_id=uuid4(),
        export_type="json",
        status=ExportStatus.queued,
        module="EDC",
        content_owner="EDC",
        requested_by=uuid4(),
    )
    with pytest.raises(ValueError, match="CTMS-owned"):
        import asyncio

        asyncio.run(run_ctms_export(AsyncMock(), export))


def test_mismatched_module_and_content_owner_is_rejected() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    with pytest.raises(ValidationError):
        import asyncio

        asyncio.run(
            ExportService().create_export(
                session,
                study_id=uuid4(),
                export_type="csv",
                actor_id=uuid4(),
                module=Module.CTMS,
                content_owner=Module.EDC,
            )
        )


@pytest.mark.asyncio
async def test_projection_export_uses_typed_allowlist() -> None:
    from app.workers.ctms_export_worker import fetch_operational_rows

    export = Export(
        id=uuid4(),
        study_id=uuid4(),
        export_type="json",
        status=ExportStatus.queued,
        module="CTMS",
        content_owner="CTMS",
        filters={"include_projections": True, "projection_types": ["query_summary"]},
        requested_by=uuid4(),
    )
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {
            "id": uuid4(),
            "projection_type": "query_summary",
            "source_module": "EDC",
            "source_record_id": uuid4(),
            "study_id": export.study_id,
            "site_id": None,
            "subject_id": uuid4(),
            "source_version": "3",
            "rule_version": 1,
            "payload_json": {
                "query_id": str(uuid4()),
                "summary": "Approved summary",
                "field_values": {"secret": "must not export"},
                "credentials": "must not export",
            },
            "source_timestamp": datetime(2026, 1, 1, tzinfo=UTC),
            "projected_at": datetime(2026, 1, 1, tzinfo=UTC),
            "correlation_id": "corr-1",
        }
    ]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    rows = await fetch_operational_rows(session, export)

    assert len(rows) == 1
    assert rows[0]["summary"] == "Approved summary"
    assert "field_values" not in rows[0]
    assert "credentials" not in rows[0]
