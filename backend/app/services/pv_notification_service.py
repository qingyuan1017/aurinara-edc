"""PV safety notification triggers on shared Notification_Service primitives.

The ``Notification_Service`` remains shared platform infrastructure that owns
notification persistence, the Unread/Read/Archived delivery state machine, and
ownership-scoped listing. PV owns only the *triggers* fired by PV safety
workflow and the PV recipient-resolution rule (Requirement 14.6). This service
is the PV-owned facade over those triggers; it reuses:

  * :class:`PVSharedIntegrationService` for PV-tagged notification creation and
    Unread listing (shared ``notifications`` table, ``module="PV"``);
  * :class:`NotificationService` for the shared Unread->Read/Archived and
    Read->Archived transition state machine (Requirement 14.4);
  * :mod:`pv_atomicity_service` to record the "no recipient resolved" PV safety
    Audit_Event (Requirement 14.8).

PV never forks notification persistence or delivery state. Every notification
created here carries ``module="PV"`` so PV safety triggers stay distinct from
EDC clinical and CTMS operational notifications.

Triggers implemented (Requirement 14):

  * 14.1/14.8 serious-case creation: one notification per resolved assigned
    safety recipient, or a single PV safety Audit_Event when none resolves;
  * 14.2/14.7 Regulatory_Clock warning window (1-30 days, report not Submitted):
    one notification identifying the report and its due date, deduped so no
    additional notification is created for the same report and due date while an
    unarchived one exists;
  * 14.3 export outcome: one notification for the requesting user when a safety
    export job reaches Completed or Failed, identifying the outcome.

All methods act on the caller-provided ``AsyncSession`` and never commit; the
request or worker unit of work owns the transaction boundary, so a created
notification (or the no-recipient Audit_Event) commits or rolls back with the
PV safety mutation that triggered it (satisfying the "within 60 seconds"
timing since the notification is persisted synchronously in the same request).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pv import ActorContext, Module
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    ScopeLevel,
    User,
    UserRole,
    UserStatus,
)
from app.models.notification import Notification, NotificationStatus
from app.services.notification_service import notification_service
from app.services.pv_atomicity_service import pv_atomicity_service
from app.services.pv_shared_integration import pv_shared_integration_service

logger = logging.getLogger(__name__)

# Notification type identifiers for the three PV safety triggers.
NOTIFICATION_TYPE_SERIOUS_CASE = "pv_serious_case_created"
NOTIFICATION_TYPE_CLOCK_WARNING = "pv_regulatory_clock_warning"
NOTIFICATION_TYPE_EXPORT_OUTCOME = "pv_export_outcome"

# The PV safety permission a user must hold (in the case's scope) to be a
# resolved assigned safety recipient for a serious case (Requirement 14.1).
# Read access is the minimal capability every safety worker who should act on a
# serious case holds; every PV safety role in ``core.permissions`` includes it.
DEFAULT_SERIOUS_CASE_PERMISSION = "safety_case.read"

# The configured Regulatory_Clock warning window bounds (Requirement 14.2).
WARNING_WINDOW_MIN_DAYS = 1
WARNING_WINDOW_MAX_DAYS = 30

# A Regulatory_Report is not eligible for a warning notification once Submitted
# (Requirement 14.2). "Submitted" is the only status that suppresses the
# warning; Acknowledged/Cancelled reports have already left the Pending state
# through Submitted, so a report reaching this trigger while not Submitted is
# still awaiting submission.
_SUBMITTED_STATUS = "Submitted"

# Notification statuses that count as "unarchived" for dedupe (Requirement
# 14.7): an Archived notification no longer suppresses a new warning.
_UNARCHIVED_STATUSES = (NotificationStatus.unread, NotificationStatus.read)


class PVNotificationService:
    """PV-owned safety notification triggers over shared primitives."""

    def __init__(
        self,
        *,
        integration=pv_shared_integration_service,
        transitions=notification_service,
        atomicity=pv_atomicity_service,
    ) -> None:
        self._integration = integration
        self._transitions = transitions
        self._atomicity = atomicity

    # ------------------------------------------------------------------
    # Trigger: serious-case creation (Requirements 14.1, 14.8)
    # ------------------------------------------------------------------

    async def on_serious_case_created(
        self,
        session: AsyncSession,
        *,
        case_id: UUID,
        study_id: UUID,
        site_id: UUID | None,
        actor: ActorContext,
        recipient_permission: str = DEFAULT_SERIOUS_CASE_PERMISSION,
    ) -> list[Notification]:
        """Create one notification per resolved assigned safety recipient.

        When a Safety_Case meeting a serious seriousness criterion is created,
        one PV safety notification is created for each resolved assigned safety
        recipient (a user holding ``recipient_permission`` within the case's
        study/site scope) (Requirement 14.1).

        When no assigned safety recipient resolves, no per-recipient
        notification is created and exactly one PV safety Audit_Event is recorded
        indicating that no recipient was resolved (Requirement 14.8). Both the
        notifications and the no-recipient Audit_Event are staged on the caller's
        transaction so they commit with the triggering case creation.
        """

        recipient_ids = await self._resolve_serious_case_recipients(
            session,
            study_id=study_id,
            site_id=site_id,
            permission_code=recipient_permission,
        )

        if not recipient_ids:
            # No recipient resolved: create no notification and record one PV
            # safety Audit_Event indicating the empty resolution (Req 14.8).
            await self._atomicity.record_mutation(
                session,
                entity_type="safety_notification",
                entity_id=case_id,
                action="no_recipient_resolved",
                actor=actor,
                study_id=study_id,
                site_id=site_id,
                changed_fields=(),
                field_name="recipient_resolution",
                old_value=None,
                new_value="no_recipient_resolved",
            )
            logger.info(
                "PV serious-case notification resolved no recipient: case_id=%s study_id=%s",
                case_id,
                study_id,
            )
            return []

        notifications = await self._integration.create_pv_notification(
            session,
            user_ids=recipient_ids,
            notification_type=NOTIFICATION_TYPE_SERIOUS_CASE,
            payload={
                "case_id": case_id,
                "study_id": study_id,
                "site_id": site_id,
            },
            study_id=study_id,
            site_id=site_id,
            correlation_id=actor.correlation_id,
        )
        logger.info(
            "PV serious-case notifications created: case_id=%s recipients=%d",
            case_id,
            len(notifications),
        )
        return notifications

    # ------------------------------------------------------------------
    # Trigger: Regulatory_Clock warning window (Requirements 14.2, 14.7)
    # ------------------------------------------------------------------

    async def on_regulatory_clock_warning(
        self,
        session: AsyncSession,
        *,
        report_id: UUID,
        report_status: str,
        due_date: date,
        recipient_ids: list[UUID],
        today_utc: date | None = None,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        correlation_id: str | None = None,
        warning_window_days: int = WARNING_WINDOW_MAX_DAYS,
    ) -> list[Notification]:
        """Create one warning notification when a clock enters the window.

        A notification is created only when the report is not Submitted and the
        Regulatory_Clock ``due_date`` is within the configured warning window of
        1 through 30 days of ``today_utc`` (inclusive of the due date itself and
        excluding past-due dates) (Requirement 14.2). The notification payload
        identifies the report and its due date.

        The trigger is idempotent for a given report and due date: if an
        unarchived (Unread or Read) PV safety warning notification already exists
        for the same report and due date, no additional notification is created
        (Requirement 14.7). An existing Archived notification does not suppress a
        new warning.

        Returns the newly created notifications (empty when the window condition
        is not met or an unarchived duplicate exists).
        """

        if not self._in_warning_window(
            report_status=report_status,
            due_date=due_date,
            today_utc=today_utc or datetime.now(UTC).date(),
            warning_window_days=warning_window_days,
        ):
            return []

        if await self._warning_notification_exists(
            session, report_id=report_id, due_date=due_date
        ):
            logger.info(
                "PV clock warning suppressed by existing unarchived notification: "
                "report_id=%s due_date=%s",
                report_id,
                due_date,
            )
            return []

        notifications = await self._integration.create_pv_notification(
            session,
            user_ids=recipient_ids,
            notification_type=NOTIFICATION_TYPE_CLOCK_WARNING,
            payload={
                "report_id": report_id,
                "due_date": due_date.isoformat(),
                "report_status": report_status,
            },
            study_id=study_id,
            site_id=site_id,
            correlation_id=correlation_id,
        )
        logger.info(
            "PV clock warning notifications created: report_id=%s due_date=%s recipients=%d",
            report_id,
            due_date,
            len(notifications),
        )
        return notifications

    # ------------------------------------------------------------------
    # Trigger: safety export outcome (Requirement 14.3)
    # ------------------------------------------------------------------

    async def on_export_outcome(
        self,
        session: AsyncSession,
        *,
        export_job_id: UUID,
        outcome: str,
        requesting_user_id: UUID,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> list[Notification]:
        """Notify the requesting user when a safety export completes or fails.

        When a PV safety export job reaches Completed or Failed, one PV safety
        notification is created for the requesting User identifying the job
        outcome (Requirement 14.3). Any other outcome is ignored so intermediate
        states (Queued/Running) do not notify.
        """

        normalized = str(outcome).strip().title()
        if normalized not in {"Completed", "Failed"}:
            return []

        notifications = await self._integration.create_pv_notification(
            session,
            user_ids=[requesting_user_id],
            notification_type=NOTIFICATION_TYPE_EXPORT_OUTCOME,
            payload={
                "export_job_id": export_job_id,
                "outcome": normalized,
            },
            study_id=study_id,
            site_id=site_id,
            correlation_id=correlation_id,
        )
        logger.info(
            "PV export-outcome notification created: export_job_id=%s outcome=%s",
            export_job_id,
            normalized,
        )
        return notifications

    # ------------------------------------------------------------------
    # Listing and status transitions (Requirements 14.4, 14.5)
    # ------------------------------------------------------------------

    async def list_unread(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
    ) -> list[Notification]:
        """Return only the requesting user's Unread PV safety notifications.

        Delegates to the PV-tagged Unread listing, which is always constrained
        to the requesting user and status Unread and returns an empty list when
        none qualify (Requirement 14.5).
        """

        return await self._integration.list_unread_pv_notifications(
            session, user_id=user_id
        )

    async def mark_read(
        self,
        session: AsyncSession,
        *,
        notification: Notification | UUID,
        user_id: UUID,
    ) -> Notification:
        """Transition an owned Unread PV notification to Read (Requirement 14.4)."""

        return await self._transitions.mark_read(session, notification, user_id)

    async def archive(
        self,
        session: AsyncSession,
        *,
        notification: Notification | UUID,
        user_id: UUID,
    ) -> Notification:
        """Transition an owned Unread/Read PV notification to Archived (Req 14.4)."""

        return await self._transitions.archive(session, notification, user_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _in_warning_window(
        *,
        report_status: str,
        due_date: date,
        today_utc: date,
        warning_window_days: int,
    ) -> bool:
        """Return whether the report is due within the configured window.

        The window is a whole number of days between 1 and 30 inclusive; any
        other configured value is clamped into range so a misconfiguration
        cannot silently disable or over-extend the warning. A report that is
        already Submitted, or a due date in the past, is outside the window.
        """

        if str(report_status).strip() == _SUBMITTED_STATUS:
            return False

        window = max(WARNING_WINDOW_MIN_DAYS, min(warning_window_days, WARNING_WINDOW_MAX_DAYS))
        days_remaining = (due_date - today_utc).days
        # Within the window: due today or later, and no more than `window` days
        # away. A past-due date (days_remaining < 0) is not a warning-window
        # event; it is handled by overdue reporting elsewhere.
        return 0 <= days_remaining <= window

    async def _warning_notification_exists(
        self,
        session: AsyncSession,
        *,
        report_id: UUID,
        due_date: date,
    ) -> bool:
        """Return whether an unarchived warning exists for this report/due date.

        Dedupe compares the PV-owned ``report_id`` and ``due_date`` recorded in
        the notification payload against unarchived (Unread/Read) PV warning
        notifications (Requirement 14.7).
        """

        result = await session.execute(
            select(Notification).where(
                Notification.module == Module.PV.value,
                Notification.type == NOTIFICATION_TYPE_CLOCK_WARNING,
                Notification.status.in_(list(_UNARCHIVED_STATUSES)),
            )
        )
        target_report = str(report_id)
        target_due = due_date.isoformat()
        for notification in result.scalars().all():
            payload = notification.payload_json or {}
            if (
                str(payload.get("report_id")) == target_report
                and str(payload.get("due_date")) == target_due
            ):
                return True
        return False

    @staticmethod
    async def _resolve_serious_case_recipients(
        session: AsyncSession,
        *,
        study_id: UUID,
        site_id: UUID | None,
        permission_code: str,
    ) -> list[UUID]:
        """Resolve active users holding a PV safety permission in the scope.

        A resolved assigned safety recipient is an active user whose role
        assignment grants ``permission_code`` and whose assignment scope covers
        the case (system, the case's study, or the case's exact study+site).
        This mirrors the shared recipient-resolution rule while keeping recipient
        resolution PV-owned (Requirement 14.1, 14.6). When no user qualifies the
        result is empty, which the caller treats per Requirement 14.8.
        """

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
        scopes = [system_scope, study_scope]
        if site_id is not None:
            scopes.append(
                and_(
                    Role.scope_level == ScopeLevel.site,
                    UserRole.study_id == study_id,
                    UserRole.site_id == site_id,
                )
            )

        result = await session.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .join(User, User.id == UserRole.user_id)
            .where(
                Permission.code == permission_code,
                User.status == UserStatus.active,
                or_(*scopes),
            )
            .distinct()
        )
        # Preserve deterministic ordering for stable notification creation.
        return list(dict.fromkeys(result.scalars().all()))


pv_notification_service = PVNotificationService()

__all__ = [
    "DEFAULT_SERIOUS_CASE_PERMISSION",
    "NOTIFICATION_TYPE_CLOCK_WARNING",
    "NOTIFICATION_TYPE_EXPORT_OUTCOME",
    "NOTIFICATION_TYPE_SERIOUS_CASE",
    "WARNING_WINDOW_MAX_DAYS",
    "WARNING_WINDOW_MIN_DAYS",
    "PVNotificationService",
    "pv_notification_service",
]
