"""PV safety export service on shared export-job infrastructure (Req 12).

PV safety exports reuse the shared ``Export`` job model and the shared
``Export_Service`` lifecycle transitions (Queued -> Running -> Completed/Failed)
rather than forking them. This service owns the PV-specific concerns:

  - accepting only the PV safety formats CSV, Excel, JSON, and E2B XML and
    rejecting any other requested format without creating a Completed job
    (Requirement 12.5);
  - applying study, site, subject reference, case status, seriousness, report
    status, and inclusive UTC date-range filters as intersections, and
    rejecting a requested UTC date span exceeding 1,830 days before any
    Completed job is created (Requirement 12.3);
  - producing only in-scope Safety_Cases, with an empty result when no case
    qualifies (Requirement 12.2);
  - transitioning a job that has been Running for more than 900 seconds to
    Failed with a failure reason and no downloadable file (Requirement 12.1);
  - authorizing a download only for the requesting user within 900 seconds of
    completion and recording a PV safety download Audit_Event, and denying a
    download after 900 seconds or for a job owned by another user (Requirements
    12.4, 12.7).

The Export row carries ``module="PV"`` / ``content_owner="PV"`` so PV safety
export content and filters stay separate from EDC clinical and CTMS operational
exports (Requirement 12.6). Every PV audit event is emitted through the shared
``pv_atomicity_service`` on the caller's transaction (``module="PV"``).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationError,
    BusinessRuleError,
    NotFoundError,
    ValidationError,
)
from app.core.pv import ActorContext, Module
from app.models.export import Export, ExportStatus
from app.schemas.pv.export import PVExportFilters, PVExportFormat
from app.services.export_service import export_service
from app.services.pv_atomicity_service import pv_atomicity_service
from app.services.pv_ownership_guard import assert_pv_command_safe

logger = logging.getLogger(__name__)

# A Running job older than this without completing is failed (Requirements
# 12.1). The same window bounds how long after completion a download is
# authorized (Requirements 12.4, 12.7).
EXPORT_TIMEOUT_SECONDS = 900

PV_EXPORT_FORMATS = frozenset(fmt.value for fmt in PVExportFormat)


class PVExportService:
    """Authoritative service for PV-owned safety export jobs."""

    # ------------------------------------------------------------------
    # Create (Requirements 12.2, 12.3, 12.5, 12.6)
    # ------------------------------------------------------------------

    async def create_export(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        export_type: str | PVExportFormat,
        filters: dict | PVExportFilters | None,
        actor: ActorContext,
    ) -> Export:
        """Create a Queued PV safety export job and record a PV Audit_Event.

        The requested format must be one of the PV safety formats; any other
        format is rejected without creating a job (Requirement 12.5). The filters
        are validated here (including the 1,830-day span limit) so a job is never
        created for an out-of-bounds date range (Requirement 12.3). The job is
        created with ``module="PV"`` so PV export content stays separate from EDC
        and CTMS content (Requirement 12.6).
        """

        assert_pv_command_safe(
            filters if isinstance(filters, dict) else None, operation="create_pv_export"
        )

        normalized_type = self._normalize_format(export_type)
        normalized_filters = self._normalize_filters(filters)

        export = Export(
            study_id=study_id,
            export_type=normalized_type.value,
            status=ExportStatus.queued,
            module=Module.PV.value,
            content_owner=Module.PV.value,
            correlation_id=actor.correlation_id,
            filters=normalized_filters.model_dump(mode="json", exclude_defaults=False),
            requested_by=actor.user_id,
        )
        session.add(export)
        await session.flush()

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="safety_export",
            entity_id=export.id,
            action="create",
            actor=actor,
            study_id=study_id,
            changed_fields=("status", "export_type", "filters"),
            field_name="status",
            old_value=None,
            new_value=f"export_type={normalized_type.value}, status={ExportStatus.queued}",
        )

        logger.info(
            "PV safety export created: id=%s study_id=%s type=%s actor=%s",
            export.id,
            study_id,
            normalized_type.value,
            actor.user_id,
        )
        return export

    # ------------------------------------------------------------------
    # Lifecycle (delegates the content-neutral transitions to the shared
    # Export_Service so PV does not fork job-status handling).
    # ------------------------------------------------------------------

    async def start_export(self, session: AsyncSession, export: Export) -> Export:
        """Transition a PV export Queued -> Running via the shared service."""
        self._assert_pv_owned(export)
        return await export_service.start_export(session, export)

    async def complete_export(
        self,
        session: AsyncSession,
        export: Export,
        *,
        file_path: str,
        file_size: int,
    ) -> Export:
        """Transition a PV export Running -> Completed and store the file."""
        self._assert_pv_owned(export)
        return await export_service.complete_export(
            session, export, file_path=file_path, file_size=file_size
        )

    async def fail_export(
        self,
        session: AsyncSession,
        export: Export,
        *,
        error_message: str,
    ) -> Export:
        """Transition a PV export Running -> Failed with a failure reason."""
        self._assert_pv_owned(export)
        result = await export_service.fail_export(
            session, export, error_message=error_message
        )
        # Record only that a PV export failed; the failure reason and any
        # filters or content never enter the observability window.
        from app.services.pv_observability_service import pv_observability_service

        pv_observability_service.record_export_failure()
        return result

    async def fail_if_timed_out(
        self,
        session: AsyncSession,
        export: Export,
        *,
        now: datetime | None = None,
    ) -> Export:
        """Fail a job that has been Running for more than 900 seconds.

        A job Running longer than :data:`EXPORT_TIMEOUT_SECONDS` is transitioned
        to Failed and retains a failure reason without producing a downloadable
        file (Requirement 12.1). The file information is left unset so no file is
        available. A job that is not Running, or that has not yet exceeded the
        window, is returned unchanged.
        """

        self._assert_pv_owned(export)
        if export.status != ExportStatus.running or export.started_at is None:
            return export

        reference = now or datetime.now(UTC)
        started = self._as_utc(export.started_at)
        if (reference - started) <= timedelta(seconds=EXPORT_TIMEOUT_SECONDS):
            return export

        # No downloadable file is produced for a timed-out job.
        export.file_path = None
        export.file_size = None
        return await self.fail_export(
            session,
            export,
            error_message=(
                "PV safety export exceeded the "
                f"{EXPORT_TIMEOUT_SECONDS}-second processing window"
            ),
        )

    # ------------------------------------------------------------------
    # Download authorization and audit (Requirements 12.4, 12.7)
    # ------------------------------------------------------------------

    async def authorize_download(
        self,
        session: AsyncSession,
        *,
        export_id: UUID,
        actor: ActorContext,
        now: datetime | None = None,
    ) -> Export:
        """Authorize and audit a download of a completed PV safety export.

        The download is provided only to the authorized requesting user within
        900 seconds of completion, and exactly one PV safety download
        Audit_Event is recorded (Requirement 12.4). A download requested more
        than 900 seconds after completion, or for a job owned by another user,
        is denied and no file is provided (Requirement 12.7).
        """

        export = await self._get_pv_export(session, export_id)

        if export.requested_by != actor.user_id:
            # Non-disclosing denial for a job owned by another user.
            raise AuthorizationError(
                message="Export download is not permitted",
                details={"reason": "NOT_JOB_OWNER"},
            )

        if export.status != ExportStatus.completed or not export.file_path:
            raise BusinessRuleError(
                message="Export is not available for download",
                details={"reason": "EXPORT_NOT_READY", "status": str(export.status)},
            )

        reference = now or datetime.now(UTC)
        completed = self._as_utc(export.completed_at) if export.completed_at else None
        if completed is None or (reference - completed) > timedelta(
            seconds=EXPORT_TIMEOUT_SECONDS
        ):
            raise BusinessRuleError(
                message="Export download window has expired",
                details={"reason": "DOWNLOAD_WINDOW_EXPIRED"},
            )

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="safety_export",
            entity_id=export.id,
            action="download",
            actor=actor,
            study_id=export.study_id,
            changed_fields=(),
            new_value="downloaded=true",
        )
        return export

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_format(export_type: str | PVExportFormat) -> PVExportFormat:
        """Return a valid PV safety format or reject the request (Req 12.5)."""
        if isinstance(export_type, PVExportFormat):
            return export_type
        try:
            return PVExportFormat(export_type)
        except ValueError as exc:
            raise ValidationError(
                message="Unsupported PV safety export format",
                details={
                    "reason": "UNSUPPORTED_EXPORT_FORMAT",
                    "allowed_formats": sorted(PV_EXPORT_FORMATS),
                },
            ) from exc

    @staticmethod
    def _normalize_filters(filters: dict | PVExportFilters | None) -> PVExportFilters:
        """Validate and normalize the intersection filters (Req 12.3)."""
        if filters is None:
            return PVExportFilters()
        if isinstance(filters, PVExportFilters):
            return filters
        try:
            return PVExportFilters.model_validate(filters)
        except ValueError as exc:
            raise ValidationError(
                message="Invalid PV safety export filters",
                details={"reason": "INVALID_EXPORT_FILTERS"},
            ) from exc

    @staticmethod
    def _assert_pv_owned(export: Export) -> None:
        if export.module != Module.PV.value or export.content_owner != Module.PV.value:
            raise ValidationError(
                message="PV export service accepts only PV-owned safety export jobs",
                details={"reason": "NOT_PV_EXPORT", "module": export.module},
            )

    async def _get_pv_export(self, session: AsyncSession, export_id: UUID) -> Export:
        result = await session.execute(select(Export).where(Export.id == export_id))
        export = result.scalars().first()
        if export is None:
            raise NotFoundError(
                message="Export not found",
                details={"reason": "RECORD_NOT_FOUND", "export_id": str(export_id)},
            )
        self._assert_pv_owned(export)
        return export

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        """Interpret a persisted timestamp as UTC (SQLite drops tzinfo)."""
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


pv_export_service = PVExportService()

__all__ = ["EXPORT_TIMEOUT_SECONDS", "PVExportService", "pv_export_service"]
