"""Build metadata-driven, form-owned raw datasets for clinical exports."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.edit_check_dsl import evaluate_rule
from app.models.designer.edit_check import ValidationResult
from app.models.designer.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.designer.raw_data_variable_setting import RawDataVariableSetting
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.edc.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.edc.form_record import FormRecord
from app.models.edc.lock import FreezeLock
from app.models.edc.query import Query, QueryStatus, QueryTargetType
from app.models.edc.subject import Subject
from app.models.shared.export import Export
from app.models.shared.identity import Permission, Role, RolePermission, UserRole
from app.schemas.designer.raw_data_variable_setting import RawDatasetVariableResponse
from app.services.designer.raw_data_variable_service import raw_data_variable_service
from app.services.edc.data_capture_service import data_capture_service
from app.services.edc.operational_service import edc_operational_service


@dataclass
class RawDatasetTable:
    name: str
    columns: list[RawDatasetVariableResponse] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    subject_keys: list[str] = field(default_factory=list, repr=False)
    design_version_ids: list[str] = field(default_factory=list)
    form_definition_ids: list[str] = field(default_factory=list)
    schema_conflicts: list[dict[str, str]] = field(default_factory=list)


@dataclass
class RawDatasetPackage:
    study_id: str
    generated_at: str
    datasets: list[RawDatasetTable]

    def manifest(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "generated_at": self.generated_at,
            "dataset_count": len(self.datasets),
            "datasets": [
                {
                    "name": table.name,
                    "row_count": len(table.rows),
                    "design_version_ids": table.design_version_ids,
                    "form_definition_ids": table.form_definition_ids,
                    "schema_conflicts": table.schema_conflicts,
                    "variables": [column.model_dump(mode="json") for column in table.columns],
                }
                for table in self.datasets
            ],
        }


def _filter_uuid(filters: dict[str, Any], *keys: str) -> UUID | None:
    for key in keys:
        value = filters.get(key)
        if value:
            return UUID(str(value))
    return None


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _utc_text(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc_datetime(value: datetime) -> datetime:
    """Normalize database timestamps before ordering them.

    SQLite-backed tests and legacy rows can return naive values while PostgreSQL
    returns aware values. Treat naive database timestamps as UTC, matching the
    platform timestamp contract.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return _utc_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _decoded_value(field_value: FieldValue) -> Any:
    return data_capture_service._deserialize_value(field_value.value)


def _record_value(record: FormRecord | None, field: FieldDefinition) -> Any:
    if record is None or not record.data_jsonb:
        return None
    values = record.data_jsonb
    return values.get(str(field.id), values.get(field.variable_name))


def _codelist_label(field: FieldDefinition, value: Any) -> str:
    if value in (None, "") or field.codelist is None:
        return ""
    labels = {str(item.code): item.label for item in field.codelist.items}
    if isinstance(value, list):
        return _stringify([labels.get(str(item), str(item)) for item in value])
    return str(labels.get(str(value), value))


def _numeric_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ""
    return format(number, "f")


def _date_component(value: Any, component: str) -> str:
    if value in (None, ""):
        return ""
    match = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", str(value))
    if match is None:
        return ""
    parts = {"date_year": match.group(1), "date_month": match.group(2), "date_day": match.group(3)}
    return parts.get(component) or ""


