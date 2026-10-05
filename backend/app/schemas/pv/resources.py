"""Pydantic v2 request/response contracts for PV/Safety resource routes.

These transport contracts back the authenticated ``/api/v1/pv`` routes for
Safety_Cases, Adverse_Event_Records, assessments, coding, narratives,
regulatory reports, reconciliation, attachments, and dashboards. They are thin
input/output shapes; every validation, transition, and transaction boundary is
owned by the PV service layer. Response schemas reuse the shared ``BaseSchema``
so timestamps serialize as UTC ISO-8601 and ORM rows validate directly.

No request schema accepts an EDC clinical field (Study_Version,
Clinical_Subject_Registry record, Visit_Instance, Form_Instance, Field_Value,
Query, SDV/review, freeze/lock, clinical signature, Clinical_Attachment,
clinical export) or a CTMS operational field; the PV service ownership guard
rejects such payloads defensively.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import ConfigDict, Field

from app.models.pv.assessment import SeriousnessCriterion
from app.models.pv.regulatory import ReportStatus
from app.models.pv.safety_case import CaseState, CaseVersionKind, CaseVersionStatus
from app.schemas.base import BaseCreateSchema, BaseSchema

# ---------------------------------------------------------------------------
# Safety cases and adverse events
# ---------------------------------------------------------------------------


class SafetyCaseCreate(BaseCreateSchema):
    """Request to open a Safety_Case bound to canonical Study/Site/Subject."""

    model_config = ConfigDict(extra="forbid")

    study_id: UUID
    site_id: UUID
    subject_reference: UUID
    case_type: str = Field(min_length=1, max_length=100)
    case_identifier: str | None = Field(default=None, max_length=100)


class SafetyCaseResponse(BaseSchema):
    """A PV Safety_Case as returned by the API."""

    id: UUID
    case_identifier: str
    study_id: UUID
    site_id: UUID
    subject_reference: UUID
    case_type: str
    lifecycle_state: str
    created_at: datetime
    updated_at: datetime | None = None


class AdverseEventCreate(BaseCreateSchema):
    """Request to capture one Adverse_Event_Record under a Safety_Case."""

    model_config = ConfigDict(extra="forbid")

    verbatim_term: str = Field(min_length=1, max_length=200)
    onset_date: date
    outcome: str = Field(min_length=1, max_length=100)
    resolution_date: date | None = None


class AdverseEventResponse(BaseSchema):
    """An Adverse_Event_Record as returned by the API."""

    id: UUID
    case_id: UUID
    verbatim_term: str
    onset_date: date
    outcome: str
    resolution_date: date | None = None
    created_at: datetime
    updated_at: datetime | None = None


class CaseTransitionRequest(BaseCreateSchema):
    """Request to move a Safety_Case to a new lifecycle state."""

    model_config = ConfigDict(extra="forbid")

    target: CaseState
    reason: str | None = Field(default=None, max_length=4000)


class CaseChangeRequest(BaseCreateSchema):
    """Request to change submitted Safety_Data with a Reason_For_Change."""

    model_config = ConfigDict(extra="forbid")

    reason_for_change: str = Field(min_length=1, max_length=4000)
    case_type: str | None = Field(default=None, min_length=1, max_length=100)


class CaseVersionResponse(BaseSchema):
    """A submitted Case_Version snapshot as returned by the API."""

    id: UUID
    case_id: UUID
    sequence_number: int
    version_kind: str
    status: str
    submitted_at: datetime | None = None
    submitted_by: UUID | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------


class SeriousnessRequest(BaseCreateSchema):
    """Request to record a Seriousness_Assessment for an adverse event."""

    model_config = ConfigDict(extra="forbid")

    serious: bool
    criteria: list[SeriousnessCriterion] = Field(default_factory=list)


class CausalityRequest(BaseCreateSchema):
    """Request to record a Causality_Assessment for an adverse event."""

    model_config = ConfigDict(extra="forbid")

    suspect_product: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)


class ExpectednessRequest(BaseCreateSchema):
    """Request to record an Expectedness_Assessment for an adverse event."""

    model_config = ConfigDict(extra="forbid")

    expected: bool
    reference_safety_information: str | None = None


class SeverityRequest(BaseCreateSchema):
    """Request to record a Severity_Grade for an adverse event."""

    model_config = ConfigDict(extra="forbid")

    grade: str = Field(min_length=1, max_length=100)


class AssessmentResponse(BaseSchema):
    """A generic assessment record as returned by the API."""

    id: UUID
    ae_id: UUID
    created_at: datetime
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Coding
# ---------------------------------------------------------------------------


class MedDraCodingRequest(BaseCreateSchema):
    """Request to assign a MedDRA coding to an adverse-event verbatim term."""

    model_config = ConfigDict(extra="forbid")

    term_id: str = Field(min_length=1, max_length=100)
    dictionary_version: str = Field(min_length=1, max_length=50)
    term_label: str | None = Field(default=None, max_length=255)


class WhoDrugCodingRequest(BaseCreateSchema):
    """Request to assign a WHODrug coding to a reported product."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    term_id: str = Field(min_length=1, max_length=100)
    dictionary_version: str = Field(min_length=1, max_length=50)
    term_label: str | None = Field(default=None, max_length=255)


