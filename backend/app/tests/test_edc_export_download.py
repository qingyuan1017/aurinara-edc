"""Focused tests for authenticated EDC export file downloads."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.responses import FileResponse

from app.api.routes.edc.exports import download_export
from app.core.exceptions import NotFoundError
from app.models.shared.export import ExportStatus


@pytest.mark.asyncio
async def test_download_export_streams_file_and_records_audit(tmp_path) -> None:
    export_file = tmp_path / "export_test.csv"
    export_file.write_text("subject_number\n001\n", encoding="utf-8")
    export = MagicMock(
        id=uuid4(),
        study_id=uuid4(),
        status=ExportStatus.completed,
        file_path=str(export_file),
        export_type="csv",
        filters={},
    )
    current_user = MagicMock(id=uuid4())
    session = AsyncMock()
    permission_service = MagicMock()

    with (
        patch(
            "app.api.routes.edc.exports.export_service.get_export",
            new_callable=AsyncMock,
            return_value=export,
        ),
        patch(
            "app.api.routes.edc.exports.export_service.record_download",
            new_callable=AsyncMock,
        ) as record_download,
        patch("app.api.routes.edc.exports.edc_scope_service.require_scope") as require_scope,
    ):
        response = await download_export(export.id, session, current_user, permission_service)

    assert isinstance(response, FileResponse)
    assert response.path == export_file
    assert response.media_type == "text/csv"
    assert 'filename="export_test.csv"' in response.headers["content-disposition"]
    require_scope.assert_called_once_with(
        current_user,
        permission_service,
        "data.export",
        study_id=export.study_id,
        site_id=None,
    )
    record_download.assert_awaited_once_with(
        session,
        export,
        actor_id=current_user.id,
    )


@pytest.mark.asyncio
async def test_download_export_rejects_missing_file_without_audit(tmp_path) -> None:
    export = MagicMock(
        id=uuid4(),
        study_id=uuid4(),
        status=ExportStatus.completed,
        file_path=str(tmp_path / "missing.csv"),
        export_type="csv",
        filters={},
    )

    with (
        patch(
            "app.api.routes.edc.exports.export_service.get_export",
            new_callable=AsyncMock,
            return_value=export,
        ),
        patch(
            "app.api.routes.edc.exports.export_service.record_download",
            new_callable=AsyncMock,
        ) as record_download,
        patch("app.api.routes.edc.exports.edc_scope_service.require_scope"),
        pytest.raises(NotFoundError, match="Export file content was not found"),
    ):
        await download_export(export.id, AsyncMock(), MagicMock(), MagicMock())

    record_download.assert_not_awaited()
