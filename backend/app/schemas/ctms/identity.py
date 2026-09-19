"""Pydantic contracts for canonical EDC identity links."""

from uuid import UUID

from pydantic import Field

from app.core.ctms import Module, OwnershipState
from app.schemas.base import BaseSchema


class CanonicalIdentityReference(BaseSchema):
    """Read-only canonical reference persisted on a CTMS-owned record."""

    id: UUID = Field(description="Stable canonical EDC identifier")
    entity_type: str
    source_module: Module = Module.EDC
    ownership_state: OwnershipState = OwnershipState.PROJECTED
    source_identifier: UUID
    target_reference: UUID | None = None
    ownership_rule_version: int
    correlation_id: str

    @property
    def read_only(self) -> bool:
        """Canonical EDC references are never writable through CTMS."""

        return True


__all__ = ["CanonicalIdentityReference"]
