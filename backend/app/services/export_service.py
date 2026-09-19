"""Export_Service — export job lifecycle management.

Manages export job creation, status transitions (Queued → Running →
Completed/Failed), and listing with pagination. The actual file generation
is delegated to a background worker; this service owns the job metadata
and audit trail.

Satisfies Requirements:
  - 19.1: Export job creation and status tracking (Queued → Running → Completed/Failed).
  - 19.2: Subject list export support.
  - 19.3: Filter parsing (site, subject, visit, form, domain, date_range,
           changed_since, locked_only, clean_only).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.api.pagination import paginate
from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.models.export import Export, ExportStatus, ExportType
from app.schemas.base import PaginatedResponse
from app.schemas.ctms.export import OperationalExportFilters, OperationalExportFormat

CTMS_EXPORT_FORMATS = frozenset(OperationalExportFormat)

logger = logging.getLogger(__name__)


class ExportService:
    """Manages export job creation, lifecycle transitions, and retrieval."""

    # ------------------------------------------------------------------
    # Create (Req 19.1, 19.2, 19.3)
    # ------------------------------------------------------------------

    async def create_export(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        export_type: str = ExportType.csv,
        filters: dict | None = None,
        actor_id: UUID,
        module: Module | str = Module.EDC,
        content_owner: Module | str | None = None,
        correlation_id: str | None = None,
    ) -> Export:
        """Create an export job with status Queued and record an Audit_Event.

        Args:
            session: Active async database session (caller's transaction).
            study_id: UUID of the study to export data from.
            export_type: Export format (csv, subject_list).
            filters: Optional filter parameters dict (site, subject, visit,
                     form, domain, date_range, changed_since, locked_only,
                     clean_only).
            actor_id: UUID of the user requesting the export.

        Returns:
            The created Export instance with status Queued.
        """
        resolved_module = module.value if isinstance(module, Module) else str(module)
        resolved_owner = (
            content_owner.value
            if isinstance(content_owner, Module)
            else str(content_owner) if content_owner is not None else resolved_module
        )
        if resolved_module != resolved_owner:
            raise ValidationError(
                message="Export module and content owner must match",
                details={"module": resolved_module, "content_owner": resolved_owner},
            )

        export = Export(
            study_id=study_id,
            export_type=export_type,
            status=ExportStatus.queued,
            module=resolved_module,
            content_owner=resolved_owner,
            correlation_id=correlation_id,
            filters=filters,
            requested_by=actor_id,
        )
        session.add(export)
        await session.flush()

        # Write Audit_Event (Req 19.1 — creation tracked)
        await audit_service.record(
            session,
            entity_type="export",
            entity_id=export.id,
            action="create",
            module=module,
            correlation_id=correlation_id,
            scope={"study_id": study_id},
            changed_fields=["status", "export_type", "filters"],
            study_id=study_id,
            actor_id=actor_id,
            new_value=f"export_type={export_type}, status=Queued",
        )

        logger.info(
            "Export created: id=%s study_id=%s type=%s actor=%s",
            export.id,
            study_id,
            export_type,
            actor_id,
        )
        return export

    # ------------------------------------------------------------------
    # Start (Queued → Running)
    # ------------------------------------------------------------------

    async def start_export(
        self,
        session: AsyncSession,
        export: Export,
    ) -> Export:
        """Transition an export job from Queued to Running.

        Sets started_at timestamp.

        Args:
            session: Active async database session.
            export: The Export instance to start.

        Returns:
            The updated Export instance with status Running.

        Raises:
            BusinessRuleError: If the export is not in Queued status.
        """
        if export.status != ExportStatus.queued:
            raise BusinessRuleError(
                message=f"Cannot start an export in status '{export.status}'",
                details={
                    "export_id": str(export.id),
                    "current_status": export.status,
                    "required_status": ExportStatus.queued,
                },
            )

        export.status = ExportStatus.running
        export.started_at = datetime.now(UTC)
        await session.flush()

        logger.info(
            "Export started: id=%s Queued -> Running",
            export.id,
        )
        return export

    # ------------------------------------------------------------------
    # Complete (Running → Completed)
    # ------------------------------------------------------------------

    async def complete_export(
        self,
        session: AsyncSession,
        export: Export,
        *,
        file_path: str,
        file_size: int,
    ) -> Export:
        """Transition an export job from Running to Completed.

        Sets file_path, file_size, and completed_at timestamp.

        Args:
            session: Active async database session.
            export: The Export instance to complete.
            file_path: Path/key to the generated file.
            file_size: Size of the generated file in bytes.

        Returns:
            The updated Export instance with status Completed.

        Raises:
            BusinessRuleError: If the export is not in Running status.
        """
        if export.status != ExportStatus.running:
            raise BusinessRuleError(
                message=f"Cannot complete an export in status '{export.status}'",
                details={
                    "export_id": str(export.id),
                    "current_status": export.status,
                    "required_status": ExportStatus.running,
                },
            )

        export.status = ExportStatus.completed
        export.file_path = file_path
        export.file_size = file_size
        export.completed_at = datetime.now(UTC)
        await session.flush()

        logger.info(
            "Export completed: id=%s file_path=%s file_size=%d",
            export.id,
            file_path,
            file_size,
        )
        return export

    # ------------------------------------------------------------------
    # Fail (Running → Failed)
    # ------------------------------------------------------------------

    async def fail_export(
        self,
        session: AsyncSession,
        export: Export,
        *,
        error_message: str,
    ) -> Export:
        """Transition an export job from Running to Failed.

        Sets error_message.

        Args:
            session: Active async database session.
            export: The Export instance that failed.
            error_message: Description of the failure.

        Returns:
            The updated Export instance with status Failed.

        Raises:
            BusinessRuleError: If the export is not in Running status.
        """
        if export.status != ExportStatus.running:
            raise BusinessRuleError(
                message=f"Cannot fail an export in status '{export.status}'",
                details={
                    "export_id": str(export.id),
                    "current_status": export.status,
                    "required_status": ExportStatus.running,
                },
            )

        export.status = ExportStatus.failed
        export.error_message = error_message
        export.completed_at = datetime.now(UTC)
        await session.flush()

        logger.warning(
            "Export failed: id=%s error=%s",
            export.id,
            error_message,
        )
        return export

    # ------------------------------------------------------------------
    # Get by ID
    # ------------------------------------------------------------------

    async def get_export(
        self,
        session: AsyncSession,
        export_id: UUID,
    ) -> Export:
        """Retrieve an export job by its primary key.

        Args:
            session: Active async database session.
            export_id: The UUID of the export job.

        Returns:
            The Export instance.

        Raises:
            NotFoundError: If no export exists with the given ID.
        """
        result = await session.execute(
            select(Export).where(Export.id == export_id)
        )
        export = result.scalars().first()
        if export is None:
            raise NotFoundError(
                message="Export not found",
                details={"export_id": str(export_id)},
            )
        return export

    # ------------------------------------------------------------------
    # List (with pagination)
    # ------------------------------------------------------------------

    async def list_exports(
        self,
        session: AsyncSession,
        study_id: UUID,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse:
        """List export jobs for a study with pagination.

        Args:
            session: Active async database session.
            study_id: UUID of the parent study.
            pagination: Page/page_size pagination parameters.

        Returns:
            PaginatedResponse containing Export instances.
        """
        stmt = (
            select(Export)
            .where(Export.study_id == study_id)
            .order_by(Export.created_at.desc())
        )

        if pagination is None:
            pagination = PaginationParams(page=1, page_size=25)

        return await paginate(session, stmt, pagination)

    async def create_ctms_export(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        export_type: str,
        filters: dict | OperationalExportFilters | None,
        actor_id: UUID,
        correlation_id: str | None = None,
    ) -> Export:
        """Create a validated CTMS-owned operational job on shared infrastructure.

        CTMS formats and filters are deliberately validated here as well as at
        the HTTP boundary because workers and internal callers can submit jobs
        without going through FastAPI.
        """
        try:
            normalized_type = OperationalExportFormat(export_type)
        except ValueError as exc:
            raise ValidationError(
                message="Unsupported CTMS operational export format",
                details={"allowed_formats": sorted(value.value for value in CTMS_EXPORT_FORMATS)},
            ) from exc

        if filters is None:
            normalized_filters = OperationalExportFilters()
        elif isinstance(filters, OperationalExportFilters):
            normalized_filters = filters
        else:
            try:
                normalized_filters = OperationalExportFilters.model_validate(filters)
            except ValueError as exc:
                raise ValidationError(
                    message="Invalid CTMS operational export filters",
                    details={"reason": "filters must match the operational export contract"},
                ) from exc

        return await self.create_export(
            session,
            study_id=study_id,
            export_type=normalized_type.value,
            filters=normalized_filters.model_dump(mode="json", exclude_defaults=False),
            actor_id=actor_id,
            module=Module.CTMS,
            content_owner=Module.CTMS,
            correlation_id=correlation_id,
        )

    async def record_download(
        self,
        session: AsyncSession,
        export: Export,
        *,
        actor_id: UUID,
        correlation_id: str | None = None,
    ) -> Export:
        """Audit an authenticated download without exposing content semantics."""
        if export.status != ExportStatus.completed or not export.file_path:
            raise BusinessRuleError(
                message="Export is not ready for download",
                details={"export_id": str(export.id), "status": str(export.status)},
            )
        await audit_service.record(
            session,
            entity_type="export",
            entity_id=export.id,
            action="download",
            module=export.module,
            actor_id=actor_id,
            correlation_id=correlation_id or export.correlation_id,
            scope={"study_id": export.study_id},
            changed_fields=[],
            study_id=export.study_id,
            new_value="downloaded=true",
        )
        return export

    # ------------------------------------------------------------------

    async def subject_list_export(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        filters: dict | None = None,
        actor_id: UUID,
    ) -> Export:
        """Create a subject list export job.

        Convenience wrapper around create_export with export_type=subject_list.

        Args:
            session: Active async database session.
            study_id: UUID of the study.
            filters: Optional filter parameters.
            actor_id: UUID of the requesting user.

        Returns:
            The created Export instance with type subject_list.
        """
        return await self.create_export(
            session,
            study_id=study_id,
            export_type=ExportType.subject_list,
            filters=filters,
            actor_id=actor_id,
        )


# Module-level singleton for convenience
export_service = ExportService()
