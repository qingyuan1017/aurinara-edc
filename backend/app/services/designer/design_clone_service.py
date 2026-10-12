"""Transactional deep-copy support for study-design amendments."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.designer.arm_definition import ArmDefinition
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.coding_setting import CodingSetting
from app.models.designer.crf_access_definition import CrfAccessDefinition
from app.models.designer.edit_check import EditCheck
from app.models.designer.form_dependency import FormDefinitionDependency
from app.models.designer.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.designer.raw_data_variable_setting import RawDataVariableSetting
from app.models.designer.schedule_of_assessment import ScheduleOfAssessment
from app.models.designer.subject_phase_definition import (
    SubjectPhaseDefinition,
    SubjectPhaseVisitDefinition,
)
from app.models.designer.subject_phase_transition import SubjectPhaseTransition
from app.models.designer.visit import VisitDefinition
from app.models.designer.visit_dependency import VisitDefinitionDependency

ModelT = TypeVar("ModelT")


def _copy_row(row: ModelT, /, **overrides: Any) -> ModelT:
    """Copy persisted scalar columns while regenerating identity and timestamps."""

    excluded = {"id", "created_at", "updated_at", "deleted_at", *overrides.keys()}
    values = {
        column.name: deepcopy(getattr(row, column.name))
        for column in row.__table__.columns  # type: ignore[attr-defined]
        if column.name not in excluded
    }
    return type(row)(**values, **overrides)


def _remap_field_references(value: Any, field_map: Mapping[UUID, FieldDefinition]) -> Any:
    """Remap UUID field references inside the declarative edit-check DSL."""

    if isinstance(value, Mapping):
        remapped: dict[Any, Any] = {}
        for key, child in value.items():
            if key in {"field", "value_field"} and isinstance(child, str):
                try:
                    source_id = UUID(child)
                except ValueError:
                    remapped[key] = child
                else:
                    target = field_map.get(source_id)
                    remapped[key] = str(target.id) if target is not None else child
            else:
                remapped[key] = _remap_field_references(child, field_map)
        return remapped
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_remap_field_references(child, field_map) for child in value]
    return deepcopy(value)


class DesignCloneService:
    """Clone the complete live Designer graph into a new draft version."""

    async def clone_version(
        self,
        session: AsyncSession,
        *,
        source_version_id: UUID,
        target_version_id: UUID,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}

        codelists = await self._version_rows(
            session, Codelist, Codelist.study_version_id, source_version_id
        )
        codelist_map: dict[UUID, Codelist] = {}
        for source in codelists:
            clone = _copy_row(source, study_version_id=target_version_id)
            session.add(clone)
            codelist_map[source.id] = clone
        await session.flush()
        counts["codelists"] = len(codelist_map)

        codelist_items = await self._rows_for_ids(
            session, CodelistItem, CodelistItem.codelist_id, set(codelist_map)
        )
        for source in codelist_items:
            session.add(_copy_row(source, codelist_id=codelist_map[source.codelist_id].id))
        counts["codelist_items"] = len(codelist_items)

        visits = await self._version_rows(
            session, VisitDefinition, VisitDefinition.study_version_id, source_version_id
        )
        visit_map: dict[UUID, VisitDefinition] = {}
        for source in visits:
            clone = _copy_row(
                source,
                study_version_id=target_version_id,
                parent_folder_id=None,
            )
            session.add(clone)
            visit_map[source.id] = clone
        await session.flush()
        for source in visits:
            if source.parent_folder_id in visit_map:
                visit_map[source.id].parent_folder_id = visit_map[source.parent_folder_id].id
        counts["visits"] = len(visit_map)

        forms = await self._version_rows(
            session, FormDefinition, FormDefinition.study_version_id, source_version_id
        )
        form_map: dict[UUID, FormDefinition] = {}
        for source in forms:
            clone = _copy_row(source, study_version_id=target_version_id)
            session.add(clone)
            form_map[source.id] = clone
        await session.flush()
        counts["forms"] = len(form_map)

        sections = await self._rows_for_ids(
            session, FormSection, FormSection.form_definition_id, set(form_map)
        )
        section_map: dict[UUID, FormSection] = {}
        for source in sections:
            clone = _copy_row(source, form_definition_id=form_map[source.form_definition_id].id)
            session.add(clone)
            section_map[source.id] = clone
        await session.flush()
        counts["sections"] = len(section_map)

        fields = await self._rows_for_ids(
            session, FieldDefinition, FieldDefinition.form_section_id, set(section_map)
        )
        field_map: dict[UUID, FieldDefinition] = {}
        for source in fields:
            mapped_codelist_id = (
                codelist_map[source.codelist_id].id
                if source.codelist_id in codelist_map
                else source.codelist_id
            )
            clone = _copy_row(
                source,
                form_section_id=section_map[source.form_section_id].id,
                codelist_id=mapped_codelist_id,
            )
            session.add(clone)
            field_map[source.id] = clone
        await session.flush()
        counts["fields"] = len(field_map)

        form_dependencies = await self._rows_for_ids(
            session,
            FormDefinitionDependency,
            FormDefinitionDependency.form_definition_id,
            set(form_map),
        )
        for source in form_dependencies:
            session.add(
                _copy_row(
                    source,
                    form_definition_id=form_map[source.form_definition_id].id,
                    depends_on_form_definition_id=(
                        form_map[source.depends_on_form_definition_id].id
                        if source.depends_on_form_definition_id in form_map
                        else source.depends_on_form_definition_id
                    ),
                )
            )
        counts["form_dependencies"] = len(form_dependencies)

        visit_dependencies = await self._rows_for_ids(
            session,
            VisitDefinitionDependency,
            VisitDefinitionDependency.visit_definition_id,
            set(visit_map),
        )
        for source in visit_dependencies:
            session.add(
                _copy_row(
                    source,
                    visit_definition_id=visit_map[source.visit_definition_id].id,
                    depends_on_visit_definition_id=(
                        visit_map[source.depends_on_visit_definition_id].id
                        if source.depends_on_visit_definition_id in visit_map
                        else source.depends_on_visit_definition_id
                    ),
                )
            )
        counts["visit_dependencies"] = len(visit_dependencies)

        phases = await self._version_rows(
            session,
            SubjectPhaseDefinition,
            SubjectPhaseDefinition.design_version_id,
            source_version_id,
            live_only=True,
        )
        phase_map: dict[UUID, SubjectPhaseDefinition] = {}
        for source in phases:
            clone = _copy_row(source, design_version_id=target_version_id)
            session.add(clone)
            phase_map[source.id] = clone
        await session.flush()
        counts["subject_phases"] = len(phase_map)

        phase_visits = list(
            (
                await session.execute(
                    select(SubjectPhaseVisitDefinition)
                    .where(SubjectPhaseVisitDefinition.subject_phase_definition_id.in_(phase_map))
                    .order_by(
                        SubjectPhaseVisitDefinition.subject_phase_definition_id,
                        SubjectPhaseVisitDefinition.display_order,
                    )
                )
            )
            .scalars()
            .all()
        )
        for source in phase_visits:
            target_phase = phase_map.get(source.subject_phase_definition_id)
            target_visit = visit_map.get(source.visit_definition_id)
            if target_phase is None or target_visit is None:
                continue
            session.add(
                SubjectPhaseVisitDefinition(
                    subject_phase_definition_id=target_phase.id,
                    visit_definition_id=target_visit.id,
                    display_order=source.display_order,
                )
            )
        counts["subject_phase_visits"] = len(phase_visits)

        transitions = await self._version_rows(
            session,
            SubjectPhaseTransition,
            SubjectPhaseTransition.design_version_id,
            source_version_id,
            live_only=True,
        )
        for source in transitions:
            session.add(
                _copy_row(
                    source,
                    design_version_id=target_version_id,
                    from_phase_id=(
                        phase_map[source.from_phase_id].id
                        if source.from_phase_id in phase_map
                        else source.from_phase_id
                    ),
                    to_phase_id=(
                        phase_map[source.to_phase_id].id
                        if source.to_phase_id in phase_map
                        else source.to_phase_id
                    ),
                )
            )
        counts["subject_phase_transitions"] = len(transitions)

        arms = list(
            (
                await session.execute(
                    select(ArmDefinition)
                    .where(
                        ArmDefinition.study_version_id == source_version_id,
                        ArmDefinition.deleted_at.is_(None),
                    )
                    .options(selectinload(ArmDefinition.visits))
                )
            )
            .scalars()
            .all()
        )
        for source in arms:
            clone = _copy_row(source, study_version_id=target_version_id)
            clone.visits = [visit_map.get(visit.id, visit) for visit in source.visits]
            session.add(clone)
        counts["arms"] = len(arms)

        schedules = list(
            (
                await session.execute(
                    select(ScheduleOfAssessment)
                    .where(
                        ScheduleOfAssessment.design_version_id == source_version_id,
                        ScheduleOfAssessment.deleted_at.is_(None),
                    )
                    .options(selectinload(ScheduleOfAssessment.entries))
                )
            )
            .scalars()
            .all()
        )
        schedule_entry_count = 0
        for source in schedules:
            clone = _copy_row(source, design_version_id=target_version_id)
            session.add(clone)
            await session.flush()
            for entry in source.entries:
                if entry.deleted_at is not None:
                    continue
                cloned_entry = _copy_row(
                    entry,
                    schedule_of_assessment_id=clone.id,
                    form_definition_id=(
                        form_map[entry.form_definition_id].id
                        if entry.form_definition_id in form_map
                        else entry.form_definition_id
                    ),
                    visit_definition_id=(
                        visit_map[entry.visit_definition_id].id
                        if entry.visit_definition_id in visit_map
                        else entry.visit_definition_id
                    ),
                )
                session.add(cloned_entry)
                schedule_entry_count += 1
        counts["schedules"] = len(schedules)
        counts["schedule_entries"] = schedule_entry_count

        edit_checks = await self._version_rows(
            session, EditCheck, EditCheck.study_version_id, source_version_id
        )
        for source in edit_checks:
            session.add(
                _copy_row(
                    source,
                    study_version_id=target_version_id,
                    rule_json=_remap_field_references(source.rule_json, field_map),
                )
            )
        counts["edit_checks"] = len(edit_checks)

        access_rows = await self._version_rows(
            session,
            CrfAccessDefinition,
            CrfAccessDefinition.design_version_id,
            source_version_id,
            live_only=True,
        )
        for source in access_rows:
            session.add(
                _copy_row(
                    source,
                    design_version_id=target_version_id,
                    form_definition_id=(
                        form_map[source.form_definition_id].id
                        if source.form_definition_id in form_map
                        else source.form_definition_id
                    ),
                    field_definition_id=(
                        field_map[source.field_definition_id].id
                        if source.field_definition_id in field_map
                        else source.field_definition_id
                    ),
                )
            )
        counts["crf_access"] = len(access_rows)

        raw_variables = await self._version_rows(
            session,
            RawDataVariableSetting,
            RawDataVariableSetting.design_version_id,
            source_version_id,
            live_only=True,
        )
        for source in raw_variables:
            session.add(
                _copy_row(
                    source,
                    design_version_id=target_version_id,
                    field_definition_id=(
                        field_map[source.field_definition_id].id
                        if source.field_definition_id in field_map
                        else source.field_definition_id
                    ),
                )
            )
        counts["raw_data_variables"] = len(raw_variables)

        coding_settings = await self._version_rows(
            session,
            CodingSetting,
            CodingSetting.design_version_id,
            source_version_id,
            live_only=True,
        )
        for source in coding_settings:
            session.add(
                _copy_row(
                    source,
                    design_version_id=target_version_id,
                    field_definition_id=(
                        field_map[source.field_definition_id].id
                        if source.field_definition_id in field_map
                        else source.field_definition_id
                    ),
                )
            )
        counts["coding_settings"] = len(coding_settings)

        await session.flush()
        return counts

    @staticmethod
    async def _version_rows(
        session: AsyncSession,
        model: type[ModelT],
        version_column: Any,
        version_id: UUID,
        *,
        live_only: bool = False,
    ) -> list[ModelT]:
        statement = select(model).where(version_column == version_id)
        if live_only:
            statement = statement.where(model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return list((await session.execute(statement)).scalars().all())

    @staticmethod
    async def _rows_for_ids(
        session: AsyncSession,
        model: type[ModelT],
        id_column: Any,
        ids: set[UUID],
    ) -> list[ModelT]:
        if not ids:
            return []
        return list(
            (await session.execute(select(model).where(id_column.in_(ids)))).scalars().all()
        )


design_clone_service = DesignCloneService()
