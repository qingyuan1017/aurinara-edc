"""Worker for PV-owned safety export generation (Requirement 12).

This worker uses the shared export lifecycle and object-storage primitives but
never queries EDC clinical tables or CTMS operational tables. Its row projection
is an explicit scalar allowlist of PV-owned safety content, so a PV safety
export can only ever contain PV-owned safety fields plus read-only canonical
references (Requirement 12.6).

The worker runs a Queued PV safety export through the shared lifecycle:
Running -> Completed on success (storing the generated file), or Running ->
Failed on error with a failure reason and no downloadable file. Only the PV
safety formats CSV, Excel, JSON, and E2B XML are produced (Requirement 12.5),
and the produced set is the in-scope Safety_Cases (empty when none qualify,
Requirement 12.2).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.observability import sanitize_error
from app.core.pv import ActorContext, Module
from app.core.storage import get_object_storage
from app.models.export import Export, ExportStatus
from app.repositories.pv.export_repository import PVExportRepository
from app.schemas.pv.export import PVExportFilters, PVExportFormat
from app.services.pv_atomicity_service import pv_atomicity_service
from app.services.pv_export_service import pv_export_service

logger = logging.getLogger(__name__)
WORKER_NAME = "pv-export"

# The explicit, scalar PV-owned safety fields a case-list export may contain.
# This allowlist deliberately excludes any EDC clinical payload and any CTMS
# operational field. ``subject_reference`` is the read-only EDC Subject_Reference
# identity, not clinical content.
_CASE_FIELDS = (
    "case_id",
    "case_identifier",
    "study_id",
    "site_id",
    "subject_reference",
    "case_type",
    "lifecycle_state",
    "created_at",
)
_ADVERSE_EVENT_FIELDS = (
    "adverse_event_id",
    "verbatim_term",
    "onset_date",
    "outcome",
    "resolution_date",
)
_EXPORT_FIELDS = _CASE_FIELDS + _ADVERSE_EVENT_FIELDS


def _as_scalar(value: Any) -> Any:
    """Render a value as a deterministic scalar for a PV safety export cell."""
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):  # date
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


async def fetch_safety_rows(session: AsyncSession, export: Export) -> list[dict[str, Any]]:
    """Fetch only in-scope, non-deleted PV Safety_Case rows for the export.

    Filters combine as an intersection (Requirement 12.3) and the result is the
    set of in-scope Safety_Cases, one row per adverse event (or one row for a
    case with no adverse event). The set is empty when no case qualifies
    (Requirement 12.2).
    """

    filters = PVExportFilters.model_validate(export.filters or {})
    repository = PVExportRepository(session)
    cases = await repository.select_cases(
        study_id=export.study_id,
        site_id=filters.site_id,
        subject_reference=filters.subject_reference,
        case_statuses=[state.value for state in filters.case_statuses],
        seriousness=filters.seriousness,
        report_statuses=[status.value for status in filters.report_statuses],
        date_from=filters.date_from,
        date_to=filters.date_to,
    )

    rows: list[dict[str, Any]] = []
    for case in cases:
        base = {
            "case_id": _as_scalar(case.id),
            "case_identifier": case.case_identifier,
            "study_id": _as_scalar(case.study_id),
            "site_id": _as_scalar(case.site_id),
            "subject_reference": _as_scalar(case.subject_reference),
            "case_type": case.case_type,
            "lifecycle_state": case.lifecycle_state,
            "created_at": _as_scalar(case.created_at),
        }
        events = await repository.list_adverse_events(case.id)
        if not events:
            rows.append(dict(base))
            continue
        for event in events:
            row = dict(base)
            row.update(
                {
                    "adverse_event_id": _as_scalar(event.id),
                    "verbatim_term": event.verbatim_term,
                    "onset_date": _as_scalar(event.onset_date),
                    "outcome": event.outcome,
                    "resolution_date": _as_scalar(event.resolution_date),
                }
            )
            rows.append(row)
    return rows


# --- Serializers (PV-owned safety content only) -----------------------------


def serialize_safety_csv(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output, fieldnames=list(_EXPORT_FIELDS), extrasaction="ignore", lineterminator="\r\n"
    )
    writer.writeheader()
    writer.writerows(
        {field: ("" if row.get(field) is None else row.get(field)) for field in _EXPORT_FIELDS}
        for row in rows
    )
    return output.getvalue().encode("utf-8")


def serialize_safety_json(rows: list[dict[str, Any]]) -> bytes:
    normalized = [{field: row.get(field) for field in _EXPORT_FIELDS} for row in rows]
    return (json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _serialize_safety_excel(rows: list[dict[str, Any]]) -> bytes:
    """Serialize to SpreadsheetML, avoiding an Excel library dependency."""

    def xml_escape(value: Any) -> str:
        text = "" if value is None else str(value)
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    columns = list(_EXPORT_FIELDS)
    sheet_rows = [
        "<Row>"
        + "".join(
            f'<Cell><Data ss:Type="String">{xml_escape(column)}</Data></Cell>' for column in columns
        )
        + "</Row>"
    ]
    sheet_rows.extend(
        "<Row>"
        + "".join(
            f'<Cell><Data ss:Type="String">{xml_escape(row.get(column))}</Data></Cell>'
            for column in columns
        )
        + "</Row>"
        for row in rows
    )
    return (
        '<?xml version="1.0"?>'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Safety Cases"><Table>'
        + "".join(sheet_rows)
        + "</Table></Worksheet></Workbook>"
    ).encode("utf-8")


def serialize_safety_e2b_xml(rows: list[dict[str, Any]]) -> bytes:
    """Serialize the in-scope Safety_Cases into an E2B(R3)-structured batch.

    The document is an ``ichicsr`` batch with one ``safetyreport`` per in-scope
    Safety_Case. It carries only PV-owned safety content: the case identifier,
    the PV lifecycle status, and the case's adverse-event verbatim terms and
    dates. It never emits EDC clinical or CTMS operational fields
    (Requirement 12.6).
    """

    root = ET.Element("ichicsr")
    # One report per distinct case, preserving deterministic row order.
    seen: dict[str, ET.Element] = {}
    for row in rows:
        case_identifier = str(row.get("case_identifier"))
        report = seen.get(case_identifier)
        if report is None:
            report = ET.SubElement(root, "safetyreport")
            ET.SubElement(report, "safetyreportid").text = case_identifier
            ET.SubElement(report, "lifecyclestate").text = str(row.get("lifecycle_state") or "")
            seen[case_identifier] = report
        if row.get("adverse_event_id") is not None:
            reaction = ET.SubElement(report, "reaction")
            ET.SubElement(reaction, "verbatim").text = str(row.get("verbatim_term") or "")
            ET.SubElement(reaction, "onsetdate").text = str(row.get("onset_date") or "")
            ET.SubElement(reaction, "outcome").text = str(row.get("outcome") or "")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


_SERIALIZERS: dict[str, tuple[str, str, Any]] = {
    PVExportFormat.CSV.value: ("csv", "text/csv", serialize_safety_csv),
    PVExportFormat.JSON.value: ("json", "application/json", serialize_safety_json),
    PVExportFormat.EXCEL.value: ("xml", "application/vnd.ms-excel", _serialize_safety_excel),
    PVExportFormat.E2B_XML.value: ("xml", "application/xml", serialize_safety_e2b_xml),
}


async def run_pv_export(session: AsyncSession, export: Export) -> None:
    """Execute a PV safety export through the shared lifecycle and object store.

    On success the generated file is stored and the job is Completed. On error
    the job is failed with a sanitized reason and no downloadable file is left
    behind (Requirement 12.1). Only PV-owned safety export jobs are accepted.
    """

    if export.module != Module.PV.value or export.content_owner != Module.PV.value:
        raise ValueError("PV export worker accepts only PV-owned safety export jobs")

    try:
        extension, content_type, serializer = _SERIALIZERS[export.export_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported PV safety export format: {export.export_type}") from exc

    actor = ActorContext(
        user_id=export.requested_by,
        request_id=export.correlation_id or str(export.id),
        correlation_id=export.correlation_id or str(export.id),
    )

    try:
        await pv_export_service.start_export(session, export)
        rows = await fetch_safety_rows(session, export)
        content = serializer(rows)
        settings = get_settings()
        key = (
            f"{settings.object_storage_namespace}/exports/pv/"
            f"{export.study_id}/{export.id}.{extension}"
        )
        await get_object_storage().put(key, content, content_type)
        await pv_export_service.complete_export(
            session, export, file_path=key, file_size=len(content)
        )
        await pv_atomicity_service.record_mutation(
            session,
            entity_type="safety_export",
            entity_id=export.id,
            action="complete",
            actor=actor,
            study_id=export.study_id,
            changed_fields=("status", "file_path", "file_size"),
            field_name="status",
            old_value=ExportStatus.running.value,
            new_value=f"status={ExportStatus.completed}, rows={len(rows)}",
        )
    except Exception as error:
        safe = sanitize_error(error)
        logger.exception(
            "PV safety export failed: export_id=%s category=%s", export.id, safe["category"]
        )
        if export.status == ExportStatus.running:
            await pv_export_service.fail_export(session, export, error_message=safe["message"])
            await pv_atomicity_service.record_mutation(
                session,
                entity_type="safety_export",
                entity_id=export.id,
                action="fail",
                actor=actor,
                study_id=export.study_id,
                changed_fields=("status", "error_message"),
                field_name="status",
                old_value=ExportStatus.running.value,
                new_value=f"status={ExportStatus.failed}",
            )
        raise


async def run_export(session: AsyncSession, export: Export) -> None:
    """Dispatch a shared job only when its content owner is PV."""
    await run_pv_export(session, export)


__all__ = [
    "WORKER_NAME",
    "fetch_safety_rows",
    "run_export",
    "run_pv_export",
    "serialize_safety_csv",
    "serialize_safety_e2b_xml",
    "serialize_safety_json",
]
