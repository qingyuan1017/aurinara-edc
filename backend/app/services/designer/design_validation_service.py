"""Publication-readiness validation for Designer study versions.

The service validates the *aggregate* design immediately before publication.
Individual authoring services still own field-level validation; this layer
detects incomplete or cross-version graphs that would otherwise produce an
empty or inconsistent operational casebook.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ValidationError
from app.core.odm_oid import is_valid_odm_oid
from app.models.designer.arm_definition import ArmDefinition
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.coding_setting import CodingSetting
from app.models.designer.crf_access_definition import CrfAccessDefinition
from app.models.designer.edit_check import EditCheck
from app.models.designer.form_dependency import FormDefinitionDependency
from app.models.designer.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.designer.odm_metadata import DerivationDefinition, MeasurementUnitDefinition
from app.models.designer.schedule_of_assessment import ScheduleOfAssessment
from app.models.designer.study_version import StudyVersion
from app.models.designer.subject_phase_definition import (
    SubjectPhaseDefinition,
    SubjectPhaseType,
)
from app.models.designer.subject_phase_transition import SubjectPhaseTransition
from app.models.designer.visit import VisitDefinition
from app.models.designer.visit_dependency import VisitDefinitionDependency
from app.schemas.designer.study_version import (
    DesignValidationCounts,
    DesignValidationIssue,
    DesignValidationResponse,
)
from app.services.designer.rule_engine_v2 import validate_derivation_expression


class DesignValidationService:
    """Build a deterministic readiness report for one Design_Version."""

    async def validate(
        self, session: AsyncSession, version: StudyVersion
    ) -> DesignValidationResponse:
        version_id = version.id

        forms = list(
            (
                await session.execute(
                    select(FormDefinition)
                    .where(FormDefinition.study_version_id == version_id)
                    .order_by(FormDefinition.display_order, FormDefinition.id)
                )
            )
            .scalars()
            .all()
        )
        form_ids = {row.id for row in forms}

        sections = list(
            (
                await session.execute(
                    select(FormSection).where(FormSection.form_definition_id.in_(form_ids))
                )
            )
            .scalars()
            .all()
        )
        section_ids = {row.id for row in sections}
        sections_by_form: dict[UUID, list[FormSection]] = {}
        for section in sections:
            sections_by_form.setdefault(section.form_definition_id, []).append(section)

        fields = list(
            (
                await session.execute(
                    select(FieldDefinition).where(FieldDefinition.form_section_id.in_(section_ids))
                )
            )
            .scalars()
            .all()
        )
        fields_by_section: dict[UUID, list[FieldDefinition]] = {}
        for field in fields:
            fields_by_section.setdefault(field.form_section_id, []).append(field)

        visits = list(
            (
                await session.execute(
                    select(VisitDefinition).where(VisitDefinition.study_version_id == version_id)
                )
            )
            .scalars()
            .all()
        )
        visit_ids = {row.id for row in visits}

        codelists = list(
            (await session.execute(select(Codelist).where(Codelist.study_version_id == version_id)))
            .scalars()
            .all()
        )
        codelist_ids = {row.id for row in codelists}
        codelist_items = list(
            (
                await session.execute(
                    select(CodelistItem).where(CodelistItem.codelist_id.in_(codelist_ids))
                )
            )
            .scalars()
            .all()
        )
        item_count_by_codelist: dict[UUID, int] = {}
        for item in codelist_items:
            item_count_by_codelist[item.codelist_id] = (
                item_count_by_codelist.get(item.codelist_id, 0) + 1
            )

        edit_checks = list(
            (
                await session.execute(
                    select(EditCheck).where(EditCheck.study_version_id == version_id)
                )
            )
            .scalars()
            .all()
        )
        derivations = list(
            (
                await session.execute(
                    select(DerivationDefinition).where(
                        DerivationDefinition.study_version_id == version_id
                    )
                )
            )
            .scalars()
            .all()
        )
        measurement_units = list(
            (
                await session.execute(
                    select(MeasurementUnitDefinition).where(
                        MeasurementUnitDefinition.study_version_id == version_id
                    )
                )
            )
            .scalars()
            .all()
        )
        phases = list(
            (
                await session.execute(
                    select(SubjectPhaseDefinition)
                    .where(
                        SubjectPhaseDefinition.design_version_id == version_id,
                        SubjectPhaseDefinition.deleted_at.is_(None),
                    )
                    .options(selectinload(SubjectPhaseDefinition.visits))
                )
            )
            .scalars()
            .all()
        )
        phase_ids = {row.id for row in phases}
        transitions = list(
            (
                await session.execute(
                    select(SubjectPhaseTransition).where(
                        SubjectPhaseTransition.design_version_id == version_id,
                        SubjectPhaseTransition.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        form_dependencies = list(
            (
                await session.execute(
                    select(FormDefinitionDependency).where(
                        FormDefinitionDependency.form_definition_id.in_(form_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        visit_dependencies = list(
            (
                await session.execute(
                    select(VisitDefinitionDependency).where(
                        VisitDefinitionDependency.visit_definition_id.in_(visit_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        arms = list(
            (
                await session.execute(
                    select(ArmDefinition).where(
                        ArmDefinition.study_version_id == version_id,
                        ArmDefinition.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        access_rows = list(
            (
                await session.execute(
                    select(CrfAccessDefinition).where(
                        CrfAccessDefinition.design_version_id == version_id,
                        CrfAccessDefinition.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        coding_settings = list(
            (
                await session.execute(
                    select(CodingSetting).where(
                        CodingSetting.design_version_id == version_id,
                        CodingSetting.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        schedules = list(
            (
                await session.execute(
                    select(ScheduleOfAssessment)
                    .where(
                        ScheduleOfAssessment.design_version_id == version_id,
                        ScheduleOfAssessment.deleted_at.is_(None),
                    )
                    .options(selectinload(ScheduleOfAssessment.entries))
                )
            )
            .scalars()
            .all()
        )
        schedule_entries = [
            entry
            for schedule in schedules
            for entry in schedule.entries
            if entry.deleted_at is None
        ]
        scheduled_form_entries = [
            entry for entry in schedule_entries if entry.form_definition_id is not None
        ]

        issues: list[DesignValidationIssue] = []

        def add(
            code: str,
            severity: Literal["error", "warning"],
            message: str,
            *,
            entity_type: str | None = None,
            entity_id: UUID | None = None,
        ) -> None:
            issues.append(
                DesignValidationIssue(
                    code=code,
                    severity=severity,
                    message=message,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
            )

        if not forms:
            add("NO_FORMS", "error", "Add at least one form before publishing.")
        if not visits:
            add("NO_VISITS", "error", "Add at least one visit before publishing.")

        oid_rows = [
            ("study_version", version.id, version.odm_study_oid),
            ("metadata_version", version.id, version.odm_metadata_version_oid),
            *(("form_definition", row.id, row.odm_oid) for row in forms),
            *(("form_section", row.id, row.odm_oid) for row in sections),
            *(("field_definition", row.id, row.odm_oid) for row in fields),
            *(("visit_definition", row.id, row.odm_oid) for row in visits),
            *(("codelist", row.id, row.odm_oid) for row in codelists),
            *(("edit_check", row.id, row.odm_oid) for row in edit_checks),
            *(("derivation", row.id, row.odm_oid) for row in derivations),
            *(("measurement_unit", row.id, row.odm_oid) for row in measurement_units),
        ]
        seen_oids: dict[str, tuple[str, UUID]] = {}
        for entity_type, entity_id, oid in oid_rows:
            if not is_valid_odm_oid(oid):
                add(
                    "ODM_OID_INVALID",
                    "error",
                    f"{entity_type} has an invalid ODM OID.",
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
            elif oid in seen_oids:
                add(
                    "ODM_OID_DUPLICATE",
                    "error",
                    f"ODM OID {oid} is used by more than one definition.",
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
            else:
                seen_oids[oid] = (entity_type, entity_id)

        for form in forms:
            form_sections = sections_by_form.get(form.id, [])
            if not form_sections:
                add(
                    "FORM_HAS_NO_SECTIONS",
                    "error",
                    f"Form {form.form_code} has no sections.",
                    entity_type="form_definition",
                    entity_id=form.id,
                )
                continue
            if not any(fields_by_section.get(section.id) for section in form_sections):
                add(
                    "FORM_HAS_NO_FIELDS",
                    "error",
                    f"Form {form.form_code} has no fields.",
                    entity_type="form_definition",
                    entity_id=form.id,
                )

        for codelist in codelists:
            if item_count_by_codelist.get(codelist.id, 0) == 0:
                add(
                    "CODELIST_HAS_NO_ITEMS",
                    "error",
                    f"Codelist {codelist.code} has no items.",
                    entity_type="codelist",
                    entity_id=codelist.id,
                )

        for field in fields:
            if field.codelist_id is not None and field.codelist_id not in codelist_ids:
                add(
                    "FIELD_CODELIST_OUTSIDE_VERSION",
                    "error",
                    f"Field {field.variable_name} references a codelist outside this version.",
                    entity_type="field_definition",
                    entity_id=field.id,
                )
            if (
                field.control_type
                in {"radio", "checkbox", "dropdown", "multi-select", "coded_term"}
                and field.codelist_id is None
                and not (field.control_type == "checkbox" and field.data_type == "boolean")
            ):
                add(
                    "FIELD_CODELIST_REQUIRED",
                    "error",
                    f"Field {field.variable_name} requires a codelist for its control type.",
                    entity_type="field_definition",
                    entity_id=field.id,
                )

        for dependency in form_dependencies:
            if dependency.depends_on_form_definition_id not in form_ids:
                add(
                    "FORM_DEPENDENCY_OUTSIDE_VERSION",
                    "error",
                    "A form dependency references a form outside this version.",
                    entity_type="form_definition_dependency",
                    entity_id=dependency.id,
                )

        for dependency in visit_dependencies:
            if dependency.depends_on_visit_definition_id not in visit_ids:
                add(
                    "VISIT_DEPENDENCY_OUTSIDE_VERSION",
                    "error",
                    "A visit dependency references a visit outside this version.",
                    entity_type="visit_definition_dependency",
                    entity_id=dependency.id,
                )

        for transition in transitions:
            if transition.from_phase_id not in phase_ids or transition.to_phase_id not in phase_ids:
                add(
                    "PHASE_TRANSITION_OUTSIDE_VERSION",
                    "error",
                    "A subject phase transition references a phase outside this version.",
                    entity_type="subject_phase_transition",
                    entity_id=transition.id,
                )

        for phase in phases:
            if phase.phase_type == SubjectPhaseType.arm and phase.visits:
                add(
                    "PHASE_TYPE_DISALLOWS_VISITS",
                    "error",
                    f"{phase.phase_type.value.replace('_', ' ').title()} phase {phase.name} cannot reference visits.",
                    entity_type="subject_phase_definition",
                    entity_id=phase.id,
                )
            if phase.phase_type == SubjectPhaseType.arm and not arms:
                add(
                    "ARM_PHASE_HAS_NO_ARMS",
                    "error",
                    f"Arm phase {phase.name} requires at least one configured arm.",
                    entity_type="subject_phase_definition",
                    entity_id=phase.id,
                )

        for access in access_rows:
            if access.form_definition_id is not None and access.form_definition_id not in form_ids:
                add(
                    "ACCESS_FORM_OUTSIDE_VERSION",
                    "error",
                    f"CRF access for role {access.role} references a form outside this version.",
                    entity_type="crf_access_definition",
                    entity_id=access.id,
                )
            if access.field_definition_id is not None and access.field_definition_id not in {
                field.id for field in fields
            }:
                add(
                    "ACCESS_FIELD_OUTSIDE_VERSION",
                    "error",
                    f"CRF access for role {access.role} references a field outside this version.",
                    entity_type="crf_access_definition",
                    entity_id=access.id,
                )

        field_ids = {field.id for field in fields}
        for setting in coding_settings:
            if (
                setting.field_definition_id is not None
                and setting.field_definition_id not in field_ids
            ):
                add(
                    "CODING_FIELD_OUTSIDE_VERSION",
                    "error",
                    "A coding setting references a field outside this version.",
                    entity_type="coding_setting",
                    entity_id=setting.id,
                )

        arm_ids = {arm.id for arm in arms}
        common_schedules = [
            schedule for schedule in schedules if schedule.arm_definition_id is None
        ]
        arm_schedules = [
            schedule for schedule in schedules if schedule.arm_definition_id is not None
        ]

        if not common_schedules:
            add(
                "NO_SCHEDULE_OF_ASSESSMENT",
                "error",
                "Create and save the common schedule of assessment before publishing.",
            )
        elif len(common_schedules) > 1:
            add(
                "MULTIPLE_ACTIVE_COMMON_SCHEDULES",
                "error",
                "Only one active common schedule of assessment may exist for a design version.",
            )

        schedules_by_arm: dict[UUID, list[ScheduleOfAssessment]] = {}
        for schedule in arm_schedules:
            arm_id = schedule.arm_definition_id
            if arm_id not in arm_ids:
                add(
                    "SCHEDULE_ARM_OUTSIDE_VERSION",
                    "error",
                    "A schedule of assessment references an arm outside this version.",
                    entity_type="schedule_of_assessment",
                    entity_id=schedule.id,
                )
                continue
            schedules_by_arm.setdefault(arm_id, []).append(schedule)

        for arm in arms:
            scoped = schedules_by_arm.get(arm.id, [])
            if not scoped:
                add(
                    "ARM_HAS_NO_SCHEDULE",
                    "error",
                    f"Treatment arm {arm.name} requires its own schedule of assessment.",
                    entity_type="arm_definition",
                    entity_id=arm.id,
                )
            elif len(scoped) > 1:
                add(
                    "MULTIPLE_ACTIVE_ARM_SCHEDULES",
                    "error",
                    f"Treatment arm {arm.name} has more than one active schedule of assessment.",
                    entity_type="arm_definition",
                    entity_id=arm.id,
                )

        mapped_form_ids: set[UUID] = set()
        for entry in schedule_entries:
            has_form = entry.form_definition_id is not None
            has_procedure = bool(entry.procedure_name and entry.procedure_name.strip())
            if has_form == has_procedure:
                add(
                    "SCHEDULE_ENTRY_TARGET_INVALID",
                    "error",
                    "A schedule entry must reference exactly one form or named procedure.",
                    entity_type="schedule_of_assessment_entry",
                    entity_id=entry.id,
                )
            if entry.visit_definition_id not in visit_ids:
                add(
                    "SCHEDULE_VISIT_OUTSIDE_VERSION",
                    "error",
                    "A schedule entry references a visit outside this version.",
                    entity_type="schedule_of_assessment_entry",
                    entity_id=entry.id,
                )
            if entry.form_definition_id is not None:
                if entry.form_definition_id not in form_ids:
                    add(
                        "SCHEDULE_FORM_OUTSIDE_VERSION",
                        "error",
                        "A schedule entry references a form outside this version.",
                        entity_type="schedule_of_assessment_entry",
                        entity_id=entry.id,
                    )
                else:
                    mapped_form_ids.add(entry.form_definition_id)

        for form in forms:
            if form.id not in mapped_form_ids:
                add(
                    "FORM_NOT_SCHEDULED",
                    "error",
                    f"Form {form.form_code} is not mapped to any visit.",
                    entity_type="form_definition",
                    entity_id=form.id,
                )

        known_variables = {
            reference
            for field in fields
            for reference in (
                field.variable_name,
                field.odm_oid,
                str(field.id),
                f"{field.variable_name}.normal_low",
                f"{field.variable_name}.normal_high",
            )
        }
        for rule in edit_checks:
            if not rule.is_active:
                continue
            if rule.needs_retesting:
                add(
                    "EDIT_CHECK_NEEDS_RETESTING",
                    "error",
                    f"Edit check {rule.name} must be retested before publication.",
                    entity_type="edit_check",
                    entity_id=rule.id,
                )

        known_field_oids = {field.odm_oid for field in fields}
        for derivation in derivations:
            if not derivation.is_active:
                continue
            if derivation.needs_retesting:
                add(
                    "DERIVATION_NEEDS_RETESTING",
                    "error",
                    f"Derivation {derivation.name} must be retested before publication.",
                    entity_type="derivation_definition",
                    entity_id=derivation.id,
                )
            if derivation.target_field_definition_id not in field_ids:
                add(
                    "DERIVATION_TARGET_OUTSIDE_VERSION",
                    "error",
                    f"Derivation {derivation.name} targets a field outside this version.",
                    entity_type="derivation_definition",
                    entity_id=derivation.id,
                )
            try:
                missing = (
                    validate_derivation_expression(derivation.expression_json) - known_field_oids
                )
            except (TypeError, ValueError) as exc:
                add(
                    "DERIVATION_INVALID",
                    "error",
                    f"Derivation {derivation.name} is invalid: {exc}.",
                    entity_type="derivation_definition",
                    entity_id=derivation.id,
                )
            else:
                if missing:
                    add(
                        "DERIVATION_FIELD_NOT_FOUND",
                        "error",
                        f"Derivation {derivation.name} references unknown field(s): {', '.join(sorted(missing))}.",
                        entity_type="derivation_definition",
                        entity_id=derivation.id,
                    )
            missing = sorted(self._field_references(rule.rule_json) - known_variables)
            if missing:
                add(
                    "EDIT_CHECK_FIELD_NOT_FOUND",
                    "error",
                    f"Edit check {rule.name} references unknown field(s): {', '.join(missing)}.",
                    entity_type="edit_check",
                    entity_id=rule.id,
                )

        if not edit_checks:
            add(
                "NO_EDIT_CHECKS",
                "warning",
                "No edit checks are configured for this design.",
            )
        if not phases:
            add(
                "NO_SUBJECT_PHASES",
                "error",
                "Configure at least one subject phase before publishing.",
            )
        elif not any(phase.phase_type == SubjectPhaseType.registered for phase in phases):
            add(
                "NO_REGISTERED_SUBJECT_PHASE",
                "error",
                "Configure at least one registered subject phase to initialize new subjects.",
            )

        counts = DesignValidationCounts(
            forms=len(forms),
            sections=len(sections),
            fields=len(fields),
            visits=len(visits),
            scheduled_form_mappings=len(scheduled_form_entries),
            codelists=len(codelists),
            codelist_items=len(codelist_items),
            edit_checks=len(edit_checks),
            derivations=len(derivations),
            measurement_units=len(measurement_units),
            subject_phases=len(phases),
        )
        return DesignValidationResponse(
            version_id=version_id,
            valid=not any(issue.severity == "error" for issue in issues),
            counts=counts,
            issues=issues,
        )

    async def require_publishable(
        self, session: AsyncSession, version: StudyVersion
    ) -> DesignValidationResponse:
        """Return the report or reject publication without changing the draft."""

        report = await self.validate(session, version)
        if not report.valid:
            raise ValidationError(
                "Study design is not ready to publish",
                details={
                    "version_id": str(version.id),
                    "issues": [
                        issue.model_dump(mode="json", exclude_none=True)
                        for issue in report.issues
                        if issue.severity == "error"
                    ],
                },
            )
        return report

    @classmethod
    def _field_references(cls, value: Any) -> set[str]:
        """Collect field/value-field identifiers from the safe edit-check DSL."""

        references: set[str] = set()
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in {"field", "value_field", "itemOID"} and isinstance(child, str):
                    references.add(child)
                else:
                    references.update(cls._field_references(child))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for child in value:
                references.update(cls._field_references(child))
        return references


design_validation_service = DesignValidationService()
