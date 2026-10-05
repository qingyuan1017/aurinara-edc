"""Pydantic contracts for the PV/Safety first-party feature module."""

from app.schemas.pv.common import (
    CaseState,
    Correlation_Identifier,
    CorrelationIdentifier,
    Idempotency_Key,
    IdempotencyKey,
    Module,
    PVCapabilityManifest,
    PVReference,
    ReportStatus,
)
from app.schemas.pv.contracts import (
    PV_DEFAULT_PAGE_SIZE,
    PV_MAX_PAGE_SIZE,
    PV_MIN_PAGE,
    PV_MIN_PAGE_SIZE,
    PVErrorBody,
    PVErrorCode,
    PVErrorEnvelope,
    PVPaginatedResponse,
    PVPaginationContract,
    PVPaginationParams,
)

# Canonical identity references use the same shape as the PV reference schema.
CanonicalIdentityReference = PVReference

__all__ = [
    "PV_DEFAULT_PAGE_SIZE",
    "PV_MAX_PAGE_SIZE",
    "PV_MIN_PAGE",
    "PV_MIN_PAGE_SIZE",
    "CanonicalIdentityReference",
    "CaseState",
    "CorrelationIdentifier",
    "Correlation_Identifier",
    "IdempotencyKey",
    "Idempotency_Key",
    "Module",
    "PVCapabilityManifest",
    "PVErrorBody",
    "PVErrorCode",
    "PVErrorEnvelope",
    "PVPaginatedResponse",
    "PVPaginationContract",
    "PVPaginationParams",
    "PVReference",
    "ReportStatus",
]
