"""PV_Safety_Module-owned ORM model boundary.

PV tables are additive, use a ``pv_`` prefix, reference canonical Study/Site and
EDC Subject_Reference identity, and never duplicate EDC clinical or CTMS
operational tables.
"""

from app.models.pv.assessment import (
    CausalityAssessment,
    ExpectednessAssessment,
    SeriousnessAssessment,
    SeriousnessCriterion,
    SeverityGrade,
)
from app.models.pv.coding import (
    CodingDictionaryVersion,
    CodingSystem,
    MedDraCoding,
    WhoDrugCoding,
)
from app.models.pv.common import (
    ActorMetadataMixin,
    CorrelationMixin,
    ProjectionStatus,
    PVBase,
    PVRecordMixin,
    RetentionMixin,
    RetentionState,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utc_now,
)
from app.models.pv.coordination import (
    APPROVED_PROJECTION_FIELDS,
    CoordinationRef,
    EdcAeProjection,
)
from app.models.pv.narrative import (
    NARRATIVE_REASON_MAX_LENGTH,
    NARRATIVE_TEXT_MAX_LENGTH,
    CaseNarrative,
    NarrativeVersion,
)
from app.models.pv.reconciliation import (
    RECONCILED_FIELDS,
    DiscrepancyStatus,
    ReconciliationDiscrepancy,
    ReconciliationRun,
)
from app.models.pv.regulatory import (
    TIMELINE_DAYS_MAX,
    TIMELINE_DAYS_MIN,
    RegulatoryClock,
    RegulatoryReport,
    ReportabilityRule,
    ReportStatus,
)
from app.models.pv.retention import PVRetentionAction
from app.models.pv.safety_case import (
    AdverseEventRecord,
    CaseState,
    CaseVersion,
    CaseVersionKind,
    CaseVersionStatus,
    SafetyCase,
)

PV_MODEL_PACKAGE = "app.models.pv"

__all__ = [
    "APPROVED_PROJECTION_FIELDS",
    "NARRATIVE_REASON_MAX_LENGTH",
    "NARRATIVE_TEXT_MAX_LENGTH",
    "PV_MODEL_PACKAGE",
    "RECONCILED_FIELDS",
    "TIMELINE_DAYS_MAX",
    "TIMELINE_DAYS_MIN",
    "ActorMetadataMixin",
    "AdverseEventRecord",
    "CaseNarrative",
    "CaseState",
    "CaseVersion",
    "CaseVersionKind",
    "CaseVersionStatus",
    "CausalityAssessment",
    "CodingDictionaryVersion",
    "CodingSystem",
    "CoordinationRef",
    "CorrelationMixin",
    "DiscrepancyStatus",
    "EdcAeProjection",
    "ExpectednessAssessment",
    "MedDraCoding",
    "NarrativeVersion",
    "PVBase",
    "PVRecordMixin",
    "PVRetentionAction",
    "ProjectionStatus",
    "ReconciliationDiscrepancy",
    "ReconciliationRun",
    "RegulatoryClock",
    "RegulatoryReport",
    "ReportStatus",
    "ReportabilityRule",
    "RetentionMixin",
    "RetentionState",
    "SafetyCase",
    "SeriousnessAssessment",
    "SeriousnessCriterion",
    "SeverityGrade",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "WhoDrugCoding",
    "utc_now",
]
