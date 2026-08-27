"""Dashboard response schemas — study, site, and query metrics.

Satisfies Requirements:
  - 20.1: Study dashboard with subject counts by status, form completion, open queries.
  - 20.2: Site dashboard with site-level progress.
  - 20.3: Query metrics with open/answered/overdue counts and aging.
  - 20.4: All metrics computed within the caller's Authorization_Scope.
"""

from pydantic import BaseModel, Field


class StudyDashboard(BaseModel):
    """Study-level dashboard metrics (Requirement 20.1)."""

    subject_counts_by_status: dict[str, int] = Field(
        default_factory=dict,
        description="Subject counts grouped by lifecycle status (e.g., Screening: 5, Enrolled: 12)",
    )
    total_form_instances: int = Field(
        default=0,
        description="Total number of form instances across all subjects in the study",
    )
    submitted_form_instances: int = Field(
        default=0,
        description="Number of form instances with status Submitted or beyond",
    )
    open_query_count: int = Field(
        default=0,
        description="Number of queries in Open or Reopened status",
    )


class SiteDashboard(BaseModel):
    """Site-level dashboard metrics (Requirement 20.2)."""

    subject_counts_by_status: dict[str, int] = Field(
        default_factory=dict,
        description="Subject counts grouped by lifecycle status for the site",
    )
    total_form_instances: int = Field(
        default=0,
        description="Total number of form instances for subjects at this site",
    )
    submitted_form_instances: int = Field(
        default=0,
        description="Number of submitted (or beyond) form instances at this site",
    )
    open_query_count: int = Field(
        default=0,
        description="Number of queries in Open or Reopened status for this site",
    )


class QueryMetrics(BaseModel):
    """Query metrics for a study (Requirement 20.3)."""

    open_count: int = Field(
        default=0,
        description="Queries in Open or Reopened status",
    )
    answered_count: int = Field(
        default=0,
        description="Queries in Answered status",
    )
    closed_count: int = Field(
        default=0,
        description="Queries in Closed status",
    )
    cancelled_count: int = Field(
        default=0,
        description="Queries in Cancelled status",
    )
    overdue_count: int = Field(
        default=0,
        description="Queries open for more than 14 days",
    )
    average_days_open: float = Field(
        default=0.0,
        description="Average number of days that currently-open queries have been open",
    )
