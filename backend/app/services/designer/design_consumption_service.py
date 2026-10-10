"""Design_Consumption_Contract — the sole read port into a Published_Design.

This service is the **only** way the EDC_Module reads a ``Published_Design``.
It is read-only and published-only by construction:

  - **Published-only (R2.5).** Every lookup resolves a ``Design_Version``
    (``study_versions`` row) and rejects anything that is not ``published``.
    A missing version raises ``NotFoundError``; a *draft* version raises
    ``ValidationError`` so draft content never crosses the boundary.
  - **Read-only views (R2.6).** Every method returns frozen Pydantic view
    objects from ``app.schemas.designer.views`` built from the published ORM
    entities — never the ORM entities themselves — so a consumer holding a
    result can neither mutate it nor reach back into Designer state.
  - **No reverse dependency.** This port lives in the Designer package; EDC
    imports it. It imports nothing from EDC.

The service owns no mutation path and performs no writes. It accepts the
caller's ``AsyncSession`` (the active read transaction), matching the session-
first convention used across the designer services (e.g.
``study_version_service``).

Satisfies Requirements:
  - 2.5: The contract returns only Published_Design content.
  - 2.6: The EDC_Module reads Designer_Definitions only through this contract and
         treats every consumed definition as read-only.
  - 7.5: ``permits_unscheduled_visits`` decides, from the published design,
         whether the EDC_Module may create unscheduled visit instances.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError, ValidationError
from app.models.designer.arm_definition import ArmDefinition
from app.models.designer.codelist import Codelist
from app.models.designer.coding_setting import CodingSetting
from app.models.designer.crf_access_definition import CrfAccessDefinition
from app.models.designer.edit_check import EditCheck
from app.models.designer.form_dependency import FormDefinitionDependency
from app.models.designer.form_metadata import FormDefinition
from app.models.designer.raw_data_variable_setting import RawDataVariableSetting
from app.models.designer.schedule_of_assessment import ScheduleOfAssessment
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.subject_phase_definition import SubjectPhaseDefinition
from app.models.designer.subject_phase_transition import SubjectPhaseTransition
from app.models.designer.visit import VisitDefinition
from app.models.designer.visit_dependency import VisitDefinitionDependency
from app.schemas.designer.views import (
    ArmDefinitionView,
    CodelistItemView,
    CodelistView,
    CodingSettingView,
    CrfAccessDefinitionView,
    EditCheckRuleView,
    FieldDefinitionView,
    FormDefinitionView,
    FormDependencyView,
    PublishedDesignView,
    RawDataVariableSettingView,
    ScheduleOfAssessmentEntryView,
    ScheduleOfAssessmentView,
    SubjectPhaseDefinitionView,
    SubjectPhaseTransitionView,
    VisitDefinitionView,
    VisitDependencyView,
)

logger = logging.getLogger(__name__)

# The visit_type value that marks a visit definition as unscheduled. The
# designer visit model documents visit_type as "scheduled, unscheduled,
# screening"; a design permits unscheduled visits (R7.5) when it declares at
# least one unscheduled visit definition.
_UNSCHEDULED_VISIT_TYPE = "unscheduled"


class DesignConsumptionService:
    """Read-only, published-only consumption port for a ``Published_Design``.

    All methods accept the caller's ``AsyncSession`` and return frozen view
    objects. Draft or missing versions are rejected before any content is read.
    """

    # ------------------------------------------------------------------
    # Published-version guard (R2.5)
    # ------------------------------------------------------------------

    async def _require_published_version(
        self, session: AsyncSession, design_version_id: UUID
    ) -> StudyVersion:
        """Resolve a published ``Design_Version`` or reject the request.

        Raises:
            NotFoundError: No ``study_versions`` row with the given id exists.
            ValidationError: The version exists but is a draft — draft content is
                never exposed through the consumption contract (R2.5).
        """
        version = await session.get(StudyVersion, design_version_id)
        if version is None:
            raise NotFoundError(
                "Published design version not found",
                details={"design_version_id": str(design_version_id)},
            )
        if version.status != StudyVersionStatus.published:
            raise ValidationError(
                "Design version is not published; only published designs are "
                "readable through the consumption contract",
                details={
                    "design_version_id": str(design_version_id),
                    "status": str(version.status),
                },
            )
        return version

    # ------------------------------------------------------------------
    # View builders (R2.6 — frozen views, never ORM entities)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_form_view(form: FormDefinition) -> FormDefinitionView:
        """Flatten a form's sections into an ordered tuple of field views."""
        fields: list[FieldDefinitionView] = []
        for section in sorted(form.sections, key=lambda s: (s.display_order, str(s.id))):
            for field in sorted(section.fields, key=lambda f: (f.display_order, str(f.id))):
                fields.append(FieldDefinitionView.model_validate(field))
        return FormDefinitionView(
            id=form.id,
            design_version_id=form.study_version_id,
            name=form.name,
            form_code=form.form_code,
            display_order=form.display_order,
            is_repeating=form.is_repeating,
            fields=tuple(fields),
        )

    @staticmethod
    def _build_visit_view(visit: VisitDefinition) -> VisitDefinitionView:
        return VisitDefinitionView(
            id=visit.id,
            design_version_id=visit.study_version_id,
            name=visit.name,
            visit_number=visit.visit_number,
            visit_type=visit.visit_type,
            target_day=visit.target_day,
            window_before=visit.window_before,
            window_after=visit.window_after,
            display_order=visit.display_order,
            is_required=visit.is_required,
            repeat_min=visit.repeat_min,
            repeat_max=visit.repeat_max,
            cycle_length=visit.cycle_length,
        )

    @staticmethod
    def _build_arm_view(arm: ArmDefinition) -> ArmDefinitionView:
        visit_ids = tuple(
            v.id for v in sorted(arm.visits, key=lambda v: (v.display_order, str(v.id)))
        )
        return ArmDefinitionView(
            id=arm.id,
            design_version_id=arm.study_version_id,
            name=arm.name,
            display_order=arm.display_order,
            description=arm.description,
            visit_definition_ids=visit_ids,
        )

    @staticmethod
    def _build_form_dependency_view(
        dep: FormDefinitionDependency,
    ) -> FormDependencyView:
        return FormDependencyView(
            id=dep.id,
            form_definition_id=dep.form_definition_id,
            depends_on_form_definition_id=dep.depends_on_form_definition_id,
            dependency_type=dep.dependency_type,
            condition_expression=dep.condition_expression,
        )

    @staticmethod
    def _build_visit_dependency_view(
        dep: VisitDefinitionDependency,
    ) -> VisitDependencyView:
        return VisitDependencyView(
            id=dep.id,
            visit_definition_id=dep.visit_definition_id,
            depends_on_visit_definition_id=dep.depends_on_visit_definition_id,
            dependency_type=dep.dependency_type,
            condition_expression=dep.condition_expression,
        )

    @staticmethod
    def _build_subject_phase_transition_view(
        t: SubjectPhaseTransition,
    ) -> SubjectPhaseTransitionView:
        return SubjectPhaseTransitionView(
            id=t.id,
            design_version_id=t.design_version_id,
            from_phase_id=t.from_phase_id,
            to_phase_id=t.to_phase_id,
            label=t.label,
            condition_expression=t.condition_expression,
        )

    @staticmethod
    def _build_edit_check_view(rule: EditCheck) -> EditCheckRuleView:
        return EditCheckRuleView(
            id=rule.id,
            design_version_id=rule.study_version_id,
            name=rule.name,
            description=rule.description,
            rule_json=rule.rule_json,
            severity=rule.severity,
            is_active=rule.is_active,
        )

    @staticmethod
    def _build_codelist_view(codelist: Codelist) -> CodelistView:
        items = tuple(
            CodelistItemView.model_validate(item)
            for item in sorted(codelist.items, key=lambda i: (i.display_order, str(i.id)))
        )
        return CodelistView(
            id=codelist.id,
            design_version_id=codelist.study_version_id,
            name=codelist.name,
            code=codelist.code,
            items=items,
        )

    @staticmethod
    def _build_schedule_view(
        soa: ScheduleOfAssessment,
    ) -> ScheduleOfAssessmentView:
        entries = tuple(
            ScheduleOfAssessmentEntryView(
                id=entry.id,
                form_definition_id=entry.form_definition_id,
                procedure_name=entry.procedure_name,
                visit_definition_id=entry.visit_definition_id,
            )
            for entry in soa.entries
        )
        return ScheduleOfAssessmentView(
            design_version_id=soa.design_version_id,
            entries=entries,
        )

    # ------------------------------------------------------------------
    # Aggregate published design (R2.5, R2.6)
    # ------------------------------------------------------------------

    async def get_published_design(
        self, session: AsyncSession, design_version_id: UUID
    ) -> PublishedDesignView:
        """Return the whole ``Published_Design`` as a frozen aggregate view.

        Rejects a draft or missing ``design_version_id`` (R2.5) and assembles
        every design-time collection into immutable views (R2.6).
        """
        version = await self._require_published_version(session, design_version_id)

        forms = await self.list_forms(session, design_version_id)
        visit_definitions = await self.list_visit_definitions(session, design_version_id)
        arm_definitions = await self.list_arm_definitions(session, design_version_id)
        edit_check_rules = await self.list_edit_check_rules(session, design_version_id)
        codelists = await self.list_codelists(session, design_version_id)
        subject_phase_definitions = await self.list_subject_phase_definitions(
            session, design_version_id
        )
        schedule_of_assessment = await self.get_schedule_of_assessment(session, design_version_id)
        crf_access_definitions = await self.list_crf_access_definitions(session, design_version_id)
        raw_data_variable_settings = await self.list_raw_data_variable_settings(
            session, design_version_id
        )
        coding_settings = await self.list_coding_settings(session, design_version_id)
        form_dependencies = await self.list_form_dependencies(session, design_version_id)
        visit_dependencies = await self.list_visit_dependencies(session, design_version_id)
        subject_phase_transitions = await self.list_subject_phase_transitions(
            session, design_version_id
        )

        permits_unscheduled = any(
            visit.visit_type == _UNSCHEDULED_VISIT_TYPE for visit in visit_definitions
        )

        return PublishedDesignView(
            design_version_id=version.id,
            study_id=version.study_id,
            version_number=version.version_number,
            status=str(version.status),
            published_at=version.published_at,
            published_by=version.published_by,
            permits_unscheduled_visits=permits_unscheduled,
            forms=tuple(forms),
            visit_definitions=tuple(visit_definitions),
            arm_definitions=tuple(arm_definitions),
            edit_check_rules=tuple(edit_check_rules),
            codelists=tuple(codelists),
            subject_phase_definitions=tuple(subject_phase_definitions),
            schedule_of_assessment=schedule_of_assessment,
            crf_access_definitions=tuple(crf_access_definitions),
            raw_data_variable_settings=tuple(raw_data_variable_settings),
            coding_settings=tuple(coding_settings),
            form_dependencies=tuple(form_dependencies),
            visit_dependencies=tuple(visit_dependencies),
            subject_phase_transitions=tuple(subject_phase_transitions),
        )

    async def get_latest_published_design(
        self, session: AsyncSession, study_id: UUID
    ) -> PublishedDesignView | None:
        """Return the most recently published design for a study, or ``None``.

        Selects the latest ``published`` ``Design_Version`` for the study (by
        publication/creation time) and returns its aggregate view. When the
        study has no published version, returns ``None`` — draft versions are
        never considered (R2.5).
        """
        result = await session.execute(
            select(StudyVersion)
            .where(
                StudyVersion.study_id == study_id,
                StudyVersion.status == StudyVersionStatus.published,
            )
            .order_by(StudyVersion.published_at.desc(), StudyVersion.created_at.desc())
            .limit(1)
        )
        version = result.scalars().first()
        if version is None:
            return None
        return await self.get_published_design(session, version.id)

    # ------------------------------------------------------------------
    # Collection reads (each published-only and read-only)
    # ------------------------------------------------------------------

    async def list_forms(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[FormDefinitionView]:
        """List the form definitions of a published design as frozen views."""
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(FormDefinition)
            .where(FormDefinition.study_version_id == design_version_id)
            .order_by(FormDefinition.display_order, FormDefinition.id)
        )
        return [self._build_form_view(form) for form in result.scalars().all()]

    async def get_form_fields(
        self, session: AsyncSession, design_version_id: UUID, form_id: UUID
    ) -> list[FieldDefinitionView]:
        """List the fields of one form in a published design as frozen views.

        Raises:
            NotFoundError: The form does not belong to the published design.
        """
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(FormDefinition).where(
                FormDefinition.id == form_id,
                FormDefinition.study_version_id == design_version_id,
            )
        )
        form = result.scalars().first()
        if form is None:
            raise NotFoundError(
                "Form definition not found in the published design",
                details={
                    "design_version_id": str(design_version_id),
                    "form_id": str(form_id),
                },
            )
        return list(self._build_form_view(form).fields)

    async def list_visit_definitions(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[VisitDefinitionView]:
        """List the visit definitions of a published design as frozen views.

        Includes cycles — a cycle is a visit of ``visit_type == 'cycle'`` and the
        view carries its ``repeat_min`` / ``repeat_max`` / ``cycle_length``
        metadata. Consumers distinguish a cycle by ``visit_type == 'cycle'``.
        """
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(VisitDefinition)
            .where(VisitDefinition.study_version_id == design_version_id)
            .order_by(VisitDefinition.display_order, VisitDefinition.id)
        )
        return [self._build_visit_view(v) for v in result.scalars().all()]

    async def list_arm_definitions(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[ArmDefinitionView]:
        """List the arm definitions of a published design as frozen views.

        Each arm view exposes its member ``visit_definition_ids`` (which visits
        occur in the arm). The ``visits`` relationship is eager-loaded so the
        view can serialize the member ids without an async lazy load.
        """
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(ArmDefinition)
            .where(
                ArmDefinition.study_version_id == design_version_id,
                ArmDefinition.deleted_at.is_(None),
            )
            .options(selectinload(ArmDefinition.visits))
            .order_by(ArmDefinition.display_order, ArmDefinition.id)
        )
        return [self._build_arm_view(a) for a in result.scalars().all()]

    async def list_form_dependencies(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[FormDependencyView]:
        """List the form-to-form dependency edges of a published design as views.

        Joins the dependency table to ``form_definitions`` so only edges whose
        dependent form belongs to the published design are returned.
        """
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(FormDefinitionDependency)
            .join(
                FormDefinition,
                FormDefinition.id == FormDefinitionDependency.form_definition_id,
            )
            .where(FormDefinition.study_version_id == design_version_id)
            .order_by(FormDefinitionDependency.created_at, FormDefinitionDependency.id)
        )
        return [self._build_form_dependency_view(d) for d in result.scalars().all()]

    async def list_visit_dependencies(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[VisitDependencyView]:
        """List the visit-to-visit dependency edges of a published design as views.

        Joins the dependency table to ``visit_definitions`` so only edges whose
        dependent visit belongs to the published design are returned. The
        ``'cycle_member'`` edges surface here, giving consumers the old
        cycle-membership information through the unified model.
        """
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(VisitDefinitionDependency)
            .join(
                VisitDefinition,
                VisitDefinition.id == VisitDefinitionDependency.visit_definition_id,
            )
            .where(VisitDefinition.study_version_id == design_version_id)
            .order_by(VisitDefinitionDependency.created_at, VisitDefinitionDependency.id)
        )
        return [self._build_visit_dependency_view(d) for d in result.scalars().all()]

    async def list_edit_check_rules(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[EditCheckRuleView]:
        """List the edit-check rules of a published design as frozen views."""
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(EditCheck)
            .where(EditCheck.study_version_id == design_version_id)
            .order_by(EditCheck.created_at, EditCheck.id)
        )
        return [self._build_edit_check_view(r) for r in result.scalars().all()]

    async def list_codelists(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[CodelistView]:
        """List the codelists of a published design as frozen views."""
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(Codelist)
            .where(Codelist.study_version_id == design_version_id)
            .order_by(Codelist.name, Codelist.id)
        )
        return [self._build_codelist_view(c) for c in result.scalars().all()]

    async def list_subject_phase_definitions(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[SubjectPhaseDefinitionView]:
        """List the subject phase definitions of a published design as views."""
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(SubjectPhaseDefinition)
            .where(
                SubjectPhaseDefinition.design_version_id == design_version_id,
                SubjectPhaseDefinition.deleted_at.is_(None),
            )
            .order_by(SubjectPhaseDefinition.display_order, SubjectPhaseDefinition.id)
        )
        return [SubjectPhaseDefinitionView.model_validate(p) for p in result.scalars().all()]

    async def list_subject_phase_transitions(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[SubjectPhaseTransitionView]:
        """List the subject-phase transition edges of a published design as views.

        Excludes soft-deleted edges and (defense-in-depth, matching the
        authoring service's ``list_transitions``) any edge whose source or
        target phase has been soft-deleted.
        """
        await self._require_published_version(session, design_version_id)
        from_phase = SubjectPhaseDefinition.__table__.alias("from_phase_c")
        to_phase = SubjectPhaseDefinition.__table__.alias("to_phase_c")
        result = await session.execute(
            select(SubjectPhaseTransition)
            .join(from_phase, from_phase.c.id == SubjectPhaseTransition.from_phase_id)
            .join(to_phase, to_phase.c.id == SubjectPhaseTransition.to_phase_id)
            .where(
                SubjectPhaseTransition.design_version_id == design_version_id,
                SubjectPhaseTransition.deleted_at.is_(None),
                from_phase.c.deleted_at.is_(None),
                to_phase.c.deleted_at.is_(None),
            )
            .order_by(SubjectPhaseTransition.created_at, SubjectPhaseTransition.id)
        )
        return [self._build_subject_phase_transition_view(t) for t in result.scalars().all()]

    async def get_schedule_of_assessment(
        self, session: AsyncSession, design_version_id: UUID
    ) -> ScheduleOfAssessmentView:
        """Return the schedule of assessment of a published design as a view.

        When the design declares no schedule of assessment, returns an empty
        view (same ``design_version_id``, no entries) so consumers get a stable
        shape rather than ``None``.
        """
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(ScheduleOfAssessment).where(
                ScheduleOfAssessment.design_version_id == design_version_id,
                ScheduleOfAssessment.deleted_at.is_(None),
            )
        )
        soa = result.scalars().first()
        if soa is None:
            return ScheduleOfAssessmentView(design_version_id=design_version_id, entries=())
        return self._build_schedule_view(soa)

    async def list_crf_access_definitions(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[CrfAccessDefinitionView]:
        """List the CRF access definitions of a published design as views."""
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(CrfAccessDefinition)
            .where(
                CrfAccessDefinition.design_version_id == design_version_id,
                CrfAccessDefinition.deleted_at.is_(None),
            )
            .order_by(CrfAccessDefinition.role, CrfAccessDefinition.id)
        )
        return [CrfAccessDefinitionView.model_validate(c) for c in result.scalars().all()]

    async def list_raw_data_variable_settings(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[RawDataVariableSettingView]:
        """List the raw-data variable settings of a published design as views."""
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(RawDataVariableSetting)
            .where(
                RawDataVariableSetting.design_version_id == design_version_id,
                RawDataVariableSetting.deleted_at.is_(None),
            )
            .order_by(RawDataVariableSetting.name, RawDataVariableSetting.id)
        )
        return [RawDataVariableSettingView.model_validate(r) for r in result.scalars().all()]

    async def list_coding_settings(
        self, session: AsyncSession, design_version_id: UUID
    ) -> list[CodingSettingView]:
        """List the coding settings of a published design as frozen views."""
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(CodingSetting)
            .where(
                CodingSetting.design_version_id == design_version_id,
                CodingSetting.deleted_at.is_(None),
            )
            .order_by(CodingSetting.dictionary_reference, CodingSetting.id)
        )
        return [CodingSettingView.model_validate(c) for c in result.scalars().all()]

    # ------------------------------------------------------------------
    # Design capability flag (R7.5)
    # ------------------------------------------------------------------

    async def permits_unscheduled_visits(
        self, session: AsyncSession, design_version_id: UUID
    ) -> bool:
        """Report whether the published design permits unscheduled visits (R7.5).

        A design permits unscheduled visits when it declares at least one visit
        definition whose ``visit_type`` is ``"unscheduled"``. The decision is
        made solely from published content; a draft or missing version is
        rejected by the published-version guard (R2.5).
        """
        await self._require_published_version(session, design_version_id)
        result = await session.execute(
            select(VisitDefinition.id)
            .where(
                VisitDefinition.study_version_id == design_version_id,
                VisitDefinition.visit_type == _UNSCHEDULED_VISIT_TYPE,
            )
            .limit(1)
        )
        return result.scalars().first() is not None


# Module-level singleton for convenience (mirrors study_version_service).
design_consumption_service = DesignConsumptionService()
