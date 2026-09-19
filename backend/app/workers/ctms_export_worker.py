"""Worker for CTMS-owned operational exports.

This worker uses the shared export lifecycle and object-storage primitives but
never queries EDC clinical tables.  The row projection is an explicit scalar
allowlist; adding a CTMS model field does not automatically expose it.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.config import get_settings
from app.core.ctms import Module
from app.core.observability import sanitize_error
from app.core.storage import get_object_storage
from app.models.ctms import (
    ActivationAction,
    EnrollmentPlan,
    EnrollmentTarget,
    MonitoringActivity,
    MonitoringPlan,
    MonitoringPlanVersion,
    OperationalContact,
    OperationalMilestone,
    OperationalSite,
    OperationalStudy,
    OperationalTask,
    ReadinessCriterion,
    StudyOperationalMilestone,
    StudyPlan,
)
from app.models.export import Export, ExportStatus
from app.schemas.ctms.export import OperationalExportFilters, OperationalExportFormat
from app.services.export_service import export_service
from app.services.status_ownership_rule_service import DEFAULT_TYPED_ALLOWLISTS

logger = logging.getLogger(__name__)
WORKER_NAME = "ctms-export"

# Only these CTMS-owned record types can be selected by an operational export.
_RECORD_MODELS: dict[str, type] = {
    "operational_study": OperationalStudy,
    "study_plan": StudyPlan,
    "enrollment_plan": EnrollmentPlan,
    "readiness_criterion": ReadinessCriterion,
    "study_milestone": StudyOperationalMilestone,
    "operational_site": OperationalSite,
    "activation_action": ActivationAction,
    "enrollment_target": EnrollmentTarget,
    "operational_milestone": OperationalMilestone,
    "monitoring_plan": MonitoringPlan,
    "monitoring_plan_version": MonitoringPlanVersion,
    "monitoring_activity": MonitoringActivity,
    "operational_task": OperationalTask,
    "operational_contact": OperationalContact,
}

# This is intentionally scalar and explicit.  In particular it excludes
# clinical values, source documents, query messages, credentials, free-form
# clinical audit history, and arbitrary JSON columns.
_COMMON_FIELDS = (
    "id",
    "study_id",
    "site_id",
    "status",
    "created_at",
    "updated_at",
    "correlation_id",
)
_RECORD_FIELDS: dict[str, tuple[str, ...]] = {
    "operational_study": ("operational_owner_id", "sponsor", "phase", "therapeutic_area", "indication"),
    "study_plan": ("title", "objective", "owner_id"),
    "enrollment_plan": ("title", "target_quantity", "planning_period_start", "planning_period_end", "owner_id"),
    "readiness_criterion": ("name", "required", "due_at", "completed_at", "completed_by", "evidence_reference"),
    "study_milestone": ("title", "milestone_type", "planned_at", "completed_at", "owner_id"),
    "operational_site": ("monitoring_readiness", "responsible_role", "planned_activation_date"),
    "activation_action": ("action_type", "responsible_role", "planned_date", "completed_by", "completed_at", "evidence_reference"),
    "enrollment_target": ("target_type", "target_quantity", "planning_period_start", "planning_period_end", "owner_id"),
    "operational_milestone": ("subject_id", "approved_pseudonym", "approved_reference", "milestone_type", "milestone_date"),
    "monitoring_plan": ("name", "description"),
    "monitoring_plan_version": ("plan_id", "version_number", "objectives", "cadence", "completion_criteria", "published_at"),
    "monitoring_activity": ("plan_version_id", "activity_type", "planned_date", "assigned_cra_id", "edc_visit_instance_id", "completed_at", "cancelled_at"),
    "operational_task": ("title", "owner_id", "due_date", "priority"),
    "operational_contact": ("name", "role", "organization", "owner_id", "effective_from", "effective_to"),
}


def _as_scalar(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value.tzinfo else None
    if hasattr(value, "value"):
        return value.value
    return str(value) if value is not None and not isinstance(value, (str, int, float, bool)) else value


def _row_for(record_type: str, record: Any) -> dict[str, Any]:
    """Build one row from the CTMS export allowlist only."""
    row: dict[str, Any] = {"record_type": record_type}
    for field in _COMMON_FIELDS + _RECORD_FIELDS[record_type]:
        if hasattr(record, field):
            row[field] = _as_scalar(getattr(record, field))
    return row


def _date_values(row: dict[str, Any]) -> Iterable[datetime]:
    for key in ("created_at", "updated_at", "planned_at", "planned_date", "milestone_date", "due_date"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo:
                yield parsed


async def _fetch_approved_projection_rows(
    session: AsyncSession,
    export: Export,
    filters: OperationalExportFilters,
) -> list[dict[str, Any]]:
    """Read projection payloads through the shared typed allowlist only."""
    statement = text(
        "SELECT id, projection_type, source_module, source_record_id, study_id, "
        "site_id, subject_id, source_version, rule_version, payload_json, "
        "source_timestamp, projected_at, correlation_id "
        "FROM ctms_operational_projections WHERE study_id = :study_id "
        "AND status = 'Current' AND deleted_at IS NULL"
    )
    if filters.site_id is not None:
        statement = text(str(statement) + " AND site_id = :site_id")
    parameters: dict[str, Any] = {"study_id": export.study_id}
    if filters.site_id is not None:
        parameters["site_id"] = filters.site_id
    result = await session.execute(statement, parameters)
    rows: list[dict[str, Any]] = []
    for projection in result.mappings().all():
        projection_type = str(projection["projection_type"])
        allowed = next(
            (fields for key, fields in DEFAULT_TYPED_ALLOWLISTS.items() if key.value == projection_type),
            {},
        )
        if filters.projection_types and projection_type not in filters.projection_types:
            continue
        payload = projection["payload_json"] if isinstance(projection["payload_json"], dict) else {}
        row: dict[str, Any] = {
            "record_type": f"projection_{projection_type}",
            "id": _as_scalar(projection["id"]),
            "study_id": _as_scalar(projection["study_id"]),
            "site_id": _as_scalar(projection["site_id"]),
            "source_module": _as_scalar(projection["source_module"]),
            "source_record_id": _as_scalar(projection["source_record_id"]),
            "source_version": _as_scalar(projection["source_version"]),
            "rule_version": _as_scalar(projection["rule_version"]),
            "source_timestamp": _as_scalar(projection["source_timestamp"]),
            "projected_at": _as_scalar(projection["projected_at"]),
            "correlation_id": _as_scalar(projection["correlation_id"]),
        }
        for field in allowed:
            if field in payload:
                row[field] = _as_scalar(payload[field])
        rows.append(row)
    return rows


async def fetch_operational_rows(
    session: AsyncSession,
    export: Export,
) -> list[dict[str, Any]]:
    """Fetch only in-scope, non-deleted CTMS operational rows."""
    filters = OperationalExportFilters.model_validate(export.filters or {})
    record_types = filters.record_types or list(_RECORD_MODELS)
    rows: list[dict[str, Any]] = []

    for record_type in record_types:
        model = _RECORD_MODELS[record_type]
        statement = select(model).where(model.study_id == export.study_id)
        if hasattr(model, "site_id") and filters.site_id is not None:
            statement = statement.where(model.site_id == filters.site_id)
        if not filters.include_archived:
            if hasattr(model, "deleted_at"):
                statement = statement.where(model.deleted_at.is_(None))
            if hasattr(model, "archived_at"):
                statement = statement.where(model.archived_at.is_(None))
        result = await session.execute(statement)
        for record in result.scalars().all():
            row = _row_for(record_type, record)
            if filters.statuses and row.get("status") not in filters.statuses:
                continue
            dates = list(_date_values(row))
            if filters.date_from and dates and max(dates) < filters.date_from:
                continue
            if filters.date_to and dates and min(dates) > filters.date_to:
                continue
            rows.append(row)

    if filters.include_projections:
        rows.extend(await _fetch_approved_projection_rows(session, export, filters))

    rows.sort(key=lambda row: (str(row.get("created_at") or row.get("projected_at") or ""), str(row.get("id") or "")))
    start = (filters.page - 1) * filters.page_size
    return rows[start : start + filters.page_size]


def serialize_operational_csv(rows: list[dict[str, Any]]) -> bytes:
    columns = sorted({key for row in rows for key in row})
    if not columns:
        columns = ["record_type", "id", "study_id", "status"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows({column: row.get(column, "") for column in columns} for row in rows)
    return output.getvalue().encode("utf-8")


def serialize_operational_json(rows: list[dict[str, Any]]) -> bytes:
    return (json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _serialize_operational_excel(rows: list[dict[str, Any]]) -> bytes:
    # SpreadsheetML is sufficient for the shared infrastructure and avoids a
    # dependency on an Excel library in workers and test environments.
    columns = sorted({key for row in rows for key in row}) or ["record_type", "id"]
    def xml_escape(value: Any) -> str:
        return ("" if value is None else str(value)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    sheet_rows = ["<Row>" + "".join(f"<Cell><Data ss:Type=\"String\">{xml_escape(column)}</Data></Cell>" for column in columns) + "</Row>"]
    sheet_rows.extend(
        "<Row>" + "".join(f"<Cell><Data ss:Type=\"String\">{xml_escape(row.get(column, ''))}</Data></Cell>" for column in columns) + "</Row>"
        for row in rows
    )
    return ("<?xml version=\"1.0\"?><Workbook xmlns=\"urn:schemas-microsoft-com:office:spreadsheet\" xmlns:ss=\"urn:schemas-microsoft-com:office:spreadsheet\"><Worksheet ss:Name=\"Operational Data\"><Table>" + "".join(sheet_rows) + "</Table></Worksheet></Workbook>").encode("utf-8")


_SERIALIZERS = {
    OperationalExportFormat.CSV.value: ("csv", "text/csv", serialize_operational_csv),
    OperationalExportFormat.JSON.value: ("json", "application/json", serialize_operational_json),
    OperationalExportFormat.EXCEL.value: ("xml", "application/vnd.ms-excel", _serialize_operational_excel),
}


async def run_ctms_export(session: AsyncSession, export: Export) -> None:
    """Execute a CTMS job through the shared lifecycle and object store."""
    if export.module != Module.CTMS.value or export.content_owner != Module.CTMS.value:
        raise ValueError("CTMS worker accepts only CTMS-owned export jobs")
    try:
        extension, content_type, serializer = _SERIALIZERS[export.export_type]
        await export_service.start_export(session, export)
        rows = await fetch_operational_rows(session, export)
        content = serializer(rows)
        settings = get_settings()
        key = f"{settings.object_storage_namespace}/exports/ctms/{export.study_id}/{export.id}.{extension}"
        await get_object_storage().put(key, content, content_type)
        await export_service.complete_export(session, export, file_path=key, file_size=len(content))
        await audit_service.record(
            session,
            entity_type="export",
            entity_id=export.id,
            action="export_completed",
            module=Module.CTMS,
            actor_id=export.requested_by,
            correlation_id=export.correlation_id,
            scope={"study_id": export.study_id},
            study_id=export.study_id,
            changed_fields=["status", "storage_key"],
            new_value=f"storage_key={key}, file_size={len(content)}, rows={len(rows)}",
        )
    except Exception as error:
        safe = sanitize_error(error)
        logger.exception("CTMS export failed: export_id=%s category=%s", export.id, safe["category"])
        if export.status == ExportStatus.running:
            await export_service.fail_export(session, export, error_message=safe["message"])
        raise


async def run_export(session: AsyncSession, export: Export) -> None:
    """Dispatch a shared job only when its content owner is CTMS."""
    await run_ctms_export(session, export)


__all__ = [
    "WORKER_NAME",
    "fetch_operational_rows",
    "run_ctms_export",
    "run_export",
    "serialize_operational_csv",
    "serialize_operational_json",
]
