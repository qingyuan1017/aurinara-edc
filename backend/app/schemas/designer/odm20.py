"""Aurinara's versioned ODM 2.0 JSON Designer metadata profile."""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from app.core.odm_oid import is_valid_odm_oid

ODM_VERSION = "2.0"
ODM_PROFILE = "urn:aurinara:odm:profile:designer-metadata:1"
AURINARA_EXTENSION = "urn:aurinara:odm:extension:1"


class OdmModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class OdmReference(OdmModel):
    oid: str
    mandatory: bool = False
    order_number: int = Field(ge=0, alias="orderNumber")


class OdmCodeListItem(OdmModel):
    coded_value: str = Field(alias="codedValue")
    decode: str
    order_number: int = Field(ge=0, alias="orderNumber")
    specify: bool = False


class OdmCodeList(OdmModel):
    oid: str
    name: str
    data_type: str = Field(default="text", alias="dataType")
    items: list[OdmCodeListItem] = Field(default_factory=list)


class OdmMeasurementUnit(OdmModel):
    oid: str
    name: str
    symbol: str
    conversion_factor: float | None = Field(None, alias="conversionFactor")
    conversion_offset: float | None = Field(None, alias="conversionOffset")


class OdmItem(OdmModel):
    oid: str
    name: str
    data_type: str = Field(alias="dataType")
    question: str | None = None
    length: int | None = Field(None, ge=0)
    significant_digits: int | None = Field(None, ge=0, alias="significantDigits")
    code_list_oid: str | None = Field(None, alias="codeListOID")
    measurement_unit_oid: str | None = Field(None, alias="measurementUnitOID")
    method_oid: str | None = Field(None, alias="methodOID")
    extensions: dict[str, Any] = Field(default_factory=dict)


class OdmItemGroup(OdmModel):
    oid: str
    name: str
    repeating: bool = False
    item_refs: list[OdmReference] = Field(default_factory=list, alias="itemRefs")
    extensions: dict[str, Any] = Field(default_factory=dict)


class OdmForm(OdmModel):
    oid: str
    name: str
    repeating: bool = False
    item_group_refs: list[OdmReference] = Field(default_factory=list, alias="itemGroupRefs")
    extensions: dict[str, Any] = Field(default_factory=dict)


class OdmStudyEvent(OdmModel):
    oid: str
    name: str
    repeating: bool = False
    event_type: Literal["scheduled", "unscheduled", "common"] = Field(
        default="scheduled", alias="type"
    )
    form_refs: list[OdmReference] = Field(default_factory=list, alias="formRefs")
    extensions: dict[str, Any] = Field(default_factory=dict)


class OdmCondition(OdmModel):
    oid: str
    name: str
    description: str | None = None
    expression: dict[str, Any]
    extensions: dict[str, Any] = Field(default_factory=dict)


class OdmMethod(OdmModel):
    oid: str
    name: str
    target_item_oid: str = Field(alias="targetItemOID")
    expression: dict[str, Any]
    order_number: int = Field(default=1, ge=0, alias="orderNumber")
    extensions: dict[str, Any] = Field(default_factory=dict)


class OdmSubjectPhase(OdmModel):
    """Aurinara subject-lifecycle phase carried in the metadata extension."""

    oid: str
    name: str = Field(min_length=1, max_length=100)
    phase_type: Literal["registered", "screen_failure", "common", "complete", "arm"] = Field(
        alias="phaseType"
    )
    display_order: int = Field(ge=1, le=999, alias="displayOrder")
    visit_oids: list[str] = Field(default_factory=list, alias="visitOIDs")


class OdmSubjectPhaseTransition(OdmModel):
    """Directed transition between two extension subject phases."""

    oid: str
    from_phase_oid: str = Field(alias="fromPhaseOID")
    to_phase_oid: str = Field(alias="toPhaseOID")
    label: str | None = Field(None, max_length=255)
    condition_expression: str | None = Field(None, max_length=10000, alias="conditionExpression")


class OdmMetaDataVersion(OdmModel):
    oid: str
    name: str
    study_events: list[OdmStudyEvent] = Field(default_factory=list, alias="studyEvents")
    forms: list[OdmForm] = Field(default_factory=list)
    item_groups: list[OdmItemGroup] = Field(default_factory=list, alias="itemGroups")
    items: list[OdmItem] = Field(default_factory=list)
    code_lists: list[OdmCodeList] = Field(default_factory=list, alias="codeLists")
    measurement_units: list[OdmMeasurementUnit] = Field(
        default_factory=list, alias="measurementUnits"
    )
    conditions: list[OdmCondition] = Field(default_factory=list)
    methods: list[OdmMethod] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


