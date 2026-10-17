"""Contracts for EDC operational status, worklists, SDR, and clinical controls."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.shared.base import BaseCreateSchema, BaseSchema, UtcDatetime


class FormOperationalStatus(BaseSchema):
    data_entry: str
    review: str
    sdv: str
    sdr: str
    freeze: Literal["Active", "Inactive"]
    lock: Literal["Active", "Inactive"]
    signature: str
    active_query_count: int = 0
    data_revision: int = 0


class EDCCapabilities(BaseSchema):
    subjects: bool = True
    data_entry: bool = True
    review: bool = True
    sdv: bool = True
    sdr: bool = True
    listings: bool = True
    exports: bool = True
    controlled_lock: bool = True
    medical_coding: bool = False


class FormWorklistItem(BaseSchema):
    form_instance_id: UUID
    study_id: UUID
    site_id: UUID
    site_name: str | None = None
    subject_id: UUID
    subject_number: str
    visit_id: UUID | None = None
    visit_name: str | None = None
    form_definition_id: UUID
    form_name: str
    design_version_id: UUID
    status: FormOperationalStatus
    updated_at: UtcDatetime | None = None


class QualityWorklistItem(FormWorklistItem):
    workflow: Literal["review", "sdv", "sdr"]
    workflow_status: str
    sdr_selection_id: UUID | None = None
    reviewer_id: UUID | None = None
    reviewed_at: UtcDatetime | None = None


class ListingCatalogItem(BaseSchema):
    dataset: str
    label: str
    design_version_id: UUID
    columns: list[dict[str, Any]] = Field(default_factory=list)


class ListingRow(BaseSchema):
    source_form_url: str
    values: dict[str, Any] = Field(default_factory=dict)


class SDRSettingUpsert(BaseCreateSchema):
    strategy: Literal["all", "percentage", "targeted"] = "all"
    percentage: int | None = Field(None, ge=1, le=100)
    targeted_field_ids: list[UUID] = Field(default_factory=list)
    is_required_for_lock: bool = True

    @model_validator(mode="after")
    def validate_strategy(self):
        if self.strategy == "percentage" and self.percentage is None:
            raise ValueError("percentage is required for percentage SDR")
        if self.strategy == "targeted" and not self.targeted_field_ids:
            raise ValueError("targeted_field_ids is required for targeted SDR")
        return self


class SDRSettingResponse(BaseSchema):
    id: UUID
    study_version_id: UUID
    strategy: str
    percentage: int | None = None
    targeted_field_ids: list[str] = Field(default_factory=list)
    is_required_for_lock: bool
    created_by: UUID
    updated_by: UUID | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None


class SDRReviewUpdate(BaseCreateSchema):
    status: Literal["In Review", "Complete"]
    outcome: str | None = Field(None, max_length=50)
    comment: str | None = Field(None, max_length=4000)


class SDRResultResponse(BaseSchema):
    id: UUID
    selection_id: UUID
    status: str
    reviewed_revision: int | None = None
    outcome: str | None = None
    comment: str | None = None
    reviewed_by: UUID | None = None
    reviewed_at: UtcDatetime | None = None


class ReadinessBlocker(BaseSchema):
    code: str
    count: int
    message: str
    drilldown: str


class LockReadinessResponse(BaseSchema):
    study_id: UUID
    ready: bool
    evaluated_at: UtcDatetime
    blockers: list[ReadinessBlocker] = Field(default_factory=list)
    snapshot_hash: str


class ClinicalControlRequestCreate(BaseCreateSchema):
    scope_type: Literal["form", "visit", "subject", "site", "study"]
    scope_id: UUID
    action: Literal["freeze", "unfreeze", "lock", "unlock"]
    reason: str = Field(min_length=1, max_length=4000)


class ClinicalControlDecision(BaseCreateSchema):
    reason: str | None = Field(None, max_length=4000)


class ClinicalControlRequestResponse(BaseSchema):
    id: UUID
    study_id: UUID
    scope_type: str
    scope_id: UUID
    action: str
    status: str
    reason: str
    requested_by: UUID
    requested_at: UtcDatetime
    approved_by: UUID | None = None
    approved_at: UtcDatetime | None = None
    executed_by: UUID | None = None
    executed_at: UtcDatetime | None = None
    readiness_snapshot: dict | None = None
    readiness_hash: str | None = None
    failure_details: dict | None = None
    correlation_id: str | None = None
    request_id: str | None = None


class LockHistoryItem(BaseSchema):
    request: ClinicalControlRequestResponse


__all__ = [
    "ClinicalControlDecision",
    "ClinicalControlRequestCreate",
    "ClinicalControlRequestResponse",
    "EDCCapabilities",
    "FormOperationalStatus",
    "FormWorklistItem",
    "ListingCatalogItem",
    "ListingRow",
    "LockHistoryItem",
    "LockReadinessResponse",
    "QualityWorklistItem",
    "ReadinessBlocker",
    "SDRResultResponse",
    "SDRReviewUpdate",
    "SDRSettingResponse",
    "SDRSettingUpsert",
]
