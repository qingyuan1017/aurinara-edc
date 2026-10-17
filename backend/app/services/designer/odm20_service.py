"""Bidirectional ODM 2.0 JSON metadata adapter for Designer."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.edit_check_dsl import validate_rule
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.core.odm_oid import new_odm_oid
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.coding_setting import CodingSetting
from app.models.designer.crf_access_definition import CrfAccessDefinition
from app.models.designer.edit_check import EditCheck
from app.models.designer.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.designer.odm_metadata import DerivationDefinition, MeasurementUnitDefinition
from app.models.designer.schedule_of_assessment import (
    ScheduleOfAssessment,
    ScheduleOfAssessmentEntry,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.subject_phase_definition import (
    SubjectPhaseDefinition,
    SubjectPhaseType,
    SubjectPhaseVisitDefinition,
)
from app.models.designer.subject_phase_transition import SubjectPhaseTransition
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import Study
from app.schemas.designer.odm20 import (
    AURINARA_EXTENSION,
    OdmCodeList,
    OdmCodeListItem,
    OdmCondition,
    OdmDocument,
    OdmForm,
    OdmImportResult,
    OdmItem,
    OdmItemGroup,
    OdmMeasurementUnit,
    OdmMetaDataVersion,
    OdmMethod,
    OdmReference,
    OdmStudy,
    OdmStudyEvent,
    OdmSubjectPhase,
    OdmSubjectPhaseTransition,
    OdmValidationIssue,
    OdmValidationReport,
    subject_phase_extension,
)
from app.schemas.designer.rule_v2 import RuleDefinitionV2
from app.services.designer.rule_engine_v2 import validate_derivation_expression
from app.services.designer.subject_phase_service import (
    DEFAULT_SUBJECT_PHASE_TRANSITIONS,
    DEFAULT_SUBJECT_PHASES,
    subject_phase_service,
)


def _canonical_payload(document: OdmDocument) -> bytes:
    return json.dumps(
        document.model_dump(by_alias=True, exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _extension(values: dict[str, Any]) -> dict[str, Any]:
    clean = {key: value for key, value in values.items() if value is not None}
    return {AURINARA_EXTENSION: clean} if clean else {}


def _ext(values: dict[str, Any]) -> dict[str, Any]:
    extension = values.get(AURINARA_EXTENSION, {})
    return extension if isinstance(extension, dict) else {}


def _bounded_code(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{value[: limit - 17]}.{digest}"


def _serialize_coding_rule(value: Any) -> str | None:
    """Store ODM scalar or structured coding rules in the legacy text column."""
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _deserialize_coding_rule(value: str | None) -> Any:
    """Restore structured ODM coding rules while preserving legacy plain text."""
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value
    return parsed if isinstance(parsed, (dict, list)) else value


class Odm20Service:
    async def validate_document(self, payload: dict[str, Any]) -> OdmValidationReport:
        try:
            document = OdmDocument.model_validate(payload)
        except PydanticValidationError as exc:
            errors = [
                OdmValidationIssue(
                    code="ODM_SCHEMA_INVALID",
                    path=".".join(str(part) for part in error["loc"]),
                    message=error["msg"],
                )
                for error in exc.errors(include_url=False)
            ]
            return OdmValidationReport(valid=False, errors=errors)
        expression_errors: list[OdmValidationIssue] = []
        for index, condition in enumerate(document.study.meta_data_version.conditions):
            try:
                validate_rule(condition.expression)
            except (ValidationError, ValueError, TypeError) as exc:
                expression_errors.append(
                    OdmValidationIssue(
                        code="ODM_CONDITION_INVALID",
                        path=f"study.metaDataVersion.conditions.{index}.expression",
                        entityOID=condition.oid,
                        message=str(exc),
                    )
                )
        for index, method in enumerate(document.study.meta_data_version.methods):
            try:
                validate_derivation_expression(method.expression)
            except (ValueError, TypeError) as exc:
                expression_errors.append(
                    OdmValidationIssue(
                        code="ODM_METHOD_INVALID",
                        path=f"study.metaDataVersion.methods.{index}.expression",
                        entityOID=method.oid,
                        message=str(exc),
                    )
                )
        return OdmValidationReport(
            valid=not expression_errors,
            errors=expression_errors,
            counts=self._counts(document),
            extensionsUsed=self._extensions_used(document),
        )

    async def export_document(
        self, session: AsyncSession, *, study_id: UUID, version_id: UUID
    ) -> OdmDocument:
        version = await session.get(StudyVersion, version_id)
        if version is None or version.study_id != study_id:
            raise NotFoundError("Design version not found")
        study = await session.get(Study, study_id)
        if study is None:
            raise NotFoundError("Study not found")

        forms = list(
            (
                await session.execute(
                    select(FormDefinition)
                    .where(FormDefinition.study_version_id == version_id)
                    .options(
                        selectinload(FormDefinition.sections)
                        .selectinload(FormSection.fields)
                        .selectinload(FieldDefinition.codelist)
                    )
                    .order_by(FormDefinition.display_order, FormDefinition.id)
                )
            )
            .scalars()
            .unique()
            .all()
        )
        visits = list(
            (
                await session.execute(
                    select(VisitDefinition)
                    .where(VisitDefinition.study_version_id == version_id)
                    .order_by(VisitDefinition.display_order, VisitDefinition.id)
                )
            )
            .scalars()
            .all()
        )
        codelists = list(
            (
                await session.execute(
                    select(Codelist)
                    .where(Codelist.study_version_id == version_id)
                    .options(selectinload(Codelist.items))
                    .order_by(Codelist.code, Codelist.id)
                )
            )
            .scalars()
            .unique()
            .all()
        )
        units = list(
            (
                await session.execute(
                    select(MeasurementUnitDefinition)
                    .where(MeasurementUnitDefinition.study_version_id == version_id)
                    .order_by(MeasurementUnitDefinition.name, MeasurementUnitDefinition.id)
                )
            )
            .scalars()
            .all()
        )
        checks = list(
            (
                await session.execute(
                    select(EditCheck)
                    .where(EditCheck.study_version_id == version_id)
                    .order_by(EditCheck.name, EditCheck.id)
                )
            )
            .scalars()
            .all()
        )
        methods = list(
            (
                await session.execute(
                    select(DerivationDefinition)
                    .where(DerivationDefinition.study_version_id == version_id)
                    .options(selectinload(DerivationDefinition.target_field))
                    .order_by(DerivationDefinition.execution_order, DerivationDefinition.id)
                )
            )
            .scalars()
            .all()
        )
        coding_settings = list(
            (
                await session.execute(
                    select(CodingSetting)
                    .where(
                        CodingSetting.design_version_id == version_id,
                        CodingSetting.deleted_at.is_(None),
                    )
                    .order_by(CodingSetting.priority, CodingSetting.id)
                )
            )
            .scalars()
            .all()
        )
        access_rows = list(
            (
                await session.execute(
                    select(CrfAccessDefinition)
                    .where(
                        CrfAccessDefinition.design_version_id == version_id,
                        CrfAccessDefinition.deleted_at.is_(None),
                    )
                    .order_by(CrfAccessDefinition.role, CrfAccessDefinition.id)
                )
            )
            .scalars()
            .all()
        )
        subject_phases = list(
            (
                await session.execute(
                    select(SubjectPhaseDefinition)
                    .where(
                        SubjectPhaseDefinition.design_version_id == version_id,
                        SubjectPhaseDefinition.deleted_at.is_(None),
                    )
                    .options(selectinload(SubjectPhaseDefinition.visits))
                    .order_by(
                        SubjectPhaseDefinition.display_order,
                        SubjectPhaseDefinition.id,
                    )
                )
            )
            .scalars()
            .unique()
            .all()
        )
        subject_phase_transitions = list(
            (
                await session.execute(
                    select(SubjectPhaseTransition)
                    .where(
                        SubjectPhaseTransition.design_version_id == version_id,
                        SubjectPhaseTransition.deleted_at.is_(None),
                    )
                    .order_by(
                        SubjectPhaseTransition.created_at,
                        SubjectPhaseTransition.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        schedule = (
            (
                await session.execute(
                    select(ScheduleOfAssessment)
                    .where(
                        ScheduleOfAssessment.design_version_id == version_id,
                        ScheduleOfAssessment.deleted_at.is_(None),
                    )
                    .options(selectinload(ScheduleOfAssessment.entries))
                    .order_by(ScheduleOfAssessment.created_at.desc())
                )
            )
            .scalars()
            .first()
        )

        unit_by_symbol = {unit.symbol: unit.odm_oid for unit in units}
        form_by_id = {form.id: form for form in forms}
        field_oid_by_id = {
            field.id: field.odm_oid
            for form in forms
            for section in form.sections
            for field in section.fields
        }
        method_oid_by_target_id = {
            method.target_field_definition_id: method.odm_oid for method in methods
        }
        subject_phase_by_id = {phase.id: phase for phase in subject_phases}
        event_forms: dict[UUID, list[ScheduleOfAssessmentEntry]] = {}
        if schedule:
            for entry in schedule.entries:
                if (
                    entry.deleted_at is None
                    and entry.visit_definition_id
                    and entry.form_definition_id
                ):
                    event_forms.setdefault(entry.visit_definition_id, []).append(entry)

        odm_forms: list[OdmForm] = []
        odm_groups: list[OdmItemGroup] = []
        odm_items: list[OdmItem] = []
        for form in forms:
            group_refs: list[OdmReference] = []
            for section in sorted(form.sections, key=lambda row: (row.display_order, str(row.id))):
                group_refs.append(
                    OdmReference(
                        oid=section.odm_oid, mandatory=True, orderNumber=section.display_order
                    )
                )
                item_refs: list[OdmReference] = []
                for field in sorted(
                    section.fields, key=lambda row: (row.display_order, str(row.id))
                ):
                    item_refs.append(
                        OdmReference(
                            oid=field.odm_oid,
                            mandatory=field.is_required,
                            orderNumber=field.display_order,
                        )
                    )
                    odm_items.append(
                        OdmItem(
                            oid=field.odm_oid,
                            name=field.variable_name,
                            dataType=field.data_type,
                            question=field.question or field.label,
                            length=field.max_length,
                            significantDigits=field.decimal_precision,
                            codeListOID=field.codelist.odm_oid if field.codelist else None,
                            measurementUnitOID=unit_by_symbol.get(field.unit or ""),
                            methodOID=method_oid_by_target_id.get(field.id),
                            extensions=_extension(
                                {
                                    "label": field.label,
                                    "controlType": field.control_type,
                                    "defaultValue": field.default_value,
                                    "helpText": field.help_text,
                                    "unit": field.unit,
                                    "dataFormat": field.data_format,
                                    "allowsPartialDate": field.allows_partial_date,
                                    "sourceDocument": field.source_document,
                                    "queryFutureDate": field.query_future_date,
                                    "queryNonconformance": field.query_nonconformance,
                                    "breaksSignature": field.breaks_signature,
                                    "reviewGroup": field.review_group,
                                    "dynamicSearchConfig": field.dynamic_search_config,
                                }
                            ),
                        )
                    )
                odm_groups.append(
                    OdmItemGroup(
                        oid=section.odm_oid,
                        name=section.name,
                        repeating=section.is_repeating,
                        itemRefs=item_refs,
                        extensions=_extension(
                            {
                                "label": section.label,
                                "repeatMin": section.repeat_min,
                                "repeatMax": section.repeat_max,
                                "isLabelOnly": section.is_label_only,
                                "outputToDataset": section.output_to_dataset,
                                "accessType": section.access_type,
                            }
                        ),
                    )
                )
            odm_forms.append(
                OdmForm(
                    oid=form.odm_oid,
                    name=form.name,
                    repeating=form.is_repeating,
                    itemGroupRefs=group_refs,
                    extensions=_extension(
                        {
                            "formCode": form.form_code,
                            "requiresSignature": form.requires_signature,
                            "formType": form.form_type,
                            "accessType": form.access_type,
                            "domain": form.domain,
                            "label": form.label,
                        }
                    ),
                )
            )

        odm_events = []
        for visit in visits:
            refs = [
                OdmReference(
                    oid=form_by_id[entry.form_definition_id].odm_oid,
                    mandatory=True,
                    orderNumber=entry.display_order,
                )
                for entry in sorted(
                    event_forms.get(visit.id, []), key=lambda row: row.display_order
                )
                if entry.form_definition_id in form_by_id
            ]
            event_type = (
                visit.visit_type
                if visit.visit_type in {"scheduled", "unscheduled", "common"}
                else "scheduled"
            )
            odm_events.append(
                OdmStudyEvent(
                    oid=visit.odm_oid,
                    name=visit.name,
                    repeating=visit.definition_kind == "cycle_visit" or bool(visit.repeat_max),
                    type=event_type,
                    formRefs=refs,
                    extensions=_extension(
                        {
                            "visitNumber": visit.visit_number,
                            "definitionKind": visit.definition_kind,
                            "parentOID": next(
                                (row.odm_oid for row in visits if row.id == visit.parent_folder_id),
                                None,
                            ),
                            "category": visit.category,
                            "subtype": visit.subtype,
                            "targetDay": visit.target_day,
                            "windowBefore": visit.window_before,
                            "windowAfter": visit.window_after,
                            "addable": visit.addable,
                            "repeatMin": visit.repeat_min,
                            "repeatMax": visit.repeat_max,
                            "cycleLength": visit.cycle_length,
                        }
                    ),
                )
            )

        document = OdmDocument(
            fileOID=new_odm_oid("FILE", version.id),
            study=OdmStudy(
                oid=version.odm_study_oid,
                studyName=study.title,
                protocolName=study.protocol_number or study.study_code,
                metaDataVersion=OdmMetaDataVersion(
                    oid=version.odm_metadata_version_oid,
                    name=version.version_number,
                    studyEvents=odm_events,
                    forms=odm_forms,
                    itemGroups=odm_groups,
                    items=odm_items,
                    codeLists=[
                        OdmCodeList(
                            oid=row.odm_oid,
                            name=row.name,
                            items=[
                                OdmCodeListItem(
                                    codedValue=item.code,
                                    decode=item.label,
                                    orderNumber=item.display_order,
                                    specify=item.specify,
                                )
                                for item in sorted(row.items, key=lambda item: item.display_order)
                            ],
                        )
                        for row in codelists
                    ],
                    measurementUnits=[
                        OdmMeasurementUnit(
                            oid=row.odm_oid,
                            name=row.name,
                            symbol=row.symbol,
                            conversionFactor=float(row.conversion_factor)
                            if row.conversion_factor is not None
                            else None,
                            conversionOffset=float(row.conversion_offset)
                            if row.conversion_offset is not None
                            else None,
                        )
                        for row in units
                    ],
                    conditions=[
                        OdmCondition(
                            oid=row.odm_oid,
                            name=row.name,
                            description=row.description,
                            expression=row.rule_json,
                            extensions=_extension(
                                {
                                    "severity": row.severity,
                                    "active": row.is_active,
                                    "schemaVersion": row.schema_version,
                                    "needsRetesting": row.needs_retesting,
                                    "retestingReason": row.retesting_reason,
                                }
                            ),
                        )
                        for row in checks
                    ],
                    methods=[
                        OdmMethod(
                            oid=row.odm_oid,
                            name=row.name,
                            targetItemOID=row.target_field.odm_oid,
                            expression=row.expression_json,
                            orderNumber=row.execution_order,
                            extensions=_extension(
                                {
                                    "active": row.is_active,
                                    "needsRetesting": row.needs_retesting,
                                    "retestingReason": row.retesting_reason,
                                }
                            ),
                        )
                        for row in methods
                    ],
                    extensions=_extension(
                        {
                            "schedule": "master",
                            "subjectPhases": [
                                OdmSubjectPhase(
                                    oid=phase.odm_oid,
                                    name=phase.name,
                                    phaseType=SubjectPhaseType(phase.phase_type).value,
                                    displayOrder=phase.display_order,
                                    visitOIDs=[visit.odm_oid for visit in phase.visits],
                                ).model_dump(by_alias=True, exclude_none=True, mode="json")
                                for phase in subject_phases
                            ],
                            "subjectPhaseTransitions": [
                                OdmSubjectPhaseTransition(
                                    oid=transition.odm_oid,
                                    fromPhaseOID=subject_phase_by_id[
                                        transition.from_phase_id
                                    ].odm_oid,
                                    toPhaseOID=subject_phase_by_id[transition.to_phase_id].odm_oid,
                                    label=transition.label,
                                    conditionExpression=transition.condition_expression,
                                ).model_dump(by_alias=True, exclude_none=True, mode="json")
                                for transition in subject_phase_transitions
                                if transition.from_phase_id in subject_phase_by_id
                                and transition.to_phase_id in subject_phase_by_id
                            ],
                            "codingSettings": [
                                {
                                    "fieldItemOID": field_oid_by_id.get(row.field_definition_id),
                                    "dictionaryReference": row.dictionary_reference,
                                    "dictionaryVersion": row.dictionary_version,
                                    "codingLevel": row.coding_level,
                                    "locale": row.locale,
                                    "priority": row.priority,
                                    "approvalRequired": row.approval_required,
                                    "autoApproval": row.auto_approval,
                                    "codingRule": _deserialize_coding_rule(row.coding_rule),
                                }
                                for row in coding_settings
                            ],
                            "crfAccess": [
                                {
                                    "role": row.role,
                                    "formOID": (
                                        form_by_id[row.form_definition_id].odm_oid
                                        if row.form_definition_id in form_by_id
                                        else None
                                    ),
                                    "itemOID": field_oid_by_id.get(row.field_definition_id),
                                    "canRead": row.can_read,
                                    "canWrite": row.can_write,
                                    "blinded": row.blinded,
                                    "unblindRole": row.unblind_role,
                                }
                                for row in access_rows
                            ],
                        }
                    ),
                ),
            ),
        )
        return document

    async def import_document(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        payload: dict[str, Any],
        actor_id: UUID,
        target_version_id: UUID | None,
        version_number: str | None,
    ) -> OdmImportResult:
        try:
            document = OdmDocument.model_validate(payload)
        except PydanticValidationError as exc:
            raise ValidationError(
                "ODM 2.0 document is invalid",
                details={"errors": [error["msg"] for error in exc.errors(include_url=False)]},
            ) from exc
        try:
            for condition in document.study.meta_data_version.conditions:
                validate_rule(condition.expression)
            for method in document.study.meta_data_version.methods:
                validate_derivation_expression(method.expression)
        except (ValidationError, ValueError, TypeError) as exc:
            raise ValidationError(
                "ODM rule or derivation expression is invalid",
                details={"reason": str(exc)},
            ) from exc
        study = await session.get(Study, study_id)
        if study is None:
            raise NotFoundError("Study not found")
        version = await self._target_version(
            session,
            study_id=study_id,
            target_version_id=target_version_id,
            version_number=version_number,
            document=document,
        )
        await self._require_empty(session, version.id)
        mdv = document.study.meta_data_version
        metadata_ext = _ext(mdv.extensions)
        has_phase_extension = (
            "subjectPhases" in metadata_ext or "subjectPhaseTransitions" in metadata_ext
        )
        phase_sources, phase_transition_sources = subject_phase_extension(mdv)
        existing_default_phases = await self._prepare_phase_target(
            session,
            version_id=version.id,
            replace_defaults=has_phase_extension,
        )
        if not has_phase_extension and not existing_default_phases:
            await subject_phase_service.seed_default_phase_flow(
                session,
                design_version_id=version.id,
                study_id=study_id,
                actor_id=actor_id,
            )
        version.odm_study_oid = document.study.oid
        version.odm_metadata_version_oid = mdv.oid

        codelists: dict[str, Codelist] = {}
        for source in mdv.code_lists:
            row = Codelist(
                study_version_id=version.id,
                odm_oid=source.oid,
                name=source.name,
                code=_bounded_code(source.oid, 100),
            )
            row.items = [
                CodelistItem(
                    code=item.coded_value,
                    label=item.decode,
                    display_order=item.order_number,
                    specify=item.specify,
                )
                for item in source.items
            ]
            session.add(row)
            codelists[source.oid] = row
        units: dict[str, MeasurementUnitDefinition] = {}
        for source in mdv.measurement_units:
            row = MeasurementUnitDefinition(
                study_version_id=version.id,
                odm_oid=source.oid,
                name=source.name,
                symbol=source.symbol,
                conversion_factor=source.conversion_factor,
                conversion_offset=source.conversion_offset,
            )
            session.add(row)
            units[source.oid] = row
        await session.flush()

        fields: dict[str, FieldDefinition] = {}
        source_items = {row.oid: row for row in mdv.items}
        groups: dict[str, FormSection] = {}
        for form_index, source_form in enumerate(mdv.forms):
            ext = _ext(source_form.extensions)
            form = FormDefinition(
                study_version_id=version.id,
                odm_oid=source_form.oid,
                name=source_form.name,
                form_code=_bounded_code(str(ext.get("formCode") or source_form.oid), 50),
                display_order=form_index,
                is_repeating=source_form.repeating,
                requires_signature=bool(ext.get("requiresSignature", False)),
                form_type=str(ext.get("formType") or "simple"),
                access_type=str(ext.get("accessType") or "open_access"),
                domain=ext.get("domain"),
                label=ext.get("label"),
            )
            session.add(form)
            await session.flush()
            for group_ref in sorted(source_form.item_group_refs, key=lambda ref: ref.order_number):
                source_group = next(row for row in mdv.item_groups if row.oid == group_ref.oid)
                group_ext = _ext(source_group.extensions)
                section = FormSection(
                    form_definition_id=form.id,
                    odm_oid=source_group.oid,
                    name=source_group.name,
                    label=str(group_ext.get("label") or source_group.name),
                    display_order=group_ref.order_number,
                    is_repeating=source_group.repeating,
                    repeat_min=group_ext.get("repeatMin"),
                    repeat_max=group_ext.get("repeatMax"),
                    is_label_only=bool(group_ext.get("isLabelOnly", False)),
                    output_to_dataset=bool(group_ext.get("outputToDataset", True)),
                    access_type=str(group_ext.get("accessType") or "open_access"),
                )
                session.add(section)
                groups[source_group.oid] = section
                await session.flush()
                for item_ref in sorted(source_group.item_refs, key=lambda ref: ref.order_number):
                    source_item = source_items[item_ref.oid]
                    item_ext = _ext(source_item.extensions)
                    unit = units.get(source_item.measurement_unit_oid or "")
                    source_label = str(
                        item_ext.get("label") or source_item.question or source_item.name
                    )
                    # Rave permits prompts longer than the compact UI label column.
                    # Preserve the complete content in question and bound only the
                    # presentation label that is stored as VARCHAR(500).
                    question = source_item.question
                    if len(source_label) > 500 and not question:
                        question = source_label
                    field = FieldDefinition(
                        form_section_id=section.id,
                        odm_oid=source_item.oid,
                        odm_id=source_item.oid,
                        label=source_label[:500],
                        question=question,
                        variable_name=source_item.name,
                        control_type=str(item_ext.get("controlType") or "text"),
                        data_type=source_item.data_type,
                        display_order=item_ref.order_number,
                        is_required=item_ref.mandatory,
                        codelist_id=codelists[source_item.code_list_oid].id
                        if source_item.code_list_oid
                        else None,
                        max_length=source_item.length,
                        decimal_precision=source_item.significant_digits,
                        default_value=item_ext.get("defaultValue"),
                        help_text=item_ext.get("helpText"),
                        unit=unit.symbol if unit else item_ext.get("unit"),
                        data_format=item_ext.get("dataFormat"),
                        allows_partial_date=bool(item_ext.get("allowsPartialDate", False)),
                        source_document=bool(item_ext.get("sourceDocument", True)),
                        query_future_date=bool(item_ext.get("queryFutureDate", False)),
                        query_nonconformance=bool(item_ext.get("queryNonconformance", False)),
                        breaks_signature=bool(item_ext.get("breaksSignature", True)),
                        review_group=item_ext.get("reviewGroup"),
                        dynamic_search_config=item_ext.get("dynamicSearchConfig"),
                    )
                    session.add(field)
                    fields[source_item.oid] = field
        await session.flush()

        visits: dict[str, VisitDefinition] = {}
        for index, source in enumerate(mdv.study_events):
            ext = _ext(source.extensions)
            definition_kind = str(ext.get("definitionKind") or "visit")
            addable = bool(ext.get("addable", False))
            if addable and definition_kind not in {"visit", "cycle_visit"}:
                raise ValidationError(
                    "Only a visit can be addable",
                    details={"field": "addable", "study_event_oid": source.oid},
                )
            row = VisitDefinition(
                study_version_id=version.id,
                odm_oid=source.oid,
                name=source.name,
                visit_number=int(ext.get("visitNumber", index + 1)),
                visit_type=source.event_type,
                definition_kind=definition_kind,
                category=ext.get("category"),
                subtype=ext.get("subtype"),
                target_day=ext.get("targetDay"),
                window_before=ext.get("windowBefore"),
                window_after=ext.get("windowAfter"),
                repeat_min=ext.get("repeatMin"),
                repeat_max=ext.get("repeatMax"),
                cycle_length=ext.get("cycleLength"),
                display_order=index,
                is_required=True,
                addable=addable,
            )
            session.add(row)
            visits[source.oid] = row
        await session.flush()
        for source in mdv.study_events:
            parent_oid = _ext(source.extensions).get("parentOID")
            if parent_oid:
                visits[source.oid].parent_folder_id = visits[parent_oid].id

        if has_phase_extension:
            phase_by_oid: dict[str, SubjectPhaseDefinition] = {}
            for source in phase_sources:
                phase = SubjectPhaseDefinition(
                    design_version_id=version.id,
                    odm_oid=source.oid,
                    name=source.name.strip(),
                    phase_type=SubjectPhaseType(source.phase_type),
                    display_order=source.display_order,
                )
                session.add(phase)
                phase_by_oid[source.oid] = phase
            await session.flush()
            for source in phase_sources:
                phase = phase_by_oid[source.oid]
                for display_order, visit_oid in enumerate(source.visit_oids, start=1):
                    session.add(
                        SubjectPhaseVisitDefinition(
                            subject_phase_definition_id=phase.id,
                            visit_definition_id=visits[visit_oid].id,
                            display_order=display_order,
                        )
                    )
            for source in phase_transition_sources:
                session.add(
                    SubjectPhaseTransition(
                        design_version_id=version.id,
                        odm_oid=source.oid,
                        from_phase_id=phase_by_oid[source.from_phase_oid].id,
                        to_phase_id=phase_by_oid[source.to_phase_oid].id,
                        label=source.label,
                        condition_expression=source.condition_expression,
                    )
                )
            await session.flush()

        form_by_oid = {
            row.odm_oid: row
            for row in (
                await session.execute(
                    select(FormDefinition).where(FormDefinition.study_version_id == version.id)
                )
            )
            .scalars()
            .all()
        }
        schedule = ScheduleOfAssessment(design_version_id=version.id)
        session.add(schedule)
        await session.flush()
        order = 0
        for event in mdv.study_events:
            for form_ref in event.form_refs:
                order += 1
                session.add(
                    ScheduleOfAssessmentEntry(
                        schedule_of_assessment_id=schedule.id,
                        form_definition_id=form_by_oid[form_ref.oid].id,
                        visit_definition_id=visits[event.oid].id,
                        display_order=order,
                    )
                )

        for source in metadata_ext.get("codingSettings", []):
            field_oid = source.get("fieldItemOID")
            session.add(
                CodingSetting(
                    design_version_id=version.id,
                    field_definition_id=fields[field_oid].id if field_oid else None,
                    dictionary_reference=str(source["dictionaryReference"]),
                    dictionary_version=source.get("dictionaryVersion"),
                    coding_level=source.get("codingLevel"),
                    locale=source.get("locale"),
                    priority=int(source.get("priority", 100)),
                    approval_required=bool(source.get("approvalRequired", True)),
                    auto_approval=bool(source.get("autoApproval", False)),
                    coding_rule=_serialize_coding_rule(source.get("codingRule")),
                )
            )
        for source in metadata_ext.get("crfAccess", []):
            form_oid = source.get("formOID")
            field_oid = source.get("itemOID")
            session.add(
                CrfAccessDefinition(
                    design_version_id=version.id,
                    role=str(source["role"]),
                    form_definition_id=form_by_oid[form_oid].id if form_oid else None,
                    field_definition_id=fields[field_oid].id if field_oid else None,
                    can_read=bool(source.get("canRead", False)),
                    can_write=bool(source.get("canWrite", False)),
                    blinded=bool(source.get("blinded", False)),
                    unblind_role=source.get("unblindRole"),
                )
            )

        for source in mdv.conditions:
            ext = _ext(source.extensions)
            schema_version = int(
                ext.get("schemaVersion", source.expression.get("schemaVersion", 1))
            )
            if schema_version == 2:
                RuleDefinitionV2.model_validate(source.expression)
            canonical_rule = validate_rule(source.expression)
            session.add(
                EditCheck(
                    study_version_id=version.id,
                    odm_oid=source.oid,
                    name=source.name,
                    description=source.description,
                    rule_json=canonical_rule,
                    severity=str(ext.get("severity") or "error"),
                    is_active=bool(ext.get("active", True)),
                    schema_version=schema_version,
                    needs_retesting=bool(ext.get("needsRetesting", False)),
                    retesting_reason=ext.get("retestingReason"),
                )
            )
        for source in mdv.methods:
            ext = _ext(source.extensions)
            validate_derivation_expression(source.expression)
            session.add(
                DerivationDefinition(
                    study_version_id=version.id,
                    target_field_definition_id=fields[source.target_item_oid].id,
                    odm_oid=source.oid,
                    name=source.name,
                    expression_json=source.expression,
                    execution_order=source.order_number,
                    is_active=bool(ext.get("active", True)),
                    needs_retesting=bool(ext.get("needsRetesting", False)),
                    retesting_reason=ext.get("retestingReason"),
                )
            )
        await session.flush()

        digest = hashlib.sha256(_canonical_payload(document)).hexdigest()
        await audit_service.record(
            session,
            entity_type="study_version",
            entity_id=version.id,
            action="odm_import",
            module=Module.DESIGNER,
            study_id=study_id,
            actor_id=actor_id,
            new_value=f"profile={document.profile}; sha256={digest}; counts={self._counts(document)}",
        )
        return OdmImportResult(
            studyVersionId=version.id,
            documentSha256=digest,
            counts=self._counts(document),
        )

    async def _prepare_phase_target(
        self,
        session: AsyncSession,
        *,
        version_id: UUID,
        replace_defaults: bool,
    ) -> bool:
        """Accept an empty/default phase scaffold and optionally remove defaults.

        Draft creation seeds a standard phase flow before an ODM import target
        is selected. That untouched scaffold is logically empty for import. A
        designer-authored or partially deleted flow is not empty and must never
        be overwritten.
        """
        phases = list(
            (
                await session.execute(
                    select(SubjectPhaseDefinition)
                    .where(SubjectPhaseDefinition.design_version_id == version_id)
                    .options(selectinload(SubjectPhaseDefinition.visits))
                    .order_by(
                        SubjectPhaseDefinition.display_order,
                        SubjectPhaseDefinition.id,
                    )
                )
            )
            .scalars()
            .unique()
            .all()
        )
        transitions = list(
            (
                await session.execute(
                    select(SubjectPhaseTransition).where(
                        SubjectPhaseTransition.design_version_id == version_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if not phases and not transitions:
            return False

        expected_phases = [
            (display_order, name, phase_type)
            for display_order, (name, phase_type) in enumerate(DEFAULT_SUBJECT_PHASES, start=1)
        ]
        actual_phases = [
            (
                phase.display_order,
                phase.name,
                SubjectPhaseType(phase.phase_type),
            )
            for phase in phases
        ]
        phase_name_by_id = {phase.id: phase.name for phase in phases}
        actual_transitions = {
            (
                phase_name_by_id.get(transition.from_phase_id),
                phase_name_by_id.get(transition.to_phase_id),
            )
            for transition in transitions
        }
        untouched_defaults = (
            actual_phases == expected_phases
            and actual_transitions == set(DEFAULT_SUBJECT_PHASE_TRANSITIONS)
            and all(
                phase.deleted_at is None
                and phase.updated_at is None
                and not phase.visit_definition_ids
                for phase in phases
            )
            and all(
                transition.deleted_at is None and transition.updated_at is None
                for transition in transitions
            )
        )
        if not untouched_defaults:
            raise BusinessRuleError(
                "ODM import target must be an empty draft",
                details={"design_version_id": str(version_id), "resource": "subject_phases"},
            )
        if not replace_defaults:
            return True

        phase_ids = [phase.id for phase in phases]
        await session.execute(
            delete(SubjectPhaseVisitDefinition).where(
                SubjectPhaseVisitDefinition.subject_phase_definition_id.in_(phase_ids)
            )
        )
        await session.execute(
            delete(SubjectPhaseTransition).where(
                SubjectPhaseTransition.design_version_id == version_id
            )
        )
        await session.execute(
            delete(SubjectPhaseDefinition).where(
                SubjectPhaseDefinition.design_version_id == version_id
            )
        )
        await session.flush()
        return False

    async def _target_version(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        target_version_id: UUID | None,
        version_number: str | None,
        document: OdmDocument,
    ) -> StudyVersion:
        if target_version_id:
            version = await session.get(StudyVersion, target_version_id)
            if version is None or version.study_id != study_id:
                raise NotFoundError("Target design version not found")
            if version.status != StudyVersionStatus.draft:
                raise BusinessRuleError("ODM import target must be a draft design version")
            return version
        number = version_number or document.study.meta_data_version.name
        existing = await session.scalar(
            select(StudyVersion.id).where(
                StudyVersion.study_id == study_id,
                StudyVersion.version_number == number,
            )
        )
        if existing is not None:
            raise BusinessRuleError(
                "A design version with this version number already exists",
                details={"version_number": number},
            )
        metadata_version_oid = document.study.meta_data_version.oid
        existing_metadata_version = await session.scalar(
            select(StudyVersion.id).where(
                StudyVersion.study_id == study_id,
                StudyVersion.odm_metadata_version_oid == metadata_version_oid,
            )
        )
        if existing_metadata_version is not None:
            raise BusinessRuleError(
                "A design version with this ODM metadata version OID already exists",
                details={
                    "metadata_version_oid": metadata_version_oid,
                    "existing_design_version_id": str(existing_metadata_version),
                },
            )
        version = StudyVersion(
            study_id=study_id,
            version_number=number,
            status=StudyVersionStatus.draft,
            odm_study_oid=document.study.oid,
            odm_metadata_version_oid=document.study.meta_data_version.oid,
        )
        session.add(version)
        await session.flush()
        return version

    async def _require_empty(self, session: AsyncSession, version_id: UUID) -> None:
        version_models = (
            VisitDefinition,
            FormDefinition,
            Codelist,
            EditCheck,
            MeasurementUnitDefinition,
            DerivationDefinition,
        )
        design_version_models = (ScheduleOfAssessment, CodingSetting, CrfAccessDefinition)
        for model, column in (
            *((model, model.study_version_id) for model in version_models),
            *((model, model.design_version_id) for model in design_version_models),
        ):
            count = await session.scalar(
                select(func.count()).select_from(model).where(column == version_id)
            )
            if count:
                raise BusinessRuleError(
                    "ODM import target must be an empty draft",
                    details={"design_version_id": str(version_id)},
                )

    @staticmethod
    def _counts(document: OdmDocument) -> dict[str, int]:
        mdv = document.study.meta_data_version
        subject_phases, subject_phase_transitions = subject_phase_extension(mdv)
        return {
            "study_events": len(mdv.study_events),
            "forms": len(mdv.forms),
            "item_groups": len(mdv.item_groups),
            "items": len(mdv.items),
            "code_lists": len(mdv.code_lists),
            "measurement_units": len(mdv.measurement_units),
            "conditions": len(mdv.conditions),
            "methods": len(mdv.methods),
            "subject_phases": len(subject_phases),
            "subject_phase_transitions": len(subject_phase_transitions),
        }

    @staticmethod
    def _extensions_used(document: OdmDocument) -> list[str]:
        dumped = document.model_dump(by_alias=True)
        return [AURINARA_EXTENSION] if AURINARA_EXTENSION in json.dumps(dumped) else []


odm20_service = Odm20Service()

__all__ = ["Odm20Service", "odm20_service"]
