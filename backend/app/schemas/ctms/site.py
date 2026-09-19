"""Pydantic contracts for CTMS operational site workflows."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from app.models.ctms.operational_site import ActivationActionStatus, OperationalSiteStatus
from app.schemas.base import BaseCreateSchema, BaseSchema, BaseUpdateSchema


def _reason(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("reason must not be blank")
    return value


class OperationalSiteProfileCreate(BaseCreateSchema):
    """CTMS-owned site readiness/profile fields."""

    study_id: UUID | None = None
    monitoring_readiness: str | None = Field(default=None, max_length=30)
    responsible_role: str | None = Field(default=None, max_length=150)
    planned_activation_date: datetime | date | None = None
    status: OperationalSiteStatus = OperationalSiteStatus.NOT_STARTED
    correlation_id: str | None = None


class OperationalSiteProfileUpdate(BaseUpdateSchema):
    """Partial update for CTMS site readiness fields."""

    monitoring_readiness: str | None = Field(default=None, max_length=30)
    responsible_role: str | None = Field(default=None, max_length=150)
    planned_activation_date: datetime | date | None = None
    correlation_id: str | None = None


class OperationalSiteStatusChange(BaseCreateSchema):
    status: OperationalSiteStatus
    reason: str
    correlation_id: str | None = None

    _validate_reason = field_validator("reason")(_reason)


class ActivationActionCreate(BaseCreateSchema):
    action_type: str = Field(min_length=1, max_length=100)
    responsible_role: str | None = Field(default=None, max_length=150)
    responsible_user_id: UUID | None = None
    planned_date: datetime | date | None = None
    completion_criteria: str | None = None
    correlation_id: str | None = None

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("action_type must not be blank")
        return value


class ActivationActionStatusChange(BaseCreateSchema):
    status: ActivationActionStatus
    reason: str
    correlation_id: str | None = None

    _validate_reason = field_validator("reason")(_reason)


class ActivationActionCompletion(BaseCreateSchema):
    evidence_reference: str | dict[str, Any]
    reason: str | None = None
    correlation_id: str | None = None

    _validate_reason = field_validator("reason")(_reason)


class OperationalSiteResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID
    monitoring_readiness: str | None = None
    responsible_role: str | None = None
    planned_activation_date: datetime | None = None
    status: OperationalSiteStatus
    retention_state: str
    archived_at: datetime | None = None
    created_by: UUID
    updated_by: UUID | None = None
    correlation_id: UUID
    created_at: datetime
    updated_at: datetime


class ActivationActionResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID
    action_type: str
    responsible_role: str | None = None
    responsible_user_id: UUID | None = None
    planned_date: datetime | None = None
    completion_criteria: str | None = None
    completed_by: UUID | None = None
    completed_at: datetime | None = None
    evidence_reference: str | None = None
    status: ActivationActionStatus
    retention_state: str
    archived_at: datetime | None = None
    created_by: UUID
    updated_by: UUID | None = None
    correlation_id: UUID
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ActivationActionCompletion",
    "ActivationActionCreate",
    "ActivationActionResponse",
    "ActivationActionStatusChange",
    "OperationalSiteProfileCreate",
    "OperationalSiteProfileUpdate",
    "OperationalSiteResponse",
    "OperationalSiteStatus",
    "OperationalSiteStatusChange",
]
