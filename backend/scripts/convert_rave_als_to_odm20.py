"""Convert a Medidata Rave Architect Loader SpreadsheetML workbook to ODM 2.0 JSON.

The legacy ``.xls`` files produced by Rave Architect Loader are XML workbooks,
not binary BIFF files.  This converter intentionally uses only the Python
standard library for workbook parsing and validates its result against
Aurinara's ``OdmDocument`` Pydantic contract before writing JSON.

Run from ``backend/``::

    python -m scripts.convert_rave_als_to_odm20 input.xls

Supported Rave postfix checks are converted to Aurinara v2 declarative rules
and marked for retesting.  The converter fails closed when unsupported checks
or derivations remain; use ``--unresolved-rules omit`` only after accepting the
omissions recorded in the sidecar report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.designer.odm20 import AURINARA_EXTENSION, ODM_PROFILE, OdmDocument
from app.schemas.designer.rule_v2 import RuleDefinitionV2

SS_NS = "urn:schemas-microsoft-com:office:spreadsheet"
SS = f"{{{SS_NS}}}"


class ConversionError(ValueError):
    """Raised when the source cannot be converted without guessing."""


@dataclass(slots=True)
class ConversionResult:
    document: dict[str, Any]
    report: dict[str, Any]


class _UnsupportedRaveCheckError(ValueError):
    """Raised when a Rave check cannot be represented without changing its meaning."""


@dataclass(slots=True)
class _RaveOperand:
    kind: str
    value: Any
    data_type: str | None = None


class SpreadsheetMLWorkbook:
    """Small reader for Excel 2003 SpreadsheetML with sparse cell indexes."""

    def __init__(self, path: Path) -> None:
        try:
            self.root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            raise ConversionError(
                "Input is not Excel 2003 SpreadsheetML XML. Export the Rave ALS workbook "
                "as XML Spreadsheet 2003 before converting it."
            ) from exc
        if self.root.tag != f"{SS}Workbook":
            raise ConversionError("Input XML is not an Excel 2003 SpreadsheetML workbook")
        self._worksheets = {
            worksheet.get(f"{SS}Name", ""): worksheet
            for worksheet in self.root.findall(f"{SS}Worksheet")
        }

    @property
    def sheet_names(self) -> tuple[str, ...]:
        return tuple(self._worksheets)

    def rows(self, sheet_name: str) -> list[dict[str, str]]:
        worksheet = self._worksheets.get(sheet_name)
        if worksheet is None:
            raise ConversionError(f"Required worksheet is missing: {sheet_name}")
        table = worksheet.find(f"{SS}Table")
        if table is None:
            return []
        xml_rows = table.findall(f"{SS}Row")
        if not xml_rows:
            return []
        headers = self._cell_values(xml_rows[0])
        result: list[dict[str, str]] = []
        for xml_row in xml_rows[1:]:
            values = self._cell_values(xml_row)
            row = {
                header: values.get(column, "").strip()
                for column, header in headers.items()
                if header.strip()
            }
            if any(row.values()):
                result.append(row)
        return result

    @staticmethod
    def _cell_values(row: ET.Element) -> dict[int, str]:
        values: dict[int, str] = {}
        column = 1
        for cell in row.findall(f"{SS}Cell"):
            sparse_index = cell.get(f"{SS}Index")
            if sparse_index:
                column = int(sparse_index)
            data = cell.find(f"{SS}Data")
            values[column] = "" if data is None or data.text is None else data.text
            column += 1
        return values


def _true(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def _integer(value: str | None, default: int | None = None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError as exc:
        raise ConversionError(f"Expected an integer, got {text!r}") from exc


def _number(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ConversionError(f"Expected a number, got {text!r}") from exc


def _oid(prefix: str, *parts: str) -> str:
    raw = ".".join(part for part in parts if part)
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-") or "UNNAMED"
    value = f"{prefix}.{cleaned}"
    if len(value) > 255:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16].upper()
        value = f"{value[:238]}.{digest}"
    return value


def _version_name(draft_name: str) -> str:
    match = re.search(r"\bVersion\s+([^\s]+)", draft_name, flags=re.IGNORECASE)
    value = match.group(1) if match else draft_name
    value = value.strip() or "1.0"
    if len(value) > 20:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:6]
        value = f"{value[:13]}-{digest}"
    return value


def _extension(values: dict[str, Any]) -> dict[str, Any]:
    compact = {key: value for key, value in values.items() if value is not None and value != ""}
    return {AURINARA_EXTENSION: compact} if compact else {}


def _field_shape(row: dict[str, str]) -> tuple[str, str, int | None, int | None, bool]:
    source_control = row.get("ControlType", "").strip().lower()
    data_format = row.get("DataFormat", "").strip()
    has_dictionary = bool(row.get("DataDictionaryName", "").strip())
    lowered_format = data_format.lower()
    length: int | None = None
    significant_digits: int | None = None
    partial_date = data_format.endswith("-") or "/" in data_format.strip("/")

    if any(token in lowered_format for token in ("yyyy", "mmm", "dd")):
        if any(token in lowered_format for token in ("hh", "nn", "ss")):
            data_type, default_control = "datetime", "datetime"
        else:
            data_type, default_control = "date", "date"
    elif any(token in lowered_format for token in ("hh", "nn", "ss")):
        data_type, default_control = "time", "time"
    elif data_format.startswith("$"):
        data_type, default_control = "text", "text"
        match = re.fullmatch(r"\$(\d+)", data_format)
        if match:
            length = int(match.group(1))
    elif re.fullmatch(r"\d+", data_format):
        data_type, default_control = "integer", "integer"
    elif match := re.fullmatch(r"\d+\.(\d+)", data_format):
        data_type, default_control = "float", "decimal"
        significant_digits = int(match.group(1))
    else:
        data_type, default_control = "text", "text"

    control_map = {
        "text": default_control,
        "longtext": "textarea",
        "radiobutton": "radio",
        "radiobutton (vertical)": "radio",
        "checkbox": "checkbox",
        "dropdownlist": "dropdown",
        "searchlist": "listbox",
        "dynamic searchlist": "coded_term",
        "datetime": default_control,
    }
    control_type = control_map.get(source_control, default_control)
    if source_control == "checkbox" and data_format in {"", "1"} and not has_dictionary:
        data_type = "boolean"
        control_type = "boolean"
    if source_control == "dynamic searchlist" and not has_dictionary:
        # A Rave Dynamic SearchList is populated from records in another form,
        # not from a DataDictionary. Aurinara does not yet have a portable ODM
        # control for that runtime lookup, so retain it as free text instead of
        # incorrectly creating a coded field with a missing codelist.
        control_type = "text"
    return data_type, control_type, length, significant_digits, partial_date


def _rave_literal(row: dict[str, str]) -> Any:
    value = row.get("StaticValue", "")
    data_format = row.get("DataFormat", "")
    if data_format.startswith("$"):
        return value
    if re.fullmatch(r"\d+(?:\.\d+)?", data_format):
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if number.is_integer() else number
    return value


def _rave_field_reference(
    row: dict[str, str],
    *,
    item_oid: dict[tuple[str, str], str],
    form_oid: dict[str, str],
    group_oid: dict[str, str],
    folder_oid: dict[str, str],
    fields_source: list[dict[str, str]],
) -> tuple[dict[str, Any], str]:
    unsupported_position = any(
        row.get(key, "") not in {"", "0"}
        for key in ("RecordPosition", "FormRepeatNumber", "FolderRepeatNumber")
    )
    if unsupported_position or any(
        row.get(key, "") for key in ("LogicalRecordPosition", "Scope", "OrderBy")
    ):
        raise _UnsupportedRaveCheckError("uses unsupported repeating-record selection")

    source_form = row.get("FormOID", "")
    source_field = row.get("FieldOID", "")
    variable = row.get("VariableOID", "")
    key = (source_form, source_field)
    if key not in item_oid:
        candidates = [
            (source["FormOID"], source["FieldOID"])
            for source in fields_source
            if (not source_form or source["FormOID"] == source_form)
            and variable
            and source.get("VariableOID") == variable
        ]
        if len(candidates) != 1:
            identity = ".".join(part for part in (source_form, source_field or variable) if part)
            raise _UnsupportedRaveCheckError(
                f"references missing or ambiguous field {identity or '<unknown>'}"
            )
        key = candidates[0]
        source_form, source_field = key

    reference: dict[str, Any] = {
        "itemOID": item_oid[key],
        "formOID": form_oid[source_form],
        "itemGroupOID": group_oid[source_form],
        "repeat": "current",
    }
    source_folder = row.get("FolderOID", "")
    if source_folder:
        if source_folder.casefold() == "subject":
            reference["studyEventOID"] = _oid("SE", "SUBJECT")
        elif source_folder in folder_oid:
            reference["studyEventOID"] = folder_oid[source_folder]
        else:
            raise _UnsupportedRaveCheckError(
                f"references missing schedule folder {source_folder}"
            )

    source = next(
        source
        for source in fields_source
        if source["FormOID"] == source_form and source["FieldOID"] == source_field
    )
    data_type = _field_shape(source)[0]
    return reference, data_type


def _rave_condition(operator: str, left: _RaveOperand, right: _RaveOperand) -> dict[str, Any]:
    comparison = {
        "IsEqualTo": "==",
        "IsNotEqualTo": "!=",
        "IsGreaterThan": ">",
        "IsGreaterThanOrEqualTo": ">=",
        "IsLessThan": "<",
        "IsLessThanOrEqualTo": "<=",
    }[operator]
    if left.kind == "field":
        field = left
        other = right
    elif right.kind == "field":
        field = right
        other = left
        comparison = {">": "<", ">=": "<=", "<": ">", "<=": ">="}.get(
            comparison, comparison
        )
    else:
        raise _UnsupportedRaveCheckError(f"{operator} does not compare a field")
    if other.kind not in {"field", "value"}:
        raise _UnsupportedRaveCheckError(f"{operator} has an unsupported operand")
    if field.data_type in {"date", "datetime"}:
        comparison = {">": "after", "<": "before"}.get(comparison, comparison)
    condition: dict[str, Any] = {"operator": comparison, "field": field.value}
    if other.kind == "field":
        condition["otherField"] = other.value
    else:
        condition["value"] = other.value
    return condition


def _rave_aggregate(operator: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    flattened: list[dict[str, Any]] = []
    for child in children:
        if child.get("operator") == operator and set(child) <= {"operator", "children"}:
            flattened.extend(child["children"])
        else:
            flattened.append(child)
    return {"operator": operator, "children": flattened}


def _invert_rave_condition(condition: dict[str, Any]) -> dict[str, Any]:
    operator = condition["operator"]
    if operator in {"any", "all"}:
        inverse = "all" if operator == "any" else "any"
        return _rave_aggregate(
            inverse,
            [_invert_rave_condition(child) for child in condition["children"]],
        )
    inverse = {
        "is_null": "not_null",
        "not_null": "is_null",
        "exists": "is_null",
        "==": "!=",
        "!=": "==",
        ">": "<=",
        ">=": "<",
        "<": ">=",
        "<=": ">",
        "before": ">=",
        "after": "<=",
        "in": "not_in",
        "not_in": "in",
    }.get(operator)
    if inverse is None:
        raise _UnsupportedRaveCheckError(f"cannot safely negate {operator}")
    result = dict(condition)
    result["operator"] = inverse
    return result


def _translate_rave_expression(
    rows: list[dict[str, str]],
    *,
    item_oid: dict[tuple[str, str], str],
    form_oid: dict[str, str],
    group_oid: dict[str, str],
    folder_oid: dict[str, str],
    fields_source: list[dict[str, str]],
) -> dict[str, Any]:
    stack: list[_RaveOperand] = []
    binary_comparisons = {
        "IsEqualTo",
        "IsNotEqualTo",
        "IsGreaterThan",
        "IsGreaterThanOrEqualTo",
        "IsLessThan",
        "IsLessThanOrEqualTo",
    }
    for row in sorted(rows, key=lambda value: _integer(value.get("StepOrdinal"), 0) or 0):
        function = row.get("CheckFunction", "")
        if not function:
            if row.get("FieldOID") or row.get("VariableOID") or row.get("FormOID"):
                reference, data_type = _rave_field_reference(
                    row,
                    item_oid=item_oid,
                    form_oid=form_oid,
                    group_oid=group_oid,
                    folder_oid=folder_oid,
                    fields_source=fields_source,
                )
                stack.append(_RaveOperand("field", reference, data_type))
            else:
                stack.append(_RaveOperand("value", _rave_literal(row)))
            continue

        if function in binary_comparisons:
            if len(stack) < 2:
                raise _UnsupportedRaveCheckError(f"{function} has too few operands")
            right = stack.pop()
            left = stack.pop()
            stack.append(_RaveOperand("condition", _rave_condition(function, left, right)))
            continue

        if function in {"IsEmpty", "IsNotEmpty", "IsPresent"}:
            if not stack or stack[-1].kind != "field":
                raise _UnsupportedRaveCheckError(f"{function} requires a field")
            field = stack.pop().value
            if function == "IsEmpty":
                condition = _rave_aggregate(
                    "any",
                    [
                        {"operator": "is_null", "field": field},
                        {"operator": "==", "field": field, "value": ""},
                    ],
                )
            elif function == "IsNotEmpty":
                condition = _rave_aggregate(
                    "all",
                    [
                        {"operator": "not_null", "field": field},
                        {"operator": "!=", "field": field, "value": ""},
                    ],
                )
            else:
                condition = {"operator": "exists", "field": field}
            stack.append(_RaveOperand("condition", condition))
            continue

        if function in {"And", "Or"}:
            if len(stack) < 2 or any(value.kind != "condition" for value in stack[-2:]):
                raise _UnsupportedRaveCheckError(f"{function} requires two conditions")
            right = stack.pop().value
            left = stack.pop().value
            stack.append(
                _RaveOperand(
                    "condition",
                    _rave_aggregate("all" if function == "And" else "any", [left, right]),
                )
            )
            continue

        if function == "Not":
            if not stack or stack[-1].kind != "condition":
                raise _UnsupportedRaveCheckError("Not requires a condition")
            stack[-1] = _RaveOperand("condition", _invert_rave_condition(stack[-1].value))
            continue

        if function in {"Contains", "StartsWith"}:
            if len(stack) < 2:
                raise _UnsupportedRaveCheckError(f"{function} has too few operands")
            right = stack.pop()
            left = stack.pop()
            if left.kind != "field" or right.kind != "value" or not isinstance(right.value, str):
                raise _UnsupportedRaveCheckError(
                    f"{function} requires a field and static text"
                )
            escaped = re.escape(right.value)
            pattern = f".*{escaped}.*" if function == "Contains" else f"{escaped}.*"
            stack.append(
                _RaveOperand(
                    "condition",
                    {"operator": "matches", "field": left.value, "value": pattern},
                )
            )
            continue

        raise _UnsupportedRaveCheckError(f"uses unsupported check function {function}")

    if len(stack) != 1 or stack[0].kind != "condition":
        raise _UnsupportedRaveCheckError(
            "postfix expression does not reduce to one condition"
        )
    return stack[0].value


def _translate_rave_action(
    row: dict[str, str],
    *,
    item_oid: dict[tuple[str, str], str],
    form_oid: dict[str, str],
    group_oid: dict[str, str],
    folder_oid: dict[str, str],
    fields_source: list[dict[str, str]],
) -> dict[str, Any]:
    action_type = row.get("ActionType", "")
    if action_type not in {"OpenQuery", "SetDataPointVisible"}:
        raise _UnsupportedRaveCheckError(
            f"uses unsupported action {action_type or '<blank>'}"
        )
    target, _ = _rave_field_reference(
        row,
        item_oid=item_oid,
        form_oid=form_oid,
        group_oid=group_oid,
        folder_oid=folder_oid,
        fields_source=fields_source,
    )
    if action_type == "OpenQuery":
        return {
            "type": "open_query",
            "target": target,
            "message": row.get("ActionString") or "Rave edit check query",
        }
    visible = row.get("ActionOptions", "").strip().upper().startswith("TRUE")
    return {"type": "show" if visible else "hide", "target": target}


def _translate_rave_checks(
    checks: list[dict[str, str]],
    steps: list[dict[str, str]],
    actions: list[dict[str, str]],
    *,
    item_oid: dict[tuple[str, str], str],
    form_oid: dict[str, str],
    group_oid: dict[str, str],
    folder_oid: dict[str, str],
    fields_source: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    steps_by_check: dict[str, list[dict[str, str]]] = defaultdict(list)
    actions_by_check: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in steps:
        steps_by_check[row.get("CheckName", "")].append(row)
    for row in actions:
        actions_by_check[row.get("CheckName", "")].append(row)

    conditions: list[dict[str, Any]] = []
    omitted_reasons: Counter[str] = Counter()
    used_condition_oids: set[str] = set()
    for check in checks:
        name = check.get("CheckName") or check.get("OID") or "Unnamed Rave check"
        source_oid = check.get("OID") or name
        try:
            check_steps = steps_by_check.get(name, [])
            check_actions = actions_by_check.get(name, [])
            if not check_steps:
                raise _UnsupportedRaveCheckError("has no CheckSteps")
            if not check_actions:
                raise _UnsupportedRaveCheckError("has no CheckActions")
            condition = _translate_rave_expression(
                check_steps,
                item_oid=item_oid,
                form_oid=form_oid,
                group_oid=group_oid,
                folder_oid=folder_oid,
                fields_source=fields_source,
            )
            converted_actions = [
                _translate_rave_action(
                    action,
                    item_oid=item_oid,
                    form_oid=form_oid,
                    group_oid=group_oid,
                    folder_oid=folder_oid,
                    fields_source=fields_source,
                )
                for action in check_actions
            ]
            expression = {
                "schemaVersion": 2,
                "scope": {
                    "sourceSystem": "Medidata Rave ALS",
                    "sourceCheckOID": source_oid,
                },
                "condition": condition,
                "actions": converted_actions,
                "execution": {
                    "trigger": "form_save",
                    "priority": 100,
                    "stopOnFailure": True,
                },
            }
            expression = RuleDefinitionV2.model_validate(expression).model_dump(
                by_alias=True, exclude_none=True, mode="json"
            )
        except (_UnsupportedRaveCheckError, ValueError) as exc:
            omitted_reasons[str(exc)] += 1
            continue

        source_reason = check.get("RetestingReason", "").strip()
        conversion_reason = (
            "Automatically translated from Medidata Rave postfix logic; verify field scope, "
            "value typing, and action behavior before publication."
        )
        # Distinct Rave check names can sanitize to the same OID, e.g.
        # "X(Unit=blank)" and "X(Unit≠blank)". Disambiguate with a digest of the
        # raw source name so the OID stays deterministic.
        condition_oid = _oid("COND", source_oid)
        if condition_oid in used_condition_oids:
            digest = hashlib.sha256(source_oid.encode("utf-8")).hexdigest()[:8].upper()
            condition_oid = _oid("COND", source_oid, digest)
        used_condition_oids.add(condition_oid)
        conditions.append(
            {
                "oid": condition_oid,
                "name": name,
                "description": check.get("Infix") or None,
                "expression": expression,
                "extensions": _extension(
                    {
                        "severity": (
                            "query"
                            if any(action["type"] == "open_query" for action in converted_actions)
                            else "info"
                        ),
                        "active": _true(check.get("CheckActive")),
                        "schemaVersion": 2,
                        "needsRetesting": True,
                        "retestingReason": (
                            f"{source_reason} {conversion_reason}".strip()
                            if source_reason
                            else conversion_reason
                        ),
                        "sourceSystem": "Medidata Rave ALS",
                        "sourceCheckOID": source_oid,
                    }
                ),
            }
        )
    return conditions, omitted_reasons


def _select_matrix(
    workbook: SpreadsheetMLWorkbook, requested: str, fallback: str
) -> tuple[str, str]:
    candidates: dict[str, str] = {}
    for name in workbook.sheet_names:
        match = re.fullmatch(r"Matrix\d+#(.+)", name)
        if match:
            candidates[match.group(1).upper()] = name
    choice = requested.upper()
    if choice == "AUTO":
        choice = "MASTER" if "MASTER" in candidates else fallback.upper()
    if choice not in candidates:
        available = ", ".join(sorted(candidates)) or "none"
        raise ConversionError(f"Matrix {choice!r} is unavailable; available matrices: {available}")
    return choice, candidates[choice]


def convert_workbook(
    input_path: Path,
    *,
    matrix: str = "AUTO",
    unresolved_rules: str = "error",
    study_name: str | None = None,
    protocol_name: str | None = None,
    version_name: str | None = None,
) -> ConversionResult:
    workbook = SpreadsheetMLWorkbook(input_path)
    required = {
        "CRFDraft",
        "Forms",
        "Fields",
        "Folders",
        "DataDictionaries",
        "DataDictionaryEntries",
        "UnitDictionaries",
        "UnitDictionaryEntries",
        "Matrices",
    }
    missing = sorted(required - set(workbook.sheet_names))
    if missing:
        raise ConversionError(
            f"Workbook is not a supported Rave ALS export; missing: {', '.join(missing)}"
        )

    warnings: list[str] = []
    omitted: dict[str, int] = {}
    draft_rows = workbook.rows("CRFDraft")
    if not draft_rows:
        raise ConversionError("CRFDraft does not contain a configuration row")
    draft = draft_rows[0]
    project_name = draft.get("ProjectName") or input_path.stem
    draft_name = draft.get("DraftName") or project_name
    chosen_matrix, matrix_sheet = _select_matrix(
        workbook, matrix, draft.get("DefaultMatrixOID", "")
    )

    forms_source = [
        row
        for row in workbook.rows("Forms")
        if row.get("OID") and _true(row.get("DraftFormActive"))
    ]
    fields_source = [
        row
        for row in workbook.rows("Fields")
        if row.get("FormOID") and row.get("FieldOID") and _true(row.get("DraftFieldActive"))
    ]
    folders_source = [row for row in workbook.rows("Folders") if row.get("OID")]
    dictionaries_source = [
        row for row in workbook.rows("DataDictionaries") if row.get("DataDictionaryName")
    ]
    dictionary_entries = workbook.rows("DataDictionaryEntries")
    unit_dictionaries = [
        row for row in workbook.rows("UnitDictionaries") if row.get("UnitDictionaryName")
    ]
    unit_entries = workbook.rows("UnitDictionaryEntries")
    checks = [row for row in workbook.rows("Checks")] if "Checks" in workbook.sheet_names else []
    derivations = (
        [row for row in workbook.rows("Derivations")]
        if "Derivations" in workbook.sheet_names
        else []
    )
    check_steps = (
        [row for row in workbook.rows("CheckSteps")] if "CheckSteps" in workbook.sheet_names else []
    )
    check_actions = (
        [row for row in workbook.rows("CheckActions")]
        if "CheckActions" in workbook.sheet_names
        else []
    )

    form_by_source = {row["OID"]: row for row in forms_source}
    unknown_field_forms = sorted(
        {row["FormOID"] for row in fields_source if row["FormOID"] not in form_by_source}
    )
    if unknown_field_forms:
        raise ConversionError(
            "Fields reference missing/inactive forms: " + ", ".join(unknown_field_forms)
        )
    fields_by_form: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in fields_source:
        fields_by_form[row["FormOID"]].append(row)
    for rows in fields_by_form.values():
        rows.sort(key=lambda row: (_integer(row.get("Ordinal"), 0) or 0, row["FieldOID"]))

    dictionary_oid: dict[str, str] = {
        row["DataDictionaryName"]: _oid("CL", row.get("OID") or row["DataDictionaryName"])
        for row in dictionaries_source
    }
    entries_by_dictionary: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in dictionary_entries:
        if row.get("DataDictionaryName"):
            entries_by_dictionary[row["DataDictionaryName"]].append(row)

    code_lists: list[dict[str, Any]] = []
    for row in sorted(dictionaries_source, key=lambda value: value["DataDictionaryName"]):
        name = row["DataDictionaryName"]
        seen_codes: set[str] = set()
        items: list[dict[str, Any]] = []
        for entry in sorted(
            entries_by_dictionary.get(name, []),
            key=lambda value: (_integer(value.get("Ordinal"), 0) or 0, value.get("CodedData", "")),
        ):
            code = entry.get("CodedData", "")
            if code in seen_codes:
                warnings.append(f"Ignored duplicate coded value {code!r} in {name}")
                continue
            seen_codes.add(code)
            items.append(
                {
                    "codedValue": code,
                    "decode": entry.get("UserDataString") or code,
                    "orderNumber": _integer(entry.get("Ordinal"), len(items) + 1),
                    "specify": _true(entry.get("Specify")),
                }
            )
        code_lists.append(
            {
                "oid": dictionary_oid[name],
                "name": name,
                "dataType": "text",
                "items": items,
            }
        )

    unit_entries_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in unit_entries:
        if row.get("UnitDictionaryName"):
            unit_entries_by_name[row["UnitDictionaryName"]].append(row)
    unit_reference: dict[str, str] = {}
    measurement_units: list[dict[str, Any]] = []
    for dictionary in sorted(unit_dictionaries, key=lambda value: value["UnitDictionaryName"]):
        name = dictionary["UnitDictionaryName"]
        standard = dictionary.get("StandardUnitName", "")
        rows = sorted(
            unit_entries_by_name.get(name, []),
            key=lambda value: (_integer(value.get("Ordinal"), 0) or 0, value.get("CodedUnit", "")),
        )
        for entry in rows:
            symbol = entry.get("UnitString") or entry.get("CodedUnit") or name
            oid = _oid("MU", dictionary.get("OID") or name, entry.get("CodedUnit") or symbol)
            a = _number(entry.get("ConstantA"))
            b = _number(entry.get("ConstantB"))
            c = _number(entry.get("ConstantC")) or 0.0
            k = _number(entry.get("ConstantK")) or 0.0
            factor = None if a is None or b in {None, 0.0} else a / b
            offset = None if factor is None else c * factor + k
            measurement_units.append(
                {
                    "oid": oid,
                    "name": f"{name} {symbol}",
                    "symbol": symbol,
                    "conversionFactor": factor,
                    "conversionOffset": offset,
                }
            )
            if symbol == standard:
                unit_reference[name] = oid
        if name not in unit_reference and rows:
            fallback_symbol = rows[0].get("CodedUnit") or rows[0].get("UnitString") or name
            unit_reference[name] = _oid("MU", dictionary.get("OID") or name, fallback_symbol)
            warnings.append(
                f"Unit dictionary {name} has no entry matching standard unit {standard!r}; used first entry"
            )

    form_oid = {source: _oid("F", source) for source in form_by_source}
    group_oid = {source: _oid("IG", source) for source in form_by_source}
    item_oid: dict[tuple[str, str], str] = {}
    items: list[dict[str, Any]] = []
    item_groups: list[dict[str, Any]] = []
    forms: list[dict[str, Any]] = []
    dynamic_search_fields: list[str] = []
    for source_form in sorted(
        forms_source, key=lambda row: (_integer(row.get("Ordinal"), 0) or 0, row["OID"])
    ):
        source_form_oid = source_form["OID"]
        source_fields = fields_by_form.get(source_form_oid, [])
        repeating = any(_true(row.get("IsLog")) for row in source_fields)
        item_refs: list[dict[str, Any]] = []
        seen_field_oids: set[str] = set()
        for index, source_field in enumerate(source_fields, start=1):
            source_field_oid = source_field["FieldOID"]
            if source_field_oid in seen_field_oids:
                raise ConversionError(
                    f"Duplicate FieldOID {source_field_oid!r} in form {source_form_oid!r}"
                )
            seen_field_oids.add(source_field_oid)
            oid = _oid("I", source_form_oid, source_field_oid)
            item_oid[(source_form_oid, source_field_oid)] = oid
            order = _integer(source_field.get("Ordinal"), index) or index
            data_type, control_type, length, digits, partial_date = _field_shape(source_field)
            dictionary_name = source_field.get("DataDictionaryName", "")
            if (
                source_field.get("ControlType", "").strip().lower() == "dynamic searchlist"
                and not dictionary_name
            ):
                dynamic_search_fields.append(f"{source_form_oid}.{source_field_oid}")
            if dictionary_name and dictionary_name not in dictionary_oid:
                raise ConversionError(
                    f"Field {source_form_oid}.{source_field_oid} references missing data dictionary "
                    f"{dictionary_name!r}"
                )
            unit_name = source_field.get("UnitDictionaryName", "")
            if unit_name and unit_name not in unit_reference:
                raise ConversionError(
                    f"Field {source_form_oid}.{source_field_oid} references missing unit dictionary "
                    f"{unit_name!r}"
                )
            label = (
                source_field.get("SASLabel")
                or source_field.get("PreText")
                or source_field.get("DraftFieldName")
                or source_field_oid
            )
            question = source_field.get("PreText") or source_field.get("HeaderText") or label
            items.append(
                {
                    "oid": oid,
                    "name": source_field.get("VariableOID") or source_field_oid,
                    "dataType": data_type,
                    "question": question,
                    "length": length,
                    "significantDigits": digits,
                    "codeListOID": dictionary_oid.get(dictionary_name),
                    "measurementUnitOID": unit_reference.get(unit_name),
                    "extensions": _extension(
                        {
                            "label": label,
                            "controlType": control_type,
                            "defaultValue": source_field.get("DefaultValue") or None,
                            "helpText": source_field.get("HelpText") or None,
                            "unit": source_field.get("FixedUnit") or None,
                            "dataFormat": source_field.get("DataFormat") or None,
                            "allowsPartialDate": partial_date,
                            "sourceDocument": _true(source_field.get("SourceDocument")),
                            "queryFutureDate": _true(source_field.get("QueryFutureDate")),
                            "queryNonconformance": _true(source_field.get("QueryNonConformance")),
                            "breaksSignature": not _true(source_field.get("DoesNotBreakSignature")),
                            "reviewGroup": source_field.get("ReviewGroups") or None,
                            "sourceSystem": "Medidata Rave ALS",
                            "sourceControlType": source_field.get("ControlType") or None,
                            "sourceFormOID": source_form_oid,
                            "sourceFieldOID": source_field_oid,
                        }
                    ),
                }
            )
            item_refs.append(
                {
                    "oid": oid,
                    "mandatory": _true(source_field.get("IsRequired")),
                    "orderNumber": order,
                }
            )
        form_name = source_form.get("DraftFormName") or source_form_oid
        item_groups.append(
            {
                "oid": group_oid[source_form_oid],
                "name": f"{form_name} fields",
                "repeating": repeating,
                "itemRefs": item_refs,
                "extensions": _extension(
                    {
                        "label": form_name,
                        "outputToDataset": True,
                        "sourceSystem": "Medidata Rave ALS",
                    }
                ),
            }
        )
        forms.append(
            {
                "oid": form_oid[source_form_oid],
                "name": form_name,
                "repeating": repeating,
                "itemGroupRefs": [
                    {
                        "oid": group_oid[source_form_oid],
                        "mandatory": True,
                        "orderNumber": 1,
                    }
                ],
                "extensions": _extension(
                    {
                        "formCode": source_form_oid,
                        "requiresSignature": _true(source_form.get("IsSignatureRequired")),
                        "formType": "log" if repeating else "simple",
                        "accessType": "open_access",
                        "domain": source_form_oid,
                        "label": form_name,
                        "sourceSystem": "Medidata Rave ALS",
                    }
                ),
            }
        )

    if dynamic_search_fields:
        warnings.append(
            f"Mapped {len(dynamic_search_fields)} Dynamic SearchList fields to text because "
            "cross-form dynamic lookup semantics are not supported; retained each original "
            "control type in sourceControlType."
        )

    matrix_rows = workbook.rows(matrix_sheet)
    if not matrix_rows:
        raise ConversionError(f"Matrix worksheet {matrix_sheet} contains no schedule rows")
    matrix_form_column = f"Matrix: {chosen_matrix}"
    if matrix_form_column not in matrix_rows[0]:
        matrix_form_column = next(iter(matrix_rows[0]))
    refs_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    subject_refs: list[dict[str, Any]] = []
    for source_row in matrix_rows:
        source_form_oid = source_row.get(matrix_form_column, "")
        if not source_form_oid or source_form_oid not in form_oid:
            continue
        for event_source_oid, marker in source_row.items():
            if event_source_oid == matrix_form_column or marker.upper() != "X":
                continue
            is_subject_event = event_source_oid.casefold() == "subject"
            event_refs = subject_refs if is_subject_event else refs_by_event[event_source_oid]
            reference = {
                "oid": form_oid[source_form_oid],
                "mandatory": True,
                "orderNumber": len(event_refs) + 1,
            }
            event_refs.append(reference)

    primary_form = draft.get("PrimaryFormOID", "")
    if primary_form in form_oid and all(
        ref["oid"] != form_oid[primary_form] for ref in subject_refs
    ):
        subject_refs.insert(
            0,
            {"oid": form_oid[primary_form], "mandatory": True, "orderNumber": 1},
        )
        for order, ref in enumerate(subject_refs, start=1):
            ref["orderNumber"] = order

    folder_oid = {row["OID"]: _oid("SE", row["OID"]) for row in folders_source}
    conditions, omitted_check_reasons = _translate_rave_checks(
        checks,
        check_steps,
        check_actions,
        item_oid=item_oid,
        form_oid=form_oid,
        group_oid=group_oid,
        folder_oid=folder_oid,
        fields_source=fields_source,
    )
    unresolved: list[str] = []
    omitted_check_count = len(checks) - len(conditions)
    if conditions:
        warnings.append(
            f"Converted {len(conditions)} of {len(checks)} Rave checks to Aurinara v2 rules; "
            "all converted rules require retesting before publication."
        )
    if omitted_check_count:
        omitted["checks"] = omitted_check_count
        reason_summary = ", ".join(
            f"{count} {reason}"
            for reason, count in omitted_check_reasons.most_common(8)
        )
        unresolved.append(
            f"{omitted_check_count} checks could not be represented safely"
            + (f" ({reason_summary})" if reason_summary else "")
        )
    if derivations:
        omitted["derivations"] = len(derivations)
        unresolved.append(
            f"{len(derivations)} derivations: Rave postfix derivations require reviewed semantic mapping"
        )
    if unresolved and unresolved_rules == "error":
        raise ConversionError(
            "Unresolved executable metadata would be omitted. "
            + "; ".join(unresolved)
            + ". Re-run with --unresolved-rules omit only after reviewing this limitation."
        )
    warnings.extend(f"Omitted {message}" for message in unresolved)

    unknown_matrix_events = sorted(set(refs_by_event) - set(folder_oid))
    if unknown_matrix_events:
        raise ConversionError(
            "Selected matrix references folders missing from Folders: "
            + ", ".join(unknown_matrix_events)
        )
    study_events: list[dict[str, Any]] = []
    if subject_refs:
        study_events.append(
            {
                "oid": _oid("SE", "SUBJECT"),
                "name": "Subject",
                "repeating": False,
                "type": "common",
                "formRefs": subject_refs,
                "extensions": _extension(
                    {"definitionKind": "subject", "sourceSystem": "Medidata Rave ALS"}
                ),
            }
        )
    for index, folder in enumerate(
        sorted(
            folders_source,
            key=lambda row: (_integer(row.get("Ordinal"), 0) or 0, row["OID"]),
        ),
        start=1,
    ):
        source_oid = folder["OID"]
        name = folder.get("FolderName") or source_oid
        lower_identity = f"{source_oid} {name}".lower()
        event_type = (
            "unscheduled"
            if "unscheduled" in lower_identity or source_oid.upper() == "UNS"
            else "common"
            if "common" in lower_identity or source_oid.upper() == "COM"
            else "scheduled"
        )
        parent = folder.get("ParentFolderOID", "")
        if parent and parent not in folder_oid:
            raise ConversionError(f"Folder {source_oid} references missing parent folder {parent}")
        # Rave calls every schedule node a Folder, including ordinary visits.
        # A node that owns forms in the selected matrix is a selectable visit;
        # form-less nodes are structural containers/templates.
        definition_kind = "visit" if refs_by_event.get(source_oid) else "folder"
        study_events.append(
            {
                "oid": folder_oid[source_oid],
                "name": name,
                "repeating": _true(folder.get("IsReusable")),
                "type": event_type,
                "formRefs": refs_by_event.get(source_oid, []),
                "extensions": _extension(
                    {
                        "visitNumber": _integer(folder.get("Ordinal"), index),
                        "definitionKind": definition_kind,
                        "parentOID": folder_oid.get(parent),
                        "targetDay": _integer(folder.get("Targetdays")),
                        "windowBefore": _integer(folder.get("StartWinDays")),
                        "windowAfter": _integer(folder.get("EndWinDays")),
                        "sourceSystem": "Medidata Rave ALS",
                    }
                ),
            }
        )

    fields_source_by_key = {(row["FormOID"], row["FieldOID"]): row for row in fields_source}
    supplemental_by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    if "CoderSupplementalTerms" in workbook.sheet_names:
        for row in workbook.rows("CoderSupplementalTerms"):
            key = (row.get("FormOID", ""), row.get("FieldOID", ""))
            term = row.get("SupplementalTerm", "")
            if term:
                supplemental_by_key[key].append(term)
    coding_settings: list[dict[str, Any]] = []
    if "CoderConfiguration" in workbook.sheet_names:
        for row in workbook.rows("CoderConfiguration"):
            key = (row.get("FormOID", ""), row.get("FieldOID", ""))
            target_oid = item_oid.get(key)
            if target_oid is None:
                warnings.append(f"Ignored coding configuration for missing field {key[0]}.{key[1]}")
                continue
            field_source = fields_source_by_key[key]
            dictionary_reference = re.sub(
                r"\s*\(Coder\)\s*$", "", field_source.get("CodingDictionary", "")
            ).strip()
            if not dictionary_reference:
                dictionary_reference = row.get("CodingLevel") or "Unspecified coding dictionary"
                warnings.append(
                    f"Coding dictionary name was absent for {key[0]}.{key[1]}; "
                    f"used {dictionary_reference!r}"
                )
            coding_rule = None
            supplemental = supplemental_by_key.get(key, [])
            if supplemental:
                resolved = [item_oid.get((key[0], source)) for source in supplemental]
                coding_rule = {
                    "supplementalItemOIDs": [value for value in resolved if value],
                    "unresolvedSupplementalTerms": [
                        source
                        for source, value in zip(supplemental, resolved, strict=True)
                        if not value
                    ],
                }
            coding_settings.append(
                {
                    "fieldItemOID": target_oid,
                    "dictionaryReference": dictionary_reference,
                    "codingLevel": row.get("CodingLevel") or None,
                    "locale": row.get("Locale") or None,
                    "priority": _integer(row.get("Priority"), 100),
                    "approvalRequired": _true(row.get("IsApprovalRequired")),
                    "autoApproval": _true(row.get("IsAutoApproval")),
                    "codingRule": coding_rule,
                }
            )

    restricted_fields = sum(
        bool(row.get("ViewRestrictions") or row.get("EntryRestrictions")) for row in fields_source
    )
    restricted_forms = sum(
        bool(row.get("ViewRestrictions") or row.get("EntryRestrictions")) for row in forms_source
    )
    if restricted_fields or restricted_forms:
        omitted["rave_restriction_rows"] = restricted_fields + restricted_forms
        warnings.append(
            "Rave ViewRestrictions/EntryRestrictions were not converted to crfAccess because "
            "their exclusion semantics do not map safely to Aurinara allow grants"
        )

    source_digest = hashlib.sha256(input_path.read_bytes()).hexdigest().upper()
    mdv_name = version_name or _version_name(draft_name)
    metadata_extension = {
        "schedule": chosen_matrix,
        "codingSettings": coding_settings,
        "crfAccess": [],
        "conversion": {
            "sourceSystem": "Medidata Rave ALS",
            "sourceSha256": source_digest.lower(),
            "sourceDraftName": draft_name,
            "sourceMatrix": chosen_matrix,
            "converted": {"checks": len(conditions)},
            "omitted": omitted,
        },
    }
    raw_document: dict[str, Any] = {
        "odmVersion": "2.0",
        "profile": ODM_PROFILE,
        "fileType": "Snapshot",
        "fileOID": _oid("FILE", source_digest[:32]),
        "study": {
            "oid": _oid("S", protocol_name or project_name),
            "studyName": study_name or project_name,
            "protocolName": protocol_name or project_name,
            "metaDataVersion": {
                "oid": _oid("MDV", protocol_name or project_name, mdv_name),
                "name": mdv_name,
                "studyEvents": study_events,
                "forms": forms,
                "itemGroups": item_groups,
                "items": items,
                "codeLists": code_lists,
                "measurementUnits": measurement_units,
                "conditions": conditions,
                "methods": [],
                "extensions": {AURINARA_EXTENSION: metadata_extension},
            },
        },
    }
    try:
        validated = OdmDocument.model_validate(raw_document)
    except Exception as exc:
        raise ConversionError(f"Generated ODM document failed Aurinara validation: {exc}") from exc
    document = validated.model_dump(by_alias=True, exclude_none=True, mode="json")
    mdv = document["study"]["metaDataVersion"]
    output_counts = {
        "study_events": len(mdv["studyEvents"]),
        "forms": len(mdv["forms"]),
        "item_groups": len(mdv["itemGroups"]),
        "items": len(mdv["items"]),
        "code_lists": len(mdv["codeLists"]),
        "measurement_units": len(mdv["measurementUnits"]),
        "conditions": len(mdv["conditions"]),
        "methods": len(mdv["methods"]),
    }
    report = {
        "source": str(input_path.resolve()),
        "source_sha256": source_digest.lower(),
        "profile": ODM_PROFILE,
        "matrix": chosen_matrix,
        "source_counts": {
            "forms": len(forms_source),
            "fields": len(fields_source),
            "folders": len(folders_source),
            "data_dictionaries": len(dictionaries_source),
            "data_dictionary_entries": len(dictionary_entries),
            "unit_dictionaries": len(unit_dictionaries),
            "unit_dictionary_entries": len(unit_entries),
            "checks": len(checks),
            "derivations": len(derivations),
        },
        "output_counts": output_counts,
        "converted": {"checks": len(conditions)},
        "omitted": omitted,
        "omitted_check_reasons": dict(omitted_check_reasons.most_common()),
        "warnings": warnings,
        "valid": True,
    }
    return ConversionResult(document=document, report=report)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert Medidata Rave ALS SpreadsheetML to Aurinara ODM 2.0 JSON"
    )
    parser.add_argument("input", type=Path, help="Rave Architect Loader .xls XML workbook")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="ODM JSON destination (default: <input>.odm2.json)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Conversion report destination (default: <output>.report.json)",
    )
    parser.add_argument(
        "--matrix",
        default="AUTO",
        help="Rave matrix OID to use; AUTO prefers MASTER then CRFDraft.DefaultMatrixOID",
    )
    parser.add_argument("--study-name", help="Override studyName")
    parser.add_argument("--protocol-name", help="Override protocolName")
    parser.add_argument("--version-name", help="Override metadata version name (max 20 chars)")
    parser.add_argument(
        "--unresolved-rules",
        choices=("error", "omit"),
        default="error",
        help=(
            "Fail closed by default; 'omit' retains safely converted checks, excludes only "
            "unsupported checks/derivations, and reports them"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    input_path = args.input.resolve()
    if not input_path.is_file():
        sys.stderr.write(f"error: input file does not exist: {input_path}\n")
        return 2
    output_path = args.output.resolve() if args.output else input_path.with_suffix(".odm2.json")
    report_path = (
        args.report.resolve()
        if args.report
        else output_path.with_name(f"{output_path.stem}.report.json")
    )
    try:
        result = convert_workbook(
            input_path,
            matrix=args.matrix,
            unresolved_rules=args.unresolved_rules,
            study_name=args.study_name,
            protocol_name=args.protocol_name,
            version_name=args.version_name,
        )
    except ConversionError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_path.write_text(
        json.dumps(result.report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    sys.stdout.write(f"ODM JSON: {output_path}\n")
    sys.stdout.write(f"Report:   {report_path}\n")
    sys.stdout.write(
        "Counts:   " + json.dumps(result.report["output_counts"], sort_keys=True) + "\n"
    )
    for warning in result.report["warnings"]:
        sys.stderr.write(f"warning: {warning}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
