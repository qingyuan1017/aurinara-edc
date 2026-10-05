"""Shared PV/Safety schema primitives and ownership-safe identifiers."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.core.pv import (
    CapabilityManifest as _CapabilityManifest,
)
from app.core.pv import (
    CaseState,
    Correlation_Identifier,
    CorrelationIdentifier,
    Idempotency_Key,
    IdempotencyKey,
    Module,
    PVPhase,
    ReportStatus,
    UTCDateTime,
    ensure_utc,
    utc_now,
)
from app.schemas.base import BaseSchema


class PVReference(BaseSchema):
    """Read-only reference to a canonical identity owned by EDC or the platform.

    The traceability fields are metadata only. They do not make the referenced
    identifier writable or copy any clinical/operational record into PV.
    """

    id: UUID
    module: Module
    source_identifier: UUID | None = None
    target_reference: UUID | None = None
    ownership_rule_version: int | None = None
    correlation_id: str | None = None

    @property
    def read_only(self) -> bool:
        return True


class PVCapabilityManifest(BaseSchema):
    """API response for server-controlled PV phase capabilities."""

    module: Module = Module.PV
    enabled: bool
    phase: PVPhase
    capabilities: list[str] = Field(default_factory=list)


__all__ = [
    "CaseState",
    "CorrelationIdentifier",
    "Correlation_Identifier",
    "IdempotencyKey",
    "Idempotency_Key",
    "Module",
    "PVCapabilityManifest",
    "PVPhase",
    "PVReference",
    "ReportStatus",
    "UTCDateTime",
    "_CapabilityManifest",
    "datetime",
    "ensure_utc",
    "utc_now",
]
