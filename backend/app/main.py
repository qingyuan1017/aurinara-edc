"""FastAPI application factory.

Mounts all routers under /api/v1 (Requirement 21.1).
Configures structured logging and request-ID middleware (Requirements 21.5, 30.4).
Registers metrics middleware (Requirement 30.2).
"""

import logging
import time
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api.routes.ai_assistant import router as ai_assistant_router
from app.api.routes.audit import fields_audit_router, subjects_audit_router
from app.api.routes.audit import router as audit_router
from app.api.routes.auth import router as auth_router
from app.api.routes.ctms import router as ctms_router
from app.api.routes.dashboards import site_dashboard_router, study_dashboard_router
from app.api.routes.edit_checks import router as edit_checks_router
from app.api.routes.edit_checks import study_router as study_edit_checks_router
from app.api.routes.exports import router as exports_router
from app.api.routes.exports import study_exports_router
from app.api.routes.files import router as files_router
from app.api.routes.form_data import router as form_data_router
from app.api.routes.forms import fields_router, study_forms_router
from app.api.routes.forms import router as forms_router
from app.api.routes.health import router as health_router
from app.api.routes.locks import router as locks_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.pv import router as pv_router
from app.api.routes.pv.ai import router as pv_ai_router
from app.api.routes.queries import router as queries_router
from app.api.routes.queries import study_queries_router
from app.api.routes.records import form_instance_records_router
from app.api.routes.records import router as records_router
from app.api.routes.reviews import router as reviews_router
from app.api.routes.reviews import study_router as study_reviews_router
from app.api.routes.sdv import router as sdv_router
from app.api.routes.signatures import router as signatures_router
from app.api.routes.sites import router as sites_router
from app.api.routes.sites import study_sites_router
from app.api.routes.studies import router as studies_router
from app.api.routes.studies import versions_router
from app.api.routes.subjects import router as subjects_router
from app.api.routes.subjects import study_subjects_router
from app.api.routes.users import router as users_router
from app.api.routes.visits import router as visits_router
from app.api.routes.visits import subject_visits_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.metrics import get_metrics
from app.core.middleware import RequestIDMiddleware
from app.core.observability import sanitized_log_extra
from app.core.openapi import API_TAGS, install_openapi_metadata
from app.services.pv_observability_service import pv_observability_service

pv_request_logger = logging.getLogger("app.pv.request")

# PV routes are mounted below this prefix; PV observability signals are scoped
# to requests under it so PV metrics reflect only PV API behavior.
_PV_PATH_PREFIX = "/api/v1/pv"


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records API request latency and status code in the metrics collector.

    Requests under the PV route prefix are additionally recorded in the PV
    observability window and produce exactly one sanitized structured log entry
    carrying the request identifier, a UTC timestamp, the operation outcome, and
    the duration in milliseconds (Requirements 25.3, 25.4). The log entry never
    includes safety content, projected fields, request bodies, or raw
    coordination payloads (Requirements 24.2, 16.3, 16.5).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        latency = time.perf_counter() - start
        get_metrics().record_request(latency, response.status_code)

        if request.url.path.startswith(_PV_PATH_PREFIX):
            duration_ms = latency * 1000
            pv_observability_service.record_request(
                latency_ms=duration_ms, status_code=response.status_code
            )
            outcome = "success" if response.status_code < 400 else "error"
            pv_request_logger.info(
                "pv request completed",
                extra={
                    "extra_fields": sanitized_log_extra(
                        module="PV",
                        request_id=getattr(request.state, "request_id", None),
                        timestamp=datetime.now(UTC).isoformat(),
                        method=request.method,
                        path=request.url.path,
                        status_code=response.status_code,
                        outcome=outcome,
                        duration_ms=round(duration_ms, 3),
                    )
                },
            )
        return response


