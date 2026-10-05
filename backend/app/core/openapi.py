"""Shared OpenAPI metadata for the unified EDC and CTMS API."""

from typing import Final

from pydantic import TypeAdapter

from app.core.ctms import CTMSPhase, Module, OwnershipState
from app.core.pv import CaseState, PVPhase, ReportStatus
from app.models.ctms.enrollment import (
    EnrollmentTargetStatus,
    EnrollmentTargetType,
    OperationalSubjectStatus,
)
from app.models.ctms.monitoring import (
    MonitoringActivityStatus,
    MonitoringActivityType,
    MonitoringPlanStatus,
    MonitoringPlanVersionStatus,
)
from app.models.ctms.operational_site import (
    ActivationActionStatus,
    OperationalSiteStatus,
)
from app.models.ctms.operational_study import (
    EnrollmentPlanStatus,
    OperationalMilestoneStatus,
    OperationalStudyStatus,
    ReadinessCriterionStatus,
    StudyPlanStatus,
)
from app.models.ctms.ownership import OwnershipRuleStatus, ProjectionType
from app.models.ctms.projection import ProjectionStatus
from app.models.ctms.work import (
    EscalationStatus,
    OperationalContactStatus,
    OperationalTaskPriority,
    OperationalTaskStatus,
)
from app.schemas.base import ErrorEnvelope
from app.schemas.ctms.contracts import (
    CoordinationConflictCode,
    CoordinationEventStatus,
    CoordinationEventType,
    CoordinationFailureCode,
    CTMSErrorCode,
    CTMSErrorEnvelope,
    CTMSOwnershipContract,
    CTMSPaginationContract,
)
from app.schemas.pv.contracts import PVErrorCode, PVPaginationContract

API_TAGS: Final[list[dict[str, str]]] = [
    {
        "name": "ctms",
        "description": "CTMS capability and health metadata. CTMS owns operational data only.",
    },
    {"name": "ctms-studies", "description": "CTMS operational study planning and lifecycle."},
    {"name": "ctms-sites", "description": "CTMS operational site readiness and activation."},
    {"name": "ctms-enrollment", "description": "CTMS recruitment and enrollment operations."},
    {"name": "ctms-milestones", "description": "CTMS operational milestones."},
    {"name": "ctms-monitoring", "description": "CTMS monitoring plans and activities."},
    {"name": "ctms-tasks", "description": "CTMS operational work management."},
    {"name": "ctms-contacts", "description": "CTMS operational contacts."},
    {"name": "ctms-projections", "description": "Minimized, read-only CTMS projections."},
    {"name": "ctms-coordination", "description": "Sanitized coordination events and conflicts."},
    {"name": "ctms-dashboards", "description": "Scoped CTMS operational dashboards."},
    {"name": "ctms-reports", "description": "Scoped CTMS operational reports."},
    {"name": "ctms-exports", "description": "CTMS operational export jobs."},
    {"name": "ctms-health", "description": "Sanitized CTMS worker and projection health."},
    {
        "name": "pv",
        "description": "PV/Safety capability and health metadata. PV owns safety data only.",
    },
    {"name": "pv-cases", "description": "Safety case intake, capture, lifecycle, and versions."},
    {"name": "pv-assessments", "description": "Seriousness, causality, expectedness, and severity."},
    {"name": "pv-coding", "description": "MedDRA and WHODrug coding with dictionary versions."},
    {"name": "pv-narratives", "description": "Versioned case narratives and history."},
    {"name": "pv-reports", "description": "Regulatory reporting, clocks, and ICSR/E2B."},
    {"name": "pv-reconciliation", "description": "One-way, read-only EDC adverse-event reconciliation."},
    {"name": "pv-attachments", "description": "Safety attachments on shared file primitives."},
    {"name": "pv-exports", "description": "PV-owned safety export jobs."},
    {"name": "pv-dashboards", "description": "Scoped PV safety dashboards and reports."},
    {"name": "pv-audit", "description": "Scoped, deterministically ordered PV safety audit."},
    {"name": "pv-health", "description": "Sanitized PV worker, export, and overdue-report health."},
]


def _values(enum_type: type) -> list[str | int]:
    return [item.value for item in enum_type]


