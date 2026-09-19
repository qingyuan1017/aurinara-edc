"""Electronic signature persistence model.

Satisfies Requirements:
  - 17.2: Persists signer identity, signing time, meaning, signed-object
    reference, and a hash of the signed data.
  - 17.3: Represents valid and stale signatures with an optional stale reason.
  - 22.4: Stores the signing timestamp as a timezone-aware UTC value.
  - 22.6: Uses UUID keys and indexes the polymorphic signed-object reference.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SignatureObjectType(enum.StrEnum):
    """Clinical object levels that may carry an electronic signature."""

    field = "field"
    form = "form"
    visit = "visit"
    subject = "subject"
    site = "site"
    study = "study"


class SignatureStatus(enum.StrEnum):
    """Lifecycle status of an electronic signature."""

    valid = "valid"
    stale = "stale"


class Signature(Base):
    """An electronic signature bound to a snapshot of a clinical object.

    ``object_type`` and ``object_id`` form the polymorphic signed-object
    reference. The hash is calculated by ``SignatureService`` from the signed
    data; this model retains the value used at signing time so later changes
    can invalidate the signature without rewriting its original attestation.
    """

    __tablename__ = "signatures"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Signed object (polymorphic reference).
    object_type: Mapped[SignatureObjectType] = mapped_column(
        String(20),
        nullable=False,
        comment="Signed object type: field, form, visit, subject, site, or study",
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        comment="ID of the signed object",
    )

    # Signer identity and attestation details.
    signed_by: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="User who re-authenticated and recorded the signature",
    )
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="UTC timestamp at which the signature was recorded",
    )
    signature_meaning: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Meaning or attestation represented by the signature",
    )
    data_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Hash of the signed data snapshot",
    )

    # Staleness is retained rather than deleting or replacing the attestation.
    status: Mapped[SignatureStatus] = mapped_column(
        String(10),
        nullable=False,
        default=SignatureStatus.valid,
        comment="One of: valid, stale",
    )
    stale_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Reason the signed data no longer matches the data hash",
    )

    signer: Mapped["User"] = relationship("User", lazy="selectin")  # noqa: F821

    __table_args__ = (
        Index("ix_signatures_object_type_object_id", "object_type", "object_id"),
        Index("ix_signatures_signed_by", "signed_by"),
        Index("ix_signatures_status", "status"),
        Index("ix_signatures_signed_at", "signed_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Signature(id={self.id}, object={self.object_type}:{self.object_id}, "
            f"signed_by={self.signed_by}, status={self.status!r})>"
        )
