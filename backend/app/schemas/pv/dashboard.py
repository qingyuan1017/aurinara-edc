"""Pydantic contracts for PV safety dashboards and reports (Requirement 13).

PV owns safety dashboard/report content. Every metric is computed from PV
safety records within the requesting user's Authorization_Scope. Any approved
EDC/CTMS projection is surfaced only as read-only, source-labeled fields and is
never folded into a PV safety metric (Requirements 13.4, 13.5).
"""

from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ReportingComplianceMetrics(BaseSchema):
    """Mutually exclusive regulatory-report compliance buckets (Requirement 13.2).

    A Regulatory_Report falls into exactly one bucket:
      - ``submitted``  when its status is Submitted;
      - ``overdue``    when it is not Submitted and its Regulatory_Clock due date
        is earlier than the current UTC date;
      - ``on_time``    when it is not Submitted and its due date is not earlier
        than the current UTC date.
    """

    submitted: int = Field(
        default=0,
        ge=0,
        description="Regulatory_Reports whose status is Submitted",
    )
    overdue: int = Field(
        default=0,
        ge=0,
        description=(
            "Not-Submitted Regulatory_Reports whose clock due date is earlier "
            "than the current UTC date"
        ),
    )
    on_time: int = Field(
        default=0,
        ge=0,
        description=(
            "Not-Submitted Regulatory_Reports whose clock due date is not "
            "earlier than the current UTC date"
        ),
    )

    @property
    def total(self) -> int:
        """Total reports across the mutually exclusive buckets."""

        return self.submitted + self.overdue + self.on_time


class ProjectedField(BaseSchema):
    """A read-only, source-labeled EDC/CTMS projection field (Requirement 13.5).

    Projected fields are display-only. They are never used in a PV safety metric
    calculation and are never mutated through PV.
    """

    projection_id: UUID
    source_module: str = Field(description="Owning module of the projected field")
    field_name: str
    value: Any = None
    read_only: bool = Field(default=True, description="Always true for projections")
    ownership: str = Field(
        default="projected",
        description="Marks the field as an approved read-only projection",
    )


class SafetyStudyDashboard(BaseSchema):
    """Study-scoped PV safety dashboard metrics (Requirements 13.1, 13.2)."""

    study_id: UUID
    case_counts_by_status: dict[str, int] = Field(
        default_factory=dict,
        description="Safety_Case counts grouped by case lifecycle status",
    )
    adverse_event_counts_by_seriousness: dict[str, int] = Field(
        default_factory=dict,
        description="Adverse-event counts grouped by seriousness classification",
    )
    report_counts_by_status: dict[str, int] = Field(
        default_factory=dict,
        description="Regulatory_Report counts grouped by report status",
    )
    reporting_compliance: ReportingComplianceMetrics = Field(
        default_factory=ReportingComplianceMetrics,
        description="Mutually exclusive submitted/overdue/on-time report buckets",
    )
    projected_fields: list[ProjectedField] = Field(
        default_factory=list,
        description="Approved read-only EDC/CTMS projections, source-labeled",
    )
    generated_at: Any = Field(
        description="UTC request timestamp the metrics were computed as of",
    )


class SafetySiteDashboard(BaseSchema):
    """Site-scoped PV safety dashboard metrics (Requirement 13.3).

    Returns only in-scope PV safety metrics for the site, with zero-valued
    metrics when no qualifying safety records exist.
    """

    study_id: UUID
    site_id: UUID
    case_counts_by_status: dict[str, int] = Field(default_factory=dict)
    adverse_event_counts_by_seriousness: dict[str, int] = Field(default_factory=dict)
    report_counts_by_status: dict[str, int] = Field(default_factory=dict)
    reporting_compliance: ReportingComplianceMetrics = Field(
        default_factory=ReportingComplianceMetrics
    )
    projected_fields: list[ProjectedField] = Field(default_factory=list)
    generated_at: Any


__all__ = [
    "ProjectedField",
    "ReportingComplianceMetrics",
    "SafetySiteDashboard",
    "SafetyStudyDashboard",
]
