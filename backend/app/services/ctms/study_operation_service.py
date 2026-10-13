"""Mutation service for the expanded CTMS Study Operations resources."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ctms import utc_now
from app.core.exceptions import NotFoundError, ValidationError
from app.core.request_context import get_correlation_id
from app.models.ctms.study_operation import StudyOperationRecord, StudyOperationResource
from app.models.edc.site import Site
from app.models.edc.subject import Subject
from app.services.ctms.ctms_atomicity_service import ctms_atomicity_service


def _values(payload: Mapping[str, Any] | Any, *, exclude_unset: bool = False) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    return dict(payload.model_dump(exclude_unset=exclude_unset))


def _correlation_uuid(value: UUID | str | None) -> UUID:
    if value is None:
        return uuid4()
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return uuid5(NAMESPACE_URL, str(value))


class StudyOperationService:
    @staticmethod
    async def _validate_references(
        session: AsyncSession,
        study_id: UUID,
        *,
        site_id: UUID | None,
        subject_id: UUID | None,
    ) -> None:
        if site_id is not None:
            site = await session.scalar(
                select(Site.id).where(Site.id == site_id, Site.study_id == study_id)
            )
            if site is None:
                raise ValidationError(
                    "site_id is not part of the requested study",
                    {"field": "site_id"},
                )
        if subject_id is not None:
            subject = await session.scalar(
                select(Subject.id).where(
                    Subject.id == subject_id,
                    Subject.study_id == study_id,
                )
            )
            if subject is None:
                raise ValidationError(
                    "subject_id is not part of the requested study",
                    {"field": "subject_id"},
                )

    async def create(
        self,
        session: AsyncSession,
        study_id: UUID,
        resource: StudyOperationResource,
        payload: Mapping[str, Any] | Any,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> StudyOperationRecord:
        values = _values(payload)
        await self._validate_references(
            session,
            study_id,
            site_id=values.get("site_id"),
            subject_id=values.get("subject_id"),
        )
        if resource == StudyOperationResource.PAYMENT and values.get("record_subtype") not in {
            "Trigger",
            "Request",
        }:
            raise ValidationError(
                "Payment record_subtype must be Trigger or Request",
                {"field": "record_subtype"},
            )
        correlation = _correlation_uuid(correlation_id or get_correlation_id())
        record = StudyOperationRecord(
            study_id=study_id,
            resource_type=resource.value,
            site_id=values.get("site_id"),
            subject_id=values.get("subject_id"),
            reference_id=values.get("reference_id"),
            title=values["title"],
            record_subtype=values.get("record_subtype"),
            status=values.get("status", "Draft"),
            owner_id=values.get("owner_id"),
            start_at=values.get("start_at"),
            end_at=values.get("end_at"),
            amount=values.get("amount"),
            currency=values.get("currency"),
            details_json=values.get("details", {}),
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation,
        )
        session.add(record)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type=f"ctms_{resource.value}",
            entity_id=record.id,
            study_id=study_id,
            site_id=record.site_id,
            actor_id=actor_id,
            correlation_id=correlation,
            action="create",
            changed_fields=[
                "title",
                "record_subtype",
                "status",
                "owner_id",
                "start_at",
                "end_at",
                "amount",
                "currency",
                "details",
            ],
            status=record.status,
            payload={"resource_type": resource.value, "record_id": record.id},
        )
        return record

    async def resolve(
        self,
        session: AsyncSession,
        study_id: UUID,
        resource: StudyOperationResource,
        record_id: UUID,
    ) -> StudyOperationRecord:
        record = await session.scalar(
            select(StudyOperationRecord).where(
                StudyOperationRecord.id == record_id,
                StudyOperationRecord.study_id == study_id,
                StudyOperationRecord.resource_type == resource.value,
                StudyOperationRecord.deleted_at.is_(None),
            )
        )
        if record is None:
            raise NotFoundError(
                "CTMS study-operation record was not found",
                {"record_id": str(record_id)},
            )
        return record

    async def update(
        self,
        session: AsyncSession,
        study_id: UUID,
        resource: StudyOperationResource,
        record_id: UUID,
        payload: Mapping[str, Any] | Any,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> StudyOperationRecord:
        record = await self.resolve(session, study_id, resource, record_id)
        values = _values(payload, exclude_unset=True)
        reason = values.pop("reason")
        next_site_id = values.get("site_id", record.site_id)
        next_subject_id = values.get("subject_id", record.subject_id)
        await self._validate_references(
            session,
            study_id,
            site_id=next_site_id,
            subject_id=next_subject_id,
        )
        if (
            resource == StudyOperationResource.PAYMENT
            and "record_subtype" in values
            and values["record_subtype"] not in {"Trigger", "Request"}
        ):
            raise ValidationError(
                "Payment record_subtype must be Trigger or Request",
                {"field": "record_subtype"},
            )
        if resource == StudyOperationResource.PAYMENT and values.get(
            "record_subtype", record.record_subtype
        ) not in {"Trigger", "Request"}:
            raise ValidationError(
                "Payment record_subtype must be Trigger or Request",
                {"field": "record_subtype"},
            )
        if "start_at" in values or "end_at" in values:
            start_at = values.get("start_at", record.start_at)
            end_at = values.get("end_at", record.end_at)
            if start_at and end_at and end_at < start_at:
                raise ValidationError("end_at must be on or after start_at")
        field_map = {"details": "details_json"}
        changed: list[str] = []
        previous_status = record.status
        for field, value in values.items():
            model_field = field_map.get(field, field)
            if getattr(record, model_field) != value:
                setattr(record, model_field, value)
                changed.append(field)
        if not changed:
            return record
        correlation = _correlation_uuid(correlation_id or get_correlation_id())
        record.updated_by = actor_id
        record.updated_at = utc_now()
        record.correlation_id = correlation
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type=f"ctms_{resource.value}",
            entity_id=record.id,
            study_id=study_id,
            site_id=record.site_id,
            actor_id=actor_id,
            correlation_id=correlation,
            action="update",
            changed_fields=changed,
            previous_status=previous_status if "status" in changed else None,
            status=record.status if "status" in changed else None,
            reason=reason,
            payload={"resource_type": resource.value, "record_id": record.id},
        )
        return record


study_operation_service = StudyOperationService()

__all__ = ["StudyOperationService", "study_operation_service"]
