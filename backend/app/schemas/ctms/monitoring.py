"""Pydantic v2 contracts for CTMS monitoring plans and activities."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.core.ctms import ensure_utc
from app.models.ctms.monitoring import (
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringPlanStatus,
    MonitoringPlanVersionStatus,
)
from app.schemas.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema


def _reason(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("reason must not be blank")
    return value


class MonitoringPlanVersionCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    objectives: str | None = None
    activity_types: list[MonitoringActivityType] = Field(default_factory=list)
    frequency: str | None = None
    frequency_value: int | None = Field(default=None, ge=1)
    frequency_unit: str | None = None
    cadence: str | None = None
    responsibilities: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)
    completion_criteria: str | None = None
    risk_level: str | None = None
    risk_strategy: str | None = None
    monitoring_strategy: str | None = None
    risk_threshold: str | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)


class MonitoringPlanCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    site_id: UUID | None = None
    version: MonitoringPlanVersionCreate | None = None
    correlation_id: str | None = None


class MonitoringPlanUpdate(BaseUpdateSchema):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    correlation_id: str | None = None


class MonitoringPlanAmend(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    reason: str
    changes: MonitoringPlanVersionCreate = Field(default_factory=MonitoringPlanVersionCreate)
    correlation_id: str | None = None

    _validate_reason = field_validator("reason")(_reason)


class MonitoringPlanResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID | None
    name: str
    description: str | None
    status: MonitoringPlanStatus
    current_version_id: UUID | None
    retention_state: str
    correlation_id: str
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime


class MonitoringPlanVersionResponse(BaseSchema):
    id: UUID
    plan_id: UUID
    study_id: UUID
    site_id: UUID | None
    version_number: int
    status: MonitoringPlanVersionStatus
    objectives: str | None
    activity_types: list[Any]
    frequency: str | None
    frequency_value: int | None
    frequency_unit: str | None
    cadence: str | None
    responsibilities: dict[str, Any]
    scope: dict[str, Any]
    completion_criteria: str | None
    risk_level: str | None
    risk_strategy: str | None
    monitoring_strategy: str | None
    risk_threshold: str | None
    thresholds: dict[str, Any]
    amendment_reason: str | None
    published_by: UUID | None
    published_at: datetime | None
    correlation_id: str
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime


class MonitoringActivityCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    activity_type: MonitoringActivityType
    planned_date: datetime | date
    site_id: UUID | None = None
    assigned_cra_id: UUID | None = None
    edc_visit_instance_id: UUID | None = None
    issue_id: UUID | None = None
    issue_reference: str | None = None
    escalation_id: UUID | None = None
    escalation_reference: str | None = None
    reason: str | None = None
    correlation_id: str | None = None

    @field_validator("planned_date")
    @classmethod
    def utc_planned_date(cls, value: datetime | date) -> datetime:
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
        return ensure_utc(value)


class MonitoringActivityReschedule(BaseCreateSchema):
    planned_date: datetime
    reason: str
    correlation_id: str | None = None

    @field_validator("planned_date")
    @classmethod
    def utc_planned_date(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    _validate_reason = field_validator("reason")(_reason)


class MonitoringActivityComplete(BaseCreateSchema):
    evidence: dict[str, Any] | str
    notes: str | None = None
    correlation_id: str | None = None


class MonitoringActivityCancel(BaseCreateSchema):
    reason: str
    correlation_id: str | None = None

    _validate_reason = field_validator("reason")(_reason)


class MonitoringActivityAssign(BaseCreateSchema):
    assigned_cra_id: UUID
    correlation_id: str | None = None


class MonitoringActivityResponse(BaseSchema):
    id: UUID
    plan_version_id: UUID
    study_id: UUID
    site_id: UUID | None
    activity_type: MonitoringActivityType
    planned_date: datetime
    assigned_cra_id: UUID | None
    status: MonitoringActivityStatus
    edc_visit_instance_id: UUID | None
    completion_evidence: dict[str, Any]
    completion_notes: str | None
    completed_at: datetime | None
    completed_by: UUID | None
    cancellation_reason: str | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    correlation_id: str
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime


__all__ = [name for name in globals() if not name.startswith("_")]
