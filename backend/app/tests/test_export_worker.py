"""Unit tests for the CSV export worker.

Tests the core logic of run_csv_export and run_subject_list_export, verifying
that filters are applied, CSV is generated correctly, and export lifecycle
transitions work as expected.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.export import Export, ExportStatus, ExportType
from app.models.form_data import FieldValue, FormInstance
from app.models.form_metadata import FieldDefinition
from app.models.site import Site
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitInstance
from app.workers.export_worker import (
    run_csv_export,
    run_export,
    run_subject_list_export,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_export(
    export_type: str = ExportType.csv,
    filters: dict | None = None,
    status: str = ExportStatus.queued,
) -> Export:
    """Create a mock Export instance for testing."""
    export = Export(
        id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        export_type=export_type,
        status=status,
        filters=filters,
        requested_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )
    return export


def _make_field_value(
    subject_number: str = "SUBJ-001",
    site_number: str = "SITE-01",
    visit_name: str = "Visit 1",
    form_name: str = "Demographics",
    variable_name: str = "AGE",
    value: str = "45",
) -> FieldValue:
    """Create a FieldValue with populated relationships for CSV generation."""
    site = MagicMock(spec=Site)
    site.site_number = site_number

    subject = MagicMock(spec=Subject)
    subject.subject_number = subject_number
    subject.site = site

    visit_instance = MagicMock(spec=VisitInstance)
    visit_instance.name = visit_name

    form_def = MagicMock()
    form_def.name = form_name

    form_instance = MagicMock(spec=FormInstance)
    form_instance.subject = subject
    form_instance.visit_instance = visit_instance
    form_instance.form_definition = form_def

    field_def = MagicMock(spec=FieldDefinition)
    field_def.variable_name = variable_name

    fv = MagicMock(spec=FieldValue)
    fv.form_instance = form_instance
    fv.field_definition = field_def
    fv.value = value

    return fv


def _make_subject(
    subject_number: str = "SUBJ-001",
    site_number: str = "SITE-01",
    status: str = SubjectStatus.enrolled,
) -> Subject:
    """Create a Subject mock for subject list export testing."""
    site = MagicMock(spec=Site)
    site.site_number = site_number

    subject = MagicMock(spec=Subject)
    subject.subject_number = subject_number
    subject.site = site
    subject.status = status
    subject.created_at = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

    return subject


def _mock_session_with_results(results):
    """Create a mock session that returns specified results from execute."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = results
    mock_result.scalars.return_value = mock_scalars
    session.execute = AsyncMock(return_value=mock_result)
    session.flush = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunCsvExport:
    """Tests for run_csv_export."""

    @pytest.mark.asyncio
    async def test_generates_csv_with_correct_columns(self, tmp_path):
        """CSV export produces file with expected header and data rows."""
        export = _make_export(filters=None)
        field_values = [
            _make_field_value(
                subject_number="SUBJ-001",
                site_number="SITE-01",
                visit_name="Visit 1",
                form_name="Demographics",
                variable_name="AGE",
                value="45",
            ),
            _make_field_value(
                subject_number="SUBJ-002",
                site_number="SITE-02",
                visit_name="Visit 2",
                form_name="Vitals",
                variable_name="WEIGHT",
                value="72.5",
            ),
        ]

        session = _mock_session_with_results(field_values)

        with (
            patch(
                "app.workers.export_worker.export_service.start_export",
                new_callable=AsyncMock,
            ) as mock_start,
            patch(
                "app.workers.export_worker.export_service.complete_export",
                new_callable=AsyncMock,
            ) as mock_complete,
            patch(
                "app.workers.export_worker.audit_service.record",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workers.export_worker._get_export_dir",
                return_value=tmp_path,
            ),
        ):
            await run_csv_export(session, export)

            # Verify start_export was called
            mock_start.assert_awaited_once_with(session, export)

            # Verify complete_export was called with file info
            mock_complete.assert_awaited_once()
            call_kwargs = mock_complete.call_args[1]
            assert "file_path" in call_kwargs
            assert call_kwargs["file_size"] > 0

            # Verify CSV content
            file_path = Path(call_kwargs["file_path"])
            assert file_path.exists()

            content = file_path.read_text()
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)

            # Header + 2 data rows
            assert len(rows) == 3
            assert rows[0] == [
                "subject_number",
                "site_number",
                "visit_name",
                "form_name",
                "field_variable_name",
                "value",
            ]
            assert rows[1] == ["SUBJ-001", "SITE-01", "Visit 1", "Demographics", "AGE", "45"]
            assert rows[2] == ["SUBJ-002", "SITE-02", "Visit 2", "Vitals", "WEIGHT", "72.5"]

    @pytest.mark.asyncio
    async def test_handles_empty_result_set(self, tmp_path):
        """CSV export produces header-only file when no data matches filters."""
        export = _make_export(filters={"site_id": str(uuid.uuid4())})
        session = _mock_session_with_results([])

        with (
            patch(
                "app.workers.export_worker.export_service.start_export",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workers.export_worker.export_service.complete_export",
                new_callable=AsyncMock,
            ) as mock_complete,
            patch(
                "app.workers.export_worker.audit_service.record",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workers.export_worker._get_export_dir",
                return_value=tmp_path,
            ),
        ):
            await run_csv_export(session, export)

            call_kwargs = mock_complete.call_args[1]
            file_path = Path(call_kwargs["file_path"])
            content = file_path.read_text()
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)

            # Only header row
            assert len(rows) == 1
            assert rows[0][0] == "subject_number"

    @pytest.mark.asyncio
    async def test_marks_export_failed_on_error(self, tmp_path):
        """Export is marked as failed if an exception occurs during processing."""
        export = _make_export(filters=None)

        session = AsyncMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        with (
            patch(
                "app.workers.export_worker.export_service.start_export",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workers.export_worker.export_service.fail_export",
                new_callable=AsyncMock,
            ) as mock_fail,
            patch(
                "app.workers.export_worker._get_export_dir",
                return_value=tmp_path,
            ),
        ):
            with pytest.raises(RuntimeError, match="DB connection lost"):
                await run_csv_export(session, export)

            mock_fail.assert_awaited_once()
            call_kwargs = mock_fail.call_args[1]
            assert "DB connection lost" in call_kwargs["error_message"]