class RecodeRequest(BaseCreateSchema):
    """Request to recode a prior assignment, retaining it immutably."""

    model_config = ConfigDict(extra="forbid")

    term_id: str = Field(min_length=1, max_length=100)
    dictionary_version: str = Field(min_length=1, max_length=50)
    term_label: str | None = Field(default=None, max_length=255)


class CodingResponse(BaseSchema):
    """A coding assignment as returned by the API."""

    id: UUID
    term_id: str
    term_label: str | None = None
    dictionary_version: str
    prior_coding_id: UUID | None = None
    assigned_by: UUID | None = None
    assigned_at: datetime
    created_at: datetime


# ---------------------------------------------------------------------------
# Narratives
# ---------------------------------------------------------------------------


class NarrativeCreate(BaseCreateSchema):
    """Request to author a Case_Narrative for a Safety_Case."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20000)


class NarrativeRevise(BaseCreateSchema):
    """Request to revise a Case_Narrative with a Reason_For_Change."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20000)
    reason_for_change: str = Field(min_length=1, max_length=4000)


class NarrativeResponse(BaseSchema):
    """A Case_Narrative (current text) as returned by the API."""

    id: UUID
    case_id: UUID
    current_text: str
    current_version_number: int
    created_at: datetime
    updated_at: datetime | None = None


class NarrativeVersionResponse(BaseSchema):
    """One retained Case_Narrative version as returned by the API."""

    id: UUID
    narrative_id: UUID
    version_number: int
    text_value: str
    reason_for_change: str | None = None
    authored_at: datetime
    authored_by: UUID | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Regulatory reporting
# ---------------------------------------------------------------------------


class ReportabilityRequest(BaseCreateSchema):
    """Request to evaluate reportability for a Safety_Case."""

    model_config = ConfigDict(extra="forbid")

    awareness_date: date


class ReportTransitionRequest(BaseCreateSchema):
    """Request to transition a Regulatory_Report (non-submit transitions)."""

    model_config = ConfigDict(extra="forbid")

    target: ReportStatus


class ReportSubmitRequest(BaseCreateSchema):
    """Request to submit a Pending Regulatory_Report with an E2B reference."""

    model_config = ConfigDict(extra="forbid")

    e2b_message_ref: str = Field(min_length=1, max_length=255)


class RegulatoryReportResponse(BaseSchema):
    """A Regulatory_Report as returned by the API."""

    id: UUID
    case_id: UUID
    rule_id: UUID | None = None
    report_type: str
    destination: str
    status: str
    awareness_date: date
    submitted_at: datetime | None = None
    submitted_by: UUID | None = None
    e2b_message_ref: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


class ReconciliationRunRequest(BaseCreateSchema):
    """Request to run EDC adverse-event reconciliation for a study."""

    model_config = ConfigDict(extra="forbid")

    study_id: UUID


class ReconciliationRunResponse(BaseSchema):
    """A reconciliation run and its match/discrepancy counts."""

    id: UUID
    study_id: UUID
    match_count: int
    discrepancy_count: int
    run_at: datetime
    created_at: datetime


class ReconciliationDiscrepancyResponse(BaseSchema):
    """A reconciliation discrepancy as returned by the API."""

    id: UUID
    run_id: UUID
    case_id: UUID
    edc_reference: UUID | None = None
    differing_fields: list[str] = Field(default_factory=list)
    status: str
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


class SafetyAttachmentResponse(BaseSchema):
    """A Safety_Attachment metadata row as returned by the API."""

    id: UUID
    object_id: UUID
    study_id: UUID | None = None
    site_id: UUID | None = None
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: UUID | None = None
    created_at: datetime


class SafetyAttachmentDeleteRequest(BaseCreateSchema):
    """Request to soft-delete a Safety_Attachment with a retained reason."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=4000)


__all__ = [
    "AdverseEventCreate",
    "AdverseEventResponse",
    "AssessmentResponse",
    "CaseChangeRequest",
    "CaseState",
    "CaseTransitionRequest",
    "CaseVersionKind",
    "CaseVersionResponse",
    "CaseVersionStatus",
    "CausalityRequest",
    "CodingResponse",
    "ExpectednessRequest",
    "MedDraCodingRequest",
    "NarrativeCreate",
    "NarrativeResponse",
    "NarrativeRevise",
    "NarrativeVersionResponse",
    "RecodeRequest",
    "ReconciliationDiscrepancyResponse",
    "ReconciliationRunRequest",
    "ReconciliationRunResponse",
    "RegulatoryReportResponse",
    "ReportStatus",
    "ReportSubmitRequest",
    "ReportTransitionRequest",
    "ReportabilityRequest",
    "SafetyAttachmentDeleteRequest",
    "SafetyAttachmentResponse",
    "SafetyCaseCreate",
    "SafetyCaseResponse",
    "SeriousnessCriterion",
    "SeriousnessRequest",
    "SeverityRequest",
]
