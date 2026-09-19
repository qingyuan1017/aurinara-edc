"""Fidelity tests for the Phase 3 export formats.

**Validates: Requirements 19.5**

These tests exercise the public export-worker dispatcher with one canonical
clinical row. JSON and ODM exports must preserve that row through a parser
round-trip. Excel and SAS XPT exports must be emitted as the format-specific
container rather than a CSV payload with a different file extension.
"""

from __future__ import annotations

import csv
import json
import struct
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.export import Export, ExportStatus
from app.models.form_data import FieldValue, FormInstance
from app.models.form_metadata import FieldDefinition
from app.models.site import Site
from app.models.subject import Subject
from app.models.visit import VisitInstance
from app.workers.export_worker import (
    FIELD_EXPORT_COLUMNS,
    ODM_NS,
    run_export,
    serialize_excel,
    serialize_json,
    serialize_odm_xml,
    serialize_sas_xpt,
)

CANONICAL_ROW = {
    "subject_number": "SUBJ-001",
    "site_number": "SITE-01",
    "visit_name": "Visit 1",
    "form_name": "Demographics",
    "field_variable_name": "AGE",
    "value": "45",
}


def _make_export(export_type: str) -> Export:
    """Build an export job without requiring database persistence."""
    return Export(
        id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        export_type=export_type,
        status=ExportStatus.queued,
        requested_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )


def _make_field_value() -> FieldValue:
    """Build one field value with the relationships used by export workers."""
    site = MagicMock(spec=Site)
    site.site_number = CANONICAL_ROW["site_number"]

    subject = MagicMock(spec=Subject)
    subject.subject_number = CANONICAL_ROW["subject_number"]
    subject.site = site

    visit = MagicMock(spec=VisitInstance)
    visit.name = CANONICAL_ROW["visit_name"]

    form_definition = MagicMock()
    form_definition.name = CANONICAL_ROW["form_name"]

    form_instance = MagicMock(spec=FormInstance)
    form_instance.subject = subject
    form_instance.visit_instance = visit
    form_instance.form_definition = form_definition

    field_definition = MagicMock(spec=FieldDefinition)
    field_definition.variable_name = CANONICAL_ROW["field_variable_name"]

    field_value = MagicMock(spec=FieldValue)
    field_value.form_instance = form_instance
    field_value.field_definition = field_definition
    field_value.value = CANONICAL_ROW["value"]
    return field_value


def _mock_session() -> AsyncMock:
    """Return a session whose query result contains the canonical row."""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_make_field_value()]
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    return session


async def _generate_export(tmp_path: Path, export_type: str) -> Path:
    """Run one export through the worker and return its generated file path."""
    export = _make_export(export_type)
    session = _mock_session()

    with (
        patch("app.workers.export_worker.export_service.start_export", new_callable=AsyncMock),
        patch(
            "app.workers.export_worker.export_service.complete_export",
            new_callable=AsyncMock,
        ) as complete_export,
        patch("app.workers.export_worker.audit_service.record", new_callable=AsyncMock),
        patch(
            "app.workers.export_worker.notification_service.on_export_completed",
            new_callable=AsyncMock,
        ),
        patch("app.workers.export_worker._get_export_dir", return_value=tmp_path),
    ):
        await run_export(session, export)

    return Path(complete_export.call_args.kwargs["file_path"])


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read the canonical row shape used by the existing CSV worker."""
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


@pytest.mark.asyncio
async def test_json_export_round_trips_data_without_loss(tmp_path):
    """JSON export preserves every canonical clinical value after parsing."""
    path = await _generate_export(tmp_path, "json")

    assert path.suffix == ".json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == [CANONICAL_ROW]
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


@pytest.mark.asyncio
async def test_odm_export_round_trips_data_without_loss(tmp_path):
    """ODM XML export preserves the subject, form, field, and value semantics."""
    path = await _generate_export(tmp_path, "odm")

    assert path.suffix == ".xml"
    root = ET.fromstring(path.read_bytes())
    values = {
        element.attrib["ItemOID"]: element.attrib["Value"]
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "ItemData"
    }

    assert values == {
        "subject_number": CANONICAL_ROW["subject_number"],
        "site_number": CANONICAL_ROW["site_number"],
        "visit_name": CANONICAL_ROW["visit_name"],
        "form_name": CANONICAL_ROW["form_name"],
        "field_variable_name": CANONICAL_ROW["field_variable_name"],
        "value": CANONICAL_ROW["value"],
    }


@pytest.mark.asyncio
async def test_excel_export_generates_a_valid_xlsx_container(tmp_path):
    """Excel export is a readable XLSX package, not a CSV text file."""
    path = await _generate_export(tmp_path, "excel")

    assert path.suffix == ".xlsx"
    assert zipfile.is_zipfile(path)
    with zipfile.ZipFile(path) as workbook:
        names = set(workbook.namelist())
        assert "[Content_Types].xml" in names
        assert "xl/workbook.xml" in names
        assert "xl/worksheets/sheet1.xml" in names


@pytest.mark.asyncio
async def test_xpt_export_generates_a_sas_transport_file(tmp_path):
    """SAS XPT export starts with the SAS transport library header."""
    path = await _generate_export(tmp_path, "xpt")

    assert path.suffix == ".xpt"
    assert path.read_bytes().startswith(b"HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!")


@pytest.mark.asyncio
async def test_advanced_export_does_not_fall_back_to_csv(tmp_path):
    """Advanced format requests must not dispatch to the CSV implementation."""
    for export_type in ("excel", "json", "xpt", "odm"):
        path = await _generate_export(tmp_path, export_type)
        assert path.suffix not in {".csv", ".txt"}, export_type
        assert not path.read_bytes().startswith(b"subject_number,site_number")


# ---------------------------------------------------------------------------
# Generated Property 34 coverage for advanced serializers
# ---------------------------------------------------------------------------

# Keep generated values representable in all target formats. In particular,
# XPORT v5 uses ASCII fixed-width records, while the JSON/ODM assertions still
# exercise XML-sensitive punctuation and whitespace.
_EXPORT_TEXT = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    min_size=0,
    max_size=16,
)


@st.composite
def _generated_rows(draw):
    """Generate bounded canonical rows with values safe for every serializer."""
    row_count = draw(st.integers(min_value=1, max_value=6))
    return [
        {column: draw(_EXPORT_TEXT) for column in FIELD_EXPORT_COLUMNS}
        for _ in range(row_count)
    ]


def _row_counter(rows: list[dict[str, str]]) -> Counter[tuple[str, ...]]:
    """Compare row content independently of ODM's subject grouping order."""
    return Counter(tuple(row[column] for column in FIELD_EXPORT_COLUMNS) for row in rows)


