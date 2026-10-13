"""Canonical CTMS report catalog shared by API discovery and dispatch."""

from __future__ import annotations

from app.schemas.ctms.report import CTMSReportDefinition


def _definition(
    category: str,
    category_label: str,
    report_type: str,
    label: str,
    data_source: str,
) -> CTMSReportDefinition:
    return CTMSReportDefinition(
        category=category,
        category_label=category_label,
        report_type=report_type,
        label=label,
        data_source=data_source,
    )


REPORT_CATALOG = (
    _definition("project-management", "Project Management", "gantt", "Gantt", "ctms"),
    _definition("project-management", "Project Management", "raci-matrix", "RACI Matrix", "ctms"),
    _definition(
        "project-management",
        "Project Management",
        "workload-assessment",
        "Workload Assessment",
        "ctms",
    ),
    _definition("project-management", "Project Management", "tasks", "Tasks", "ctms"),
    _definition("project-management", "Project Management", "deliverables", "Deliverables", "ctms"),
    _definition(
        "project-management", "Project Management", "activity-types", "Activity Types", "ctms"
    ),
    _definition("crf", "CRF", "status-summary", "Status Summary", "approved_projection"),
    _definition("crf", "CRF", "visit-status", "Visit Status", "approved_projection"),
    _definition("crf", "CRF", "form-status", "Form Status", "approved_projection"),
    _definition("crf", "CRF", "item-status", "Item Status", "approved_projection"),
    _definition("crf", "CRF", "completion-status", "Completion Status", "approved_projection"),
    _definition("crf", "CRF", "study-summary", "Study Summary", "approved_projection"),
    _definition("crf", "CRF", "subject-summary", "Subject Summary", "approved_projection"),
    _definition(
        "query", "Query", "query-aging-summary", "Query Aging Summary", "approved_projection"
    ),
    _definition(
        "query", "Query", "manual-query-details", "Manual Query Details", "approved_projection"
    ),
    _definition(
        "query", "Query", "system-query-details", "System Query Details", "approved_projection"
    ),
    _definition("query", "Query", "all-query-details", "All Query Details", "approved_projection"),
    _definition("query", "Query", "pd-queries", "PD Queries", "approved_projection"),
    _definition(
        "query", "Query", "trip-report-queries", "Trip Report Queries", "approved_projection"
    ),
    _definition(
        "query",
        "Query",
        "ic-tracking-log-queries",
        "IC Tracking Log Queries",
        "approved_projection",
    ),
    _definition(
        "query", "Query", "action-item-queries", "Action Item Queries", "approved_projection"
    ),
)

REPORT_CATALOG_BY_KEY = {
    (definition.category, definition.report_type): definition for definition in REPORT_CATALOG
}


__all__ = ["REPORT_CATALOG", "REPORT_CATALOG_BY_KEY"]