def create_app() -> FastAPI:
    """Application factory — creates and configures the FastAPI instance."""
    settings = get_settings()

    # Configure structured logging before anything else
    setup_logging(log_level=settings.log_level, log_json=settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        description=(
            "Unified Clinical Platform API. EDC remains authoritative for clinical data; "
            "CTMS owns operational workflows and exposes only approved projections."
        ),
        openapi_tags=API_TAGS,
        docs_url=f"{settings.api_v1_prefix}/docs",
        redoc_url=f"{settings.api_v1_prefix}/redoc",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    )
    install_openapi_metadata(app)

    # --- Middleware (outermost first) ---
    # RequestIDMiddleware must be outermost so all inner middleware/routes see request_id
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # --- Exception handlers (Requirement 21.3) ---
    register_exception_handlers(app)

    # --- Mount routers under /api/v1 ---
    app.include_router(health_router, prefix=settings.api_v1_prefix)
    app.include_router(ctms_router, prefix=settings.api_v1_prefix)
    app.include_router(pv_router, prefix=settings.api_v1_prefix)
    # The optional PV-scoped AI assistant is mounted only while enabled so that
    # disabling it exposes none of its operations (Requirement 22.1). It is
    # nested under the PV prefix (``/api/v1/pv/ai``).
    if settings.ai_assistant_enabled and settings.pv_ai_enabled:
        app.include_router(
            pv_ai_router, prefix=f"{settings.api_v1_prefix}/pv"
        )
    app.include_router(ai_assistant_router, prefix=settings.api_v1_prefix)
    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(users_router, prefix=settings.api_v1_prefix)
    app.include_router(studies_router, prefix=settings.api_v1_prefix)
    app.include_router(versions_router, prefix=settings.api_v1_prefix)
    app.include_router(study_sites_router, prefix=settings.api_v1_prefix)
    app.include_router(sites_router, prefix=settings.api_v1_prefix)
    app.include_router(study_subjects_router, prefix=settings.api_v1_prefix)
    app.include_router(subjects_router, prefix=settings.api_v1_prefix)
    app.include_router(subject_visits_router, prefix=settings.api_v1_prefix)
    app.include_router(visits_router, prefix=settings.api_v1_prefix)
    app.include_router(study_forms_router, prefix=settings.api_v1_prefix)
    app.include_router(forms_router, prefix=settings.api_v1_prefix)
    app.include_router(fields_router, prefix=settings.api_v1_prefix)
    app.include_router(form_data_router, prefix=settings.api_v1_prefix)
    app.include_router(files_router, prefix=settings.api_v1_prefix)
    app.include_router(study_queries_router, prefix=settings.api_v1_prefix)
    app.include_router(queries_router, prefix=settings.api_v1_prefix)
    app.include_router(form_instance_records_router, prefix=settings.api_v1_prefix)
    app.include_router(records_router, prefix=settings.api_v1_prefix)
    app.include_router(study_exports_router, prefix=settings.api_v1_prefix)
    app.include_router(exports_router, prefix=settings.api_v1_prefix)
    app.include_router(study_edit_checks_router, prefix=settings.api_v1_prefix)
    app.include_router(edit_checks_router, prefix=settings.api_v1_prefix)
    app.include_router(study_dashboard_router, prefix=settings.api_v1_prefix)
    app.include_router(site_dashboard_router, prefix=settings.api_v1_prefix)
    app.include_router(sdv_router, prefix=settings.api_v1_prefix)
    app.include_router(study_reviews_router, prefix=settings.api_v1_prefix)
    app.include_router(reviews_router, prefix=settings.api_v1_prefix)
    app.include_router(locks_router, prefix=settings.api_v1_prefix)
    app.include_router(signatures_router, prefix=settings.api_v1_prefix)
    app.include_router(notifications_router, prefix=settings.api_v1_prefix)
    app.include_router(audit_router, prefix=settings.api_v1_prefix)
    app.include_router(subjects_audit_router, prefix=settings.api_v1_prefix)
    app.include_router(fields_audit_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
