"""Server-side EDC status aggregation, worklists, and clinical listings."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import PaginationParams
from app.core.edit_check_dsl import evaluate_rule
from app.models.designer.crf_access_definition import CrfAccessDefinition
from app.models.designer.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.edc.form_data import FieldValue, FormInstance
from app.models.edc.form_record import FormRecord
from app.models.edc.lock import FreezeLock
from app.models.edc.operations import SDRResult, SDRSelection
from app.models.edc.query import Query, QueryStatus, QueryTargetType
from app.models.edc.review import ReviewStatus
from app.models.edc.sdv import SDVStatus
from app.models.edc.signature import Signature
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitInstance
from app.schemas.edc.operations import (
    EDCCapabilities,
    FormOperationalStatus,
    FormWorklistItem,
    ListingCatalogItem,
    ListingRow,
    QualityWorklistItem,
)
from app.schemas.shared.base import PaginatedResponse
from app.schemas.shared.export import ExportDatasetOption
from app.services.edc.data_capture_service import data_capture_service

_ACTIVE_QUERY_STATUSES = (
    QueryStatus.open.value,
    QueryStatus.answered.value,
    QueryStatus.reopened.value,
)


class EDCOperationalService:
    @staticmethod
    def capabilities() -> EDCCapabilities:
        return EDCCapabilities()

    async def subject_summaries(
        self, session: AsyncSession, subjects: list[Subject]
    ) -> dict[UUID, dict[str, Any]]:
        if not subjects:
            return {}
        subject_ids = [subject.id for subject in subjects]
        forms = list(
            (
                await session.execute(
                    select(FormInstance)
                    .where(FormInstance.subject_id.in_(subject_ids))
                    .options(
                        selectinload(FormInstance.subject).selectinload(Subject.site),
                        selectinload(FormInstance.visit_instance),
                        selectinload(FormInstance.form_definition),
                    )
                )
            )
            .scalars()
            .unique()
            .all()
        )
        statuses = await self.form_statuses(session, forms)
        forms_by_subject: dict[UUID, list[FormInstance]] = defaultdict(list)
        for form in forms:
            forms_by_subject[form.subject_id].append(form)
        visits = list(
            (
                await session.execute(
                    select(VisitInstance)
                    .where(VisitInstance.subject_id.in_(subject_ids))
                    .order_by(
                        VisitInstance.visit_date.desc().nullslast(), VisitInstance.created_at.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
        latest_visit: dict[UUID, VisitInstance] = {}
        for visit in visits:
            latest_visit.setdefault(visit.subject_id, visit)
        query_counts = dict(
            (
                await session.execute(
                    select(Query.subject_id, func.count(Query.id))
                    .where(
                        Query.subject_id.in_(subject_ids),
                        Query.status.in_(_ACTIVE_QUERY_STATUSES),
                    )
                    .group_by(Query.subject_id)
                )
            ).all()
        )
        summaries: dict[UUID, dict[str, Any]] = {}
        for subject in subjects:
            subject_forms = forms_by_subject.get(subject.id, [])
            form_statuses = [statuses[form.id] for form in subject_forms]
            submitted = sum(status.data_entry == "Submitted" for status in form_statuses)
            total = len(subject_forms)
            visit = latest_visit.get(subject.id)
            summaries[subject.id] = {
                "enrollment_at": subject.created_at,
                "latest_visit_at": (
                    datetime.combine(visit.visit_date, datetime.min.time(), tzinfo=UTC)
                    if visit and visit.visit_date
                    else (visit.created_at if visit else None)
                ),
                "latest_visit_name": visit.name if visit else None,
                "forms_total": total,
                "forms_submitted": submitted,
                "completion_percent": round((submitted / total) * 100, 1) if total else 0,
                "active_query_count": int(query_counts.get(subject.id, 0)),
                "review_summary": self._rollup([status.review for status in form_statuses]),
                "sdv_summary": self._rollup([status.sdv for status in form_statuses]),
                "sdr_summary": self._rollup([status.sdr for status in form_statuses]),
            }
        return summaries

    async def form_statuses(
        self, session: AsyncSession, forms: list[FormInstance]
    ) -> dict[UUID, FormOperationalStatus]:
        if not forms:
            return {}
        form_ids = [form.id for form in forms]
        review_rows = (
            (
                await session.execute(
                    select(ReviewStatus).where(ReviewStatus.form_instance_id.in_(form_ids))
                )
            )
            .scalars()
            .all()
        )
        reviews = {row.form_instance_id: row for row in review_rows}

        field_rows = (
            (
                await session.execute(
                    select(FieldValue).where(FieldValue.form_instance_id.in_(form_ids))
                )
            )
            .scalars()
            .all()
        )
        field_to_form = {field.id: field.form_instance_id for field in field_rows}
        field_ids = list(field_to_form)

        sdv_rows = (
            (
                await session.execute(
                    select(SDVStatus).where(
                        or_(
                            (SDVStatus.scope_type == "form") & (SDVStatus.scope_id.in_(form_ids)),
                            (SDVStatus.scope_type == "field")
                            & (SDVStatus.scope_id.in_(field_ids or [UUID(int=0)])),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        form_sdv = {row.scope_id: row for row in sdv_rows if row.scope_type == "form"}
        field_sdv = {row.scope_id: row for row in sdv_rows if row.scope_type == "field"}

        sdr_rows = (
            await session.execute(
                select(SDRSelection, SDRResult)
                .outerjoin(SDRResult, SDRResult.selection_id == SDRSelection.id)
                .where(SDRSelection.form_instance_id.in_(form_ids))
            )
        ).all()
        sdr_by_form = {selection.form_instance_id: result for selection, result in sdr_rows}
        selected_forms = {selection.form_instance_id for selection, _ in sdr_rows}

        records = (
            await session.execute(
                select(FormRecord.id, FormRecord.form_instance_id).where(
                    FormRecord.form_instance_id.in_(form_ids), FormRecord.deleted_at.is_(None)
                )
            )
        ).all()
        record_to_form = {record_id: form_id for record_id, form_id in records}

        target_ids = set(form_ids) | set(field_ids) | set(record_to_form)
        target_ids.update(form.subject_id for form in forms)
        target_ids.update(form.visit_instance_id for form in forms if form.visit_instance_id)
        query_rows = (
            await session.execute(
                select(Query.target_type, Query.target_id).where(
                    Query.status.in_(_ACTIVE_QUERY_STATUSES), Query.target_id.in_(target_ids)
                )
            )
        ).all()
        query_counts: dict[UUID, int] = defaultdict(int)
        for target_type, target_id in query_rows:
            if target_type == QueryTargetType.form_instance.value:
                query_counts[target_id] += 1
            elif target_type == QueryTargetType.field.value and target_id in field_to_form:
                query_counts[field_to_form[target_id]] += 1
            elif target_type == QueryTargetType.form_record.value and target_id in record_to_form:
                query_counts[record_to_form[target_id]] += 1
            elif target_type == QueryTargetType.subject.value:
                for form in forms:
                    if form.subject_id == target_id:
                        query_counts[form.id] += 1
            elif target_type == QueryTargetType.visit_instance.value:
                for form in forms:
                    if form.visit_instance_id == target_id:
                        query_counts[form.id] += 1

        signature_rows = (
            (
                await session.execute(
                    select(Signature).where(
                        Signature.object_type == "form", Signature.object_id.in_(form_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        signatures: dict[UUID, list[Signature]] = defaultdict(list)
        for signature in signature_rows:
            signatures[signature.object_id].append(signature)

        scope_pairs: set[tuple[str, UUID]] = set()
        for form in forms:
            subject = form.subject
            scope_pairs.update(
                {
                    ("study", subject.study_id),
                    ("site", subject.site_id),
                    ("subject", subject.id),
                    ("form", form.id),
                }
            )
            if form.visit_instance_id:
                scope_pairs.add(("visit", form.visit_instance_id))
        controls = (
            (await session.execute(select(FreezeLock).where(FreezeLock.is_active.is_(True))))
            .scalars()
            .all()
        )
        active_controls = {
            (control.object_type, control.object_id, control.lock_type)
            for control in controls
            if (control.object_type, control.object_id) in scope_pairs
        }

        fields_by_form: dict[UUID, list[FieldValue]] = defaultdict(list)
        for field in field_rows:
            fields_by_form[field.form_instance_id].append(field)

        result: dict[UUID, FormOperationalStatus] = {}
        for form in forms:
            review = reviews.get(form.id)
            if not review or not review.is_reviewed:
                review_value = "Not Reviewed"
            elif review.reviewed_revision != form.data_revision:
                review_value = "Stale"
            else:
                review_value = "Reviewed"

            direct_sdv = form_sdv.get(form.id)
            if direct_sdv and direct_sdv.is_verified:
                sdv_value = (
                    "Verified" if direct_sdv.verified_revision == form.data_revision else "Stale"
                )
            else:
                form_fields = fields_by_form.get(form.id, [])
                if not form_fields:
                    sdv_value = "Not Required"
                else:
                    current_verified = 0
                    stale = False
                    for field in form_fields:
                        field_status = field_sdv.get(field.id)
                        if field_status and field_status.is_verified:
                            if field_status.verified_revision == field.data_revision:
                                current_verified += 1
                            else:
                                stale = True
                    if current_verified == len(form_fields):
                        sdv_value = "Verified"
                    elif stale:
                        sdv_value = "Stale"
                    elif current_verified:
                        sdv_value = "Partial"
                    else:
                        sdv_value = "Not Verified"

            sdr_result = sdr_by_form.get(form.id)
            if form.id not in selected_forms:
                sdr_value = "Not Selected"
            elif sdr_result is None:
                sdr_value = "Pending"
            elif (
                sdr_result.reviewed_revision is not None
                and sdr_result.reviewed_revision != form.data_revision
            ):
                sdr_value = "Stale"
            else:
                sdr_value = sdr_result.status

            refs = {
                ("study", form.subject.study_id),
                ("site", form.subject.site_id),
                ("subject", form.subject_id),
                ("form", form.id),
            }
            if form.visit_instance_id:
                refs.add(("visit", form.visit_instance_id))
            frozen = any((kind, object_id, "freeze") in active_controls for kind, object_id in refs)
            locked = any((kind, object_id, "lock") in active_controls for kind, object_id in refs)
            form_signatures = signatures.get(form.id, [])
            if any(signature.status == "valid" for signature in form_signatures):
                signature_value = "Valid"
            elif form_signatures:
                signature_value = "Stale"
            else:
                signature_value = "Missing"

            result[form.id] = FormOperationalStatus(
                data_entry=form.data_entry_status,
                review=review_value,
                sdv=sdv_value,
                sdr=sdr_value,
                freeze="Active" if frozen else "Inactive",
                lock="Active" if locked else "Inactive",
                signature=signature_value,
                active_query_count=query_counts.get(form.id, 0),
                data_revision=form.data_revision,
            )
        return result

    async def form_worklist(
        self,
        session: AsyncSession,
        study_id: UUID,
        pagination: PaginationParams,
        *,
        authorized_site_ids: set[UUID] | None = None,
        site_id: UUID | None = None,
        subject_id: UUID | None = None,
        state: str | None = None,
    ) -> PaginatedResponse[FormWorklistItem]:
        conditions = [Subject.study_id == study_id, Subject.deleted_at.is_(None)]
        if authorized_site_ids is not None:
            conditions.append(Subject.site_id.in_(authorized_site_ids))
        if site_id:
            conditions.append(Subject.site_id == site_id)
        if subject_id:
            conditions.append(Subject.id == subject_id)
        if state == "incomplete":
            conditions.append(FormInstance.data_entry_status != "Submitted")
        elif state == "submitted":
            conditions.append(FormInstance.data_entry_status == "Submitted")
        elif state == "queried":
            conditions.append(
                exists(
                    select(Query.id).where(
                        Query.status.in_(_ACTIVE_QUERY_STATUSES),
                        or_(
                            (Query.target_type == QueryTargetType.form_instance.value)
                            & (Query.target_id == FormInstance.id),
                            (Query.target_type == QueryTargetType.subject.value)
                            & (Query.target_id == FormInstance.subject_id),
                            (Query.target_type == QueryTargetType.visit_instance.value)
                            & (Query.target_id == FormInstance.visit_instance_id),
                            (Query.target_type == QueryTargetType.field.value)
                            & (
                                Query.target_id.in_(
                                    select(FieldValue.id).where(
                                        FieldValue.form_instance_id == FormInstance.id
                                    )
                                )
                            ),
                            (Query.target_type == QueryTargetType.form_record.value)
                            & (
                                Query.target_id.in_(
                                    select(FormRecord.id).where(
                                        FormRecord.form_instance_id == FormInstance.id,
                                        FormRecord.deleted_at.is_(None),
                                    )
                                )
                            ),
                        ),
                    )
                )
            )
        elif state == "changed_since_review":
            conditions.append(
                exists(
                    select(ReviewStatus.id).where(
                        ReviewStatus.form_instance_id == FormInstance.id,
                        ReviewStatus.is_reviewed.is_(True),
                        ReviewStatus.reviewed_revision != FormInstance.data_revision,
                    )
                )
            )

        base = (
            select(FormInstance)
            .join(Subject, Subject.id == FormInstance.subject_id)
            .where(*conditions)
            .options(
                selectinload(FormInstance.subject).selectinload(Subject.site),
                selectinload(FormInstance.visit_instance),
                selectinload(FormInstance.form_definition),
            )
        )
        total = int(
            (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        )
        forms = list(
            (
                await session.execute(
                    base.order_by(
                        FormInstance.updated_at.desc().nullslast(), FormInstance.created_at.desc()
                    )
                    .offset((pagination.page - 1) * pagination.page_size)
                    .limit(pagination.page_size)
                )
            )
            .scalars()
            .unique()
            .all()
        )
        statuses = await self.form_statuses(session, forms)
        items = [self._worklist_item(form, statuses[form.id]) for form in forms]
        return PaginatedResponse(
            items=items, page=pagination.page, page_size=pagination.page_size, total=total
        )

    async def quality_worklist(
        self,
        session: AsyncSession,
        study_id: UUID,
        pagination: PaginationParams,
        *,
        workflow: str,
        authorized_site_ids: set[UUID] | None = None,
        site_id: UUID | None = None,
        subject_id: UUID | None = None,
        status: str | None = None,
    ) -> PaginatedResponse[QualityWorklistItem]:
        page = await self.form_worklist(
            session,
            study_id,
            pagination,
            authorized_site_ids=authorized_site_ids,
            site_id=site_id,
            subject_id=subject_id,
        )
        attr = {"review": "review", "sdv": "sdv", "sdr": "sdr"}[workflow]
        selection_ids: dict[UUID, UUID] = {}
        if workflow == "sdr" and page.items:
            selection_ids = dict(
                (
                    await session.execute(
                        select(
                            SDRSelection.form_instance_id,
                            SDRSelection.id,
                        ).where(
                            SDRSelection.form_instance_id.in_(
                                [item.form_instance_id for item in page.items]
                            )
                        )
                    )
                ).all()
            )
        items = [
            QualityWorklistItem(
                **item.model_dump(),
                workflow=workflow,
                workflow_status=getattr(item.status, attr),
                sdr_selection_id=selection_ids.get(item.form_instance_id),
            )
            for item in page.items
            if workflow != "sdr" or item.status.sdr != "Not Selected"
        ]
        if status:
            items = [item for item in items if item.workflow_status.lower() == status.lower()]
        return PaginatedResponse(
            items=items,
            page=page.page,
            page_size=page.page_size,
            total=len(items) if status else page.total,
        )

    async def listing_catalog(
        self,
        session: AsyncSession,
        study_id: UUID,
        *,
        role_names: set[str],
    ) -> list[ListingCatalogItem]:
        definitions = list(
            (
                await session.execute(
                    select(FormDefinition)
                    .join(StudyVersion, StudyVersion.id == FormDefinition.study_version_id)
                    .where(
                        StudyVersion.study_id == study_id,
                        StudyVersion.status == StudyVersionStatus.published.value,
                    )
                    .options(selectinload(FormDefinition.sections).selectinload(FormSection.fields))
                    .order_by(FormDefinition.display_order)
                )
            )
            .scalars()
            .unique()
            .all()
        )
        catalog: list[ListingCatalogItem] = []
        for definition in definitions:
            fields = [
                field
                for section in definition.sections
                if section.output_to_dataset
                for field in section.fields
            ]
            readable_fields = await self.readable_fields(session, definition, fields, role_names)
            if not readable_fields:
                continue
            catalog.append(
                ListingCatalogItem(
                    dataset=str(definition.id),
                    label=definition.name,
                    design_version_id=definition.study_version_id,
                    columns=[
                        {
                            "key": field.variable_name,
                            "label": field.label,
                            "data_type": field.data_type,
                        }
                        for field in readable_fields
                    ],
                )
            )
        return catalog

    async def export_dataset_catalog(
        self,
        session: AsyncSession,
        study_id: UUID,
        *,
        role_names: set[str],
    ) -> list[ExportDatasetOption]:
        """Return selectable raw datasets merged across published design versions."""
        definitions = list(
            (
                await session.execute(
                    select(FormDefinition)
                    .join(StudyVersion, StudyVersion.id == FormDefinition.study_version_id)
                    .where(
                        StudyVersion.study_id == study_id,
                        StudyVersion.status == StudyVersionStatus.published.value,
                    )
                    .options(selectinload(FormDefinition.sections).selectinload(FormSection.fields))
                    .order_by(FormDefinition.display_order, FormDefinition.id)
                )
            )
            .scalars()
            .unique()
            .all()
        )
        grouped: dict[str, ExportDatasetOption] = {}
        for definition in definitions:
            fields = [
                field
                for section in definition.sections
                if section.output_to_dataset and not section.is_label_only
                for field in section.fields
                if field.control_type != "label"
            ]
            if not await self.readable_fields(session, definition, fields, role_names):
                continue
            name = definition.domain or definition.form_code
            key = name.casefold()
            option = grouped.get(key)
            if option is None:
                option = ExportDatasetOption(name=name, label=name)
                grouped[key] = option
            if definition.study_version_id not in option.design_version_ids:
                option.design_version_ids.append(definition.study_version_id)
            option.form_definition_ids.append(definition.id)
        return list(grouped.values())

    async def listing_rows(
        self,
        session: AsyncSession,
        study_id: UUID,
        form_definition_id: UUID,
        pagination: PaginationParams,
        *,
        role_names: set[str],
        authorized_site_ids: set[UUID] | None = None,
        site_id: UUID | None = None,
        subject_id: UUID | None = None,
    ) -> PaginatedResponse[ListingRow]:
        definition = (
            (
                await session.execute(
                    select(FormDefinition)
                    .join(StudyVersion, StudyVersion.id == FormDefinition.study_version_id)
                    .where(
                        FormDefinition.id == form_definition_id,
                        StudyVersion.study_id == study_id,
                        StudyVersion.status == StudyVersionStatus.published.value,
                    )
                )
            )
            .scalars()
            .first()
        )
        if definition is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(message="Listing dataset not found", details={})
        fields = list(
            (
                await session.execute(
                    select(FieldDefinition)
                    .join(FormSection, FormSection.id == FieldDefinition.form_section_id)
                    .where(
                        FormSection.form_definition_id == form_definition_id,
                        FormSection.output_to_dataset.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        fields = await self.readable_fields(session, definition, fields, role_names)
        if not fields:
            from app.core.exceptions import AuthorizationError

            raise AuthorizationError(
                message="Access denied",
                details={},
            )
        field_names = {field.id: field.variable_name for field in fields}
        field_definitions = {field.id: field for field in fields}
        conditions = [
            Subject.study_id == study_id,
            FormInstance.form_definition_id == form_definition_id,
        ]
        if authorized_site_ids is not None:
            conditions.append(Subject.site_id.in_(authorized_site_ids))
        if site_id:
            conditions.append(Subject.site_id == site_id)
        if subject_id:
            conditions.append(Subject.id == subject_id)
        base = (
            select(FormInstance)
            .join(Subject, Subject.id == FormInstance.subject_id)
            .where(*conditions)
            .options(selectinload(FormInstance.subject), selectinload(FormInstance.field_values))
        )
        total = int(
            (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        )
        forms = list(
            (
                await session.execute(
                    base.order_by(Subject.subject_number)
                    .offset((pagination.page - 1) * pagination.page_size)
                    .limit(pagination.page_size)
                )
            )
            .scalars()
            .unique()
            .all()
        )
        rows = []
        for form in forms:
            raw_values = {
                field_names[field.field_definition_id]: data_capture_service._deserialize_value(
                    field.value
                )
                for field in form.field_values
                if field.field_definition_id in field_names
            }
            values: dict[str, Any] = {
                "subject_number": form.subject.subject_number,
                "subject_id": str(form.subject_id),
                "site_id": str(form.subject.site_id),
                "data_entry_status": form.data_entry_status,
                "design_version_id": str(form.design_version_id),
            }
            for field in form.field_values:
                name = field_names.get(field.field_definition_id)
                definition = field_definitions.get(field.field_definition_id)
                if name and (
                    definition is None
                    or not definition.visibility_rule
                    or evaluate_rule(definition.visibility_rule, raw_values)
                ):
                    values[name] = raw_values[name]
            rows.append(
                ListingRow(
                    source_form_url=f"/subjects/{form.subject_id}/forms/{form.id}",
                    values=values,
                )
            )
        return PaginatedResponse(
            items=rows, page=pagination.page, page_size=pagination.page_size, total=total
        )

    @staticmethod
    async def readable_fields(
        session: AsyncSession,
        definition: FormDefinition,
        fields: list[FieldDefinition],
        role_names: set[str],
    ) -> list[FieldDefinition]:
        """Apply published per-role CRF and field read/blinding grants."""
        if "System Administrator" in role_names:
            return fields
        access_rows = [
            row
            for row in (
                (
                    await session.execute(
                        select(CrfAccessDefinition).where(
                            CrfAccessDefinition.design_version_id == definition.study_version_id,
                            CrfAccessDefinition.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if hasattr(row, "role")
        ]
        if not access_rows:
            return fields
        role_rows = [row for row in access_rows if row.role in role_names]
        readable: list[FieldDefinition] = []
        for field in fields:
            scoped = [
                (2, row)
                if row.field_definition_id == field.id
                else (1, row)
                if row.field_definition_id is None and row.form_definition_id == definition.id
                else (0, row)
                for row in role_rows
                if row.field_definition_id == field.id
                or (
                    row.field_definition_id is None
                    and row.form_definition_id in {None, definition.id}
                )
            ]
            if not scoped:
                continue
            specificity = max(level for level, _ in scoped)
            applicable = [row for level, row in scoped if level == specificity]
            if any(
                row.can_read
                and (
                    not row.blinded
                    or (row.unblind_role is not None and row.unblind_role in role_names)
                )
                for row in applicable
            ):
                readable.append(field)
        return readable

    @staticmethod
    def _worklist_item(form: FormInstance, status: FormOperationalStatus) -> FormWorklistItem:
        return FormWorklistItem(
            form_instance_id=form.id,
            study_id=form.subject.study_id,
            site_id=form.subject.site_id,
            site_name=getattr(form.subject.site, "name", None),
            subject_id=form.subject_id,
            subject_number=form.subject.subject_number,
            visit_id=form.visit_instance_id,
            visit_name=getattr(form.visit_instance, "name", None),
            form_definition_id=form.form_definition_id,
            form_name=form.form_definition.name,
            design_version_id=form.design_version_id,
            status=status,
            updated_at=form.updated_at,
        )

    @staticmethod
    def _rollup(values: list[str]) -> str:
        if not values:
            return "Not Applicable"
        distinct = set(values)
        if len(distinct) == 1:
            return values[0]
        if "Stale" in distinct:
            return "Stale"
        return "Partial"


edc_operational_service = EDCOperationalService()

__all__ = ["EDCOperationalService", "edc_operational_service"]