def subject_phase_extension(
    metadata_version: OdmMetaDataVersion,
) -> tuple[list[OdmSubjectPhase], list[OdmSubjectPhaseTransition]]:
    """Return typed phase extension rows from a validated metadata version."""
    extension = metadata_version.extensions.get(AURINARA_EXTENSION, {})
    if not isinstance(extension, dict):
        raise ValueError("Aurinara metadata extension must be an object")
    raw_phases = extension.get("subjectPhases", [])
    raw_transitions = extension.get("subjectPhaseTransitions", [])
    if not isinstance(raw_phases, list) or not isinstance(raw_transitions, list):
        raise ValueError("subject phase extensions must be arrays")
    try:
        phases = [OdmSubjectPhase.model_validate(row) for row in raw_phases]
        transitions = [OdmSubjectPhaseTransition.model_validate(row) for row in raw_transitions]
    except PydanticValidationError as exc:
        raise ValueError(f"Subject phase extension is invalid: {exc}") from exc
    return phases, transitions


class OdmStudy(OdmModel):
    oid: str
    study_name: str = Field(alias="studyName")
    protocol_name: str = Field(alias="protocolName")
    meta_data_version: OdmMetaDataVersion = Field(alias="metaDataVersion")


class OdmDocument(OdmModel):
    odm_version: Literal["2.0"] = Field(default="2.0", alias="odmVersion")
    profile: Literal[ODM_PROFILE] = ODM_PROFILE
    file_type: Literal["Snapshot"] = Field(default="Snapshot", alias="fileType")
    file_oid: str = Field(alias="fileOID")
    study: OdmStudy

    @model_validator(mode="after")
    def validate_references(self) -> OdmDocument:
        mdv = self.study.meta_data_version
        metadata_extension = mdv.extensions.get(AURINARA_EXTENSION, {})
        if not isinstance(metadata_extension, dict):
            raise ValueError("Aurinara metadata extension must be an object")
        subject_phases, subject_phase_transitions = subject_phase_extension(mdv)
        has_phase_extension = (
            "subjectPhases" in metadata_extension or "subjectPhaseTransitions" in metadata_extension
        )
        if has_phase_extension and not subject_phases:
            raise ValueError("subjectPhases must contain at least one phase")
        if not is_valid_odm_oid(self.file_oid):
            raise ValueError("fileOID is not a valid ODM OID")
        objects = [
            self.study.oid,
            mdv.oid,
            *(x.oid for x in mdv.study_events),
            *(x.oid for x in mdv.forms),
            *(x.oid for x in mdv.item_groups),
            *(x.oid for x in mdv.items),
            *(x.oid for x in mdv.code_lists),
            *(x.oid for x in mdv.measurement_units),
            *(x.oid for x in mdv.conditions),
            *(x.oid for x in mdv.methods),
            *(x.oid for x in subject_phases),
            *(x.oid for x in subject_phase_transitions),
        ]
        invalid = sorted({oid for oid in objects if not is_valid_odm_oid(oid)})
        if invalid:
            raise ValueError(f"Invalid ODM OID(s): {', '.join(invalid)}")
        duplicates = sorted(oid for oid, count in Counter(objects).items() if count > 1)
        if duplicates:
            raise ValueError(f"Duplicate ODM OID(s): {', '.join(duplicates)}")

        forms = {x.oid for x in mdv.forms}
        groups = {x.oid for x in mdv.item_groups}
        items = {x.oid for x in mdv.items}
        codelists = {x.oid for x in mdv.code_lists}
        units = {x.oid for x in mdv.measurement_units}
        methods = {x.oid for x in mdv.methods}
        events = {x.oid for x in mdv.study_events}
        event_by_oid = {x.oid: x for x in mdv.study_events}
        phase_oids = {x.oid for x in subject_phases}
        missing: set[str] = set()
        for event in mdv.study_events:
            missing.update(ref.oid for ref in event.form_refs if ref.oid not in forms)
        for form in mdv.forms:
            missing.update(ref.oid for ref in form.item_group_refs if ref.oid not in groups)
        for group in mdv.item_groups:
            missing.update(ref.oid for ref in group.item_refs if ref.oid not in items)
        for item in mdv.items:
            if item.code_list_oid and item.code_list_oid not in codelists:
                missing.add(item.code_list_oid)
            if item.measurement_unit_oid and item.measurement_unit_oid not in units:
                missing.add(item.measurement_unit_oid)
            if item.method_oid and item.method_oid not in methods:
                missing.add(item.method_oid)
        missing.update(
            method.target_item_oid for method in mdv.methods if method.target_item_oid not in items
        )
        for event in mdv.study_events:
            extension = event.extensions.get(AURINARA_EXTENSION, {})
            if isinstance(extension, dict):
                parent_oid = extension.get("parentOID")
                if parent_oid and parent_oid not in events:
                    missing.add(parent_oid)
        for phase in subject_phases:
            missing.update(oid for oid in phase.visit_oids if oid not in events)
        for transition in subject_phase_transitions:
            if transition.from_phase_oid not in phase_oids:
                missing.add(transition.from_phase_oid)
            if transition.to_phase_oid not in phase_oids:
                missing.add(transition.to_phase_oid)
        if missing:
            raise ValueError(f"Dangling ODM reference(s): {', '.join(sorted(missing))}")

        duplicate_phase_names = sorted(
            name
            for name, count in Counter(
                phase.name.strip().casefold() for phase in subject_phases
            ).items()
            if count > 1
        )
        if duplicate_phase_names:
            raise ValueError("Duplicate subject phase name(s): " + ", ".join(duplicate_phase_names))
        for phase in subject_phases:
            if len(set(phase.visit_oids)) != len(phase.visit_oids):
                raise ValueError(f"Subject phase {phase.oid} contains duplicate visit references")
            if phase.phase_type == "arm" and phase.visit_oids:
                raise ValueError(
                    f"Subject phase {phase.oid} of type {phase.phase_type} cannot contain visits"
                )
            common_visits = sorted(
                oid for oid in phase.visit_oids if event_by_oid[oid].event_type == "common"
            )
            if common_visits:
                raise ValueError(
                    f"Subject phase {phase.oid} cannot contain common study event(s): "
                    + ", ".join(common_visits)
                )
        transition_pairs = [
            (transition.from_phase_oid, transition.to_phase_oid)
            for transition in subject_phase_transitions
        ]
        duplicate_transition_pairs = sorted(
            pair for pair, count in Counter(transition_pairs).items() if count > 1
        )
        if duplicate_transition_pairs:
            raise ValueError("Duplicate subject phase transition(s) are not allowed")
        if any(source == target for source, target in transition_pairs):
            raise ValueError("A subject phase cannot transition to itself")
        coding_settings = metadata_extension.get("codingSettings", [])
        access_rows = metadata_extension.get("crfAccess", [])
        if not isinstance(coding_settings, list) or not all(
            isinstance(row, dict)
            and isinstance(row.get("dictionaryReference"), str)
            and row["dictionaryReference"].strip()
            and (row.get("fieldItemOID") is None or row.get("fieldItemOID") in items)
            for row in coding_settings
        ):
            raise ValueError("codingSettings extension is invalid or has a dangling item reference")
        if not isinstance(access_rows, list) or not all(
            isinstance(row, dict)
            and isinstance(row.get("role"), str)
            and row["role"].strip()
            and (row.get("formOID") is None or row.get("formOID") in forms)
            and (row.get("itemOID") is None or row.get("itemOID") in items)
            for row in access_rows
        ):
            raise ValueError("crfAccess extension is invalid or has a dangling reference")
        method_targets = [method.target_item_oid for method in mdv.methods]
        duplicate_targets = sorted(
            oid for oid, count in Counter(method_targets).items() if count > 1
        )
        if duplicate_targets:
            raise ValueError(
                f"Multiple methods target the same item(s): {', '.join(duplicate_targets)}"
            )

        allowed_extension = {AURINARA_EXTENSION}
        extension_maps = [mdv.extensions]
        extension_maps.extend(x.extensions for x in mdv.study_events)
        extension_maps.extend(x.extensions for x in mdv.forms)
        extension_maps.extend(x.extensions for x in mdv.item_groups)
        extension_maps.extend(x.extensions for x in mdv.items)
        extension_maps.extend(x.extensions for x in mdv.conditions)
        extension_maps.extend(x.extensions for x in mdv.methods)
        unknown = sorted(
            {key for values in extension_maps for key in values if key not in allowed_extension}
        )
        if unknown:
            raise ValueError(f"Unsupported ODM extension namespace(s): {', '.join(unknown)}")
        return self


class OdmValidationIssue(OdmModel):
    code: str
    message: str
    path: str | None = None
    entity_oid: str | None = Field(None, alias="entityOID")


class OdmValidationReport(OdmModel):
    valid: bool
    profile: str = ODM_PROFILE
    errors: list[OdmValidationIssue] = Field(default_factory=list)
    warnings: list[OdmValidationIssue] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    extensions_used: list[str] = Field(default_factory=list, alias="extensionsUsed")


class OdmImportResult(OdmModel):
    study_version_id: UUID = Field(alias="studyVersionId")
    document_sha256: str = Field(alias="documentSha256")
    counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[OdmValidationIssue] = Field(default_factory=list)


__all__ = [
    "AURINARA_EXTENSION",
    "ODM_PROFILE",
    "ODM_VERSION",
    "OdmDocument",
    "OdmImportResult",
    "OdmSubjectPhase",
    "OdmSubjectPhaseTransition",
    "OdmValidationIssue",
    "OdmValidationReport",
    "subject_phase_extension",
]
