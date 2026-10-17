"""Raw_Data_Variable_Service — authoring of Raw_Data_Variable_Settings.

Owns creation of design-time ``Raw_Data_Variable_Setting`` records within a
``Draft_Design``. Each setting records a captured variable's name, data type,
and a free-form attributes bag, and binds to exactly one ``Design_Version``.

Satisfies Requirements:
  - 4.7: Persist a raw-data variable setting (name, type, attributes) per
         captured item within a design version, bound to exactly one
         Design_Version, with an audit event.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ValidationError
from app.models.designer.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.designer.raw_data_variable_setting import RawDataVariableSetting
from app.schemas.designer.raw_data_variable_setting import (
    RawDatasetDefinitionResponse,
    RawDatasetVariableResponse,
)

logger = logging.getLogger(__name__)

_NAME_MIN_LENGTH = 1
_NAME_MAX_LENGTH = 255
_DATA_TYPE_MIN_LENGTH = 1
_DATA_TYPE_MAX_LENGTH = 50
_SUFFIX_PATTERN = re.compile(r"^_?[A-Za-z][A-Za-z0-9_]*$")

FIXED_DATASET_VARIABLES: tuple[tuple[str, str, str], ...] = (
    ("PROTOCOL", "string", "Protocol"),
    ("SITE", "string", "Site"),
    ("SUBJID", "string", "Subject identifier"),
    ("SUBJINIT", "string", "Subject initials"),
    ("VISIT", "string", "Visit"),
    ("FORM", "string", "Form"),
    ("PROCEDUR", "string", "Procedure"),
    ("VISITINS", "integer", "Visit instance"),
    ("FORMINS", "integer", "Form instance"),
    ("GROUPINS", "integer", "Group instance"),
    ("LRMODDTS", "datetime", "Last record modification date/time"),
    ("ERMODDDTS", "datetime", "EDC record modification date/time"),
    ("LRMODBY", "string", "Last record modified by"),
)

_CODELIST_CONTROLS = frozenset(
    {"dropdown", "listbox", "radio", "checkbox", "multi-select", "coded_term"}
)
_NUMERIC_CONTROLS = frozenset({"integer", "decimal", "float", "slider"})
_NUMERIC_TYPES = frozenset({"integer", "decimal", "float", "number", "numeric"})
_DATE_CONTROLS = frozenset({"date"})


def _field_generation_kind(field: FieldDefinition) -> str | None:
    if field.codelist_id is not None or field.control_type in _CODELIST_CONTROLS:
        return "codelist"
    if field.control_type in _DATE_CONTROLS or field.data_type.lower() == "date":
        return "date"
    if field.control_type in _NUMERIC_CONTROLS or field.data_type.lower() in _NUMERIC_TYPES:
        return "numeric"
    return None


def _variable_with_suffix(variable_name: str, suffix: str) -> str:
    return f"{variable_name}_{suffix.strip().lstrip('_')}"


def _normalize_suffix(value: str | None, *, default: str | None = None) -> str | None:
    normalized = value.strip() if value is not None else default
    if not normalized:
        normalized = default
    if normalized is not None and not _SUFFIX_PATTERN.fullmatch(normalized):
        raise ValidationError(
            "Raw-data variable suffix must contain only letters, numbers, and underscores",
            details={"field": "suffix", "value": normalized},
        )
    return normalized


class RawDataVariableService:
    """Creates and validates Raw_Data_Variable_Settings for a Draft_Design."""

    async def create_variable_setting(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        name: str,
        data_type: str,
        attributes: dict[str, Any] | None = None,
        label: str | None = None,
        suffix: str | None = None,
        actor_id: UUID | None = None,
    ) -> RawDataVariableSetting:
        """Persist a Raw_Data_Variable_Setting within one Design_Version.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version (R4.7).
            name: The variable name; 1-255 characters.
            data_type: The variable data type; 1-50 characters.
            attributes: Optional free-form, type-specific metadata.
            label: Optional display label for a fixed variable.
            suffix: Optional suffix applied for special variable types.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted RawDataVariableSetting.

        Raises:
            ValidationError: If the name or data type length is out of range.
        """
        normalized_name = name.strip()
        if not (_NAME_MIN_LENGTH <= len(normalized_name) <= _NAME_MAX_LENGTH):
            raise ValidationError(
                "Raw-data variable name must be 1 to 255 characters",
                details={"field": "name"},
            )
        normalized_data_type = data_type.strip()
        if not (_DATA_TYPE_MIN_LENGTH <= len(normalized_data_type) <= _DATA_TYPE_MAX_LENGTH):
            raise ValidationError(
                "Raw-data variable data type must be 1 to 50 characters",
                details={"field": "data_type"},
            )

        normalized_label = label.strip() if label is not None else None
        if normalized_label == "":
            normalized_label = None
        normalized_suffix = _normalize_suffix(suffix)

        setting = RawDataVariableSetting(
            design_version_id=design_version_id,
            name=normalized_name,
            data_type=normalized_data_type,
            attributes=attributes or {},
            label=normalized_label,
            suffix=normalized_suffix,
        )
        session.add(setting)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="raw_data_variable_setting",
            entity_id=setting.id,
            action="create",
            module=Module.DESIGNER,
            new_value=(
                f"name={normalized_name}; data_type={normalized_data_type}; "
                f"label={normalized_label}; suffix={normalized_suffix}"
            ),
            actor_id=actor_id,
        )

        logger.info(
            "Raw-data variable setting created: id=%s design_version_id=%s name=%r",
            setting.id,
            design_version_id,
            normalized_name,
        )
        return setting

    async def list_variable_settings(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[RawDataVariableSetting]:
        """List live variable settings for a draft or published design."""
        result = await session.execute(
            select(RawDataVariableSetting)
            .where(
                RawDataVariableSetting.design_version_id == design_version_id,
                RawDataVariableSetting.deleted_at.is_(None),
            )
            .order_by(RawDataVariableSetting.name, RawDataVariableSetting.id)
        )
        return list(result.scalars().all())

    async def configure_field_setting(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        field_definition_id: UUID,
        suffix: str | None = None,
        year_suffix: str | None = None,
        month_suffix: str | None = None,
        day_suffix: str | None = None,
        actor_id: UUID | None = None,
    ) -> RawDataVariableSetting:
        """Create or update the generated-variable suffixes for one form field."""
        field_result = await session.execute(
            select(FieldDefinition)
            .join(FormSection, FieldDefinition.form_section_id == FormSection.id)
            .join(FormDefinition, FormSection.form_definition_id == FormDefinition.id)
            .where(
                FieldDefinition.id == field_definition_id,
                FormDefinition.study_version_id == design_version_id,
            )
        )
        field = field_result.scalars().first()
        if field is None:
            raise ValidationError(
                "Raw-data field must belong to the selected design version",
                details={"field_definition_id": str(field_definition_id)},
            )

        generation_kind = _field_generation_kind(field)
        if generation_kind is None:
            raise ValidationError(
                "Only codelist, numeric, and date fields have companion variable settings",
                details={"field_definition_id": str(field_definition_id)},
            )

        normalized_suffix = None
        normalized_year_suffix = None
        normalized_month_suffix = None
        normalized_day_suffix = None
        if generation_kind == "codelist":
            normalized_suffix = _normalize_suffix(suffix, default="LABEL")
        elif generation_kind == "numeric":
            normalized_suffix = _normalize_suffix(suffix, default="NUM")
        else:
            normalized_year_suffix = _normalize_suffix(year_suffix, default="YEAR")
            normalized_month_suffix = _normalize_suffix(month_suffix, default="MONTH")
            normalized_day_suffix = _normalize_suffix(day_suffix, default="DAY")

        setting_result = await session.execute(
            select(RawDataVariableSetting).where(
                RawDataVariableSetting.field_definition_id == field_definition_id,
                RawDataVariableSetting.deleted_at.is_(None),
            )
        )
        setting = setting_result.scalars().first()
        action = "update" if setting is not None else "create"
        if setting is None:
            setting = RawDataVariableSetting(
                design_version_id=design_version_id,
                field_definition_id=field.id,
                name=field.variable_name,
                data_type=field.data_type,
                attributes={"generation_kind": generation_kind},
            )
            session.add(setting)

        setting.name = field.variable_name
        setting.data_type = field.data_type
        setting.label = field.label
        setting.suffix = normalized_suffix
        setting.year_suffix = normalized_year_suffix
        setting.month_suffix = normalized_month_suffix
        setting.day_suffix = normalized_day_suffix
        setting.updated_at = datetime.now(UTC)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="raw_data_variable_setting",
            entity_id=setting.id,
            action=action,
            module=Module.DESIGNER,
            actor_id=actor_id,
            new_value=(
                f"field_definition_id={field.id}; suffix={normalized_suffix}; "
                f"year_suffix={normalized_year_suffix}; "
                f"month_suffix={normalized_month_suffix}; day_suffix={normalized_day_suffix}"
            ),
        )
        return setting

    async def build_dataset_definitions(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[RawDatasetDefinitionResponse]:
        """Generate one raw-data variable schema for every form in a design."""
        form_result = await session.execute(
            select(FormDefinition)
            .where(FormDefinition.study_version_id == design_version_id)
            .options(selectinload(FormDefinition.sections).selectinload(FormSection.fields))
            .execution_options(populate_existing=True)
            .order_by(FormDefinition.display_order, FormDefinition.id)
        )
        forms = list(form_result.scalars().all())
        settings = await self.list_variable_settings(session, design_version_id)
        settings_by_field = {
            setting.field_definition_id: setting
            for setting in settings
            if setting.field_definition_id is not None
        }

        datasets: list[RawDatasetDefinitionResponse] = []
        for form in forms:
            datasets.append(self.build_form_dataset_definition(form, settings_by_field))
        return datasets

    @staticmethod
    def build_form_dataset_definition(
        form: FormDefinition,
        settings_by_field: dict[UUID, RawDataVariableSetting],
    ) -> RawDatasetDefinitionResponse:
        """Build the authoritative raw dataset schema for one form definition."""
        variables = [
            RawDatasetVariableResponse(
                name=name,
                data_type=data_type,
                label=label,
                source="fixed",
            )
            for name, data_type, label in FIXED_DATASET_VARIABLES
        ]
        for section in sorted(form.sections, key=lambda item: item.display_order):
            if section.is_label_only or not section.output_to_dataset:
                continue
            for field in sorted(section.fields, key=lambda item: item.display_order):
                if field.control_type == "label":
                    continue
                variables.append(
                    RawDatasetVariableResponse(
                        name=field.variable_name,
                        data_type=field.data_type,
                        label=field.label,
                        source="field",
                        field_definition_id=field.id,
                    )
                )
                kind = _field_generation_kind(field)
                setting = settings_by_field.get(field.id)
                if kind in {"codelist", "numeric"}:
                    default_suffix = "LABEL" if kind == "codelist" else "NUM"
                    companion_suffix = (
                        setting.suffix if setting and setting.suffix else default_suffix
                    )
                    variables.append(
                        RawDatasetVariableResponse(
                            name=_variable_with_suffix(field.variable_name, companion_suffix),
                            data_type="string" if kind == "codelist" else "decimal",
                            label=f"{field.label} ({kind})",
                            source=f"{kind}_companion",
                            field_definition_id=field.id,
                        )
                    )
                elif kind == "date":
                    date_suffixes = (
                        (setting.year_suffix if setting else None) or "YEAR",
                        (setting.month_suffix if setting else None) or "MONTH",
                        (setting.day_suffix if setting else None) or "DAY",
                    )
                    for component, component_suffix in zip(
                        ("year", "month", "day"), date_suffixes, strict=True
                    ):
                        variables.append(
                            RawDatasetVariableResponse(
                                name=_variable_with_suffix(field.variable_name, component_suffix),
                                data_type="integer",
                                label=f"{field.label} ({component})",
                                source=f"date_{component}",
                                field_definition_id=field.id,
                            )
                        )
        return RawDatasetDefinitionResponse(
            form_definition_id=form.id,
            form_code=form.form_code,
            dataset_name=form.domain or form.form_code,
            variables=variables,
        )


# Module-level singleton for convenience
raw_data_variable_service = RawDataVariableService()
