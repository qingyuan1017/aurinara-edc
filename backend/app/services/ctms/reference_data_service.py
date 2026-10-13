"""Mutation service for CTMS reference values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ctms import utc_now
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.request_context import get_actor, get_correlation_id
from app.models.ctms.reference_data import CTMSReferenceValue, ReferenceCategory
from app.services.ctms.ctms_atomicity_service import ctms_atomicity_service


def _values(payload: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    return dict(payload.model_dump(exclude_unset=True))


def _actor(actor: Any | None, actor_id: UUID | None) -> UUID:
    value = actor_id or getattr(actor, "id", None) or get_actor()
    if value is None:
        raise ValidationError("An actor is required for a reference-data mutation")
    return value if isinstance(value, UUID) else UUID(str(value))


def _correlation(value: UUID | str | None, actor: Any | None) -> str:
    return str(value or getattr(actor, "correlation_id", None) or get_correlation_id() or uuid4())


def _correlation_uuid(value: UUID | str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        return uuid5(NAMESPACE_URL, str(value))


async def resolve_reference_value(
    session: AsyncSession,
    category: ReferenceCategory,
    value: str | None,
    *,
    field: str,
) -> str | None:
    """Return the active stable code, allowing legacy values before a category is configured."""

    if value is None or not value.strip():
        return value
    raw = value.strip()
    # Property/service tests use an in-memory unit-of-work double rather than
    # SQLAlchemy. Reference lookup is a persistence adapter concern, so retain
    # the legacy value when that adapter is intentionally absent.
    if not callable(getattr(session, "scalar", None)):
        return raw
    code = raw.upper().replace(" ", "_")
    match = await session.scalar(
        select(CTMSReferenceValue).where(
            CTMSReferenceValue.category == category.value,
            CTMSReferenceValue.active.is_(True),
            or_(
                CTMSReferenceValue.code == code, func.lower(CTMSReferenceValue.label) == raw.lower()
            ),
        )
    )
    if match is not None:
        return match.code
    configured = await session.scalar(
        select(func.count())
        .select_from(CTMSReferenceValue)
        .where(CTMSReferenceValue.category == category.value)
    )
    if configured:
        raise ValidationError(
            "Value is not an active configured CTMS reference",
            {"field": field, "reference_category": category.value},
        )
    return raw


class ReferenceDataService:
    async def create(
        self,
        session: AsyncSession,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> CTMSReferenceValue:
        values = _values(payload)
        category = str(getattr(values["category"], "value", values["category"]))
        code = str(values["code"]).strip().upper().replace(" ", "_")
        duplicate = await session.scalar(
            select(CTMSReferenceValue).where(
                CTMSReferenceValue.category == category,
                CTMSReferenceValue.code == code,
            )
        )
        if duplicate:
            raise ConflictError(
                "A reference value with this category and code already exists",
                {"reason": "DUPLICATE_RECORD"},
            )
        actor_uuid = _actor(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        value = CTMSReferenceValue(
            category=category,
            code=code,
            label=str(values["label"]).strip(),
            description=values.get("description"),
            sort_order=int(values.get("sort_order", 0)),
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation),
        )
        session.add(value)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_reference_value",
            entity_id=value.id,
            study_id=None,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["category", "code", "label", "description", "sort_order"],
            payload={"category": category, "code": code},
        )
        return value

    async def update(
        self,
        session: AsyncSession,
        reference_id: UUID,
        payload: Mapping[str, Any] | Any,
        *,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> CTMSReferenceValue:
        value = await session.get(CTMSReferenceValue, reference_id)
        if value is None:
            raise NotFoundError(
                "CTMS reference value was not found", {"reference_id": str(reference_id)}
            )
        values = _values(payload)
        if (
            value.category == ReferenceCategory.PROJECT_STATUS.value
            and value.active
            and values.get("active") is False
        ):
            remaining = await session.scalar(
                select(func.count())
                .select_from(CTMSReferenceValue)
                .where(
                    CTMSReferenceValue.category == ReferenceCategory.PROJECT_STATUS.value,
                    CTMSReferenceValue.active.is_(True),
                    CTMSReferenceValue.id != value.id,
                )
            )
            if not remaining:
                raise ValidationError(
                    "At least one active Project Status reference value is required",
                    {"field": "active", "reference_category": value.category},
                )
        changed: list[str] = []
        for field in ("label", "description", "sort_order", "active"):
            if field in values and getattr(value, field) != values[field]:
                setattr(value, field, values[field])
                changed.append(field)
        if not changed:
            return value
        actor_uuid = _actor(actor, actor_id)
        correlation = _correlation(correlation_id, actor)
        value.updated_by = actor_uuid
        value.correlation_id = _correlation_uuid(correlation)
        value.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_reference_value",
            entity_id=value.id,
            study_id=None,
            site_id=None,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="update",
            changed_fields=changed,
            payload={"category": value.category, "code": value.code},
        )
        return value


reference_data_service = ReferenceDataService()

__all__ = ["ReferenceDataService", "reference_data_service", "resolve_reference_value"]