CTMS_ERROR_RESPONSES: Final[dict[int, dict[str, object]]] = {
    400: {"model": CTMSErrorEnvelope, "description": "Invalid CTMS operation or business rule."},
    401: {"model": CTMSErrorEnvelope, "description": "Authentication is required."},
    403: {"model": CTMSErrorEnvelope, "description": "The requested CTMS scope or operation is not permitted."},
    404: {"model": CTMSErrorEnvelope, "description": "The CTMS resource or canonical reference was not found."},
    409: {"model": CTMSErrorEnvelope, "description": "Ownership, ordering, idempotency, or coordination conflict."},
    422: {"model": CTMSErrorEnvelope, "description": "The CTMS request failed schema validation."},
    500: {"model": CTMSErrorEnvelope, "description": "The request failed without exposing internal details."},
    503: {"model": CTMSErrorEnvelope, "description": "A CTMS dependency is temporarily unavailable."},
}


# PV uses the baseline platform error envelope shared by EDC.
PV_ERROR_RESPONSES: Final[dict[int, dict[str, object]]] = {
    400: {"model": ErrorEnvelope, "description": "Invalid PV/Safety operation or business rule."},
    401: {"model": ErrorEnvelope, "description": "Authentication is required."},
    403: {"model": ErrorEnvelope, "description": "The requested PV scope or operation is not permitted."},
    404: {"model": ErrorEnvelope, "description": "The PV safety resource or canonical reference was not found."},
    409: {"model": ErrorEnvelope, "description": "Ownership, lifecycle, versioning, or coordination conflict."},
    422: {"model": ErrorEnvelope, "description": "The PV request failed schema or safety-data validation."},
    500: {"model": ErrorEnvelope, "description": "The request failed without exposing internal details."},
    503: {"model": ErrorEnvelope, "description": "A PV dependency is temporarily unavailable."},
}


CTMS_OPENAPI_EXTENSIONS: Final[dict[str, object]] = {
    "x-contract-version": "ctms-api-v1",
    "x-module-ownership": {
        "CTMS": "operational study, site, enrollment, monitoring, work, projections, and operational exports",
        "EDC": "clinical configuration, subjects, visits, clinical data, quality, signatures, and clinical exports",
    },
    "x-ctms-error-codes": _values(CTMSErrorCode),
    "x-ctms-enums": {
        "module": _values(Module),
        "ownership_state": _values(OwnershipState),
        "ctms_phase": _values(CTMSPhase),
        "ownership_rule_status": _values(OwnershipRuleStatus),
        "projection_type": _values(ProjectionType),
        "projection_state": _values(ProjectionStatus),
        "coordination_event_status": _values(CoordinationEventStatus),
        "coordination_event_type": _values(CoordinationEventType),
        "operational_study_status": _values(OperationalStudyStatus),
        "operational_site_status": _values(OperationalSiteStatus),
        "activation_action_status": _values(ActivationActionStatus),
        "enrollment_target_type": _values(EnrollmentTargetType),
        "enrollment_target_status": _values(EnrollmentTargetStatus),
        "operational_subject_status": _values(OperationalSubjectStatus),
        "study_plan_status": _values(StudyPlanStatus),
        "enrollment_plan_status": _values(EnrollmentPlanStatus),
        "readiness_criterion_status": _values(ReadinessCriterionStatus),
        "operational_milestone_status": _values(OperationalMilestoneStatus),
        "monitoring_plan_status": _values(MonitoringPlanStatus),
        "monitoring_plan_version_status": _values(MonitoringPlanVersionStatus),
        "monitoring_activity_type": _values(MonitoringActivityType),
        "monitoring_activity_status": _values(MonitoringActivityStatus),
        "operational_task_status": _values(OperationalTaskStatus),
        "operational_task_priority": _values(OperationalTaskPriority),
        "operational_contact_status": _values(OperationalContactStatus),
        "escalation_status": _values(EscalationStatus),
    },
    "x-ctms-ownership-rules": [
        CTMSOwnershipContract(
            authoritative_module="EDC",
            writable_module="EDC",
            projection_target="CTMS",
            projection_types=[ProjectionType.SUBJECT_STATUS, ProjectionType.QUERY_SUMMARY, ProjectionType.DATA_QUALITY_SIGNAL],
        ).model_dump(mode="json"),
        CTMSOwnershipContract(
            authoritative_module="CTMS",
            writable_module="CTMS",
            projection_target="EDC",
            projection_types=[ProjectionType.COORDINATED_TRANSITION],
        ).model_dump(mode="json"),
    ],
    "x-ctms-event-types": _values(CoordinationEventType),
    "x-ctms-projection-states": _values(ProjectionStatus),
    "x-ctms-failure-codes": _values(CoordinationFailureCode),
    "x-ctms-conflict-codes": _values(CoordinationConflictCode),
    "x-ctms-pagination": {
        "schema": "CTMSPaginationContract",
        "properties": {
            "items": {"type": "array"},
            "page": {"type": "integer", "minimum": 1},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
            "total": {"type": "integer", "minimum": 0},
        },
    },
    "x-ctms-error-responses": {
        str(status): {"code": response["description"]}
        for status, response in CTMS_ERROR_RESPONSES.items()
    },
    "x-pv-module-ownership": {
        "PV": "safety cases, adverse-event records, assessments, coding, narratives, "
        "regulatory reports/clocks, reconciliation, safety notifications, safety "
        "attachments, safety dashboards/reports, and safety exports",
        "EDC": "clinical configuration, subjects, visits, clinical data, quality, "
        "signatures, and clinical exports",
        "CTMS": "operational study/site, enrollment, monitoring, work, and operational exports",
    },
    "x-pv-error-codes": _values(PVErrorCode),
    "x-pv-enums": {
        "module": _values(Module),
        "pv_phase": _values(PVPhase),
        "case_state": _values(CaseState),
        "report_status": _values(ReportStatus),
        "pv_error_code": _values(PVErrorCode),
    },
    "x-pv-pagination": {
        "schema": "PVPaginationContract",
        "properties": {
            "items": {"type": "array"},
            "page": {"type": "integer", "minimum": 1},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 1000},
            "total": {"type": "integer", "minimum": 0},
        },
    },
    "x-pv-error-responses": {
        str(status): {"code": response["description"]}
        for status, response in PV_ERROR_RESPONSES.items()
    },
}


