"""Designer / EDC refactor migration tooling.

The Migration_Process is phased, reversible, and value-preserving (R11). This
subpackage holds the Phase 0 snapshot used to verify, after reassignment, that
no record count or stored value changed (R11.5), and the Phase 4 reassignment
audit that records ownership reassignments as immutable audit events (R11.7)
while preserving all existing audit history with no physical removal (R11.8).

It also holds the Phase 5/6 verification that compares a fresh post-migration
snapshot against the Phase 0 snapshot and confirms every published design is
still consumable (R11.3, R11.5), aborting on any data-loss risk while leaving
the pre-migration records unchanged (R11.6).
"""

from app.services.designer.migration.reassignment_service import (
    REASSIGN_ACTION,
    ReassignmentEvent,
    ReassignmentResult,
    ReassignmentService,
    reassignment_service,
)
from app.services.designer.migration.snapshot_service import (
    RECORD_SET_MODELS,
    MigrationSnapshot,
    RecordSetSnapshot,
    SnapshotService,
    snapshot_service,
)
from app.services.designer.migration.verification_service import (
    FailureKind,
    MigrationAbortError,
    PublishedDesignFailure,
    RecordSetFailure,
    VerificationResult,
    VerificationService,
    verification_service,
)

__all__ = [
    "REASSIGN_ACTION",
    "RECORD_SET_MODELS",
    "FailureKind",
    "MigrationAbortError",
    "MigrationSnapshot",
    "PublishedDesignFailure",
    "ReassignmentEvent",
    "ReassignmentResult",
    "ReassignmentService",
    "RecordSetFailure",
    "RecordSetSnapshot",
    "SnapshotService",
    "VerificationResult",
    "VerificationService",
    "reassignment_service",
    "snapshot_service",
    "verification_service",
]
