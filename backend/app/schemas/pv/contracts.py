"""Public PV/Safety API vocabulary and shared response contracts.

PV deliberately reuses the baseline platform ``ErrorEnvelope``/``ErrorBody`` and
request-ID behavior rather than forking a second error model. The only PV-specific
API contract is the pagination envelope, whose page size ranges from 1 through
1,000 (Requirement 16.2 / 24.2) rather than the EDC/CTMS default cap of 100.

These types are transport-facing so PV error codes, enum values, and the
pagination envelope are discoverable in the same OpenAPI document as the PV
routes without exposing internal details, safety data, or coordination payloads.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

from app.schemas.base import ErrorBody, ErrorEnvelope

T = TypeVar("T")

# Bounds for the PV pagination envelope (Requirements 16.2, 24.2).
PV_MIN_PAGE = 1
PV_MIN_PAGE_SIZE = 1
PV_MAX_PAGE_SIZE = 1000
PV_DEFAULT_PAGE_SIZE = 50


class PVErrorCode(StrEnum):
    """Stable, caller-safe API error codes used by PV/Safety routes.

    Codes name the failed operation without exposing internal database errors,
    prohibited safety data, raw coordination payloads, credentials, or stack
    traces (Requirement 16.3). They mirror the design's Error Handling table.
    """

    UNAUTHENTICATED = "UNAUTHENTICATED"
    SESSION_INACTIVE = "SESSION_INACTIVE"
    PV_SCOPE_DENIED = "PV_SCOPE_DENIED"
    PV_RECORD_NOT_FOUND = "PV_RECORD_NOT_FOUND"
    PV_DUPLICATE_IDENTIFIER = "PV_DUPLICATE_IDENTIFIER"
    PV_VALIDATION_ERROR = "PV_VALIDATION_ERROR"
    PV_INVALID_TRANSITION = "PV_INVALID_TRANSITION"
    PV_VERSION_IMMUTABLE = "PV_VERSION_IMMUTABLE"
    PV_SERIOUSNESS_CRITERION_REQUIRED = "PV_SERIOUSNESS_CRITERION_REQUIRED"
    PV_CODING_DICTIONARY_UNAVAILABLE = "PV_CODING_DICTIONARY_UNAVAILABLE"
    PV_AWARENESS_DATE_REQUIRED = "PV_AWARENESS_DATE_REQUIRED"
    PV_E2B_INVALID = "PV_E2B_INVALID"
    PV_PROJECTION_UNAVAILABLE = "PV_PROJECTION_UNAVAILABLE"
    OWNERSHIP_VIOLATION = "OWNERSHIP_VIOLATION"
    PV_CASE_CLOSED = "PV_CASE_CLOSED"
    PV_ATTACHMENT_REJECTED = "PV_ATTACHMENT_REJECTED"
    PV_AUDIT_FAILURE = "PV_AUDIT_FAILURE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# PV reuses the baseline platform error envelope and body verbatim. Aliasing
# keeps a single, sanitized error shape while giving PV routes a named contract.
PVErrorBody = ErrorBody
PVErrorEnvelope = ErrorEnvelope


class PVPaginatedResponse(BaseModel, Generic[T]):
    """PV list envelope: ``items/page/page_size/total`` with page size 1-1,000.

    This mirrors the shared ``PaginatedResponse`` shape and UTC conventions but
    raises the page-size ceiling to 1,000 as required for large safety
    databases (Requirements 16.2, 24.2). It is the only PV-specific deviation
    from the baseline contract; error handling and request context are shared.
    """

    items: list[T]
    page: int = Field(ge=PV_MIN_PAGE, description="1-indexed page number")
    page_size: int = Field(
        ge=PV_MIN_PAGE_SIZE,
        le=PV_MAX_PAGE_SIZE,
        description="Items per page, from 1 through 1,000",
    )
    total: int = Field(ge=0, description="Total number of matching records")


class PVPaginationContract(BaseModel):
    """OpenAPI-visible pagination contract for every PV collection."""

    items: list[Any]
    page: int = Field(ge=PV_MIN_PAGE, description="1-indexed page number")
    page_size: int = Field(
        ge=PV_MIN_PAGE_SIZE,
        le=PV_MAX_PAGE_SIZE,
        description="Items per page, from 1 through 1,000",
    )
    total: int = Field(ge=0, description="Total number of matching records")


@dataclass
class PVPaginationParams:
    """Query-string pagination parameters for PV list endpoints.

    Defaults: ``page=1``, ``page_size=50``. Maximum ``page_size`` is 1,000
    (Requirements 16.2, 24.2). FastAPI enforces the bounds at the boundary so a
    request outside 1-1,000 fails validation rather than returning an oversized
    page.
    """

    page: int = Query(default=PV_MIN_PAGE, ge=PV_MIN_PAGE, description="Page number (1-indexed)")
    page_size: int = Query(
        default=PV_DEFAULT_PAGE_SIZE,
        ge=PV_MIN_PAGE_SIZE,
        le=PV_MAX_PAGE_SIZE,
        description="Items per page (1 through 1,000)",
    )

    @property
    def offset(self) -> int:
        """Compute the SQL OFFSET from page and page_size."""

        return (self.page - 1) * self.page_size


__all__ = [
    "PV_DEFAULT_PAGE_SIZE",
    "PV_MAX_PAGE_SIZE",
    "PV_MIN_PAGE",
    "PV_MIN_PAGE_SIZE",
    "PVErrorBody",
    "PVErrorCode",
    "PVErrorEnvelope",
    "PVPaginatedResponse",
    "PVPaginationContract",
    "PVPaginationParams",
]