def install_openapi_metadata(app: object) -> None:
    """Add CTMS ownership and contract metadata to FastAPI's OpenAPI document."""

    original_openapi = app.openapi  # type: ignore[attr-defined]

    def custom_openapi() -> dict[str, object]:
        schema = original_openapi()
        info = schema.setdefault("info", {})
        info.update(CTMS_OPENAPI_EXTENSIONS)

        components = schema.setdefault("components", {})
        component_schemas = components.setdefault("schemas", {})
        # These contracts are deliberately added even when a deployment has no
        # enabled CTMS routes, so clients can generate against one stable API.
        for name, model in {
            "CTMSErrorEnvelope": CTMSErrorEnvelope,
            "CTMSOwnershipContract": CTMSOwnershipContract,
            "CTMSPaginationContract": CTMSPaginationContract,
        }.items():
            model_schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
            component_schemas.setdefault(name, model_schema)
            for definition_name, definition in model_schema.pop("$defs", {}).items():
                component_schemas.setdefault(definition_name, definition)
        for name, enum_type in {
            "CTMSErrorCode": CTMSErrorCode,
            "CoordinationConflictCode": CoordinationConflictCode,
            "CoordinationEventStatus": CoordinationEventStatus,
            "CoordinationEventType": CoordinationEventType,
            "CoordinationFailureCode": CoordinationFailureCode,
        }.items():
            component_schemas.setdefault(name, TypeAdapter(enum_type).json_schema())
        # PV publishes its pagination envelope and error-code vocabulary so
        # clients can generate against a stable PV contract even when PV routes
        # are phase-gated off. PV reuses the baseline ErrorEnvelope, so no
        # separate PV error body schema is registered here.
        pv_pagination_schema = PVPaginationContract.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        component_schemas.setdefault("PVPaginationContract", pv_pagination_schema)
        for definition_name, definition in pv_pagination_schema.pop("$defs", {}).items():
            component_schemas.setdefault(definition_name, definition)
        component_schemas.setdefault("PVErrorCode", TypeAdapter(PVErrorCode).json_schema())
        return schema

    app.openapi = custom_openapi  # type: ignore[attr-defined]
