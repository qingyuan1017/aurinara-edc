"""Versioned EDC API route package.

Aggregates all EDC clinical resource routers into a single ``router`` mounted
below ``/api/v1``. The aggregate adds no prefix of its own, so each resource
router keeps the exact path prefix it declares (e.g. ``/studies``, ``/sites``,
``/visits``). EDC routes are kept separate from CTMS and PV routes so disabling
either of those never changes EDC clinical route ownership or behavior.
"""

from fastapi import APIRouter

from app.api.routes.edc.dashboards import (
    site_dashboard_router,
    study_dashboard_router,
)
from app.api.routes.edc.edit_checks import router as edit_checks_router
from app.api.routes.edc.edit_checks import study_router as study_edit_checks_router
from app.api.routes.edc.exports import router as exports_router
from app.api.routes.edc.exports import study_exports_router
from app.api.routes.edc.form_data import router as form_data_router
from app.api.routes.edc.forms import fields_router, study_forms_router
from app.api.routes.edc.forms import router as forms_router
from app.api.routes.edc.locks import router as locks_router
from app.api.routes.edc.queries import router as queries_router
from app.api.routes.edc.queries import study_queries_router
from app.api.routes.edc.records import form_instance_records_router
from app.api.routes.edc.records import router as records_router
from app.api.routes.edc.reviews import router as reviews_router
from app.api.routes.edc.reviews import study_router as study_reviews_router
from app.api.routes.edc.sdv import router as sdv_router
from app.api.routes.edc.signatures import router as signatures_router
from app.api.routes.edc.sites import router as sites_router
from app.api.routes.edc.sites import study_sites_router
from app.api.routes.edc.studies import router as studies_router
from app.api.routes.edc.studies import versions_router
from app.api.routes.edc.subjects import router as subjects_router
from app.api.routes.edc.subjects import study_subjects_router
from app.api.routes.edc.visits import router as visits_router
from app.api.routes.edc.visits import subject_visits_router

# Mounted without an added prefix so each resource router keeps its own path.
router = APIRouter()
for resource_router in (
    studies_router,
    versions_router,
    study_sites_router,
    sites_router,
    study_subjects_router,
    subjects_router,
    subject_visits_router,
    visits_router,
    study_forms_router,
    forms_router,
    fields_router,
    form_data_router,
    study_queries_router,
    queries_router,
    form_instance_records_router,
    records_router,
    study_exports_router,
    exports_router,
    study_edit_checks_router,
    edit_checks_router,
    study_dashboard_router,
    site_dashboard_router,
    sdv_router,
    study_reviews_router,
    reviews_router,
    locks_router,
    signatures_router,
):
    router.include_router(resource_router)

__all__ = ["router"]
