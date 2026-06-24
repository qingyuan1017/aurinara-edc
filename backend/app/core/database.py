"""Engine, async session factory, and unit-of-work / transaction scope.

Satisfies Requirements:
  - 23.2: Database access only through the repository layer (session provided via DI).
  - 21.4 / 23.3: Services commit data + audit in a single transaction.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


def _build_engine():
    settings = get_settings()
    return create_async_engine(
        str(settings.database_url),
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )


engine = _build_engine()

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields a session and commits on success / rolls back on error.

    This is the primary unit-of-work boundary: services perform all data + audit
    writes within the yielded session, and the commit/rollback happens here.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def transaction_scope() -> AsyncGenerator[AsyncSession, None]:
    """Explicit transaction scope for service-layer use outside request context.

    Use this when business logic needs a guaranteed single-transaction boundary
    (e.g., background workers, CLI scripts).
    """
    async with async_session_factory() as session, session.begin():
        yield session
