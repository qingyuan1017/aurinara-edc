"""Export workers for CSV and advanced clinical-data formats.

The worker applies the same study/site/subject/visit/form/domain/date and
quality filters for every data format, then stores the generated artifact in
the configured local export directory. Advanced formats are implemented with
Python's standard library so the worker remains usable in minimal deployments:
JSON, SpreadsheetML-compatible XLSX, SAS Transport v5, and CDISC ODM 1.3.2.

Satisfies Requirements:
  - 19.1: Export job lifecycle (Queued → Running → Completed/Failed).
  - 19.3: Filter support (study, site, subject, visit, form, domain, date range,
           changed_since, locked_only, clean_only).
  - 19.4: Audit download events.
  - 19.5: CSV, Excel, JSON, SAS XPT, and ODM XML formats.
  - 29.3: Background worker infrastructure.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import struct
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_service
from app.core.config import get_settings
from app.models.export import Export, ExportType
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.query import Query, QueryStatus
from app.models.subject import Subject
from app.services.export_service import export_service
from app.services.notification_service import notification_service

logger = logging.getLogger(__name__)

DEFAULT_EXPORT_DIR = "exports"
FIELD_EXPORT_COLUMNS = (
    "subject_number",
    "site_number",
    "visit_name",
    "form_name",
    "field_variable_name",
    "value",
)


def _get_export_dir() -> Path:
    """Resolve the export storage directory from settings or default."""
    settings = get_settings()
    if settings.s3_bucket_name:
        # S3 upload is an infrastructure concern; local generation remains the
        # deterministic fallback used by local, test, and non-S3 environments.
        pass
    export_dir = Path(DEFAULT_EXPORT_DIR)
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def _filter_uuid(filters: dict, *keys: str) -> uuid.UUID | None:
    """Return the first configured UUID filter, accepting API aliases."""
    for key in keys:
        value = filters.get(key)
        if value:
            return uuid.UUID(str(value))
    return None


async def _fetch_field_values(session: AsyncSession, export: Export) -> list[FieldValue]:
    """Fetch field values and apply the complete Requirement 19.3 filter set."""
    filters = export.filters or {}
    stmt = (
        select(FieldValue)
        .join(FormInstance, FieldValue.form_instance_id == FormInstance.id)
        .join(Subject, FormInstance.subject_id == Subject.id)
        .join(FieldDefinition, FieldValue.field_definition_id == FieldDefinition.id)
        .join(FormSection, FieldDefinition.form_section_id == FormSection.id)
        .join(FormDefinition, FormSection.form_definition_id == FormDefinition.id)
        .where(Subject.study_id == export.study_id)
        .options(
            selectinload(FieldValue.form_instance)
            .selectinload(FormInstance.subject)
            .selectinload(Subject.site),
            selectinload(FieldValue.form_instance).selectinload(FormInstance.visit_instance),
            selectinload(FieldValue.form_instance).selectinload(FormInstance.form_definition),
            selectinload(FieldValue.field_definition),
        )
    )

    conditions = []
    site_id = _filter_uuid(filters, "site_id")
    subject_id = _filter_uuid(filters, "subject_id")
    visit_id = _filter_uuid(filters, "visit_instance_id", "visit_id")
    form_id = _filter_uuid(filters, "form_definition_id", "form_id")
    if site_id:
        conditions.append(Subject.site_id == site_id)
    if subject_id:
        conditions.append(FormInstance.subject_id == subject_id)
    if visit_id:
        conditions.append(FormInstance.visit_instance_id == visit_id)
    if form_id:
        conditions.append(FormInstance.form_definition_id == form_id)
    if filters.get("domain"):
        conditions.append(FormDefinition.form_code == filters["domain"])
    if filters.get("date_from"):
        conditions.append(
            FormInstance.created_at >= datetime.fromisoformat(str(filters["date_from"]))
        )
    if filters.get("date_to"):
        conditions.append(
            FormInstance.created_at <= datetime.fromisoformat(str(filters["date_to"]))
        )
    if filters.get("changed_since"):
        conditions.append(
            FormInstance.updated_at >= datetime.fromisoformat(str(filters["changed_since"]))
        )
    if filters.get("locked_only"):
        conditions.append(FormInstance.status == FormInstanceStatus.locked)
    if filters.get("clean_only"):
        open_query_form_ids = select(Query.target_id).where(
            Query.target_type == "Form_Instance",
            Query.status.in_(
                [
                    QueryStatus.open,
                    QueryStatus.answered,
                    QueryStatus.reopened,
                ]
            ),
        )
        conditions.extend(
            [
                FormInstance.status == FormInstanceStatus.submitted,
                FormInstance.id.notin_(open_query_form_ids),
            ]
        )
    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await session.execute(stmt)
    return list(result.scalars().all())


def _field_value_rows(field_values: list[FieldValue]) -> list[dict[str, str]]:
    """Convert normalized field values into the canonical export row shape."""
    rows: list[dict[str, str]] = []
    for field_value in field_values:
        form_instance = field_value.form_instance
        subject = form_instance.subject if form_instance else None
        site = subject.site if subject else None
        visit_instance = form_instance.visit_instance if form_instance else None
        form_definition = form_instance.form_definition if form_instance else None
        field_definition = field_value.field_definition
        rows.append(
            {
                "subject_number": str(subject.subject_number) if subject else "",
                "site_number": str(site.site_number) if site else "",
                "visit_name": str(visit_instance.name) if visit_instance else "",
                "form_name": str(form_definition.name) if form_definition else "",
                "field_variable_name": str(field_definition.variable_name)
                if field_definition
                else "",
                "value": "" if field_value.value is None else str(field_value.value),
            }
        )
    return rows


def serialize_csv(rows: list[dict[str, str]]) -> bytes:
    """Serialize canonical rows as UTF-8 CSV."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(FIELD_EXPORT_COLUMNS), lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def serialize_json(rows: list[dict[str, str]]) -> bytes:
    """Serialize canonical rows as a stable JSON array."""
    return (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _xml_escape_text(value: object) -> str:
    return "" if value is None else str(value)


def serialize_excel(rows: list[dict[str, str]]) -> bytes:
    """Create a minimal standards-compliant XLSX workbook.

    Inline strings avoid a shared-string table and make the resulting workbook
    readable by Excel, LibreOffice, and other OOXML readers without optional
    third-party packages.
    """

    def cell(ref: str, value: object) -> str:
        text = _xml_escape_text(value)
        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )
        preserve = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""
        return f'<c r="{ref}" t="inlineStr"><is><t{preserve}>{escaped}</t></is></c>'

    def column_name(index: int) -> str:
        result = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    xml_rows = []
    header = list(FIELD_EXPORT_COLUMNS)
    for row_number, values in enumerate(
        [header] + [[row[column] for column in header] for row in rows], 1
    ):
        cells = "".join(
            cell(f"{column_name(column_number)}{row_number}", value)
            for column_number, value in enumerate(values, 1)
        )
        xml_rows.append(f'<row r="{row_number}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:F{max(1, len(rows) + 1)}"/><sheetData>{"".join(xml_rows)}</sheetData>'
        "</worksheet>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Clinical Data" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as workbook_zip:
        workbook_zip.writestr("[Content_Types].xml", content_types)
        workbook_zip.writestr("_rels/.rels", root_rels)
        workbook_zip.writestr("xl/workbook.xml", workbook)
        workbook_zip.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        workbook_zip.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
ET.register_namespace("", ODM_NS)


def _odm_tag(name: str) -> str:
    return f"{{{ODM_NS}}}{name}"


def _safe_oid(prefix: str, value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_") or "UNSPECIFIED"
    return f"{prefix}_{safe[:48]}"


def serialize_odm_xml(rows: list[dict[str, str]]) -> bytes:
    """Serialize rows into a CDISC ODM 1.3.2 snapshot with metadata and data."""
    root = ET.Element(
        _odm_tag("ODM"),
        {
            "ODMVersion": "1.3.2",
            "FileType": "Snapshot",
            "FileOID": "ClinicalEDC.Export",
            "CreationDateTime": datetime.now().astimezone().isoformat(),
        },
    )
    study = ET.SubElement(root, _odm_tag("Study"), {"OID": "STUDY.ClinicalEDC"})
    globals_element = ET.SubElement(study, _odm_tag("GlobalVariables"))
    ET.SubElement(globals_element, _odm_tag("StudyName")).text = "Clinical EDC Export"
    ET.SubElement(globals_element, _odm_tag("StudyDescription")).text = "Clinical data export"
    ET.SubElement(globals_element, _odm_tag("ProtocolName")).text = "ClinicalEDC"
    metadata = ET.SubElement(
        study,
        _odm_tag("MetaDataVersion"),
        {
            "OID": "MDV.ClinicalEDC",
            "Name": "Clinical EDC Export Metadata",
            "Description": "Metadata generated from exported clinical rows",
        },
    )

    form_fields: dict[str, list[str]] = {}
    visit_forms: dict[str, set[str]] = {}
    for row in rows:
        form = row["form_name"] or "UNSPECIFIED"
        field = row["field_variable_name"] or "UNSPECIFIED"
        if field not in form_fields.setdefault(form, []):
            form_fields[form].append(field)
        visit_forms.setdefault(row["visit_name"] or "UNSCHEDULED", set()).add(form)

    canonical_group = ET.SubElement(
        metadata,
        _odm_tag("ItemGroupDef"),
        {"OID": "IG_EXPORT", "Name": "Clinical Data", "Repeating": "Yes"},
    )
    for column in FIELD_EXPORT_COLUMNS:
        ET.SubElement(canonical_group, _odm_tag("ItemRef"), {"ItemOID": column})
        ET.SubElement(
            metadata,
            _odm_tag("ItemDef"),
            {"OID": column, "Name": column, "DataType": "text"},
        )

    for form, fields in form_fields.items():
        group_oid = _safe_oid("IG", form)
        group = ET.SubElement(
            metadata,
            _odm_tag("ItemGroupDef"),
            {
                "OID": group_oid,
                "Name": form,
                "Repeating": "No",
                "SASDatasetName": form[:8].upper(),
            },
        )
        for field in fields:
            ET.SubElement(
                group, _odm_tag("ItemRef"), {"ItemOID": _safe_oid("IT", f"{form}_{field}")}
            )
            ET.SubElement(
                metadata,
                _odm_tag("ItemDef"),
                {
                    "OID": _safe_oid("IT", f"{form}_{field}"),
                    "Name": field,
                    "DataType": "text",
                },
            )
        form_def = ET.SubElement(
            metadata,
            _odm_tag("FormDef"),
            {
                "OID": _safe_oid("FORM", form),
                "Name": form,
                "Repeating": "No",
            },
        )
        ET.SubElement(
            form_def, _odm_tag("ItemGroupRef"), {"ItemGroupOID": group_oid, "Mandatory": "No"}
        )

    for visit, forms in visit_forms.items():
        event_def = ET.SubElement(
            metadata,
            _odm_tag("StudyEventDef"),
            {
                "OID": _safe_oid("SE", visit),
                "Name": visit,
                "Repeating": "Yes",
                "Type": "Scheduled",
            },
        )
        for form in sorted(forms):
            ET.SubElement(
                event_def,
                _odm_tag("FormRef"),
                {
                    "FormOID": _safe_oid("FORM", form),
                    "Mandatory": "No",
                },
            )

    study_data = ET.SubElement(
        root,
        _odm_tag("ClinicalData"),
        {
            "StudyOID": "STUDY.ClinicalEDC",
            "MetaDataVersionOID": "MDV.ClinicalEDC",
        },
    )
    subject_nodes: dict[str, ET.Element] = {}
    event_nodes: dict[tuple[str, str], ET.Element] = {}
    form_nodes: dict[tuple[str, str, str], ET.Element] = {}
    for row in rows:
        subject_key = row["subject_number"] or "UNSPECIFIED"
        visit = row["visit_name"] or "UNSCHEDULED"
        form = row["form_name"] or "UNSPECIFIED"
        subject_node = subject_nodes.get(subject_key)
        if subject_node is None:
            subject_node = ET.SubElement(
                study_data, _odm_tag("SubjectData"), {"SubjectKey": subject_key}
            )
            subject_nodes[subject_key] = subject_node
        event_key = (subject_key, visit)
        event_node = event_nodes.get(event_key)
        if event_node is None:
            event_node = ET.SubElement(
                subject_node,
                _odm_tag("StudyEventData"),
                {
                    "StudyEventOID": _safe_oid("SE", visit),
                },
            )
            event_nodes[event_key] = event_node
        form_key = (subject_key, visit, form)
        form_node = form_nodes.get(form_key)
        if form_node is None:
            form_node = ET.SubElement(
                event_node, _odm_tag("FormData"), {"FormOID": _safe_oid("FORM", form)}
            )
            ET.SubElement(form_node, _odm_tag("ItemGroupData"), {"ItemGroupOID": "IG_EXPORT"})
            form_nodes[form_key] = form_node
        group_node = next(iter(form_node))
        for column in FIELD_EXPORT_COLUMNS:
            ET.SubElement(
                group_node,
                _odm_tag("ItemData"),
                {"ItemOID": column, "Value": row[column]},
            )

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _xpt_record(value: str) -> bytes:
    return value.encode("ascii", errors="replace")[:80].ljust(80, b" ")


def serialize_sas_xpt(rows: list[dict[str, str]]) -> bytes:
    """Serialize canonical rows as a SAS Transport Version 5 data set.

    The descriptor and observation records use the fixed-width XPORT layout;
    all columns are intentionally character variables because normalized EDC
    values are stored as text and must round-trip without numeric coercion.
    """
    names = ("SUBJNUM", "SITENUM", "VISIT", "FORM", "FIELD", "VALUE")
    values = [[row[column] for column in FIELD_EXPORT_COLUMNS] for row in rows]
    lengths = [
        max(1, min(32767, max([len(name)] + [len(value) for value in column_values])))
        for name, column_values in zip(
            names,
            zip(*values, strict=True) if values else ([[]] * len(names)),
            strict=True,
        )
    ]
    output = io.BytesIO()
    output.write(_xpt_record("HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!"))
    output.write(_xpt_record("SAS     SAS     SASLIB  9.4     "))
    output.write(_xpt_record("HEADER RECORD*******MEMBER  HEADER RECORD!!!!!!!"))
    output.write(_xpt_record("SAS     SASDATA DATASET         "))
    output.write(_xpt_record("HEADER RECORD*******DSCRPTR HEADER RECORD!!!!!!!"))
    output.write(_xpt_record("SAS     SASDATA DATASET         "))
    output.write(_xpt_record("HEADER RECORD*******NAMESTR HEADER RECORD!!!!!!!"))
    output.write(struct.pack(">d", float(len(names))))

    position = 0
    for name, length in zip(names, lengths, strict=True):
        descriptor = bytearray(140)
        # XPORT NAMESTR fields: type, function, length, reserved, position.
        struct.pack_into(">hhhhI", descriptor, 0, 2, 0, length, 0, position)
        descriptor[12:20] = name.encode("ascii").ljust(8, b" ")
        descriptor[20:60] = name.encode("ascii").ljust(40, b" ")
        descriptor[60:68] = b" " * 8  # format
        descriptor[76:84] = b" " * 8  # informat
        output.write(descriptor)
        position += length

    output.write(_xpt_record("HEADER RECORD*******OBS     HEADER RECORD!!!!!!!"))
    for row in values:
        observation = b"".join(
            value.encode("utf-8", errors="replace")[:length].ljust(length, b" ")
            for value, length in zip(row, lengths, strict=True)
        )
        output.write(observation)
        padding = (-len(observation)) % 80
        if padding:
            output.write(b" " * padding)
    output.write(b" " * ((-output.tell()) % 80))
    return output.getvalue()


_SERIALIZERS = {
    ExportType.csv: ("csv", serialize_csv),
    ExportType.excel: ("xlsx", serialize_excel),
    ExportType.json: ("json", serialize_json),
    ExportType.sas_xpt: ("xpt", serialize_sas_xpt),
    ExportType.xpt: ("xpt", serialize_sas_xpt),
    ExportType.odm_xml: ("xml", serialize_odm_xml),
    ExportType.odm: ("xml", serialize_odm_xml),
}


def _serializer_for(export_type: str):
    try:
        return _SERIALIZERS[ExportType(export_type)]
    except ValueError as exc:
        raise ValueError(f"Unsupported clinical data export format: {export_type}") from exc


async def run_data_export(session: AsyncSession, export: Export) -> None:
    """Run a CSV or advanced-format field-value export."""
    try:
        await export_service.start_export(session, export)
        await session.flush()
        field_values = await _fetch_field_values(session, export)
        rows = _field_value_rows(field_values)
        extension, serializer = _serializer_for(str(export.export_type))
        content = serializer(rows)
        export_dir = _get_export_dir()
        file_path = export_dir / f"export_{export.id}_{export.study_id}.{extension}"
        file_path.write_bytes(content)
        file_size = file_path.stat().st_size
        await export_service.complete_export(
            session,
            export,
            file_path=str(file_path),
            file_size=file_size,
        )
        await audit_service.record(
            session,
            entity_type="export",
            entity_id=export.id,
            action="export_completed",
            study_id=export.study_id,
            actor_id=export.requested_by,
            new_value=f"file_path={file_path}, file_size={file_size}, rows={len(rows)}, format={extension}",
        )
        await notification_service.on_export_completed(session, export)
        logger.info(
            "%s export completed: export_id=%s rows=%d file_size=%d",
            extension.upper(),
            export.id,
            len(rows),
            file_size,
        )
    except Exception as error:
        logger.exception("Data export failed: export_id=%s error=%s", export.id, str(error))
        try:
            await export_service.fail_export(session, export, error_message=str(error))
        except Exception:
            logger.exception("Failed to mark export as failed: export_id=%s", export.id)
        raise


async def run_csv_export(session: AsyncSession, export: Export) -> None:
    """Execute a CSV field-value export."""
    await run_data_export(session, export)


async def run_advanced_export(session: AsyncSession, export: Export) -> None:
    """Execute an Excel, JSON, SAS XPT, or ODM XML field-value export."""
    await run_data_export(session, export)


async def run_subject_list_export(session: AsyncSession, export: Export) -> None:
    """Execute the subject list export job as CSV."""
    try:
        await export_service.start_export(session, export)
        await session.flush()
        filters = export.filters or {}
        stmt = (
            select(Subject)
            .where(Subject.study_id == export.study_id)
            .where(Subject.deleted_at.is_(None))
            .options(selectinload(Subject.site))
        )
        conditions = []
        site_id = _filter_uuid(filters, "site_id")
        subject_id = _filter_uuid(filters, "subject_id")
        if site_id:
            conditions.append(Subject.site_id == site_id)
        if subject_id:
            conditions.append(Subject.id == subject_id)
        if filters.get("date_from"):
            conditions.append(
                Subject.created_at >= datetime.fromisoformat(str(filters["date_from"]))
            )
        if filters.get("date_to"):
            conditions.append(Subject.created_at <= datetime.fromisoformat(str(filters["date_to"])))
        if conditions:
            stmt = stmt.where(and_(*conditions))
        result = await session.execute(stmt.order_by(Subject.subject_number))
        subjects = result.scalars().all()
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(["subject_number", "site_number", "status", "created_at"])
        for subject in subjects:
            writer.writerow(
                [
                    subject.subject_number,
                    subject.site.site_number if subject.site else "",
                    subject.status,
                    subject.created_at.isoformat() if subject.created_at else "",
                ]
            )
        content = output.getvalue().encode("utf-8")
        export_dir = _get_export_dir()
        file_path = export_dir / f"subject_list_{export.id}_{export.study_id}.csv"
        file_path.write_bytes(content)
        file_size = file_path.stat().st_size
        await export_service.complete_export(
            session, export, file_path=str(file_path), file_size=file_size
        )
        await audit_service.record(
            session,
            entity_type="export",
            entity_id=export.id,
            action="export_completed",
            study_id=export.study_id,
            actor_id=export.requested_by,
            new_value=f"file_path={file_path}, file_size={file_size}, subjects={len(subjects)}",
        )
        await notification_service.on_export_completed(session, export)
    except Exception as error:
        logger.exception("Subject list export failed: export_id=%s error=%s", export.id, str(error))
        try:
            await export_service.fail_export(session, export, error_message=str(error))
        except Exception:
            logger.exception("Failed to mark export as failed: export_id=%s", export.id)
        raise


async def run_export(session: AsyncSession, export: Export) -> None:
    """Dispatch a queued export job to its format-specific worker."""
    if export.export_type == ExportType.subject_list:
        await run_subject_list_export(session, export)
    elif export.export_type == ExportType.csv:
        await run_csv_export(session, export)
    else:
        await run_advanced_export(session, export)
