"""Health, readiness, and metrics endpoints.

Satisfies Requirements:
  - 30.1: GET /health/live (liveness), GET /health/ready (readiness with DB check)
  - 30.2: GET /metrics (application metrics: latency, error rate, DB pool stats)
  - 30.3: Metrics include auth, export, worker failure counters
  - 30.5: JSON metrics response
"""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.database import engine
from app.core.metrics import get_metrics

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """Simple liveness probe (legacy, kept for backward compat)."""
    return {"status": "ok"}


@router.get("/health/live")
async def liveness() -> dict:
    """Liveness probe — confirms the process is running.

    Returns 200 with {"status": "alive"} unconditionally.
    """
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness() -> dict:
    """Readiness probe — checks downstream dependencies (database).

    Returns 200 if DB is reachable, 503 otherwise.
    """
    from fastapi.responses import JSONResponse

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": str(exc)},
        )


@router.get("/metrics")
async def metrics_endpoint() -> dict:
    """Application metrics endpoint.

    Returns JSON with request latency, error rate, DB connection pool stats,
    and failure counters for auth, export, and worker subsystems.
    """
    collector = get_metrics()
    snapshot = collector.snapshot()

    # Enrich with DB connection pool stats from the async engine
    pool = engine.pool
    pool_stats = {
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
    }

    return {
        **snapshot,
        "db_connections": pool_stats,
    }
