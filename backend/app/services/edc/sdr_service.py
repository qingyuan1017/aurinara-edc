"""Versioned SDR selection and operational review workflow."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.models.designer.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.edc.form_data import FormInstance
from app.models.edc.operations import SDRResult, SDRSelection, SDRSetting
from app.models.edc.study import StudyVersion, StudyVersionStatus
from app.models.edc.subject import Subject
from app.schemas.edc.operations import SDRReviewUpdate, SDRSettingUpsert
from app.services.edc.lock_service import lock_service


class SDRService:
    async def upsert_setting(
        self,
        session: AsyncSession,
        study_version_id: UUID,
        data: SDRSettingUpsert,
        actor_id: UUID,
    ) -> SDRSetting:
        version = await session.get(StudyVersion, study_version_id)
        if version is None:
            raise NotFoundError(message="Design version not found", details={})
        if version.status != StudyVersionStatus.draft:
            raise BusinessRuleError(
                message="SDR settings may only be changed on a draft design",
                details={"study_version_id": str(study_version_id)},
            )
        target_ids = set(data.targeted_field_ids)
        if target_ids:
            rows = await session.execute(
                select(FieldDefinition.id)
                .join(FormSection, FormSection.id == FieldDefinition.form_section_id)
                .join(FormDefinition, FormDefinition.id == FormSection.form_definition_id)
                .where(
                    FormDefinition.study_version_id == study_version_id,
                    FieldDefinition.id.in_(target_ids),
                )
            )
            if set(rows.scalars().all()) != target_ids:
                raise ValidationError(
                    message="Every targeted SDR field must belong to the design version",
                    details={},
                )
        setting = (
            (
                await session.execute(
                    select(SDRSetting).where(SDRSetting.study_version_id == study_version_id)
                )
            )
            .scalars()
            .first()
        )
        old_value = None
        if setting is None:
            setting = SDRSetting(id=uuid4(), study_version_id=study_version_id, created_by=actor_id)
            session.add(setting)
        else:
            old_value = {
                "strategy": setting.strategy,
                "percentage": setting.percentage,
                "targeted_field_ids": setting.targeted_field_ids,
            }
            setting.updated_by = actor_id
            setting.updated_at = datetime.now(UTC)
        setting.strategy = data.strategy
        setting.percentage = data.percentage if data.strategy == "percentage" else None
        setting.targeted_field_ids = [str(value) for value in data.targeted_field_ids]
        setting.is_required_for_lock = data.is_required_for_lock
        await session.flush()
        await audit_service.record(
            session,
            entity_type="sdr_setting",
            entity_id=setting.id,
            action="configure",
            study_id=version.study_id,
            actor_id=actor_id,
            old_value=str(old_value) if old_value else None,
            new_value=str(data.model_dump(mode="json")),
        )
        return setting

    async def get_setting(self, session: AsyncSession, study_version_id: UUID) -> SDRSetting:
        setting = (
            (
                await session.execute(
                    select(SDRSetting).where(SDRSetting.study_version_id == study_version_id)
                )
            )
            .scalars()
            .first()
        )
        if setting is None:
            raise NotFoundError(message="SDR settings not found", details={})
        return setting

    async def materialize(self, session: AsyncSession, study_id: UUID) -> int:
        """Persist stable selections. Existing selections are never recalculated."""
        settings = list(
            (
                await session.execute(
                    select(SDRSetting)
                    .join(StudyVersion, StudyVersion.id == SDRSetting.study_version_id)
                    .where(
                        StudyVersion.study_id == study_id,
                        StudyVersion.status == StudyVersionStatus.published.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        created = 0
        for setting in settings:
            forms = list(
                (
                    await session.execute(
                        select(FormInstance)
                        .join(Subject, Subject.id == FormInstance.subject_id)
                        .where(
                            Subject.study_id == study_id,
                            FormInstance.design_version_id == setting.study_version_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            targeted_form_ids: set[UUID] = set()
            if setting.strategy == "targeted":
                field_ids = [UUID(value) for value in setting.targeted_field_ids or []]
                targeted_form_ids = set(
                    (
                        await session.execute(
                            select(FormSection.form_definition_id)
                            .join(
                                FieldDefinition,
                                FieldDefinition.form_section_id == FormSection.id,
                            )
                            .where(FieldDefinition.id.in_(field_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
            for form in forms:
                selected = setting.strategy == "all"
                reason = "All forms"
                if setting.strategy == "percentage":
                    bucket = int(hashlib.sha256(str(form.id).encode()).hexdigest()[:8], 16) % 100
                    selected = bucket < int(setting.percentage or 0)
                    reason = f"Deterministic {setting.percentage}% sample"
                elif setting.strategy == "targeted":
                    selected = form.form_definition_id in targeted_form_ids
                    reason = "Targeted field selection"
                if not selected:
                    continue
                exists = await session.scalar(
                    select(SDRSelection.id).where(
                        SDRSelection.form_instance_id == form.id,
                        SDRSelection.design_version_id == form.design_version_id,
                    )
                )
                if exists:
                    continue
                selection = SDRSelection(
                    id=uuid4(),
                    study_id=study_id,
                    site_id=form.subject.site_id,
                    subject_id=form.subject_id,
                    form_instance_id=form.id,
                    design_version_id=form.design_version_id,
                    selection_reason=reason,
                )
                session.add(selection)
                await session.flush()
                session.add(SDRResult(id=uuid4(), selection_id=selection.id, status="Pending"))
                created += 1
        await session.flush()
        return created

    async def review(
        self,
        session: AsyncSession,
        selection_id: UUID,
        data: SDRReviewUpdate,
        actor_id: UUID,
    ) -> SDRResult:
        selection = await session.get(SDRSelection, selection_id)
        if selection is None:
            raise NotFoundError(message="SDR selection not found", details={})
        result = (
            (await session.execute(select(SDRResult).where(SDRResult.selection_id == selection_id)))
            .scalars()
            .first()
        )
        if result is None:
            result = SDRResult(id=uuid4(), selection_id=selection_id)
            session.add(result)
        form = await session.get(FormInstance, selection.form_instance_id)
        if form is None:
            raise NotFoundError(message="Selected form not found", details={})
        if await lock_service.is_hard_locked(session, form):
            raise BusinessRuleError(
                message="SDR cannot be changed while the form is locked",
                details={},
            )
        old_status = result.status
        result.status = data.status
        result.outcome = data.outcome
        result.comment = data.comment
        result.reviewed_by = actor_id
        result.reviewed_at = datetime.now(UTC)
        result.reviewed_revision = int(form.data_revision if form else 0)
        result.updated_at = datetime.now(UTC)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="sdr_result",
            entity_id=result.id,
            action="review",
            study_id=selection.study_id,
            site_id=selection.site_id,
            subject_id=selection.subject_id,
            actor_id=actor_id,
            old_value=old_status,
            new_value=result.status,
            reason=data.comment,
        )
        return result


sdr_service = SDRService()

__all__ = ["SDRService", "sdr_service"]
