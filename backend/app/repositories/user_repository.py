"""User repository — data access for User aggregate.

Satisfies Requirements:
  - 3.1: User CRUD, invitation-based creation, deactivation (soft).
  - 3.3: User listing with filters and pagination.
  - 23.2: Database access only through the repository layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User, UserStatus
from app.schemas.base import PaginatedResponse
from app.schemas.user import UserCreate, UserResponse, UserUpdate


class UserRepository:
    """Encapsulates all User database operations."""

    # --- Read ---

    async def get_by_id(self, session: AsyncSession, user_id: UUID) -> User | None:
        """Fetch a single User by primary key."""
        return await session.get(User, user_id)

    async def get_by_email(self, session: AsyncSession, email: str) -> User | None:
        """Fetch a single User by email address (case-insensitive)."""
        stmt = select(User).where(func.lower(User.email) == email.lower())
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_users(
        self,
        session: AsyncSession,
        *,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> PaginatedResponse[UserResponse]:
        """List Users with optional filters and pagination.

        Filters:
          - status: filter by UserStatus value.
          - search: case-insensitive substring match on email, first_name, or last_name.
        """
        stmt = select(User)

        if status:
            stmt = stmt.where(User.status == status)

        if search:
            pattern = f"%{search.lower()}%"
            stmt = stmt.where(
                func.lower(User.email).like(pattern)
                | func.lower(User.first_name).like(pattern)
                | func.lower(User.last_name).like(pattern)
            )

        # Total count before pagination
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        # Apply pagination
        offset = (page - 1) * page_size
        stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(page_size)

        result = await session.execute(stmt)
        users = result.scalars().all()

        items = [UserResponse.model_validate(u) for u in users]
        return PaginatedResponse[UserResponse](
            items=items,
            page=page,
            page_size=page_size,
            total=total,
        )

    # --- Write ---

    async def create(self, session: AsyncSession, data: UserCreate, password_hash: str) -> User:
        """Persist a new User.

        The caller is responsible for hashing the password before passing it here.
        """
        user = User(
            email=data.email,
            first_name=data.first_name,
            last_name=data.last_name,
            password_hash=password_hash,
            status=UserStatus.pending,
        )
        session.add(user)
        await session.flush()
        return user

    async def update(self, session: AsyncSession, user: User, data: UserUpdate) -> User:
        """Apply a partial update to an existing User."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)
        user.updated_at = datetime.now(UTC)
        await session.flush()
        return user

    async def deactivate(self, session: AsyncSession, user: User) -> User:
        """Soft-deactivate a User by setting status to inactive.

        The User record is retained for traceability (Requirement 3.4).
        """
        user.status = UserStatus.inactive
        user.updated_at = datetime.now(UTC)
        await session.flush()
        return user
