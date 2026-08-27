"""CSV export worker — background job that generates export files.

Applies filters (study/site/subject/visit/form/domain/date range/changed-since/
locked-only/clean-only), generates CSV, stores it, and audits downloads.

For Phase 1, runs synchronously (invoked in-process). Redis-backed async
job queuing is optional (Phase 2).

Satisfies Requirements:
  - 19.1: Export job lifecycle (Queued → Running → Completed/Failed).
  - 19.3: Filter support (study, site, subject, visit, form, domain, date range,
           changed_since, locked_only, clean_only).
  - 19.4: Audit download events.
  - 19.5: CSV export format.
  - 29.3: Background worker infrastructure.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_service
from app.core.config import get_settings
from app.models.export import Export, ExportType
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.query import Query, QueryStatus
from app.models.subject import Subject
from app.services.export_service import export_service

logger = logging.getLogger(__name__)

# Default export storage directory (local filesystem)
DEFAULT_EXPORT_DIR = "exports"


def _get_export_dir() -> Path:
    """Resolve the export storage directory from settings or default."""
    settings = get_settings()
    # If S3 is configured, we'd upload there — for Phase 1, use local filesystem
    if settings.s3_bucket_name:
        # S3 upload path would be handled here in Phase 2
        pass
    export_dir = Path(DEFAULT_EXPORT_DIR)
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


async def run_csv_export(session: AsyncSession, export: Export) -> None:
    """Execute the CSV export job: apply filters, generate CSV, store file.

    This is the main worker function that processes a queued CSV export job.
    It transitions the export through Running → Completed (or Failed on error).

    Args:
        session: Active async database session.
        export: The Export instance to process (should be in Queued status).
    """
    try:
        # Transition to Running
        await export_service.start_export(session, export)
        await session.flush()

        # Parse filters from the export record
        filters = export.filters or {}
        study_id = export.study_id

        # Build the query for form instances + field values
        stmt = (
            select(FieldValue)
            .join(FormInstance, FieldValue.form_instance_id == FormInstance.id)
            .join(Subject, FormInstance.subject_id == Subject.id)
            .join(FieldDefinition, FieldValue.field_definition_id == FieldDefinition.id)
            .join(FormSection, FieldDefinition.form_section_id == FormSection.id)
            .join(FormDefinition, FormSection.form_definition_id == FormDefinition.id)
            .where(Subject.study_id == study_id)
        )

        # Eagerly load relationships needed for CSV columns
        stmt = stmt.options(
            selectinload(FieldValue.form_instance).selectinload(FormInstance.subject).selectinload(Subject.site),
            selectinload(FieldValue.form_instance).selectinload(FormInstance.visit_instance),
            selectinload(FieldValue.form_instance).selectinload(FormInstance.form_definition),
            selectinload(FieldValue.field_definition),
        )

        # Apply filters
        conditions = []

        # site_id filter
        if filters.get("site_id"):
            conditions.append(Subject.site_id == uuid.UUID(filters["site_id"]))

        # subject_id filter
        if filters.get("subject_id"):
            conditions.append(FormInstance.subject_id == uuid.UUID(filters["subject_id"]))

        # visit_instance_id filter
        if filters.get("visit_instance_id"):
            conditions.append(
                FormInstance.visit_instance_id == uuid.UUID(filters["visit_instance_id"])
            )

        # form_definition_id filter
        if filters.get("form_definition_id"):
            conditions.append(
                FormInstance.form_definition_id == uuid.UUID(filters["form_definition_id"])
            )

        # domain filter (form_code on FormDefinition)
        if filters.get("domain"):
            conditions.append(FormDefinition.form_code == filters["domain"])

        # date range filter (form_instance created_at between date_from and date_to)
        if filters.get("date_from"):
            date_from = datetime.fromisoformat(filters["date_from"])
            conditions.append(FormInstance.created_at >= date_from)

        if filters.get("date_to"):
            date_to = datetime.fromisoformat(filters["date_to"])
            conditions.append(FormInstance.created_at <= date_to)

        # changed_since filter (updated_at >= changed_since)
        if filters.get("changed_since"):
            changed_since = datetime.fromisoformat(filters["changed_since"])
            conditions.append(FormInstance.updated_at >= changed_since)

        # locked_only filter (status == Locked)
        if filters.get("locked_only"):
            conditions.append(FormInstance.status == FormInstanceStatus.locked)

        # clean_only filter (status == Submitted and no open queries)
        if filters.get("clean_only"):
            # Subquery: form_instance IDs that have unresolved queries
            open_query_form_ids = (
                select(Query.target_id).where(
                    Query.target_type == "Form_Instance",
                    Query.status.in_([
                        QueryStatus.open,
                        QueryStatus.answered,
                        QueryStatus.reopened,
                    ]),
                )
            )
            conditions.append(FormInstance.status == FormInstanceStatus.submitted)
            conditions.append(FormInstance.id.notin_(open_query_form_ids))

        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Execute query
        result = await session.execute(stmt)
        field_values = result.scalars().all()

        # Generate CSV content
        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        writer.writerow([
            "subject_number",
            "site_number",
            "visit_name",
            "form_name",
            "field_variable_name",
            "value",
        ])

        # Data rows
        for fv in field_values:
            form_instance = fv.form_instance
            subject = form_instance.subject if form_instance else None
            site = subject.site if subject else None
            visit_instance = form_instance.visit_instance if form_instance else None
            form_definition = form_instance.form_definition if form_instance else None
            field_definition = fv.field_definition

            writer.writerow([
                subject.subject_number if subject else "",
                site.site_number if site else "",
                visit_instance.name if visit_instance else "",
                form_definition.name if form_definition else "",
                field_definition.variable_name if field_definition else "",
                fv.value if fv.value is not None else "",
            ])

        csv_content = output.getvalue()
        output.close()

        # Write file to storage
        export_dir = _get_export_dir()
        filename = f"export_{export.id}_{export.study_id}.csv"
        file_path = export_dir / filename

        file_path.write_text(csv_content, encoding="utf-8")
        file_size = file_path.stat().st_size

        # Complete the export
        await export_service.complete_export(
            session,
            export,
            file_path=str(file_path),
            file_size=file_size,
        )

        # Audit the export completion
        await audit_service.record(
            session,
            entity_type="export",
            entity_id=export.id,
            action="export_completed",
            study_id=export.study_id,
            actor_id=export.requested_by,
            new_value=f"file_path={file_path}, file_size={file_size}, rows={len(field_values)}",
        )

        logger.info(
            "CSV export completed: export_id=%s rows=%d file_size=%d",
            export.id,
            len(field_values),
            file_size,
        )

    except Exception as e:
        logger.exception("CSV export failed: export_id=%s error=%s", export.id, str(e))
        try:
            await export_service.fail_export(
                session,
                export,
                error_message=str(e),
            )
        except Exception:
            # If we can't even mark it as failed, log and re-raise original
            logger.exception(
                "Failed to mark export as failed: export_id=%s", export.id
            )
        raise


async def run_subject_list_export(session: AsyncSession, export: Export) -> None:
    """Execute the subject list export job: query subjects, generate CSV.

    Produces a CSV with columns: subject_number, site_number, status, created_at.

    Args:
        session: Active async database session.
        export: The Export instance to process (should be in Queued status).
    """
    try:
        # Transition to Running
        await export_service.start_export(session, export)
        await session.flush()

        # Parse filters
        filters = export.filters or {}
        study_id = export.study_id

        # Build query for subjects
        stmt = (
            select(Subject)
            .where(Subject.study_id == study_id)
            .where(Subject.deleted_at.is_(None))  # Exclude soft-deleted
            .options(selectinload(Subject.site))
        )

        # Apply filters
        conditions = []

        # site_id filter
        if filters.get("site_id"):
            conditions.append(Subject.site_id == uuid.UUID(filters["site_id"]))

        # subject_id filter (specific subject)
        if filters.get("subject_id"):
            conditions.append(Subject.id == uuid.UUID(filters["subject_id"]))

        # date range filter (subject created_at)
        if filters.get("date_from"):
            date_from = datetime.fromisoformat(filters["date_from"])
            conditions.append(Subject.created_at >= date_from)

        if filters.get("date_to"):
            date_to = datetime.fromisoformat(filters["date_to"])
            conditions.append(Subject.created_at <= date_to)

        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Order by subject number for consistent output
        stmt = stmt.order_by(Subject.subject_number)

        # Execute
        result = await session.execute(stmt)
        subjects = result.scalars().all()

        # Generate CSV content
        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        writer.writerow([
            "subject_number",
            "site_number",
            "status",
            "created_at",
        ])

        # Data rows
        for subject in subjects:
            site = subject.site
            writer.writerow([
                subject.subject_number,
                site.site_number if site else "",
                subject.status,
                subject.created_at.isoformat() if subject.created_at else "",
            ])

        csv_content = output.getvalue()
        output.close()

        # Write file to storage
        export_dir = _get_export_dir()
        filename = f"subject_list_{export.id}_{export.study_id}.csv"
        file_path = export_dir / filename

        file_path.write_text(csv_content, encoding="utf-8")
        file_size = file_path.stat().st_size

        # Complete the export
        await export_service.complete_export(
            session,
            export,
            file_path=str(file_path),
            file_size=file_size,
        )

        # Audit the export completion
        await audit_service.record(
            session,
            entity_type="export",
            entity_id=export.id,
            action="export_completed",
            study_id=export.study_id,
            actor_id=export.requested_by,
            new_value=f"file_path={file_path}, file_size={file_size}, subjects={len(subjects)}",
        )

        logger.info(
            "Subject list export completed: export_id=%s subjects=%d file_size=%d",
            export.id,
            len(subjects),
            file_size,
        )

    except Exception as e:
        logger.exception(
            "Subject list export failed: export_id=%s error=%s", export.id, str(e)
        )
        try:
            await export_service.fail_export(
                session,
                export,
                error_message=str(e),
            )
        except Exception:
            logger.exception(
                "Failed to mark export as failed: export_id=%s", export.id
            )
        raise


async def run_export(session: AsyncSession, export: Export) -> None:
    """Dispatch an export job to the appropriate worker based on export_type.

    This is the main entry point for processing export jobs.

    Args:
        session: Active async database session.
        export: The Export instance to process.
    """
    if export.export_type == ExportType.subject_list:
        await run_subject_list_export(session, export)
    else:
        # Default to CSV export
        await run_csv_export(session, export)
