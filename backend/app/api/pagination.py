"""Pagination utility for SQLAlchemy async queries.

Satisfies Requirements:
  - 21.2: List endpoints return a pagination envelope (items, page, page_size, total).
  - 29.2: List endpoints return paginated results.
"""

from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.schemas.base import PaginatedResponse

T = TypeVar("T")


async def paginate(
    session: AsyncSession,
    query: Select[Any],
    params: PaginationParams,
) -> PaginatedResponse[Any]:
    """Apply pagination to a SQLAlchemy select statement.

    Executes a COUNT query for the total and a LIMIT/OFFSET query for the items.
    Returns a PaginatedResponse envelope.

    Args:
        session: The active async database session.
        query: A SQLAlchemy Select statement (un-paginated).
        params: The resolved PaginationParams dependency.

    Returns:
        PaginatedResponse with items, page, page_size, and total.
    """
    # Count total rows matching the query (without limit/offset).
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    # Apply limit and offset to get the current page of items.
    paginated_query = query.limit(params.page_size).offset(params.offset)
    result = await session.execute(paginated_query)
    items: Sequence[Any] = result.scalars().all()

    return PaginatedResponse(
        items=list(items),
        page=params.page,
        page_size=params.page_size,
        total=total,
    )
