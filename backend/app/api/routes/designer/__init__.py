"""Versioned Designer API route package.

Aggregates design-authoring resource routers (study versions, forms/fields,
form dependencies, edit checks, codelists, subject phases, schedule of
assessment, arms, visits, visit dependencies, CRF access, raw-data variables,
coding settings) into a single ``router``.
The aggregate is mounted below ``/api/v1`` with a ``/designer`` prefix, keeping
design-time routes isolated from the operational EDC, CTMS, and PV routes so
module ownership stays explicit.
"""

from fastapi import APIRouter

from app.api.routes.designer.arms import router as arms_router
from app.api.routes.designer.codelists import (
    router as codelists_router,
)
from app.api.routes.designer.codelists import (
    study_codelists_router,
)
from app.api.routes.designer.coding_settings import router as coding_settings_router
from app.api.routes.designer.crf_access import router as crf_access_router
from app.api.routes.designer.edit_checks import (
    router as edit_checks_router,
)
from app.api.routes.designer.edit_checks import (
    study_router as edit_checks_study_router,
)
from app.api.routes.designer.form_dependencies import (
    router as form_dependencies_router,
)
from app.api.routes.designer.forms import (
    fields_router,
    sections_router,
    study_forms_router,
)
from app.api.routes.designer.forms import (
    router as forms_router,
)
from app.api.routes.designer.raw_data_variables import router as raw_data_variables_router
from app.api.routes.designer.schedule_of_assessment import (
    router as schedule_of_assessment_router,
)
from app.api.routes.designer.study_versions import (
    study_versions_router,
    versions_router,
)
from app.api.routes.designer.subject_phase_transitions import (
    router as subject_phase_transitions_router,
)
from app.api.routes.designer.subject_phases import (
    router as subject_phases_router,
)
from app.api.routes.designer.subject_phases import (
    subject_phases_router as subject_phases_single_router,
)
from app.api.routes.designer.visit_dependencies import (
    router as visit_dependencies_router,
)
from app.api.routes.designer.visits import router as visits_router

DESIGNER_ROUTE_PACKAGE = "app.api.routes.designer"

# The Designer aggregate carries its own ``/designer`` prefix (mirroring the
# CTMS and PV aggregates), so every resource keeps the path it declares nested
# below ``/api/v1/designer``.
router = APIRouter(prefix="/designer")
for resource_router in (
    study_versions_router,
    versions_router,
    study_forms_router,
    forms_router,
    fields_router,
    sections_router,
    form_dependencies_router,
    edit_checks_study_router,
    edit_checks_router,
    study_codelists_router,
    codelists_router,
    subject_phases_router,
    subject_phases_single_router,
    subject_phase_transitions_router,
    schedule_of_assessment_router,
    visits_router,
    visit_dependencies_router,
    arms_router,
    crf_access_router,
    raw_data_variables_router,
    coding_settings_router,
):
    router.include_router(resource_router)

__all__ = ["DESIGNER_ROUTE_PACKAGE", "router"]
