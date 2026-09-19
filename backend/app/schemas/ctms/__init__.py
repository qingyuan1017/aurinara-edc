"""Pydantic contracts for the CTMS first-party feature module."""

from app.schemas.ctms.common import CTMSCapabilityManifest, CTMSReference
from app.schemas.ctms.contracts import (
    CoordinationConflictCode,
    CoordinationEventStatus,
    CoordinationEventType,
    CoordinationFailureCode,
    CTMSErrorBody,
    CTMSErrorCode,
    CTMSErrorEnvelope,
    CTMSOwnershipContract,
    CTMSPaginationContract,
    ProjectionState,
)
from app.schemas.ctms.dashboard import DashboardQueryCreate, DashboardQueryResponse
from app.schemas.ctms.enrollment import (
    EnrollmentTargetCreate,
    EnrollmentTargetResponse,
    EnrollmentTargetUpdate,
    OperationalMilestoneCreate,
    OperationalMilestoneResponse,
    SubjectStatusProjectionRule,
)
from app.schemas.ctms.ownership import (
    PROHIBITED_PROJECTION_TOKENS,
    ProjectionFieldType,
    ProjectionValidationResult,
    StatusOwnershipRuleCreate,
    StatusOwnershipRuleResponse,
)
from app.schemas.ctms.projection import (
    ProjectionCreate,
    ProjectionListResponse,
    ProjectionResponse,
)
from app.schemas.ctms.report import ReportQueryCreate, ReportQueryResponse
from app.schemas.ctms.study import (
    EnrollmentPlanCreate,
    OperationalStudyArchive,
    OperationalStudyCreate,
    OperationalStudyResponse,
    OperationalStudyStatusChange,
    OperationalStudyUpdate,
    ReadinessCriterionCreate,
    StudyPlanCreate,
)
from app.schemas.ctms.study import OperationalMilestoneCreate as OperationalStudyMilestoneCreate
from app.schemas.ctms.work import (
    ContactCreate,
    ContactResponse,
    ContactStatusChange,
    DependencyCreate,
    EscalationCreate,
    EscalationStatusChange,
    TaskCreate,
    TaskResponse,
    TaskStatusChange,
    TaskUpdate,
)

# Existing integrations use this name for canonical identity references.
CanonicalIdentityReference = CTMSReference

__all__ = [
    "PROHIBITED_PROJECTION_TOKENS",
    "CTMSCapabilityManifest",
    "CTMSErrorBody",
    "CTMSErrorCode",
    "CTMSErrorEnvelope",
    "CTMSOwnershipContract",
    "CTMSPaginationContract",
    "CTMSReference",
    "CanonicalIdentityReference",
    "ContactCreate",
    "ContactResponse",
    "ContactStatusChange",
    "CoordinationConflictCode",
    "CoordinationEventStatus",
    "CoordinationEventType",
    "CoordinationFailureCode",
    "DashboardQueryCreate",
    "DashboardQueryResponse",
    "DependencyCreate",
    "EnrollmentPlanCreate",
    "EnrollmentTargetCreate",
    "EnrollmentTargetResponse",
    "EnrollmentTargetUpdate",
    "EscalationCreate",
    "EscalationStatusChange",
    "OperationalMilestoneCreate",
    "OperationalMilestoneResponse",
    "OperationalStudyArchive",
    "OperationalStudyCreate",
    "OperationalStudyMilestoneCreate",
    "OperationalStudyResponse",
    "OperationalStudyStatusChange",
    "OperationalStudyUpdate",
    "ProjectionCreate",
    "ProjectionFieldType",
    "ProjectionListResponse",
    "ProjectionResponse",
    "ProjectionState",
    "ProjectionValidationResult",
    "ReadinessCriterionCreate",
    "ReportQueryCreate",
    "ReportQueryResponse",
    "StatusOwnershipRuleCreate",
    "StatusOwnershipRuleResponse",
    "StudyPlanCreate",
    "SubjectStatusProjectionRule",
    "TaskCreate",
    "TaskResponse",
    "TaskStatusChange",
    "TaskUpdate",
]
