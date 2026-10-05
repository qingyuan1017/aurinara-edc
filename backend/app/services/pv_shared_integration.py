"""PV_Safety_Module integration with shared platform primitives.

PV owns safety content semantics but reuses the platform's shared primitives
rather than forking them:

* the immutable append-only ``Audit_Service`` (via :mod:`pv_atomicity_service`);
* shared notification persistence and delivery state (``Notification_Service``);
* shared file metadata/access/retention primitives (``File_Attachment_Service``);
* shared export-job lifecycle/storage/download controls (``Export_Service``);
* the shared ``Coordination_Service`` transactional outbox.

This module is a thin, PV-owned facade. It tags shared records with the ``PV``
module so PV safety content stays separate from EDC clinical and CTMS
operational content, and it routes every PV Safety_Data or Safety_Attachment
mutation through the atomic Audit_Event write so no PV state persists without
its Audit_Event (Requirements 11.1-11.3, 11.6-11.7, 16.4, 18.1-18.3). All
methods act on the caller-provided ``AsyncSession`` and never commit or open an
independent session.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pv import ActorContext, Module
from app.models.notification import Notification, NotificationStatus
from app.services.pv_atomicity_service import PVMutationRecord, pv_atomicity_service

# Shared primitives reused, not forked.
_PV_MODULE = Module.PV.value


def _safe_scalar(value: Any) -> Any:
    """Render a notification payload value as a caller-safe scalar."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat()
    return str(value)


class PVSharedIntegrationService:
    """PV-owned facade over shared notification/file/export/coordination state."""

    def __init__(self, *, atomicity_service: Any = pv_atomicity_service) -> None:
        self._atomicity = atomicity_service

    # ------------------------------------------------------------------
    # Notifications — shared persistence/delivery state, PV-owned triggers.
    # ------------------------------------------------------------------

    async def create_pv_notification(
        self,
        session: AsyncSession,
        *,
        user_ids: Sequence[UUID],
        notification_type: str,
        payload: dict[str, Any],
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Persist one PV safety notification per resolved recipient.

        Notifications reuse the shared ``notifications`` table and delivery
        state machine (Unread/Read/Archived) but are tagged ``module="PV"`` so
        PV safety triggers stay distinct from EDC/CTMS notifications. Delivery
        state remains shared; PV owns only the trigger and content.
        """

        safe_payload = {key: _safe_scalar(value) for key, value in payload.items()}
        notifications = [
            Notification(
                user_id=user_id,
                module=_PV_MODULE,
                correlation_id=correlation_id,
                study_id=study_id,
                site_id=site_id,
                type=notification_type,
                payload_json=safe_payload,
                status=NotificationStatus.unread,
                created_at=datetime.now(UTC),
            )
            # Deduplicate recipients while preserving order.
            for user_id in dict.fromkeys(user_ids)
        ]
        for notification in notifications:
            session.add(notification)
        if notifications:
            await session.flush()
        return notifications

    async def list_unread_pv_notifications(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
    ) -> list[Notification]:
        """Return only the requesting user's Unread PV safety notifications."""

        result = await session.execute(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.module == _PV_MODULE,
                Notification.status == NotificationStatus.unread,
            )
            .order_by(Notification.created_at.desc())
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Attachments — shared file primitives, PV-owned safety access rules.
    # ------------------------------------------------------------------

    async def record_attachment_action(
        self,
        session: AsyncSession,
        *,
        attachment_id: UUID,
        action: str,
        actor: ActorContext,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        case_id: UUID | None = None,
        reason: str | None = None,
    ) -> PVMutationRecord:
        """Record one PV safety Audit_Event for a completed attachment action.

        The shared ``File_Attachment_Service`` owns storage/metadata/retention;
        PV records the ``upload``/``download``/``deletion`` action atomically so
        no completed attachment action persists without its Audit_Event. The
        caller invokes this only after the shared file action has succeeded on
        the same transaction, and the shared unit of work rolls both back on
        failure.
        """

        return await self._atomicity.record_mutation(
            session,
            entity_type="safety_attachment",
            entity_id=attachment_id,
            action=action,
            actor=actor,
            study_id=study_id,
            site_id=site_id,
            changed_fields=["case_id"] if case_id is not None else (),
            new_value=case_id,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Exports — shared job lifecycle/storage/download controls, PV content.
    # ------------------------------------------------------------------

    async def record_export_download(
        self,
        session: AsyncSession,
        *,
        export_job_id: UUID,
        actor: ActorContext,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
    ) -> PVMutationRecord:
        """Record one PV safety Audit_Event when an export file is downloaded.

        Export-job lifecycle, storage, and the 900-second download window are
        owned by the shared ``Export_Service``. PV records the authorized
        download action atomically on the caller's transaction.
        """

        return await self._atomicity.record_mutation(
            session,
            entity_type="safety_export_job",
            entity_id=export_job_id,
            action="download",
            actor=actor,
            study_id=study_id,
            site_id=site_id,
        )

    # ------------------------------------------------------------------
    # Coordination — shared transactional outbox, PV-owned safety events.
    # ------------------------------------------------------------------

    async def record_coordination_event(
        self,
        session: AsyncSession,
        *,
        entity_type: str,
        entity_id: UUID,
        action: str,
        actor: ActorContext,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        target_module: Module | str = Module.PV,
        target_record_id: UUID | None = None,
    ) -> PVMutationRecord:
        """Append a PV coordination outbox row and its Audit_Event atomically.

        Used when a PV mutation must also emit an approved coordination event;
        the outbox row commits in the same transaction as the Safety_Data change
        and its Audit_Event.
        """

        return await self._atomicity.record_mutation(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            study_id=study_id,
            site_id=site_id,
            emit_outbox=True,
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
            target_module=target_module,
            target_record_id=target_record_id,
        )


pv_shared_integration_service = PVSharedIntegrationService()

__all__ = [
    "PVSharedIntegrationService",
    "pv_shared_integration_service",
]
