"""Read-only published-design view models — the Design_Consumption_Contract.

These frozen view models are the sole shape through which the EDC_Module reads
a ``Published_Design``. They are immutable (``frozen=True``) and expose no
mutation path: the EDC_Module consumes definitions read-only (R2.6) and can
never write Designer state through them. The ``DesignConsumptionService``
(task 8.1) constructs these views from published ORM entities and returns them
in place of the entities themselves, so the EDC_Module never holds a mutable
Designer record.

Satisfies Requirements:
  - 2.5: The contract returns only Published_Design content.
  - 2.6: The EDC_Module reads Designer_Definitions only through this contract and
         treats every consumed definition as read-only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.shared.base import UtcDatetime

# ---------------------------------------------------------------------------
# Frozen base — immutable, ORM-constructible, no mutation path (R2.6)
# ---------------------------------------------------------------------------


class FrozenView(BaseModel):
    """Base for every published-design view model.

    ``frozen=True`` makes instances hashable and rejects attribute assignment,
    so a consumer holding a view cannot mutate it. ``from_attributes=True`` lets
    the consumption service build a view directly from a published ORM entity
    while still returning an immutable value object rather than the entity.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)


# ---------------------------------------------------------------------------
# Field / form views (R4.1, R4.2 — read side)
# ---------------------------------------------------------------------------


class FieldDefinitionView(FrozenView):
    """Immutable view of a published field definition."""

    id: UUID
    form_section_id: UUID
    label: str
    question: str | None = None
    caption: str | None = None
    text_align: str = "left"
    variable_name: str
    record_id: str | None = None
    crf_id: str | None = None
    odm_id: str | None = None
    odm_oid: str | None = None
    control_type: str
    data_type: str
    display_order: int
    is_required: bool
    codelist_id: UUID | None = None
    default_value: str | None = None
    help_text: str | None = None
    unit: str | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    max_length: int | None = None
    decimal_precision: int | None = None
    regex_validation: str | None = None
    visibility_rule: dict[str, Any] | None = None
    is_read_only: bool = False
    is_calculated: bool = False
    calculation_expression: str | None = None
    data_format: str | None = None
    allows_partial_date: bool = False
    source_document: bool = True
    query_future_date: bool = False
    query_nonconformance: bool = False
    breaks_signature: bool = True
    review_group: str | None = None
    dynamic_search_config: dict[str, Any] | None = None


class FormDefinitionView(FrozenView):
    """Immutable view of a published form definition and its fields."""

    id: UUID
    odm_oid: str | None = None
    design_version_id: UUID
    name: str
    form_code: str
    display_order: int
    is_repeating: bool
    requires_signature: bool = False
    form_type: str = "simple"
    access_type: str = "open_access"
    domain: str | None = None
    label: str | None = None
    grid_rows: int | None = None
    grid_columns: int | None = None
    header_name: str | None = None
    detail_name: str | None = None
    detail_type: str | None = None
    show_variable_name: bool = False
    show_crf_id: bool = False
    show_odm_id: bool = False
    fields: tuple[FieldDefinitionView, ...] = Field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Visit / cycle / arm views (R4.2, R4.4, R4.5 — read side)
# ---------------------------------------------------------------------------


class VisitDefinitionView(FrozenView):
    """Immutable view of a published visit definition.

    A cycle is a visit of ``visit_type == 'cycle'`` carrying the cycle metadata
    (``repeat_min`` / ``repeat_max`` / ``cycle_length``); plain visits leave
    those null. Consumers distinguish a cycle by ``visit_type == 'cycle'``.
    """

    id: UUID
    odm_oid: str | None = None
    design_version_id: UUID
    name: str
    visit_number: int
    visit_type: str
    definition_kind: str = "visit"
    parent_folder_id: UUID | None = None
    category: str | None = None
    subtype: str | None = None
    target_day: int | None = None
    window_before: int | None = None
    window_after: int | None = None
    display_order: int
    is_required: bool
    addable: bool = False
    repeat_min: int | None = None
    repeat_max: int | None = None
    cycle_length: int | None = None


class ArmDefinitionView(FrozenView):
    """Immutable view of a published arm/treatment-group definition."""

    id: UUID
    design_version_id: UUID
    name: str
    display_order: int
    description: str | None = None


# ---------------------------------------------------------------------------
# Edit-check / codelist views (R5, R6 — read side)
# ---------------------------------------------------------------------------


class EditCheckRuleView(FrozenView):
    """Immutable view of a published, declaratively stored edit-check rule."""

    id: UUID
    odm_oid: str | None = None
    schema_version: int = 1
    needs_retesting: bool = False
    design_version_id: UUID
    name: str
    description: str | None = None
    rule_json: dict[str, Any]
    severity: str
    is_active: bool


class CodelistItemView(FrozenView):
    """Immutable view of a published codelist item."""

    id: UUID
    code: str
    label: str
    display_order: int
    normal_low: Decimal | None = None
    normal_high: Decimal | None = None
    specify: bool = False


class CodelistView(FrozenView):
    """Immutable view of a published codelist and its items."""

    id: UUID
    odm_oid: str | None = None
    design_version_id: UUID
    name: str
    code: str
    items: tuple[CodelistItemView, ...] = Field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Subject-phase / schedule-of-assessment views (R3, R4.1 — read side)
# ---------------------------------------------------------------------------


class SubjectPhaseDefinitionView(FrozenView):
    """Immutable view of a published subject phase definition."""

    id: UUID
    design_version_id: UUID
    name: str
    phase_type: str
    display_order: int
    visit_definition_ids: tuple[UUID, ...] = Field(default_factory=tuple)


