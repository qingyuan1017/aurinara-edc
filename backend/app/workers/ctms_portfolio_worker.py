"""Scheduled CTMS portfolio projection jobs.

The scheduler may invoke these functions daily. They keep their transaction
boundary explicit so a failed refresh cannot leave partial site snapshots.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from app.core.database import async_session_factory
from app.services.ctms.portfolio_management_service import portfolio_management_service


async def refresh_daily_site_performance(snapshot_date: date | None = None) -> int:
    async with async_session_factory() as session, session.begin():
        return await portfolio_management_service.refresh_performance_snapshots(
            session, snapshot_date=snapshot_date
        )


async def execute_portfolio_workflow_trigger(
    *,
    trigger_type: str,
    source_type: str,
    source_id: UUID,
    occurrence_key: str,
    context: dict[str, Any],
    actor_id: UUID,
    correlation_id: str,
) -> int:
    async with async_session_factory() as session, session.begin():
        executions = await portfolio_management_service.execute_workflow_trigger(
            session,
            trigger_type=trigger_type,
            source_type=source_type,
            source_id=source_id,
            occurrence_key=occurrence_key,
            context=context,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        return len(executions)


__all__ = ["execute_portfolio_workflow_trigger", "refresh_daily_site_performance"]