class RawDatasetExportService:
    async def build_package(self, session: AsyncSession, export: Export) -> RawDatasetPackage:
        filters = dict(export.filters or {})
        role_names, authorized_site_ids = await self._requester_scope(session, export)
        selected_names = {
            str(name).casefold() for name in (filters.get("datasets") or []) if str(name).strip()
        }
        legacy_dataset = str(filters.get("dataset") or "").strip()
        if legacy_dataset and legacy_dataset.casefold() not in {"all", "clinical"}:
            selected_names.add(legacy_dataset.casefold())

        definitions_list = await self._load_definitions(session, export.study_id)
        form_id = _filter_uuid(filters, "form_definition_id", "form_id")
        requested_domain = str(filters.get("domain") or "").casefold()
        definitions_list = [
            definition
            for definition in definitions_list
            if not selected_names
            or (definition.domain or definition.form_code).casefold() in selected_names
        ]
        if form_id:
            definitions_list = [item for item in definitions_list if item.id == form_id]
        if requested_domain:
            definitions_list = [
                item
                for item in definitions_list
                if (item.domain or item.form_code).casefold() == requested_domain
                or item.form_code.casefold() == requested_domain
            ]
        definitions = {item.id: item for item in definitions_list}
        readable_by_definition: dict[UUID, dict[UUID, FieldDefinition]] = {}
        for definition_id, definition in definitions.items():
            candidate_fields = [
                field
                for section in definition.sections
                if section.output_to_dataset and not section.is_label_only
                for field in section.fields
                if field.control_type != "label"
            ]
            readable = await edc_operational_service.readable_fields(
                session, definition, candidate_fields, role_names
            )
            if readable:
                readable_by_definition[definition_id] = {field.id: field for field in readable}

        definitions = {
            definition_id: definition
            for definition_id, definition in definitions.items()
            if definition_id in readable_by_definition
        }
        definition_ids = set(definitions)

        forms = await self._load_forms(session, export, filters, authorized_site_ids)
        forms = [item for item in forms if item.form_definition_id in definition_ids]

        version_ids = {definition.study_version_id for definition in definitions.values()}
        settings = list(
            (
                await session.execute(
                    select(RawDataVariableSetting).where(
                        RawDataVariableSetting.design_version_id.in_(version_ids),
                        RawDataVariableSetting.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        settings_by_field = {
            setting.field_definition_id: setting
            for setting in settings
            if setting.field_definition_id is not None
        }
        records: list[FormRecord] = []
        if forms:
            records = list(
                (
                    await session.execute(
                        select(FormRecord)
                        .where(
                            FormRecord.form_instance_id.in_([item.id for item in forms]),
                            FormRecord.deleted_at.is_(None),
                        )
                        .order_by(FormRecord.form_instance_id, FormRecord.sequence_number)
                    )
                )
                .scalars()
                .all()
            )
        records_by_form: dict[UUID, list[FormRecord]] = defaultdict(list)
        for record in records:
            records_by_form[record.form_instance_id].append(record)

        tables: dict[str, RawDatasetTable] = {}
        schemas_by_definition: dict[UUID, list[RawDatasetVariableResponse]] = {}
        for definition_id, definition in definitions.items():
            schema = raw_data_variable_service.build_form_dataset_definition(
                definition, settings_by_field
            )
            readable_ids = set(readable_by_definition[definition_id])
            columns = [
                column
                for column in schema.variables
                if column.field_definition_id is None or column.field_definition_id in readable_ids
            ]
            schemas_by_definition[definition_id] = columns
            key = schema.dataset_name.casefold()
            table = tables.setdefault(key, RawDatasetTable(name=schema.dataset_name))
            version_id = str(definition.study_version_id)
            if version_id not in table.design_version_ids:
                table.design_version_ids.append(version_id)
            table.form_definition_ids.append(str(definition.id))
            existing = {column.name: column for column in table.columns}
            for column in columns:
                previous = existing.get(column.name)
                if previous is None:
                    table.columns.append(column)
                    existing[column.name] = column
                elif previous.data_type != column.data_type:
                    conflict = {
                        "variable": column.name,
                        "existing_type": previous.data_type,
                        "additional_type": column.data_type,
                        "design_version_id": version_id,
                    }
                    if conflict not in table.schema_conflicts:
                        table.schema_conflicts.append(conflict)

        visit_instances = {
            item.visit_instance.id: item.visit_instance
            for item in forms
            if item.visit_instance is not None
        }
        visit_numbers: dict[UUID, int] = {}
        visits_by_subject_and_definition: dict[tuple[UUID, str], list[Any]] = defaultdict(list)
        for visit in visit_instances.values():
            definition_key = str(visit.visit_definition_id or visit.name)
            visits_by_subject_and_definition[(visit.subject_id, definition_key)].append(visit)
        for visits in visits_by_subject_and_definition.values():
            for index, visit in enumerate(
                sorted(visits, key=lambda item: (item.created_at, str(item.id))), 1
            ):
                visit_numbers[visit.id] = index

        form_numbers: dict[UUID, int] = {}
        forms_by_occurrence: dict[tuple[UUID, UUID | None, str], list[FormInstance]] = defaultdict(
            list
        )
        for item in forms:
            dataset_name = item.form_definition.domain or item.form_definition.form_code
            forms_by_occurrence[
                (item.subject_id, item.visit_instance_id, dataset_name.casefold())
            ].append(item)
        for occurrences in forms_by_occurrence.values():
            for index, item in enumerate(
                sorted(occurrences, key=lambda value: (value.created_at, str(value.id))), 1
            ):
                form_numbers[item.id] = index

        for item in sorted(forms, key=lambda value: (value.created_at, str(value.id))):
            definition = item.form_definition
            table = tables[(definition.domain or definition.form_code).casefold()]
            field_map = readable_by_definition[item.form_definition_id]
            base_values = {
                value.field_definition_id: _decoded_value(value)
                for value in item.field_values
                if value.field_definition_id in field_map
            }
            row_records: list[FormRecord | None] = records_by_form.get(item.id, []) or [None]
            for record in row_records:
                values = dict(base_values)
                if record is not None:
                    for field_id, field_definition in field_map.items():
                        record_value = _record_value(record, field_definition)
                        if record_value is not None:
                            values[field_id] = record_value
                visibility_context = {
                    field_map[field_id].variable_name: value for field_id, value in values.items()
                }
                row = self._base_row(item, record, visit_numbers, form_numbers, values)
                for column in schemas_by_definition[item.form_definition_id]:
                    if column.field_definition_id is None:
                        continue
                    field_definition = field_map.get(column.field_definition_id)
                    if field_definition is None:
                        continue
                    if field_definition.visibility_rule and not evaluate_rule(
                        field_definition.visibility_rule, visibility_context
                    ):
                        continue
                    value = values.get(field_definition.id)
                    if column.source == "field":
                        row[column.name] = _stringify(value)
                    elif column.source == "codelist_companion":
                        row[column.name] = _codelist_label(field_definition, value)
                    elif column.source == "numeric_companion":
                        row[column.name] = _numeric_value(value)
                    elif column.source.startswith("date_"):
                        row[column.name] = _date_component(value, column.source)
                table.rows.append(
                    {column.name: row.get(column.name, "") for column in table.columns}
                )
                table.subject_keys.append(str(item.subject_id))

        return RawDatasetPackage(
            study_id=str(export.study_id),
            generated_at=_utc_text(datetime.now(UTC)),
            datasets=list(tables.values()),
        )

    async def _load_definitions(
        self, session: AsyncSession, study_id: UUID
    ) -> list[FormDefinition]:
        result = await session.execute(
            select(FormDefinition)
            .join(StudyVersion, StudyVersion.id == FormDefinition.study_version_id)
            .where(
                StudyVersion.study_id == study_id,
                StudyVersion.status == StudyVersionStatus.published.value,
            )
            .options(
                selectinload(FormDefinition.sections)
                .selectinload(FormSection.fields)
                .selectinload(FieldDefinition.codelist)
            )
            .order_by(
                StudyVersion.created_at,
                StudyVersion.version_number,
                FormDefinition.display_order,
                FormDefinition.id,
            )
        )
        return list(result.scalars().unique().all())

    async def _requester_scope(
        self, session: AsyncSession, export: Export
    ) -> tuple[set[str], set[UUID] | None]:
        active_role = or_(Role.platform_managed.is_(False), Role.platform_status == "active")
        role_names = set(
            (
                await session.execute(
                    select(Role.name)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(
                        UserRole.user_id == export.requested_by,
                        or_(UserRole.study_id.is_(None), UserRole.study_id == export.study_id),
                        active_role,
                    )
                )
            )
            .scalars()
            .all()
        )
        grants = list(
            (
                await session.execute(
                    select(UserRole.study_id, UserRole.site_id)
                    .join(Role, Role.id == UserRole.role_id)
                    .join(RolePermission, RolePermission.role_id == Role.id)
                    .join(Permission, Permission.id == RolePermission.permission_id)
                    .where(
                        UserRole.user_id == export.requested_by,
                        Permission.code == "data.export",
                        or_(UserRole.study_id.is_(None), UserRole.study_id == export.study_id),
                        active_role,
                    )
                )
            ).all()
        )
        if any(site_id is None for _, site_id in grants):
            return role_names, None
        return role_names, {site_id for _, site_id in grants if site_id is not None}

    async def _load_forms(
        self,
        session: AsyncSession,
        export: Export,
        filters: dict[str, Any],
        authorized_site_ids: set[UUID] | None,
    ) -> list[FormInstance]:
        conditions: list[Any] = [
            Subject.study_id == export.study_id,
            FormInstance.data_entry_status == FormInstanceStatus.submitted.value,
        ]
        if authorized_site_ids is not None:
            conditions.append(Subject.site_id.in_(authorized_site_ids))
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
            domain = str(filters["domain"])
            conditions.append(
                or_(FormDefinition.domain == domain, FormDefinition.form_code == domain)
            )
        if filters.get("date_from"):
            conditions.append(FormInstance.created_at >= _as_datetime(filters["date_from"]))
        if filters.get("date_to"):
            conditions.append(FormInstance.created_at <= _as_datetime(filters["date_to"]))
        if filters.get("changed_since"):
            conditions.append(FormInstance.updated_at >= _as_datetime(filters["changed_since"]))
        if filters.get("locked_only"):
            conditions.append(
                exists(
                    select(FreezeLock.id).where(
                        FreezeLock.is_active.is_(True),
                        FreezeLock.lock_type == "lock",
                        or_(
                            (FreezeLock.object_type == "form")
                            & (FreezeLock.object_id == FormInstance.id),
                            (FreezeLock.object_type == "visit")
                            & (FreezeLock.object_id == FormInstance.visit_instance_id),
                            (FreezeLock.object_type == "subject")
                            & (FreezeLock.object_id == FormInstance.subject_id),
                            (FreezeLock.object_type == "site")
                            & (FreezeLock.object_id == Subject.site_id),
                            (FreezeLock.object_type == "study")
                            & (FreezeLock.object_id == Subject.study_id),
                        ),
                    )
                )
            )
        if filters.get("clean_only"):
            active_query = exists(
                select(Query.id).where(
                    Query.status.in_(
                        [
                            QueryStatus.open.value,
                            QueryStatus.answered.value,
                            QueryStatus.reopened.value,
                        ]
                    ),
                    or_(
                        (Query.target_type == QueryTargetType.form_instance.value)
                        & (Query.target_id == FormInstance.id),
                        (Query.target_type == QueryTargetType.subject.value)
                        & (Query.target_id == FormInstance.subject_id),
                        (Query.target_type == QueryTargetType.visit_instance.value)
                        & (Query.target_id == FormInstance.visit_instance_id),
                        (Query.target_type == QueryTargetType.field.value)
                        & Query.target_id.in_(
                            select(FieldValue.id).where(
                                FieldValue.form_instance_id == FormInstance.id
                            )
                        ),
                        (Query.target_type == QueryTargetType.form_record.value)
                        & Query.target_id.in_(
                            select(FormRecord.id).where(
                                FormRecord.form_instance_id == FormInstance.id,
                                FormRecord.deleted_at.is_(None),
                            )
                        ),
                    ),
                )
            )
            active_finding = exists(
                select(ValidationResult.id).where(
                    ValidationResult.form_instance_id == FormInstance.id,
                    ValidationResult.is_resolved.is_(False),
                    ValidationResult.severity.in_(("error", "query")),
                )
            )
            conditions.extend([~active_query, ~active_finding])

        result = await session.execute(
            select(FormInstance)
            .join(Subject, Subject.id == FormInstance.subject_id)
            .join(FormDefinition, FormDefinition.id == FormInstance.form_definition_id)
            .where(and_(*conditions))
            .options(
                selectinload(FormInstance.subject).selectinload(Subject.site),
                selectinload(FormInstance.subject).selectinload(Subject.study),
                selectinload(FormInstance.visit_instance),
                selectinload(FormInstance.field_values)
                .selectinload(FieldValue.field_definition)
                .selectinload(FieldDefinition.codelist),
                selectinload(FormInstance.form_definition)
                .selectinload(FormDefinition.sections)
                .selectinload(FormSection.fields)
                .selectinload(FieldDefinition.codelist),
            )
            .order_by(FormInstance.created_at, FormInstance.id)
        )
        return list(result.scalars().unique().all())

    @staticmethod
    def _base_row(
        form: FormInstance,
        record: FormRecord | None,
        visit_numbers: dict[UUID, int],
        form_numbers: dict[UUID, int],
        values: dict[UUID, Any],
    ) -> dict[str, str]:
        del values
        subject = form.subject
        study = subject.study
        visit = form.visit_instance
        timestamps = [_utc_datetime(form.updated_at or form.created_at)]
        timestamps.extend(
            _utc_datetime(value.updated_at or value.created_at) for value in form.field_values
        )
        if record is not None:
            timestamps.append(_utc_datetime(record.updated_at or record.created_at))
        latest = max(timestamps)
        actor_candidates = [
            (_utc_datetime(value.updated_at or value.created_at), value.updated_by)
            for value in form.field_values
            if value.updated_by is not None
        ]
        if form.submitted_by is not None:
            actor_candidates.append(
                (_utc_datetime(form.submitted_at or form.created_at), form.submitted_by)
            )
        actor = max(actor_candidates, default=(latest, None), key=lambda item: item[0])[1]
        return {
            "PROTOCOL": str(study.protocol_number or study.study_code),
            "SITE": str(subject.site.site_number),
            "SUBJID": f"{subject.site.site_number}{subject.subject_number}",
            "SUBJINIT": "",
            "VISIT": str(visit.name) if visit is not None else "",
            "FORM": str(form.form_definition.form_code),
            "PROCEDUR": "",
            "VISITINS": str(visit_numbers.get(visit.id, 1)) if visit is not None else "1",
            "FORMINS": str(form_numbers.get(form.id, 1)),
            "GROUPINS": str(record.sequence_number if record is not None else 1),
            "LRMODDTS": _utc_text(latest),
            "ERMODDDTS": _utc_text(latest),
            "LRMODBY": str(actor) if actor is not None else "",
        }


raw_dataset_export_service = RawDatasetExportService()

__all__ = [
    "RawDatasetExportService",
    "RawDatasetPackage",
    "RawDatasetTable",
    "raw_dataset_export_service",
]
