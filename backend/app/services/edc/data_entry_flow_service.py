"""Data_Entry_Flow_Service — the operational sequential data-entry state machine.

The ``Data_Entry_Flow`` is a **sequential state machine** in the EDC_Module. A
site data-entry user walks through five ordered steps:

    SITE -> SUBJECT -> VISIT -> FORM -> DATA

Each step reads the bound ``Published_Design`` **only** through the
``DesignConsumptionService`` and delegates all persistence to the existing
operational services (``subject_service``, ``visit_service``,
``data_capture_service``). The user cannot advance to a later step before the
required prior step is complete (R7.8); an out-of-order advance is rejected, the
current step is retained, and the error identifies the incomplete prior step.

The flow is modelled as an explicit, immutable-by-convention
``DataEntryFlowState`` (current step + the selections accumulated so far) plus a
``DataEntryFlowService`` that validates each transition and mutates the state in
place on success. The service owns no design-write path — it never imports a
designer write service — and reads design configuration exclusively through the
consumption contract.

Satisfies Requirements:
  - 7.1 / 7.10: Scope-gated site selection via ``permission_service.filter_sites``;
          an out-of-scope site is rejected with a not-authorized error.
  - 7.2:  A site selection is required before subject selection; a subject
          selection/creation is required before visit selection; a visit before
          form; a form before data entry.
  - 7.3 / 2.7: Adding a new subject binds it to exactly one ``Published_Design``
          (delegated to ``subject_service`` which binds via the published
          version).
  - 7.4:  A scheduled or unscheduled visit must be selected before form entry.
  - 7.5:  Unscheduled visits are allowed only where the bound design permits
          them (``DesignConsumptionService.permits_unscheduled_visits``).
  - 7.6 / 7.7: Form choices and field sets come from the bound design; entered
          values persist as Operational_Records (delegated to
          ``data_capture_service``).
  - 7.8:  Out-of-order advances are rejected, the current step is retained, and
          the error identifies the incomplete prior step.
  - 7.9 / 2.8: Subject creation with no ``Published_Design`` is rejected and
          study data is left unchanged (delegated to ``subject_service``, which
          raises before any write).
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BusinessRuleError, NotFoundError
from app.models.edc.form_data import FormInstance
from app.models.edc.site import Site
from app.models.edc.subject import Subject
from app.models.shared.identity import User
from app.schemas.edc.subject import SubjectCreate
from app.schemas.edc.visit import UnscheduledVisitCreate
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)
from app.services.edc.data_capture_service import DataCaptureService, data_capture_service
from app.services.edc.subject_service import SubjectService, subject_service
from app.services.edc.visit_service import VisitService, visit_service
from app.services.shared.permission_service import PermissionService

logger = logging.getLogger(__name__)


class FlowStep(enum.IntEnum):
    """The ordered steps of the Data_Entry_Flow.

    The integer ordering encodes the sequence so step comparisons (``<``/``>``)
    express "earlier"/"later" directly. ``START`` is the entry point before any
    site is selected; each later value is reached only after the prior step is
    complete.
    """

    START = 0
    SITE = 1
    SUBJECT = 2
    VISIT = 3
    FORM = 4
    DATA = 5


# Human-readable names for the prior step an out-of-order advance is missing
# (R7.8 — the error must identify the incomplete prior step).
_STEP_LABELS: dict[FlowStep, str] = {
    FlowStep.START: "start",
    FlowStep.SITE: "site selection",
    FlowStep.SUBJECT: "subject selection",
    FlowStep.VISIT: "visit selection",
    FlowStep.FORM: "form selection",
    FlowStep.DATA: "data entry",
}


@dataclass
class DataEntryFlowState:
    """The accumulated state of one Data_Entry_Flow session.

    ``current_step`` is the furthest step completed so far. The selection fields
    are populated as each step completes and are read by later steps (e.g. the
    bound ``design_version_id`` captured at subject selection gates unscheduled
    visits and drives form/field choices).
    """

    study_id: UUID
    current_step: FlowStep = FlowStep.START

    site_id: UUID | None = None
    subject_id: UUID | None = None
    design_version_id: UUID | None = None
    visit_instance_id: UUID | None = None
    form_instance_id: UUID | None = None
    # Field definition ids presented for the selected form (R7.6/R7.7).
    form_field_ids: tuple[UUID, ...] = field(default_factory=tuple)


class DataEntryFlowService:
    """Sequential state machine for operational data entry.

    One instance is reusable across flows; each flow is represented by a
    ``DataEntryFlowState`` passed to every transition. The service accepts its
    collaborators by constructor injection (defaulting to the module singletons)
    so tests can substitute fakes without patching import sites.
    """

    def __init__(
        self,
        *,
        permission_service: PermissionService | None = None,
        design_service: DesignConsumptionService | None = None,
        subjects: SubjectService | None = None,
        visits: VisitService | None = None,
        data_capture: DataCaptureService | None = None,
    ) -> None:
        self._permissions = permission_service or PermissionService()
        self._design = design_service or design_consumption_service
        self._subjects = subjects or subject_service
        self._visits = visits or visit_service
        self._data_capture = data_capture or data_capture_service

    # ------------------------------------------------------------------
    # Flow start
    # ------------------------------------------------------------------

    def start(self, study_id: UUID) -> DataEntryFlowState:
        """Begin a new Data_Entry_Flow for a study at the ``START`` step."""
        return DataEntryFlowState(study_id=study_id)

    # ------------------------------------------------------------------
    # Step ordering guard (R7.8)
    # ------------------------------------------------------------------

    def _require_prior_step(
        self, state: DataEntryFlowState, required: FlowStep, target: FlowStep
    ) -> None:
        """Reject an advance to ``target`` when the required prior step is unmet.

        Retains the current step (no mutation on this path) and raises an error
        that identifies the incomplete prior step (R7.8).
        """
        if state.current_step < required:
            raise BusinessRuleError(
                message=(
                    f"Cannot advance to {_STEP_LABELS[target]} before completing "
                    f"{_STEP_LABELS[required]}"
                ),
                details={
                    "attempted_step": _STEP_LABELS[target],
                    "incomplete_prior_step": _STEP_LABELS[required],
                    "current_step": _STEP_LABELS[state.current_step],
                },
            )

    # ------------------------------------------------------------------
    # Step 1 — Site selection (R7.1, R7.10)
    # ------------------------------------------------------------------

    async def select_site(
        self,
        session: AsyncSession,
        state: DataEntryFlowState,
        user: User,
        site_id: UUID,
    ) -> DataEntryFlowState:
        """Select a Site within the user's authorization scope (R7.1, R7.10).

        Only sites inside the user's scope are selectable: the candidate site is
        passed through ``permission_service.filter_sites`` and, if it is not
        returned, the selection is rejected with a not-authorized error (R7.10).
        A site outside the study (or soft-deleted) is a not-found.
        """
        site = await self._get_site(session, state.study_id, site_id)

        allowed = self._permissions.filter_sites(user, [site_id], {site_id: state.study_id})
        if site_id not in allowed:
            raise AuthorizationError(
                message="Site is not within the user's authorization scope",
                details={
                    "site_id": str(site_id),
                    "study_id": str(state.study_id),
                },
            )

        state.site_id = site.id
        state.current_step = FlowStep.SITE
        logger.info(
            "Data entry flow: site selected study_id=%s site_id=%s user=%s",
            state.study_id,
            site.id,
            user.id,
        )
        return state

    # ------------------------------------------------------------------
    # Step 2 — Subject selection / creation (R7.2, R7.3, R7.9, R2.7, R2.8)
    # ------------------------------------------------------------------

    async def select_subject(
        self,
        session: AsyncSession,
        state: DataEntryFlowState,
        subject_id: UUID,
    ) -> DataEntryFlowState:
        """Select an existing Subject under the selected site (R7.2).

        Requires a completed site selection (R7.8). The subject must belong to
        the flow's study and selected site; its bound ``design_version_id`` is
        captured for the later visit/form steps.
        """
        self._require_prior_step(state, FlowStep.SITE, FlowStep.SUBJECT)

        subject = await self._subjects.get_subject(session, subject_id)
        if subject.study_id != state.study_id or subject.site_id != state.site_id:
            raise BusinessRuleError(
                message="Subject does not belong to the selected study and site",
                details={
                    "subject_id": str(subject_id),
                    "expected_study_id": str(state.study_id),
                    "expected_site_id": str(state.site_id),
                },
            )

        self._bind_subject(state, subject)
        logger.info("Data entry flow: existing subject selected subject_id=%s", subject.id)
        return state

    async def add_subject(
        self,
        session: AsyncSession,
        state: DataEntryFlowState,
        data: SubjectCreate,
        actor_id: UUID,
    ) -> DataEntryFlowState:
        """Add a new Subject bound to exactly one ``Published_Design`` (R7.3).

        Requires a completed site selection (R7.8). Delegates creation to
        ``subject_service.create_subject``, which binds the subject to the
        study's latest published ``Design_Version`` (R2.7) and, when no
        ``Published_Design`` exists, raises before any write — so the subject
        creation is rejected and study data is left unchanged (R7.9, R2.8).

        The ``site_id`` on ``data`` is forced to the site already selected in
        the flow so the new subject cannot be bound to a different site.
        """
        self._require_prior_step(state, FlowStep.SITE, FlowStep.SUBJECT)

        if state.site_id is not None and data.site_id != state.site_id:
            data = data.model_copy(update={"site_id": state.site_id})

        subject = await self._subjects.create_subject(session, state.study_id, data, actor_id)

        self._bind_subject(state, subject)
        logger.info(
            "Data entry flow: subject created subject_id=%s design_version_id=%s",
            subject.id,
            subject.study_version_id,
        )
        return state

    def _bind_subject(self, state: DataEntryFlowState, subject: Subject) -> None:
        """Record the selected subject and its bound design on the state."""
        state.subject_id = subject.id
        state.design_version_id = subject.study_version_id
        state.current_step = FlowStep.SUBJECT

    # ------------------------------------------------------------------
    # Step 3 — Visit selection / unscheduled creation (R7.4, R7.5)
    # ------------------------------------------------------------------

    async def select_visit(
        self,
        session: AsyncSession,
        state: DataEntryFlowState,
        visit_instance_id: UUID,
    ) -> DataEntryFlowState:
        """Select a scheduled Visit_Instance for the subject (R7.4).

        Requires a completed subject selection (R7.8). The visit must belong to
        the selected subject.
        """
        self._require_prior_step(state, FlowStep.SUBJECT, FlowStep.VISIT)

        instance = await self._visits.get_instance(session, visit_instance_id)
        if instance.subject_id != state.subject_id:
            raise BusinessRuleError(
                message="Visit instance does not belong to the selected subject",
                details={
                    "visit_instance_id": str(visit_instance_id),
                    "expected_subject_id": str(state.subject_id),
                },
            )

        state.visit_instance_id = instance.id
        state.current_step = FlowStep.VISIT
        logger.info(
            "Data entry flow: scheduled visit selected visit_instance_id=%s",
            instance.id,
        )
        return state

    async def create_unscheduled_visit(
        self,
        session: AsyncSession,
        state: DataEntryFlowState,
        data: UnscheduledVisitCreate,
        actor_id: UUID,
    ) -> DataEntryFlowState:
        """Create an unscheduled Visit_Instance where the design permits it (R7.5).

        Requires a completed subject selection (R7.8). The bound
        ``Published_Design`` is consulted through
        ``DesignConsumptionService.permits_unscheduled_visits``; when it does not
        permit unscheduled visits the creation is rejected and no visit is
        persisted. On success the created visit becomes the selected visit.
        """
        self._require_prior_step(state, FlowStep.SUBJECT, FlowStep.VISIT)

        permits = await self._design.permits_unscheduled_visits(session, state.design_version_id)
        if not permits:
            raise BusinessRuleError(
                message="The bound published design does not permit unscheduled visits",
                details={
                    "design_version_id": str(state.design_version_id),
                    "subject_id": str(state.subject_id),
                },
            )

        subject = await self._subjects.get_subject(session, state.subject_id)
        instance = await self._visits.create_unscheduled(session, subject, data, actor_id)

        state.visit_instance_id = instance.id
        state.current_step = FlowStep.VISIT
        logger.info(
            "Data entry flow: unscheduled visit created visit_instance_id=%s",
            instance.id,
        )
        return state

    # ------------------------------------------------------------------
    # Step 4 — Form selection (R7.6)
    # ------------------------------------------------------------------

    async def select_form(
        self,
        session: AsyncSession,
        state: DataEntryFlowState,
        form_instance_id: UUID,
    ) -> DataEntryFlowState:
        """Select a form defined by the bound ``Published_Design`` (R7.6).

        Requires a completed visit selection (R7.8). The chosen ``FormInstance``
        must belong to the selected subject and visit, and its underlying form
        definition must exist in the bound published design — the field set is
        read from the design (via the consumption contract) and captured on the
        state so data entry presents exactly those fields (R7.6/R7.7).
        """
        self._require_prior_step(state, FlowStep.VISIT, FlowStep.FORM)

        form_instance = await self._get_form_instance(session, form_instance_id)
        if form_instance.subject_id != state.subject_id:
            raise BusinessRuleError(
                message="Form instance does not belong to the selected subject",
                details={
                    "form_instance_id": str(form_instance_id),
                    "expected_subject_id": str(state.subject_id),
                },
            )
        if form_instance.visit_instance_id != state.visit_instance_id:
            raise BusinessRuleError(
                message="Form instance does not belong to the selected visit",
                details={
                    "form_instance_id": str(form_instance_id),
                    "expected_visit_instance_id": str(state.visit_instance_id),
                },
            )

        # Fields come from the bound published design, not the operational store
        # (R7.6). A form not defined in the published design is rejected here by
        # the consumption contract's NotFoundError.
        fields = await self._design.get_form_fields(
            session, state.design_version_id, form_instance.form_definition_id
        )

        state.form_instance_id = form_instance.id
        state.form_field_ids = tuple(f.id for f in fields)
        state.current_step = FlowStep.FORM
        logger.info(
            "Data entry flow: form selected form_instance_id=%s field_count=%d",
            form_instance.id,
            len(state.form_field_ids),
        )
        return state

    # ------------------------------------------------------------------
    # Step 5 — Data entry (R7.7)
    # ------------------------------------------------------------------

    async def enter_data(
        self,
        session: AsyncSession,
        state: DataEntryFlowState,
        values: dict[str, Any],
        actor_id: UUID,
    ) -> FormInstance:
        """Persist entered field values as Operational_Records (R7.7).

        Requires a completed form selection (R7.8). Only fields presented from
        the bound design are accepted; a value for a field outside the design's
        field set is rejected. Persistence is delegated to
        ``data_capture_service.save_draft`` so values are stored as
        Operational_Records with the normal audit/hybrid-storage guarantees.
        """
        self._require_prior_step(state, FlowStep.FORM, FlowStep.DATA)

        allowed_field_ids = {str(fid) for fid in state.form_field_ids}
        unknown = [key for key in values if key not in allowed_field_ids]
        if unknown:
            raise BusinessRuleError(
                message="One or more fields are not part of the selected form's design",
                details={
                    "form_instance_id": str(state.form_instance_id),
                    "unknown_field_ids": unknown,
                },
            )

        form_instance = await self._data_capture.load(session, state.form_instance_id)
        updated = await self._data_capture.save_draft(session, form_instance, values, actor_id)

        state.current_step = FlowStep.DATA
        logger.info(
            "Data entry flow: data entered form_instance_id=%s field_count=%d",
            state.form_instance_id,
            len(values),
        )
        return updated

    # ------------------------------------------------------------------
    # Internal lookups
    # ------------------------------------------------------------------

    async def _get_site(self, session: AsyncSession, study_id: UUID, site_id: UUID) -> Site:
        """Resolve a non-deleted Site within the study, or raise NotFoundError."""
        result = await session.execute(
            select(Site).where(
                Site.id == site_id,
                Site.study_id == study_id,
                Site.deleted_at.is_(None),
            )
        )
        site = result.scalars().first()
        if site is None:
            raise NotFoundError(
                message="Site not found within this study",
                details={"site_id": str(site_id), "study_id": str(study_id)},
            )
        return site

    async def _get_form_instance(
        self, session: AsyncSession, form_instance_id: UUID
    ) -> FormInstance:
        """Resolve a FormInstance by id, or raise NotFoundError."""
        result = await session.execute(
            select(FormInstance).where(FormInstance.id == form_instance_id)
        )
        form_instance = result.scalars().first()
        if form_instance is None:
            raise NotFoundError(
                message="Form instance not found",
                details={"form_instance_id": str(form_instance_id)},
            )
        return form_instance


# Module-level singleton for convenience (mirrors the other EDC services).
data_entry_flow_service = DataEntryFlowService()
