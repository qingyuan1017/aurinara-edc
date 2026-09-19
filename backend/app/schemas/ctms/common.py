"""Shared CTMS schema primitives and ownership-safe identifiers."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.core.ctms import (
    Correlation_Identifier,
    CorrelationIdentifier,
    CTMSPhase,
    Idempotency_Key,
    IdempotencyKey,
    Module,
    OwnershipState,
    UTCDateTime,
    ensure_utc,
    utc_now,
)
from app.schemas.base import BaseSchema


class CTMSReference(BaseSchema):
    """Read-only reference to a canonical identity owned by EDC or the platform.

    The extra traceability fields are metadata only.  They do not make the EDC
    identifier writable or copy any clinical record into CTMS.
    """

    id: UUID
    module: Module
    ownership_state: OwnershipState = OwnershipState.PROJECTED
    source_identifier: UUID | None = None
    target_reference: UUID | None = None
    ownership_rule_version: int | None = None
    correlation_id: str | None = None

    @property
    def read_only(self) -> bool:
        return True


class CTMSCapabilityManifest(BaseSchema):
    """API response for server-controlled CTMS phase capabilities."""

    module: Module = Module.CTMS
    enabled: bool
    phase: CTMSPhase
    capabilities: list[str] = Field(default_factory=list)


__all__ = [
    "CTMSCapabilityManifest",
    "CTMSPhase",
    "CTMSReference",
    "CorrelationIdentifier",
    "Correlation_Identifier",
    "IdempotencyKey",
    "Idempotency_Key",
    "Module",
    "OwnershipState",
    "UTCDateTime",
    "datetime",
    "ensure_utc",
    "utc_now",
]
