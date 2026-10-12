"""Database-backed runner for queued EDC clinical exports.

The HTTP request creates the durable export row and returns immediately. This
worker claims EDC-owned rows without waiting on another worker, then delegates
content generation and lifecycle transitions to ``export_worker``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ctms import Module
from app.core.database import async_session_factory
from app.core.logging import setup_logging
from app.core.observability import sanitize_error
from app.models.shared.export import Export, ExportStatus
from app.services.shared.export_service import export_service
from app.workers.export_worker import run_export

WORKER_NAME = "edc-export"
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_BATCH_SIZE = 10

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


async def claim_next(session: AsyncSession) -> Export | None:
    """Claim the oldest queued EDC-owned export without waiting on row locks."""
    return await session.scalar(
        select(Export)
        .where(
            Export.status == ExportStatus.queued,
            Export.module == Module.EDC.value,
            Export.content_owner == Module.EDC.value,
        )
        .order_by(Export.created_at.asc(), Export.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )


async def process_next(session: AsyncSession) -> Export | None:
    """Process one queued EDC export, retaining a worker-recorded failure."""
    export = await claim_next(session)
    if export is None:
        return None

    try:
        await run_export(session, export)
    except Exception as exc:
        # Format-specific workers transition Running jobs to Failed before
        # re-raising. Keep the exception inside this transaction so that the
        # failure state is committed instead of rolled back.
        safe_error = sanitize_error(exc)
        logger.error(
            "EDC export job failed: export_id=%s category=%s",
            export.id,
            safe_error["category"],
        )
        # Guard against an unexpected failure before the format worker starts
        # the lifecycle. A poison job must not remain Queued forever.
        if export.status == ExportStatus.queued:
            await export_service.start_export(session, export)
        if export.status == ExportStatus.running:
            await export_service.fail_export(
                session,
                export,
                error_message=f"{safe_error['category']}: {safe_error['message']}",
            )
    return export


async def consume_once(
    *,
    max_jobs: int = DEFAULT_BATCH_SIZE,
    session_factory: SessionFactory = async_session_factory,
) -> int:
    """Process at most ``max_jobs`` currently queued exports."""
    if max_jobs < 1:
        raise ValueError("max_jobs must be at least 1")

    processed = 0
    while processed < max_jobs:
        async with session_factory() as session:
            export = await process_next(session)
            if export is None:
                await session.rollback()
                break
            await session.commit()
            processed += 1
            logger.info(
                "EDC export job processed: export_id=%s status=%s",
                export.id,
                export.status,
            )
    return processed


async def run_forever(
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    session_factory: SessionFactory = async_session_factory,
) -> None:
    """Poll continuously, backing off only when no queued work is available."""
    if poll_interval <= 0:
        raise ValueError("poll_interval must be greater than 0")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    logger.info(
        "EDC export worker started: poll_interval=%s batch_size=%s",
        poll_interval,
        batch_size,
    )
    while True:
        try:
            processed = await consume_once(
                max_jobs=batch_size,
                session_factory=session_factory,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            safe_error = sanitize_error(exc)
            logger.error(
                "EDC export worker poll failed: category=%s",
                safe_error["category"],
            )
            processed = 0
        if processed == 0:
            await asyncio.sleep(poll_interval)


def main() -> None:
    settings = get_settings()
    setup_logging(log_level=settings.log_level, log_json=settings.log_json)
    parser = argparse.ArgumentParser(description="Process queued EDC clinical exports")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continue polling instead of processing one bounded batch",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Seconds to wait when no work is available (watch mode only)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Maximum jobs to process per polling pass",
    )
    args = parser.parse_args()

    if args.watch:
        asyncio.run(
            run_forever(
                poll_interval=args.poll_interval,
                batch_size=args.batch_size,
            )
        )
    else:
        asyncio.run(consume_once(max_jobs=args.batch_size))


if __name__ == "__main__":
    main()


__all__ = [
    "WORKER_NAME",
    "claim_next",
    "consume_once",
    "process_next",
    "run_forever",
]
