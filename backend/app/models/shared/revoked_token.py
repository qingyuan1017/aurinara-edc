"""Revoked token store — persists JTIs of revoked refresh tokens.

Satisfies Requirement 1.4: logout revokes the refresh token so it cannot be
reused to obtain new access tokens.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RevokedToken(Base):
    """A revoked refresh token identified by its JTI claim."""

    __tablename__ = "revoked_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    jti: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="JWT ID of the revoked token"
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Original token expiry; allows periodic cleanup of expired entries",
    )

    __table_args__ = (Index("ix_revoked_tokens_jti", "jti"),)

    def __repr__(self) -> str:
        return f"<RevokedToken(jti={self.jti!r}, user_id={self.user_id})>"