def _read_odm_rows(payload: bytes) -> list[dict[str, str]]:
    """Read canonical rows from the repeated ODM export item groups."""
    root = ET.fromstring(payload)
    item_group_tag = f"{{{ODM_NS}}}ItemGroupData"
    item_data_tag = f"{{{ODM_NS}}}ItemData"
    rows: list[dict[str, str]] = []
    for group in root.iter(item_group_tag):
        if group.attrib.get("ItemGroupOID") != "IG_EXPORT":
            continue
        items = list(group.findall(item_data_tag))
        assert len(items) % len(FIELD_EXPORT_COLUMNS) == 0
        for offset in range(0, len(items), len(FIELD_EXPORT_COLUMNS)):
            chunk = items[offset : offset + len(FIELD_EXPORT_COLUMNS)]
            assert [item.attrib["ItemOID"] for item in chunk] == list(FIELD_EXPORT_COLUMNS)
            rows.append({column: item.attrib.get("Value", "") for column, item in zip(FIELD_EXPORT_COLUMNS, chunk, strict=True)})
    return rows


def _read_excel_rows(payload: bytes) -> list[dict[str, str]]:
    """Read inline-string rows from the minimal OOXML workbook."""
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(BytesIO(payload)) as workbook:
        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in sheet.findall(".//main:row", namespace):
        rows.append(
            [node.text or "" for node in row.findall("./main:c/main:is/main:t", namespace)]
        )
    assert rows[0] == list(FIELD_EXPORT_COLUMNS)
    return [dict(zip(FIELD_EXPORT_COLUMNS, values, strict=True)) for values in rows[1:]]


def _read_xpt_rows(payload: bytes, row_count: int) -> list[dict[str, str]]:
    """Read the fixed-width XPORT v5 rows emitted by the worker."""
    variable_count_offset = 7 * 80
    variable_count = int(struct.unpack(">d", payload[variable_count_offset : variable_count_offset + 8])[0])
    assert variable_count == len(FIELD_EXPORT_COLUMNS)
    descriptor_start = variable_count_offset + 8
    lengths = [
        struct.unpack(">h", payload[offset + 4 : offset + 6])[0]
        for offset in range(descriptor_start, descriptor_start + variable_count * 140, 140)
    ]
    observation_start = descriptor_start + variable_count * 140 + 80
    row_width = sum(lengths)
    row_stride = ((row_width + 79) // 80) * 80
    rows: list[dict[str, str]] = []
    for row_number in range(row_count):
        start = observation_start + row_number * row_stride
        observation = payload[start : start + row_width]
        values: list[str] = []
        cursor = 0
        for length in lengths:
            values.append(observation[cursor : cursor + length].decode("ascii").rstrip())
            cursor += length
        rows.append(dict(zip(FIELD_EXPORT_COLUMNS, values, strict=True)))
    return rows


@pytest.mark.parametrize(
    ("serializer", "extension"),
    [
        (serialize_json, ".json"),
        (serialize_odm_xml, ".xml"),
    ],
)
@settings(max_examples=100, deadline=None)
@given(rows=_generated_rows())
def test_property_34_json_and_odm_round_trip_generated_rows(serializer, extension, rows):
    """Generated JSON/ODM exports preserve all canonical clinical rows.

    **Validates: Requirements 19.5**
    """
    payload = serializer(rows)
    assert payload

    if extension == ".json":
        import json

        assert json.loads(payload) == rows
    else:
        # ODM groups rows by subject/visit/form, so compare semantic content
        # rather than relying on the serializer's grouping order.
        assert _row_counter(_read_odm_rows(payload)) == _row_counter(rows)


@st.composite
def _generated_nonempty_rows(draw):
    """Generate rows representable by XPORT's padded character fields."""
    rows = draw(_generated_rows())
    for row in rows:
        for column, value in row.items():
            # XPORT uses spaces for right-padding, so edge spaces are not
            # distinguishable from padding when a file is read back.
            row[column] = value.strip()
        if not any(row.values()):
            row["value"] = "0"
    return rows


@settings(max_examples=100, deadline=None)
@given(rows=_generated_nonempty_rows())
def test_property_34_excel_and_xpt_generate_round_trippable_rows(rows):
    """Generated Excel/XPT artifacts contain every canonical row and value.

    **Validates: Requirements 19.5**
    """
    excel_payload = serialize_excel(rows)
    assert zipfile.is_zipfile(BytesIO(excel_payload))
    assert _read_excel_rows(excel_payload) == rows

    xpt_payload = serialize_sas_xpt(rows)
    assert xpt_payload.startswith(b"HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!")
    assert len(xpt_payload) % 80 == 0
    assert _read_xpt_rows(xpt_payload, len(rows)) == rows