class TestRunSubjectListExport:
    """Tests for run_subject_list_export."""

    @pytest.mark.asyncio
    async def test_generates_subject_list_csv(self, tmp_path):
        """Subject list export produces file with correct columns and data."""
        export = _make_export(export_type=ExportType.subject_list)
        subjects = [
            _make_subject("SUBJ-001", "SITE-01", SubjectStatus.enrolled),
            _make_subject("SUBJ-002", "SITE-02", SubjectStatus.screening),
        ]

        session = _mock_session_with_results(subjects)

        with (
            patch(
                "app.workers.export_worker.export_service.start_export",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workers.export_worker.export_service.complete_export",
                new_callable=AsyncMock,
            ) as mock_complete,
            patch(
                "app.workers.export_worker.audit_service.record",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workers.export_worker._get_export_dir",
                return_value=tmp_path,
            ),
        ):
            await run_subject_list_export(session, export)

            call_kwargs = mock_complete.call_args[1]
            file_path = Path(call_kwargs["file_path"])
            content = file_path.read_text()
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)

            # Header + 2 data rows
            assert len(rows) == 3
            assert rows[0] == ["subject_number", "site_number", "status", "created_at"]
            assert rows[1][0] == "SUBJ-001"
            assert rows[1][1] == "SITE-01"
            assert rows[2][0] == "SUBJ-002"


class TestRunExport:
    """Tests for the run_export dispatcher."""

    @pytest.mark.asyncio
    async def test_dispatches_csv_export(self, tmp_path):
        """run_export dispatches to run_csv_export for csv type."""
        export = _make_export(export_type=ExportType.csv)

        with patch(
            "app.workers.export_worker.run_csv_export",
            new_callable=AsyncMock,
        ) as mock_csv:
            await run_export(AsyncMock(), export)
            mock_csv.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatches_subject_list_export(self, tmp_path):
        """run_export dispatches to run_subject_list_export for subject_list type."""
        export = _make_export(export_type=ExportType.subject_list)

        with patch(
            "app.workers.export_worker.run_subject_list_export",
            new_callable=AsyncMock,
        ) as mock_subject:
            await run_export(AsyncMock(), export)
            mock_subject.assert_awaited_once()
