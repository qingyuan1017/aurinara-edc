"""PV ICSR/E2B(R3) produce and import request/response schemas.

These transport contracts wrap the pure ``produce_e2b``/``parse_e2b`` functions
on the ``Regulatory_Reporting_Service``. Producing serializes a reportable
Safety_Case representation into an E2B(R3) message; importing parses a
structurally valid message back into that representation. No Safety_Case is
created or mutated by either endpoint (Requirement 9).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ICSRProduceRequest(BaseModel):
    """Request to produce an E2B(R3) message from a reportable Safety_Case."""

    model_config = ConfigDict(populate_by_name=True)

    case: dict[str, Any] = Field(
        description=(
            "Reportable Safety_Case representation: case_identifier, every "
            "mandatory E2B(R3) field, and a dictionary_versions map of coding "
            "dictionary name to Coding_Dictionary_Version."
        )
    )
    case_id: UUID | None = Field(
        default=None,
        description="Optional PV Safety_Case identifier for audit correlation.",
    )
    study_id: UUID | None = Field(default=None, description="Study scope for the audit event.")
    site_id: UUID | None = Field(default=None, description="Site scope for the audit event.")


class ICSRProduceResponse(BaseModel):
    """The produced E2B(R3) message."""

    message: str = Field(description="The E2B(R3)-structured XML message.")


class ICSRImportRequest(BaseModel):
    """Request to import (parse) a structurally valid E2B(R3) message."""

    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(description="The E2B(R3) XML message to parse.")
    study_id: UUID | None = Field(default=None, description="Study scope for the audit event.")
    site_id: UUID | None = Field(default=None, description="Site scope for the audit event.")


class ICSRImportResponse(BaseModel):
    """The parsed Safety_Case representation extracted from the message."""

    case_identifier: str = Field(description="The parsed case identifier.")
    mandatory_fields: dict[str, Any] = Field(
        description="Every mandatory E2B(R3) field parsed from the message."
    )
    dictionary_versions: dict[str, str] = Field(
        description="Coding_Dictionary_Versions parsed from the message."
    )


__all__ = [
    "ICSRImportRequest",
    "ICSRImportResponse",
    "ICSRProduceRequest",
    "ICSRProduceResponse",
]
