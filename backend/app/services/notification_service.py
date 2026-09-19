"""Notification_Service for clinical workflow events.

Notifications are persisted in the caller's active transaction. Recipient
resolution is deliberately server-side: role assignments are filtered by the
same study/site scope used by the permission model, and unread listing is
always constrained to the requested user's ID.

Satisfies Requirements 28.1-28.5.
"""

from __future__ import annotations

import inspect
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.api.pagination import paginate
from app.core.ctms import Module
from app.core.exceptions import AuthorizationError, BusinessRuleError, NotFoundError
from app.models.form_data import FormInstance
from app.models.identity import Role, ScopeLevel, User, UserRole, UserStatus
from app.models.notification import Notification, NotificationStatus
from app.models.query import Query
from app.schemas.base import PaginatedResponse

logger = logging.getLogger(__name__)

_MEDICAL_REVIEWER_ROLE = "Medical Reviewer"


def _safe_datetime(value: Any) -> str | None:
    """Serialize only timezone-aware timestamps into notification payloads."""
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat()
    return None


def _as_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


class NotificationService:
    """Create, query, and transition user workflow notifications."""

    async def create_ctms_notification(
        self,
        session: AsyncSession,
        *,
        user_ids: list[UUID],
        notification_type: str,
        payload: dict[str, Any],
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Persist a CTMS notification without taking ownership of delivery.

        The shared table stores only operational references and sanitized
        payloads. Delivery state remains shared; CTMS owns the trigger.
        """
        return await self._create_for_users(
            session,
            user_ids,
            notification_type=notification_type,
            payload=payload,
            module=Module.CTMS,
            study_id=study_id,
            site_id=site_id,
            correlation_id=correlation_id,
        )

    async def on_task_assigned(
        self,
        session: AsyncSession,
        task: Any,
        *,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Notify the assigned operational task owner in its scope."""
        owner_id = getattr(task, "owner_id", None)
        if owner_id is None:
            return []
        study_id = getattr(task, "study_id", None)
        site_id = getattr(task, "site_id", None)
        return await self.create_ctms_notification(
            session,
            user_ids=[owner_id],
            notification_type="ctms_task_assigned",
            payload={
                "task_id": str(task.id),
                "study_id": str(study_id),
                "site_id": str(site_id) if site_id else None,
                "priority": str(getattr(task, "priority", "Normal")),
            },
            study_id=study_id,
            site_id=site_id,
            correlation_id=correlation_id or str(getattr(task, "correlation_id", "")),
        )

    async def on_monitoring_assigned(
        self,
        session: AsyncSession,
        activity: Any,
        *,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Notify the CRA assigned to a monitoring activity."""
        assigned_cra_id = getattr(activity, "assigned_cra_id", None)
        if assigned_cra_id is None:
            return []
        return await self.create_ctms_notification(
            session,
            user_ids=[assigned_cra_id],
            notification_type="ctms_monitoring_assigned",
            payload={
                "activity_id": str(activity.id),
                "study_id": str(activity.study_id),
                "site_id": str(activity.site_id) if activity.site_id else None,
                "planned_date": _safe_datetime(getattr(activity, "planned_date", None)),
            },
            study_id=activity.study_id,
            site_id=activity.site_id,
            correlation_id=correlation_id or str(getattr(activity, "correlation_id", "")),
        )

    async def on_monitoring_rescheduled(
        self,
        session: AsyncSession,
        activity: Any,
        *,
        previous_planned_date: Any = None,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Notify the assigned CRA after an activity date changes."""
        assigned_cra_id = getattr(activity, "assigned_cra_id", None)
        if assigned_cra_id is None:
            return []
        return await self.create_ctms_notification(
            session,
            user_ids=[assigned_cra_id],
            notification_type="ctms_monitoring_rescheduled",
            payload={
                "activity_id": str(activity.id),
                "study_id": str(activity.study_id),
                "site_id": str(activity.site_id) if activity.site_id else None,
                "previous_planned_date": _safe_datetime(previous_planned_date),
                "planned_date": _safe_datetime(getattr(activity, "planned_date", None)),
            },
            study_id=activity.study_id,
            site_id=activity.site_id,
            correlation_id=correlation_id or str(getattr(activity, "correlation_id", "")),
        )

    async def on_monitoring_overdue(
        self,
        session: AsyncSession,
        activity: Any,
        *,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Notify scoped CTMS operations users when monitoring becomes overdue."""
        user_ids = await self._recipient_ids_for_roles(
            session,
            study_id=activity.study_id,
            site_id=activity.site_id,
            role_names=("CTMS_Admin", "CTMS_Operations_User"),
        )
        return await self.create_ctms_notification(
            session,
            user_ids=user_ids,
            notification_type="ctms_monitoring_overdue",
            payload={
                "activity_id": str(activity.id),
                "study_id": str(activity.study_id),
                "site_id": str(activity.site_id) if activity.site_id else None,
                "planned_date": _safe_datetime(getattr(activity, "planned_date", None)),
            },
            study_id=activity.study_id,
            site_id=activity.site_id,
            correlation_id=correlation_id or str(getattr(activity, "correlation_id", "")),
        )

    async def on_failed_event(
        self,
        session: AsyncSession,
        event: Any,
        *,
        reason: str | None = None,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Notify authorized CTMS administrators of a failed event.

        Only identifiers and a bounded reason code are retained; event payloads
        are intentionally never copied into notification content.
        """
        payload = getattr(event, "payload_json", {}) or {}
        resolved_study_id = study_id or _as_uuid(payload.get("study_id"))
        resolved_site_id = site_id or _as_uuid(payload.get("site_id"))
        user_ids = await self._recipient_ids_for_roles(
            session,
            study_id=resolved_study_id,
            site_id=resolved_site_id,
            role_names=("CTMS_Admin",),
        ) if resolved_study_id is not None else await self._system_recipient_ids(
            session, role_names=("CTMS_Admin",)
        )
        safe_reason = str(reason or getattr(event, "last_error_category", None) or "COORDINATION_FAILED_EVENT")[:100]
        return await self.create_ctms_notification(
            session,
            user_ids=user_ids,
            notification_type="ctms_failed_event",
            payload={
                "event_id": str(getattr(event, "event_id", getattr(event, "id", ""))),
                "event_type": str(getattr(event, "event_type", "")),
                "reason_code": safe_reason,
            },
            study_id=resolved_study_id,
            site_id=resolved_site_id,
            correlation_id=correlation_id or str(getattr(event, "correlation_id", "")),
        )

    async def on_coordination_conflict(
        self,
        session: AsyncSession,
        conflict: Any,
        *,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Notify scoped CTMS administrators without copying event content."""
        study_id = _as_uuid(getattr(conflict, "study_id", None))
        site_id = _as_uuid(getattr(conflict, "site_id", None))
        user_ids = (
            await self._recipient_ids_for_roles(
                session, study_id=study_id, site_id=site_id, role_names=("CTMS_Admin",)
            )
            if study_id is not None
            else await self._system_recipient_ids(session, role_names=("CTMS_Admin",))
        )
        reason_code = str(reason or getattr(conflict, "conflict_type", None) or "COORDINATION_CONFLICT")[:100]
        return await self.create_ctms_notification(
            session,
            user_ids=user_ids,
            notification_type="ctms_coordination_conflict",
            payload={
                "conflict_id": str(getattr(conflict, "id", "")),
                "event_id": str(getattr(conflict, "event_id", "")),
                "reason_code": reason_code,
            },
            study_id=study_id,
            site_id=site_id,
            correlation_id=correlation_id or str(getattr(conflict, "correlation_id", "")),
        )

    async def on_query_assigned(
        self,
        session: AsyncSession,
        query: Query,
        *,
        assigned_role: str | None = None,
    ) -> list[Notification]:
        """Notify active users assigned the query's role in its scope.

        ``assigned_role`` can be supplied explicitly by callers or read from
        the query record. If a query has no assignment, no notification is
        emitted; this preserves the distinction between an unassigned query
        and one assigned to a role.
        """
        role_name = assigned_role or getattr(query, "assigned_role", None)
        if not role_name:
            return []

        user_ids = await self._recipient_ids(
            session,
            study_id=query.study_id,
            site_id=query.site_id,
            role_name=role_name,
        )
        return await self._create_for_users(
            session,
            user_ids,
            notification_type="query_assigned",
            payload={
                "query_id": str(query.id),
                "study_id": str(query.study_id),
                "site_id": str(query.site_id) if query.site_id else None,
                "subject_id": str(query.subject_id) if query.subject_id else None,
                "assigned_role": role_name,
            },
        )

    async def on_form_submitted(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        *,
        reviewer_role: str = _MEDICAL_REVIEWER_ROLE,
    ) -> list[Notification]:
        """Notify responsible reviewers when a form is successfully submitted."""
        # FormInstance queries use select-in loading for Subject. Avoid an
        # implicit async lazy load, and avoid guessing scope when the caller
        # did not load the parent subject.
        subject = form_instance.__dict__.get("subject")
        if subject is None:
            return []

        study_id = subject.study_id
        site_id = subject.site_id
        user_ids = await self._recipient_ids(
            session,
            study_id=study_id,
            site_id=site_id,
            role_name=reviewer_role,
        )
        return await self._create_for_users(
            session,
            user_ids,
            notification_type="form_submitted",
            payload={
                "form_instance_id": str(form_instance.id),
                "study_id": str(study_id),
                "site_id": str(site_id) if site_id else None,
                "subject_id": str(form_instance.subject_id),
                "submitted_by": (
                    str(form_instance.submitted_by)
                    if form_instance.submitted_by
                    else None
                ),
            },
        )

    async def on_export_completed(
        self,
        session: AsyncSession,
        job: Any,
    ) -> list[Notification]:
        """Notify the user who requested a completed export job."""
        requester_id = getattr(job, "requested_by", None)
        if requester_id is None:
            return []
        return await self._create_for_users(
            session,
            [requester_id],
            notification_type="export_completed",
            payload={
                "export_id": str(job.id),
                "study_id": str(job.study_id),
                "export_type": job.export_type,
                "file_path": job.file_path,
                "file_size": job.file_size,
            },
        )

    async def list_for_user(
        self,
        session: AsyncSession,
        user: UUID | User,
        *,
        statuses: set[NotificationStatus] | None = None,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        module: Module | str | None = Module.CTMS,
    ) -> list[Notification]:
        """List owned notifications with optional module and scope filters."""
        user_id = self._user_id(user)
        conditions = [Notification.user_id == user_id]
        if statuses:
            conditions.append(Notification.status.in_(list(statuses)))
        if module is not None:
            conditions.append(Notification.module == getattr(module, "value", module))
        if study_id is not None:
            conditions.append(Notification.study_id == study_id)
        if site_id is not None:
            conditions.append(Notification.site_id == site_id)
        result = await session.execute(
            select(Notification).where(and_(*conditions)).order_by(Notification.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_ctms_for_scope(
        self,
        session: AsyncSession,
        user: UUID | User,
        *,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        statuses: set[NotificationStatus] | None = None,
    ) -> list[Notification]:
        """Convenience scope-filtered CTMS inbox query."""
        return await self.list_for_user(
            session, user, statuses=statuses, study_id=study_id, site_id=site_id,
            module=Module.CTMS,
        )

    async def list_unread(
        self,
        session: AsyncSession,
        user: UUID | User,
    ) -> list[Notification]:
        """Return only unread notifications addressed to ``user``."""
        user_id = self._user_id(user)
        result = await session.execute(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.status == NotificationStatus.unread,
            )
            .order_by(Notification.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_unread_paginated(
        self,
        session: AsyncSession,
        user: UUID | User,
        pagination: PaginationParams,
    ) -> PaginatedResponse[Notification]:
        """Return an ownership-scoped pagination envelope for unread records."""
        user_id = self._user_id(user)
        query = (
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.status == NotificationStatus.unread,
            )
            .order_by(Notification.created_at.desc())
        )
        return await paginate(session, query, pagination)

    async def mark_read(
        self,
        session: AsyncSession,
        notification: Notification | UUID,
        user: UUID | User,
    ) -> Notification:
        """Transition an owned Unread notification to Read."""
        notification = await self._owned_notification(session, notification, user)
        self._transition(notification, NotificationStatus.read)
        await session.flush()
        return notification

    async def archive(
        self,
        session: AsyncSession,
        notification: Notification | UUID,
        user: UUID | User,
    ) -> Notification:
        """Transition an owned Unread/Read notification to Archived."""
        notification = await self._owned_notification(session, notification, user)
        self._transition(notification, NotificationStatus.archived)
        await session.flush()
        return notification

    async def get_for_user(
        self,
        session: AsyncSession,
        notification_id: UUID,
        user: UUID | User,
    ) -> Notification:
        """Fetch a notification only when it belongs to the requesting user."""
        return await self._owned_notification(session, notification_id, user)

    async def _recipient_ids_for_roles(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        site_id: UUID | None,
        role_names: tuple[str, ...],
    ) -> list[UUID]:
        """Resolve active users for any authorized role within one scope."""
        return await self._recipient_ids(
            session,
            study_id=study_id,
            site_id=site_id,
            role_name=None,
            role_names=role_names,
        )

    async def _system_recipient_ids(
        self, session: AsyncSession, *, role_names: tuple[str, ...]
    ) -> list[UUID]:
        result = await session.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .join(User, User.id == UserRole.user_id)
            .where(
                Role.name.in_(role_names),
                User.status == UserStatus.active,
                Role.scope_level == ScopeLevel.system,
                UserRole.study_id.is_(None),
                UserRole.site_id.is_(None),
            )
            .distinct()
        )
        return list(result.scalars().all())

    async def _recipient_ids(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        site_id: UUID | None,
        role_name: str | None = None,
        role_names: tuple[str, ...] | None = None,
    ) -> list[UUID]:
        """Resolve active role members whose assignment covers the scope."""
        system_scope = and_(
            Role.scope_level == ScopeLevel.system,
            UserRole.study_id.is_(None),
            UserRole.site_id.is_(None),
        )
        study_scope = and_(
            Role.scope_level == ScopeLevel.study,
            UserRole.study_id == study_id,
            UserRole.site_id.is_(None),
        )
        site_scope = and_(
            Role.scope_level == ScopeLevel.site,
            UserRole.study_id == study_id,
            UserRole.site_id == site_id,
        )
        scope_filter = or_(system_scope, study_scope, site_scope)
        result = await session.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .join(User, User.id == UserRole.user_id)
            .where(
                Role.name == role_name if role_name is not None else Role.name.in_(role_names or ()),
                User.status == UserStatus.active,
                scope_filter,
            )
            .distinct()
        )
        return list(result.scalars().all())

    async def _create_for_users(
        self,
        session: AsyncSession,
        user_ids: list[UUID],
        *,
        notification_type: str,
        payload: dict[str, Any],
        module: Module = Module.EDC,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Create unread notifications in the caller's transaction."""
        notifications = [
            Notification(
                user_id=user_id,
                module=module.value,
                correlation_id=correlation_id,
                study_id=study_id,
                site_id=site_id,
                type=notification_type,
                payload_json=payload,
                status=NotificationStatus.unread,
                created_at=datetime.now(UTC),
            )
            for user_id in dict.fromkeys(user_ids)
        ]
        def add_notifications() -> Any:
            if hasattr(session, "add_all"):
                return session.add_all(notifications)
            for notification in notifications:
                session.add(notification)
            return None

        if notifications:
            add_result = add_notifications()
            # SQLAlchemy's AsyncSession.add_all is synchronous, while a few
            # lightweight test doubles expose it as an async mock.
            if inspect.isawaitable(add_result):
                await add_result
            await session.flush()
        logger.info(
            "Workflow notifications created: type=%s recipients=%d",
            notification_type,
            len(notifications),
        )
        return notifications

    async def _owned_notification(
        self,
        session: AsyncSession,
        notification: Notification | UUID,
        user: UUID | User,
    ) -> Notification:
        user_id = self._user_id(user)
        if isinstance(notification, UUID):
            result = await session.execute(
                select(Notification).where(
                    Notification.id == notification,
                    Notification.user_id == user_id,
                )
            )
            resolved = result.scalars().first()
            if resolved is None:
                raise NotFoundError(
                    message="Notification not found",
                    details={"notification_id": str(notification)},
                )
            return resolved

        if notification.user_id != user_id:
            raise AuthorizationError(
                message="Notification does not belong to the current user",
                details={"notification_id": str(notification.id)},
            )
        return notification

    @staticmethod
    def _transition(
        notification: Notification,
        target: NotificationStatus,
    ) -> None:
        current = NotificationStatus(notification.status)
        allowed = {
            NotificationStatus.unread: {
                NotificationStatus.read,
                NotificationStatus.archived,
            },
            NotificationStatus.read: {NotificationStatus.archived},
            NotificationStatus.archived: set(),
        }
        if target not in allowed[current]:
            raise BusinessRuleError(
                message=f"Cannot transition notification from {current.value} to {target.value}",
                details={
                    "notification_id": str(notification.id),
                    "current_status": current.value,
                    "target_status": target.value,
                },
            )
        notification.status = target
        if target in {NotificationStatus.read, NotificationStatus.archived}:
            notification.read_at = notification.read_at or datetime.now(UTC)

    @staticmethod
    def _user_id(user: UUID | User) -> UUID:
        value = user if isinstance(user, UUID) else user.id
        return UUID(str(value))


notification_service = NotificationService()
