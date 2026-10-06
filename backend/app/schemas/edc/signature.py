"""Pydantic schemas for re-authenticated electronic signatures."""

from uuid import UUID

from pydantic import Field

from app.models.edc.signature import SignatureObjectType, SignatureStatus
from app.schemas.shared.base import BaseCreateSchema, BaseSchema, UtcDatetime


class SignatureRequest(BaseCreateSchema):
    """Credentials and attestation meaning submitted to record a signature."""

    meaning: str = Field(min_length=1, max_length=2000)
    password: str = Field(min_length=1, max_length=1024)


class SignatureResponse(BaseSchema):
    """Electronic signature metadata returned to the client."""

    id: UUID
    object_type: SignatureObjectType
    object_id: UUID
    signed_by: UUID
    signed_at: UtcDatetime
    signature_meaning: str
    data_hash: str
    status: SignatureStatus
    stale_reason: str | None = None