class SubjectPhaseTransitionView(FrozenView):
    """Immutable view of a published subject-phase-to-phase transition edge."""

    id: UUID
    design_version_id: UUID
    from_phase_id: UUID
    to_phase_id: UUID
    label: str | None = None
    condition_expression: str | None = None


class ScheduleOfAssessmentEntryView(FrozenView):
    """Immutable view of one form/procedure-to-visit mapping entry.

    ``visit_definition_id`` references a plain visit or a cycle (a cycle is now a
    visit of ``visit_type == 'cycle'``).
    """

    id: UUID
    form_definition_id: UUID | None = None
    procedure_name: str | None = None
    visit_definition_id: UUID | None = None


class ScheduleOfAssessmentView(FrozenView):
    """Immutable view of a published schedule of assessment (R4.1)."""

    design_version_id: UUID
    arm_definition_id: UUID | None = None
    entries: tuple[ScheduleOfAssessmentEntryView, ...] = Field(default_factory=tuple)


# ---------------------------------------------------------------------------
# CRF access / raw-data variable / coding views (R4.6, R4.7, R4.8 — read side)
# ---------------------------------------------------------------------------


class CrfAccessDefinitionView(FrozenView):
    """Immutable view of a published per-role CRF read/write access definition.

    ``blinded`` applies at whichever scope the grant expresses (form or field);
    ``unblind_role`` optionally names a role permitted to unblind.
    """

    id: UUID
    design_version_id: UUID
    role: str
    form_definition_id: UUID | None = None
    field_definition_id: UUID | None = None
    can_read: bool
    can_write: bool
    blinded: bool = False
    unblind_role: str | None = None


class RawDataVariableSettingView(FrozenView):
    """Immutable view of a published raw-data variable setting (R4.7).

    ``label`` and ``suffix`` are the dataset-generation configuration columns.
    """

    id: UUID
    design_version_id: UUID
    name: str
    data_type: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    label: str | None = None
    suffix: str | None = None
    field_definition_id: UUID | None = None
    year_suffix: str | None = None
    month_suffix: str | None = None
    day_suffix: str | None = None


class CodingSettingView(FrozenView):
    """Immutable view of a published coding setting (R4.8)."""

    id: UUID
    design_version_id: UUID
    field_definition_id: UUID | None = None
    dictionary_reference: str
    coding_rule: str | None = None
    dictionary_version: str | None = None
    coding_level: str | None = None
    locale: str | None = None
    priority: int = 100
    approval_required: bool = True
    auto_approval: bool = False


# ---------------------------------------------------------------------------
# Dependency views (form-to-form / visit-to-visit — read side)
# ---------------------------------------------------------------------------


class FormDependencyView(FrozenView):
    """Immutable view of a published form-to-form dependency edge."""

    id: UUID
    form_definition_id: UUID
    depends_on_form_definition_id: UUID
    dependency_type: str
    condition_expression: str | None = None


class VisitDependencyView(FrozenView):
    """Immutable view of a published visit-to-visit dependency edge.

    Includes the ``'cycle_member'`` edges migrated from the former cycle
    membership, surfacing old cycle-membership information through the unified
    model.
    """

    id: UUID
    visit_definition_id: UUID
    depends_on_visit_definition_id: UUID
    dependency_type: str
    condition_expression: str | None = None


# ---------------------------------------------------------------------------
# Aggregate published-design view (R2.5 — only published content)
# ---------------------------------------------------------------------------


class PublishedDesignView(FrozenView):
    """Immutable aggregate view of a whole Published_Design.

    This is the top-level object returned by ``get_published_design`` /
    ``get_latest_published_design``. Every nested collection is a ``tuple`` so
    the entire bundle is immutable end to end (R2.6). It carries only published
    content (R2.5); draft versions never reach this view.
    """

    design_version_id: UUID
    study_id: UUID
    version_number: str
    status: str
    published_at: UtcDatetime | None = None
    published_by: UUID | None = None
    permits_unscheduled_visits: bool = False

    forms: tuple[FormDefinitionView, ...] = Field(default_factory=tuple)
    visit_definitions: tuple[VisitDefinitionView, ...] = Field(default_factory=tuple)
    arm_definitions: tuple[ArmDefinitionView, ...] = Field(default_factory=tuple)
    edit_check_rules: tuple[EditCheckRuleView, ...] = Field(default_factory=tuple)
    codelists: tuple[CodelistView, ...] = Field(default_factory=tuple)
    subject_phase_definitions: tuple[SubjectPhaseDefinitionView, ...] = Field(default_factory=tuple)
    schedule_of_assessment: ScheduleOfAssessmentView | None = None
    crf_access_definitions: tuple[CrfAccessDefinitionView, ...] = Field(default_factory=tuple)
    raw_data_variable_settings: tuple[RawDataVariableSettingView, ...] = Field(
        default_factory=tuple
    )
    coding_settings: tuple[CodingSettingView, ...] = Field(default_factory=tuple)
    form_dependencies: tuple[FormDependencyView, ...] = Field(default_factory=tuple)
    visit_dependencies: tuple[VisitDependencyView, ...] = Field(default_factory=tuple)
    subject_phase_transitions: tuple[SubjectPhaseTransitionView, ...] = Field(default_factory=tuple)


__all__ = [
    "ArmDefinitionView",
    "CodelistItemView",
    "CodelistView",
    "CodingSettingView",
    "CrfAccessDefinitionView",
    "EditCheckRuleView",
    "FieldDefinitionView",
    "FormDefinitionView",
    "FormDependencyView",
    "FrozenView",
    "PublishedDesignView",
    "RawDataVariableSettingView",
    "ScheduleOfAssessmentEntryView",
    "ScheduleOfAssessmentView",
    "SubjectPhaseDefinitionView",
    "SubjectPhaseTransitionView",
    "VisitDefinitionView",
    "VisitDependencyView",
]
