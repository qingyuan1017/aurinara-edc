"""Versioned EDC API route package.

Aggregates the operational EDC clinical resource routers into a single
``router`` mounted below ``/api/v1``. The aggregate adds no prefix of its own,
so each resource router keeps the exact path prefix it declares (e.g.
``/studies``, ``/sites``, ``/visits``). EDC routes are kept separate from CTMS
and PV routes so disabling either of those never changes EDC clinical route
ownership or behavior.

Design-authoring surfaces (study-version create/publish/amend, form/field
definition authoring, and edit-check authoring/testing) are no longer served
here — they live in the Designer aggregate mounted under ``/designer``. Only
operational routers (operational study CRUD + study-info reads, sites,
subjects, visit instances, form data, records, queries, SDV, reviews, locks,
signatures, dashboards, exports) remain in the EDC aggregate, keeping their
existing no-prefix paths for backward compatibility.
"""

from fastapi import APIRouter

from app.api.routes.edc.dashboards import (
    site_dashboard_router,
    study_dashboard_router,
)
from app.api.routes.edc.exports import router as exports_router
from app.api.routes.edc.exports import study_exports_router
from app.api.routes.edc.form_data import router as form_data_router
from app.api.routes.edc.locks import router as locks_router
from app.api.routes.edc.queries import router as queries_router
from app.api.routes.edc.queries import study_queries_router
from app.api.routes.edc.records import form_instance_records_router
from app.api.routes.edc.records import router as records_router

# --- Report_Area routers (task 16.1): read-only, server-side scope-filtered ---
from app.api.routes.edc.reports import reports_router, study_reports_router
from app.api.routes.edc.reviews import router as reviews_router
from app.api.routes.edc.reviews import study_router as study_reviews_router
from app.api.routes.edc.sdv import router as sdv_router
from app.api.routes.edc.signatures import router as signatures_router
from app.api.routes.edc.sites import router as sites_router
from app.api.routes.edc.sites import study_sites_router
from app.api.routes.edc.studies import router as studies_router

# --- Study_Info_Area sub-area routers (task 15.1, R8.1-R8.2, R8.5, R8.8-R8.13) ---
from app.api.routes.edc.study_info import (
    crf_version_router,
    design_version_router,
    study_information_router,
)
from app.api.routes.edc.study_info_areas import (
    adjudication_router,
    alerts_router,
    external_data_source_router,
    integrations_router,
    lab_router,
    saes_router,
    sdr_router,
)
from app.api.routes.edc.subjects import router as subjects_router
from app.api.routes.edc.subjects import study_subjects_router
from app.api.routes.edc.visits import router as visits_router
from app.api.routes.edc.visits import subject_visits_router

# Mounted without an added prefix so each resource router keeps its own path.
router = APIRouter()
for resource_router in (
    studies_router,
    study_sites_router,
    sites_router,
    study_subjects_router,
    subjects_router,
    subject_visits_router,
    visits_router,
    form_data_router,
    study_queries_router,
    queries_router,
    form_instance_records_router,
    records_router,
    study_exports_router,
    exports_router,
    study_dashboard_router,
    site_dashboard_router,
    sdv_router,
    study_reviews_router,
    reviews_router,
    locks_router,
    signatures_router,
    # --- Report_Area (task 16.1): read-only, server-side scope-filtered ---
    study_reports_router,
    reports_router,
    # --- Study_Info_Area (task 15.1, R8.1-R8.2, R8.5, R8.8-R8.13) ---
    study_information_router,
    crf_version_router,
    design_version_router,
    alerts_router,
    sdr_router,
    lab_router,
    external_data_source_router,
    adjudication_router,
    saes_router,
    integrations_router,
):
    router.include_router(resource_router)

__all__ = ["router"]
