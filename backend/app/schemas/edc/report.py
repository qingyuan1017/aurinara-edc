"""Report_Area response schemas — read-only reporting surface.

The EDC_Module reporting surface groups several report families. Every report
is **scope-filtered server-side** via the shared ``permission_service`` so the
returned payload contains only records within the requesting user's
Authorization_Scope (R9.8), is empty when nothing is in scope (R9.9), and the
request is rejected with a not-authorized error when the user lacks the
required permission (R9.10).

Satisfies Requirements:
  - 9.1: Data Summary reports.
  - 9.2: CRF Status reports.
  - 9.3: Query Report.
  - 9.4: Enrollment Status reports.
  - 9.5: eCOA / eDiary Report.
  - 9.6: On-Demand / KRI-Central Monitoring / SDV-SDR Workload / Data Analysis /
         Comment / Source Document Tracker.
  - 9.7: End of Study reports.
  - 9.8: Only in-scope records are returned.
  - 9.9: Empty result set when nothing is in scope.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ReportMeta(BaseModel):
    """Shared metadata describing a scope-filtered report response.

    ``study_ids_in_scope`` lists the studies the requesting user was authorized
    to see within the requested scope. An empty list means nothing was in scope
    and the ``rows`` collection is therefore empty (R9.9).
    """

    report_key: str = Field(description="Stable identifier of the report family and section")
    report_group: str = Field(description="The Report_Area group this report belongs to")
    study_ids_in_scope: list[UUID] = Field(
        default_factory=list,
        description="Studies within the requesting user's authorization scope",
    )
    site_ids_in_scope: list[UUID] = Field(
        default_factory=list,
        description="Sites within the requesting user's authorization scope",
    )
    total: int = Field(default=0, ge=0, description="Number of in-scope rows returned")


class ReportResponse(BaseModel):
    """Generic read-only report envelope.

    ``rows`` holds the scope-filtered report rows. Each row is a free-form
    mapping so a single envelope can carry any report family's columns while a
    backing data model is not yet available for every section. The scope and
    authorization behavior is real regardless of the row shape (R9.8-R9.10).
    """

    meta: ReportMeta
    rows: list[dict] = Field(default_factory=list)


class EnrollmentStatusRow(BaseModel):
    """A single row of the Enrollment Status report (R9.4)."""

    study_id: UUID
    site_id: UUID | None = None
    status: str
    subject_count: int = Field(ge=0)


class EnrollmentStatusReport(BaseModel):
    """Enrollment Status report — subject counts by status within scope (R9.4).

    This report is backed by the Subject operational model, so its rows reflect
    real stored data filtered to the requesting user's Authorization_Scope.
    """

    meta: ReportMeta
    rows: list[EnrollmentStatusRow] = Field(default_factory=list)


__all__ = [
    "EnrollmentStatusReport",
    "EnrollmentStatusRow",
    "ReportMeta",
    "ReportResponse",
]
