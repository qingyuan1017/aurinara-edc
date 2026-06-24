"""Role repository — data access for Role aggregate.

Satisfies Requirements:
  - 3.3: Role management with system/study/site scope and permission codes.
  - 23.2: Database access only through the repository layer.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Role
from app.schemas.base import PaginatedResponse
from app.schemas.user import RoleResponse


class RoleRepository:
    """Encapsulates all Role database operations."""

    async def get_by_id(self, session: AsyncSession, role_id: UUID) -> Role | None:
        """Fetch a single Role by primary key."""
        return await session.get(Role, role_id)

    async def list_roles(
        self,
        session: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 25,
    ) -> PaginatedResponse[RoleResponse]:
        """List all Roles with pagination."""
        stmt = select(Role)

        # Total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        # Apply pagination
        offset = (page - 1) * page_size
        stmt = stmt.order_by(Role.name).offset(offset).limit(page_size)

        result = await session.execute(stmt)
        roles = result.scalars().all()

        items = [RoleResponse.model_validate(r) for r in roles]
        return PaginatedResponse[RoleResponse](
            items=items,
            page=page,
            page_size=page_size,
            total=total,
        )

    async def create(self, session: AsyncSession, *, name: str, scope_level: str, description: str | None = None, is_system: bool = False) -> Role:
        """Persist a new Role."""
        role = Role(
            name=name,
            scope_level=scope_level,
            description=description,
            is_system=is_system,
        )
        session.add(role)
        await session.flush()
        return role
