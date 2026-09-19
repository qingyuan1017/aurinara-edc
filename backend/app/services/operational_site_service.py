"""CTMS operational site service.

The service owns operational readiness and activation state while preserving the
canonical EDC ``Site`` as a read-only reference.  Callers provide the active
``AsyncSession``; no method commits so data, status history, audit, and outbox
records share the caller's transaction.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import ensure_utc, utc_now
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.request_context import get_actor, get_correlation_id
from app.models.ctms.operational_site import (
    ActivationAction,
    ActivationActionStatus,
    OperationalSite,
    OperationalSiteStatus,
    RetentionState,
)
from app.models.ctms.work import OperationalContact, OperationalContactStatus
from app.models.site import Site
from app.services.ctms_atomicity_service import ctms_atomicity_service
from app.services.ctms_ownership_guard import assert_ctms_command_safe

logger = logging.getLogger(__name__)


_ACTIVE_ACTION_STATUSES = {
    ActivationActionStatus.OPEN.value,
    ActivationActionStatus.IN_PROGRESS.value,
}

# The graph intentionally allows pausing and resuming work while preventing a
# closed site from silently becoming operational again.
_SITE_TRANSITIONS: dict[str, set[str]] = {
    OperationalSiteStatus.NOT_STARTED.value: {
        OperationalSiteStatus.IN_PROGRESS.value,
        OperationalSiteStatus.READY_FOR_ACTIVATION.value,
        OperationalSiteStatus.SUSPENDED.value,
        OperationalSiteStatus.CLOSED.value,
    },
    OperationalSiteStatus.IN_PROGRESS.value: {
        OperationalSiteStatus.NOT_STARTED.value,
        OperationalSiteStatus.READY_FOR_ACTIVATION.value,
        OperationalSiteStatus.SUSPENDED.value,
        OperationalSiteStatus.CLOSED.value,
    },
    OperationalSiteStatus.READY_FOR_ACTIVATION.value: {
        OperationalSiteStatus.IN_PROGRESS.value,
        OperationalSiteStatus.ACTIVE.value,
        OperationalSiteStatus.SUSPENDED.value,
        OperationalSiteStatus.CLOSED.value,
    },
    OperationalSiteStatus.ACTIVE.value: {
        OperationalSiteStatus.SUSPENDED.value,
        OperationalSiteStatus.CLOSED.value,
    },
    OperationalSiteStatus.SUSPENDED.value: {
        OperationalSiteStatus.IN_PROGRESS.value,
        OperationalSiteStatus.READY_FOR_ACTIVATION.value,
        OperationalSiteStatus.ACTIVE.value,
        OperationalSiteStatus.CLOSED.value,
    },
    OperationalSiteStatus.CLOSED.value: set(),
    OperationalSiteStatus.SITE_ARCHIVED.value: set(),
}


def _as_mapping(payload: Mapping[str, Any] | Any | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, Mapping):
        return dict(payload)
    model_dump = getattr(payload, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(exclude_unset=True))
    raise ValidationError("CTMS site payload must be a mapping")


def _actor_id(actor: Any | None = None, actor_id: UUID | None = None) -> UUID:
    value = actor_id
    if value is None and actor is not None:
        value = getattr(actor, "user_id", None) or getattr(actor, "id", None)
    if value is None:
        value = get_actor()
    if value is None:
        raise ValidationError("An actor is required for an operational site mutation")
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Actor identifier must be a UUID") from exc


def _correlation(value: UUID | str | None, actor: Any | None = None) -> str:
    if value is not None:
        return str(value)
    actor_value = getattr(actor, "correlation_id", None) if actor is not None else None
    return str(actor_value or get_correlation_id() or uuid4().hex)


def _correlation_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return uuid5(NAMESPACE_URL, str(value))


def _timestamp(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min, tzinfo=UTC)
    return ensure_utc(value)


def _normalize_loaded_timestamps(record: ActivationAction) -> ActivationAction:
    """Treat SQLite's reloaded naive timestamps as persisted UTC values.

    PostgreSQL returns ``TIMESTAMPTZ`` values as aware datetimes. SQLite does
    not retain the offset in its portable test dialect, so an existing action
    returned by an idempotent command needs the same UTC contract as a newly
    created action before Pydantic serializes it.
    """

    for field in ("created_at", "updated_at", "planned_date", "completed_at"):
        value = getattr(record, field, None)
        if isinstance(value, datetime) and value.tzinfo is None:
            setattr(record, field, value.replace(tzinfo=UTC))
    return record


def _required_reason(reason: str | None) -> str:
    if reason is None or not reason.strip():
        raise ValidationError("A non-empty reason is required for this transition")
    return reason.strip()


def _status(value: OperationalSiteStatus | ActivationActionStatus | str) -> str:
    return value.value if isinstance(value, (OperationalSiteStatus, ActivationActionStatus)) else str(value)


def _evidence_reference(evidence: Mapping[str, Any] | str) -> str:
    if isinstance(evidence, str):
        reference = evidence.strip()
    else:
        reference = str(
            evidence.get("evidence_reference")
            or evidence.get("reference")
            or evidence.get("uri")
            or evidence.get("id")
            or ""
        ).strip()
        if not reference and evidence:
            reference = json.dumps(dict(evidence), sort_keys=True, separators=(",", ":"))
    if not reference:
        raise ValidationError("Completion evidence is required")
    if len(reference) > 500:
        raise ValidationError("Completion evidence reference is too long")
    return reference


class OperationalSiteService:
    """Manage CTMS site profiles and activation/readiness actions."""

    async def _canonical_site(
        self,
        session: AsyncSession,
        site_id: UUID,
        study_id: UUID | None = None,
    ) -> Site:
        try:
            canonical_id = site_id if isinstance(site_id, UUID) else UUID(str(site_id))
        except (TypeError, ValueError) as exc:
            raise ValidationError("site_id must be a canonical UUID") from exc

        result = await session.execute(
            select(Site).where(Site.id == canonical_id, Site.deleted_at.is_(None))
        )
        site = result.scalars().first()
        if site is None:
            raise NotFoundError(
                "Canonical EDC Site reference was not found",
                {"reason": "RECORD_NOT_FOUND", "site_id": str(canonical_id)},
            )
        if study_id is not None:
            try:
                expected_study = study_id if isinstance(study_id, UUID) else UUID(str(study_id))
            except (TypeError, ValueError) as exc:
                raise ValidationError("study_id must be a canonical UUID") from exc
            if site.study_id != expected_study:
                raise ConflictError(
                    "Canonical Site reference is outside the requested study",
                    {"reason": "REFERENCE_SCOPE_MISMATCH", "site_id": str(canonical_id)},
                )
        return site

    async def get_profile(self, session: AsyncSession, site_id: UUID) -> OperationalSite:
        result = await session.execute(
            select(OperationalSite).where(
                OperationalSite.site_id == site_id,
                OperationalSite.deleted_at.is_(None),
            )
        )
        profile = result.scalars().first()
        if profile is None:
            raise NotFoundError("Operational site profile was not found", {"site_id": str(site_id)})
        return profile

    async def create_profile(
        self,
        session: AsyncSession,
        *,
        site_id: UUID,
        payload: Mapping[str, Any] | Any | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        study_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> OperationalSite:
        """Create one operational profile for a canonical EDC site."""

        values = _as_mapping(payload)
        assert_ctms_command_safe(values, operation="create_operational_site_profile")
        actor_uuid = _actor_id(actor, actor_id)
        site = await self._canonical_site(session, site_id, study_id or values.get("study_id"))
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)

        existing = await session.execute(
            select(OperationalSite).where(
                OperationalSite.site_id == site.id,
                OperationalSite.deleted_at.is_(None),
            )
        )
        if existing.scalars().first() is not None:
            raise ConflictError(
                "An operational site profile already exists",
                {"site_id": str(site.id), "reason": "DUPLICATE_RECORD"},
            )

        requested_status = _status(values.get("status", OperationalSiteStatus.NOT_STARTED))
        if requested_status not in _SITE_TRANSITIONS:
            raise ValidationError("Invalid operational site status", {"status": requested_status})
        profile = OperationalSite(
            study_id=site.study_id,
            site_id=site.id,
            monitoring_readiness=values.get("monitoring_readiness"),
            responsible_role=values.get("responsible_role"),
            planned_activation_date=_timestamp(values.get("planned_activation_date")),
            status=requested_status,
            retention_state=RetentionState.ACTIVE.value,
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(profile)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="operational_site",
            entity_id=profile.id,
            study_id=profile.study_id,
            site_id=profile.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["site_id", "monitoring_readiness", "responsible_role", "planned_activation_date", "status"],
            status=requested_status,
            payload={"site_id": site.id, "status": requested_status},
        )
        return profile

    async def update_profile(
        self,
        session: AsyncSession,
        profile: OperationalSite | UUID,
        changes: Mapping[str, Any] | Any,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
        reason: str | None = None,
    ) -> OperationalSite:
        """Update CTMS-owned profile fields only."""

        values = _as_mapping(changes)
        assert_ctms_command_safe(values, operation="update_operational_site_profile")
        actor_uuid = _actor_id(actor, actor_id)
        if isinstance(profile, UUID):
            profile = await self.get_profile(session, profile)
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)
        allowed = {"monitoring_readiness", "responsible_role", "planned_activation_date"}
        unknown = set(values) - allowed - {"correlation_id"}
        if unknown:
            raise ValidationError("Unknown operational site profile field", {"field": sorted(unknown)[0]})
        changed: list[str] = []
        for field in allowed:
            if field in values:
                setattr(profile, field, _timestamp(values[field]) if field == "planned_activation_date" else values[field])
                changed.append(field)
        if not changed:
            return profile
        profile.updated_by = actor_uuid
        profile.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="operational_site",
            entity_id=profile.id,
            study_id=profile.study_id,
            site_id=profile.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="update",
            changed_fields=changed,
            reason=reason,
            payload={"site_id": profile.site_id, "changed_fields": changed},
        )
        return profile

    async def transition_status(
        self,
        session: AsyncSession,
        profile: OperationalSite | UUID,
        target_status: OperationalSiteStatus | str,
        reason: str | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> OperationalSite:
        """Apply a configured operational site status transition."""

        actor_uuid = _actor_id(actor, actor_id)
        if isinstance(profile, UUID):
            profile = await self.get_profile(session, profile)
        target = _status(target_status)
        current = _status(profile.status)
        if target == current:
            return profile
        if target not in _SITE_TRANSITIONS.get(current, set()):
            raise ConflictError(
                f"Invalid operational site transition from '{current}' to '{target}'",
                {"reason": "INVALID_TRANSITION", "current_status": current, "target_status": target},
            )
        change_reason = _required_reason(reason)
        correlation = _correlation(correlation_id, actor)
        profile.status = target
        profile.updated_by = actor_uuid
        profile.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="operational_site",
            entity_id=profile.id,
            study_id=profile.study_id,
            site_id=profile.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="status_transition",
            changed_fields=["status"],
            previous_status=current,
            status=target,
            reason=change_reason,
            payload={"site_id": profile.site_id, "status": target},
        )
        return profile

    async def create_activation_action(
        self,
        session: AsyncSession,
        *,
        site_id: UUID,
        payload: Mapping[str, Any] | Any | None = None,
        action_type: str | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        study_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> ActivationAction:
        """Create or return the active action for ``(canonical site, type)``."""

        values = _as_mapping(payload)
        assert_ctms_command_safe(values, operation="create_activation_action")
        actor_uuid = _actor_id(actor, actor_id)
        site = await self._canonical_site(session, site_id, study_id or values.get("study_id"))
        action_name = (action_type or values.get("action_type") or "").strip()
        if not action_name:
            raise ValidationError("action_type is required")
        correlation = _correlation(correlation_id or values.get("correlation_id"), actor)

        existing_result = await session.execute(
            select(ActivationAction).where(
                ActivationAction.site_id == site.id,
                ActivationAction.action_type == action_name,
                ActivationAction.deleted_at.is_(None),
                ActivationAction.status.in_(_ACTIVE_ACTION_STATUSES),
            )
        )
        existing = existing_result.scalars().first()
        if existing is not None:
            return _normalize_loaded_timestamps(existing)

        action = ActivationAction(
            study_id=site.study_id,
            site_id=site.id,
            action_type=action_name,
            responsible_role=values.get("responsible_role"),
            responsible_user_id=values.get("responsible_user_id"),
            planned_date=_timestamp(values.get("planned_date")),
            completion_criteria=values.get("completion_criteria"),
            status=ActivationActionStatus.OPEN.value,
            retention_state=RetentionState.ACTIVE.value,
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(action)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="activation_action",
            entity_id=action.id,
            study_id=action.study_id,
            site_id=action.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="create",
            changed_fields=["action_type", "responsible_role", "planned_date", "status"],
            status=action.status,
            payload={"site_id": site.id, "action_type": action_name, "status": action.status},
        )
        return action

    async def transition_activation_action(
        self,
        session: AsyncSession,
        action: ActivationAction | UUID,
        target_status: ActivationActionStatus | str,
        reason: str | None = None,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        correlation_id: UUID | str | None = None,
    ) -> ActivationAction:
        """Transition an activation/readiness action and retain its reason."""

        actor_uuid = _actor_id(actor, actor_id)
        action = await self._resolve_action(session, action)
        target = _status(target_status)
        current = _status(action.status)
        allowed = {
            ActivationActionStatus.OPEN.value: {ActivationActionStatus.IN_PROGRESS.value, ActivationActionStatus.CANCELLED.value},
            ActivationActionStatus.IN_PROGRESS.value: {ActivationActionStatus.COMPLETED.value, ActivationActionStatus.CANCELLED.value},
            ActivationActionStatus.COMPLETED.value: set(),
            ActivationActionStatus.CANCELLED.value: set(),
            ActivationActionStatus.ARCHIVED.value: set(),
        }
        if target not in allowed.get(current, set()):
            raise ConflictError(
                f"Invalid activation action transition from '{current}' to '{target}'",
                {"reason": "INVALID_TRANSITION", "current_status": current, "target_status": target},
            )
        if target == ActivationActionStatus.COMPLETED.value:
            raise ValidationError("Use complete_activation_action to provide completion evidence")
        change_reason = _required_reason(reason)
        correlation = _correlation(correlation_id, actor)
        action.status = target
        action.updated_by = actor_uuid
        action.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="activation_action",
            entity_id=action.id,
            study_id=action.study_id,
            site_id=action.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="status_transition",
            changed_fields=["status"],
            previous_status=current,
            status=target,
            reason=change_reason,
            payload={"site_id": action.site_id, "status": target},
        )
        return action

    async def complete_activation_action(
        self,
        session: AsyncSession,
        action: ActivationAction | UUID,
        evidence: Mapping[str, Any] | str,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        reason: str | None = None,
        correlation_id: UUID | str | None = None,
    ) -> ActivationAction:
        """Complete an action with actor, UTC time, and mandatory evidence."""

        actor_uuid = _actor_id(actor, actor_id)
        action = await self._resolve_action(session, action)
        if action.status not in _ACTIVE_ACTION_STATUSES:
            raise ConflictError(
                "Only an open or in-progress activation action can be completed",
                {"reason": "INVALID_TRANSITION", "status": action.status},
            )
        previous_status = action.status
        evidence_reference = _evidence_reference(evidence)
        correlation = _correlation(correlation_id, actor)
        completion_reason = reason.strip() if reason and reason.strip() else None
        action.status = ActivationActionStatus.COMPLETED.value
        action.completed_by = actor_uuid
        action.completed_at = utc_now()
        action.evidence_reference = evidence_reference
        action.updated_by = actor_uuid
        action.updated_at = utc_now()
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="activation_action",
            entity_id=action.id,
            study_id=action.study_id,
            site_id=action.site_id,
            actor_id=actor_uuid,
            correlation_id=correlation,
            action="complete",
            changed_fields=["status", "completed_by", "completed_at", "evidence_reference"],
            previous_status=previous_status,
            status=ActivationActionStatus.COMPLETED.value,
            reason=completion_reason,
            payload={"site_id": action.site_id, "status": action.status, "evidence_reference": evidence_reference},
        )
        return action

    async def _resolve_action(self, session: AsyncSession, action: ActivationAction | UUID) -> ActivationAction:
        if isinstance(action, ActivationAction):
            return action
        result = await session.execute(
            select(ActivationAction).where(
                ActivationAction.id == action,
                ActivationAction.deleted_at.is_(None),
            )
        )
        resolved = result.scalars().first()
        if resolved is None:
            raise NotFoundError("Activation action was not found", {"action_id": str(action)})
        return resolved

    async def list_activation_actions(
        self,
        session: AsyncSession,
        site_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ActivationAction]:
        query = select(ActivationAction).where(
            ActivationAction.site_id == site_id,
            ActivationAction.deleted_at.is_(None),
        )
        if not include_archived:
            query = query.where(ActivationAction.status != ActivationActionStatus.ARCHIVED.value)
        query = query.order_by(ActivationAction.created_at.asc())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def archive_site(
        self,
        session: AsyncSession,
        site_id: UUID,
        actor: Any | None = None,
        actor_id: UUID | None = None,
        reason: str | None = None,
        correlation_id: UUID | str | None = None,
        archive_rule: str = "site_archived",
    ) -> OperationalSite | None:
        """Archive CTMS records linked to an EDC-archived canonical site."""

        actor_uuid = _actor_id(actor, actor_id)
        change_reason = _required_reason(reason or "EDC site archived")
        profile_result = await session.execute(
            select(OperationalSite).where(
                OperationalSite.site_id == site_id,
                OperationalSite.deleted_at.is_(None),
            )
        )
        profile = profile_result.scalars().first()
        correlation = _correlation(correlation_id, actor)
        if profile is not None and profile.status != OperationalSiteStatus.SITE_ARCHIVED.value:
            previous = profile.status
            profile.status = OperationalSiteStatus.SITE_ARCHIVED.value
            profile.retention_state = RetentionState.ARCHIVED.value
            profile.archived_at = utc_now()
            profile.archived_by = actor_uuid
            profile.retention_reason = change_reason
            profile.updated_by = actor_uuid
            profile.updated_at = utc_now()
            await session.flush()
            await ctms_atomicity_service.record_mutation(
                session,
                entity_type="operational_site",
                entity_id=profile.id,
                study_id=profile.study_id,
                site_id=profile.site_id,
                actor_id=actor_uuid,
                correlation_id=correlation,
                action="archive",
                changed_fields=["status", "retention_state", "archived_at", "archived_by"],
                previous_status=previous,
                status=OperationalSiteStatus.SITE_ARCHIVED.value,
                reason=change_reason,
                event_type=f"site_archive_{archive_rule}",
                payload={"site_id": site_id, "status": OperationalSiteStatus.SITE_ARCHIVED.value},
            )

        actions = await self.list_activation_actions(session, site_id, include_archived=True)
        for action in actions:
            if action.status == ActivationActionStatus.ARCHIVED.value:
                continue
            previous = action.status
            action.status = ActivationActionStatus.ARCHIVED.value
            action.retention_state = RetentionState.ARCHIVED.value
            action.archived_at = utc_now()
            action.archived_by = actor_uuid
            action.retention_reason = change_reason
            action.updated_by = actor_uuid
            action.updated_at = utc_now()
            await session.flush()
            await ctms_atomicity_service.record_mutation(
                session,
                entity_type="activation_action",
                entity_id=action.id,
                study_id=action.study_id,
                site_id=action.site_id,
                actor_id=actor_uuid,
                correlation_id=correlation,
                action="archive",
                changed_fields=["status", "retention_state", "archived_at", "archived_by"],
                previous_status=previous,
                status=ActivationActionStatus.ARCHIVED.value,
                reason=change_reason,
                event_type=f"site_archive_{archive_rule}",
                payload={"site_id": site_id, "status": ActivationActionStatus.ARCHIVED.value},
            )

        contact_result = await session.execute(
            select(OperationalContact).where(
                OperationalContact.site_id == site_id,
                OperationalContact.deleted_at.is_(None),
                OperationalContact.status != OperationalContactStatus.ARCHIVED.value,
            )
        )
        contacts = list(contact_result.scalars().all())
        for contact in contacts:
            contact.status = OperationalContactStatus.ARCHIVED.value
            contact.retention_state = RetentionState.ARCHIVED.value
            contact.archived_at = utc_now()
            contact.archived_by = actor_uuid
            contact.retention_reason = change_reason
            contact.updated_by = actor_uuid
            contact.updated_at = utc_now()
            await audit_service.record(
                session,
                entity_type="operational_contact",
                entity_id=contact.id,
                action="archive",
                module="CTMS",
                actor_id=actor_uuid,
                correlation_id=correlation,
                scope={"study_id": contact.study_id, "site_id": contact.site_id},
                changed_fields=["status", "retention_state", "archived_at", "archived_by"],
                study_id=contact.study_id,
                site_id=contact.site_id,
                reason=change_reason,
            )
        await session.flush()
        return profile

    async def on_edc_site_archived(self, session: AsyncSession, **kwargs: Any) -> OperationalSite | None:
        """Coordination-friendly alias for EDC site archive events."""

        return await self.archive_site(session, **kwargs)

    async def mark_site_archived(self, session: AsyncSession, **kwargs: Any) -> OperationalSite | None:
        """Compatibility alias for archive event consumers."""

        return await self.archive_site(session, **kwargs)


operational_site_service = OperationalSiteService()

__all__ = ["OperationalSiteService", "operational_site_service"]
