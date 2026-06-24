"""Invitation repository — data access for Invitation aggregate.

Satisfies Requirements:
  - 3.1: Invitation creation, lookup by token, and listing by status.
  - 23.2: Database access only through the repository layer.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Invitation, InvitationStatus
from app.schemas.base import PaginatedResponse
from app.schemas.user import InvitationCreate, InvitationResponse


class InvitationRepository:
    """Encapsulates all Invitation database operations."""

    async def get_by_token(self, session: AsyncSession, token: str) -> Invitation | None:
        """Fetch a single Invitation by its unique token."""
        stmt = select(Invitation).where(Invitation.token == token)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        session: AsyncSession,
        data: InvitationCreate,
        invited_by: UUID,
        *,
        expires_in_hours: int = 72,
    ) -> Invitation:
        """Persist a new Invitation with a generated token and expiry.

        Args:
            session: Active database session.
            data: Invitation creation payload.
            invited_by: UUID of the user issuing the invitation.
            expires_in_hours: Token validity window (default 72 hours).
        """
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)

        invitation = Invitation(
            email=data.email,
            token=token,
            role_id=data.role_id,
            study_id=data.study_id,
            site_id=data.site_id,
            invited_by=invited_by,
            status=InvitationStatus.pending,
            created_at=now,
            expires_at=now + timedelta(hours=expires_in_hours),
        )
        session.add(invitation)
        await session.flush()
        return invitation

    async def list_by_status(
        self,
        session: AsyncSession,
        status: str,
        *,
        page: int = 1,
        page_size: int = 25,
    ) -> PaginatedResponse[InvitationResponse]:
        """List Invitations filtered by status with pagination."""
        stmt = select(Invitation).where(Invitation.status == status)

        # Total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        # Apply pagination
        offset = (page - 1) * page_size
        stmt = stmt.order_by(Invitation.created_at.desc()).offset(offset).limit(page_size)

        result = await session.execute(stmt)
        invitations = result.scalars().all()

        items = [InvitationResponse.model_validate(inv) for inv in invitations]
        return PaginatedResponse[InvitationResponse](
            items=items,
            page=page,
            page_size=page_size,
            total=total,
        )
