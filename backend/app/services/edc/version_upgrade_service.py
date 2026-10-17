"""Version_Upgrade_Service — transactional rebind of Operational_Records (R8.3, R8.15).

CRF Version management (R8.2) exposes a **Version Upgrade** that moves a Subject
(or every subject of a Site) from its currently bound ``Design_Version`` to a
newer *published* ``Design_Version``. Upgrading rebinds the affected
Operational_Records to the newer ``design_version_id`` and records the upgrade
in the shared Audit_Service (R8.3).

Transactional guarantee (R8.15). The rebind is all-or-nothing: it runs inside a
SAVEPOINT (``session.begin_nested()``). If any step fails before every affected
record is rebound, the SAVEPOINT is rolled back so the affected records stay
bound to their prior ``Design_Version`` — no partial rebind is ever observable
(design Property 11). The failed attempt is then audited and an error is raised.

Audit durability on failure. The shared ``audit_service`` writes within the
caller's transaction (same session), which is correct for the success path: the
rebind and its audit event commit or roll back together. On the *failure* path
the data mutations must roll back but the failed-attempt audit must **not** be
lost. Because the route's ``get_db`` dependency rolls the whole session back
when an exception propagates, simply writing the failure audit on that session
and raising would discard it. So on failure this service: (1) rolls back the
rebind via the SAVEPOINT so the affected records return to their prior version,
(2) writes the failure audit on the caller's session, (3) **commits** the
caller's session — which now contains only the failure audit, since the rebind
was already reverted — and only then (4) raises the error. Committing from the
service keeps the failure audit durable on a single connection (so it also
holds under SQLite's single-writer model, not only Postgres) while the success
audit still follows the project's audit-in-same-transaction convention.

Design-version validation (R8.3) is delegated to the
``DesignConsumptionService`` so the target is required to be a published design
of the same study; a draft or missing target is rejected before any mutation.

Satisfies Requirements:
  - 8.3: Rebind affected Operational_Records to the newer Design_Version and
         record the upgrade in the Audit_Service.
  - 8.15: On failure, leave affected records on their prior Design_Version,
         audit the failed attempt, and return an error.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.models.designer.study_version import StudyVersion
from app.models.edc.form_data import FieldValue, FormInstance
from app.models.edc.form_record import FormRecord
from app.models.edc.lock import FreezeLock
from app.models.edc.query import Query
from app.models.edc.review import ReviewStatus
from app.models.edc.sdv import SDVStatus
from app.models.edc.signature import Signature
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitInstance
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)

logger = logging.getLogger(__name__)

# Polymorphic scope/object-type values that denote a per-subject operational
# object on the sdv_status / freezes_locks / signatures tables. The upgrade only
# rebinds rows whose scope resolves to the upgraded subject's own object graph.
_SDV_SUBJECT_SCOPES = ("subject",)
_SDV_FORM_SCOPES = ("form",)
_SDV_VISIT_SCOPES = ("visit",)
_SDV_FIELD_SCOPES = ("field",)


class VersionUpgradeService:
    """Rebinds a Subject's (or a Site's subjects') Operational_Records (R8.3)."""

    def __init__(self, *, design_service: DesignConsumptionService | None = None) -> None:
        self._design = design_service or design_consumption_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upgrade_subject(
        self,
        session: AsyncSession,
        *,
        subject_id: UUID,
        target_design_version_id: UUID,
        actor_id: UUID,
    ) -> dict:
        """Upgrade one Subject to a newer published Design_Version (R8.3, R8.15).

        Args:
            session: The active async session (caller's transaction). The rebind
                runs in a SAVEPOINT inside this transaction so a failure leaves
                the subject's records on their prior version (R8.15).
            subject_id: The Subject to rebind.
            target_design_version_id: The published Design_Version to rebind to.
            actor_id: The acting user.

        Returns:
            A result dict (see ``VersionUpgradeResult``) describing the rebind.

        Raises:
            NotFoundError: The subject does not exist (or is soft-deleted).
            ValidationError: The target version is draft/missing, or belongs to a
                different study, or equals the subject's current version.
            BusinessRuleError: The rebind failed; records are left on the prior
                version and the failed attempt is audited (R8.15).
        """
        subject = await self._get_subject(session, subject_id)
        prior_version_id = subject.study_version_id

        target = await self._validate_target(
            session,
            target_design_version_id=target_design_version_id,
            study_id=subject.study_id,
        )

        if prior_version_id == target.id:
            raise ValidationError(
                "Subject is already bound to the target design version",
                details={
                    "subject_id": str(subject_id),
                    "target_design_version_id": str(target.id),
                },
            )

        try:
            counts = await self._rebind_subject_in_savepoint(
                session, subject=subject, target_version_id=target.id
            )
        except Exception as exc:
            await self._audit_failure(
                session,
                scope_type="subject",
                scope_id=subject_id,
                study_id=subject.study_id,
                site_id=subject.site_id,
                subject_id=subject_id,
                from_version_id=prior_version_id,
                to_version_id=target.id,
                actor_id=actor_id,
                error=exc,
            )
            raise BusinessRuleError(
                "Version upgrade failed; affected records remain on their prior design version",
                details={
                    "scope_type": "subject",
                    "scope_id": str(subject_id),
                    "to_design_version_id": str(target.id),
                },
            ) from exc

        total = sum(counts.values())
        # Success audit: same transaction as the rebind (R8.3), so rebind + audit
        # commit or roll back together via the caller's transaction boundary.
        await audit_service.record(
            session,
            entity_type="subject",
            entity_id=subject_id,
            action="version_upgrade",
            study_id=subject.study_id,
            site_id=subject.site_id,
            subject_id=subject_id,
            actor_id=actor_id,
            field_name="design_version_id",
            old_value=str(prior_version_id),
            new_value=str(target.id),
        )

        logger.info(
            "Version upgrade (subject): subject=%s %s→%s rebound=%s actor=%s",
            subject_id,
            prior_version_id,
            target.id,
            total,
            actor_id,
        )
        return {
            "scope_type": "subject",
            "scope_id": subject_id,
            "study_id": subject.study_id,
            "from_design_version_id": prior_version_id,
            "to_design_version_id": target.id,
            "rebound_counts": counts,
            "rebound_total": total,
        }

    async def upgrade_site(
        self,
        session: AsyncSession,
        *,
        site_id: UUID,
        study_id: UUID,
        target_design_version_id: UUID,
        actor_id: UUID,
    ) -> dict:
        """Upgrade every non-deleted Subject of a Site to a newer design (R8.3).

        The whole site rebind runs in a single SAVEPOINT: if rebinding any
        subject fails, the SAVEPOINT rolls back and *no* subject of the site is
        rebound (R8.15) — the failed attempt is audited and an error is raised.

        Args:
            session: The active async session (caller's transaction).
            site_id: The Site whose subjects are rebound.
            study_id: The owning study (used to validate the target).
            target_design_version_id: The published Design_Version to rebind to.
            actor_id: The acting user.

        Returns:
            A result dict (see ``VersionUpgradeResult``). ``from_design_version_id``
            is ``None`` when the site's subjects were on more than one version.
        """
        target = await self._validate_target(
            session,
            target_design_version_id=target_design_version_id,
            study_id=study_id,
        )

        subjects = await self._list_site_subjects(session, site_id, study_id)
        prior_versions = {s.study_version_id for s in subjects}
        from_version_id: UUID | None = (
            next(iter(prior_versions)) if len(prior_versions) == 1 else None
        )

        try:
            counts: dict[str, int] = {}
            async with session.begin_nested():
                for subject in subjects:
                    if subject.study_version_id == target.id:
                        continue
                    subject_counts = await self._rebind_subject(
                        session, subject=subject, target_version_id=target.id
                    )
                    for table, count in subject_counts.items():
                        counts[table] = counts.get(table, 0) + count
        except Exception as exc:
            await self._audit_failure(
                session,
                scope_type="site",
                scope_id=site_id,
                study_id=study_id,
                site_id=site_id,
                subject_id=None,
                from_version_id=from_version_id,
                to_version_id=target.id,
                actor_id=actor_id,
                error=exc,
            )
            raise BusinessRuleError(
                "Version upgrade failed; affected records remain on their prior design version",
                details={
                    "scope_type": "site",
                    "scope_id": str(site_id),
                    "to_design_version_id": str(target.id),
                },
            ) from exc

        total = sum(counts.values())
        await audit_service.record(
            session,
            entity_type="site",
            entity_id=site_id,
            action="version_upgrade",
            study_id=study_id,
            site_id=site_id,
            actor_id=actor_id,
            field_name="design_version_id",
            old_value=str(from_version_id) if from_version_id else None,
            new_value=str(target.id),
        )

        logger.info(
            "Version upgrade (site): site=%s subjects=%s →%s rebound=%s actor=%s",
            site_id,
            len(subjects),
            target.id,
            total,
            actor_id,
        )
        return {
            "scope_type": "site",
            "scope_id": site_id,
            "study_id": study_id,
            "from_design_version_id": from_version_id,
            "to_design_version_id": target.id,
            "rebound_counts": counts,
            "rebound_total": total,
        }

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    async def _get_subject(self, session: AsyncSession, subject_id: UUID) -> Subject:
        result = await session.execute(
            select(Subject).where(Subject.id == subject_id, Subject.deleted_at.is_(None))
        )
        subject = result.scalars().first()
        if subject is None:
            raise NotFoundError(
                "Subject not found",
                details={"subject_id": str(subject_id)},
            )
        return subject

    async def _list_site_subjects(
        self, session: AsyncSession, site_id: UUID, study_id: UUID
    ) -> list[Subject]:
        result = await session.execute(
            select(Subject).where(
                Subject.site_id == site_id,
                Subject.study_id == study_id,
                Subject.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def _validate_target(
        self,
        session: AsyncSession,
        *,
        target_design_version_id: UUID,
        study_id: UUID,
    ) -> StudyVersion:
        """Resolve the target as a published design of the same study (R8.3).

        Delegates the published-only guard to the Design_Consumption_Contract so
        a draft/missing target is rejected before any Operational_Record is
        touched. Also enforces that the target belongs to the same study as the
        upgraded Subject/Site.
        """
        # Published-only guard (raises NotFoundError / ValidationError).
        await self._design.get_published_design(session, target_design_version_id)
        version = await session.get(StudyVersion, target_design_version_id)
        if version is None:  # pragma: no cover — guard above already resolved it
            raise NotFoundError(
                "Target design version not found",
                details={"target_design_version_id": str(target_design_version_id)},
            )
        if version.study_id != study_id:
            raise ValidationError(
                "Target design version belongs to a different study",
                details={
                    "target_design_version_id": str(target_design_version_id),
                    "study_id": str(study_id),
                    "target_study_id": str(version.study_id),
                },
            )
        return version

    # ------------------------------------------------------------------
    # Rebind helpers
    # ------------------------------------------------------------------

    async def _rebind_subject_in_savepoint(
        self,
        session: AsyncSession,
        *,
        subject: Subject,
        target_version_id: UUID,
    ) -> dict[str, int]:
        """Rebind one subject's records inside a SAVEPOINT (R8.15).

        A failure rolls back only the rebind mutations (the SAVEPOINT), leaving
        the subject on its prior version while keeping the caller's outer
        transaction usable for the failure audit path.
        """
        async with session.begin_nested():
            return await self._rebind_subject(
                session, subject=subject, target_version_id=target_version_id
            )

    async def _rebind_subject(
        self,
        session: AsyncSession,
        *,
        subject: Subject,
        target_version_id: UUID,
    ) -> dict[str, int]:
        """Rebind every affected Operational_Record of one subject.

        Uses set-based ``UPDATE ... WHERE`` statements for the directly and
        transitively subject-scoped tables, and id-set updates for the
        polymorphic (scope_type/scope_id) tables. Returns a per-table count of
        rebound rows.
        """
        subject_id = subject.id
        counts: dict[str, int] = {}

        # Resolve the subject's operational object graph up front so polymorphic
        # tables (sdv_status/freezes_locks/signatures) can match by id-set.
        visit_ids = await self._scalar_ids(
            session,
            select(VisitInstance.id).where(VisitInstance.subject_id == subject_id),
        )
        form_instance_ids = await self._scalar_ids(
            session,
            select(FormInstance.id).where(FormInstance.subject_id == subject_id),
        )
        field_value_ids = (
            await self._scalar_ids(
                session,
                select(FieldValue.id).where(FieldValue.form_instance_id.in_(form_instance_ids)),
            )
            if form_instance_ids
            else []
        )

        # 1) Subject itself (study_version_id is the subject's binding column).
        counts["subjects"] = await self._update_rows(
            session,
            update(Subject)
            .where(Subject.id == subject_id)
            .values(study_version_id=target_version_id),
        )

        # 2) Directly subject-scoped operational tables.
        counts["visit_instances"] = await self._update_rows(
            session,
            update(VisitInstance)
            .where(VisitInstance.subject_id == subject_id)
            .values(design_version_id=target_version_id),
        )
        counts["form_instances"] = await self._update_rows(
            session,
            update(FormInstance)
            .where(FormInstance.subject_id == subject_id)
            .values(design_version_id=target_version_id),
        )
        counts["queries"] = await self._update_rows(
            session,
            update(Query)
            .where(Query.subject_id == subject_id)
            .values(design_version_id=target_version_id),
        )

        # 3) Transitively subject-scoped (via form_instance_id).
        if form_instance_ids:
            counts["field_values"] = await self._update_rows(
                session,
                update(FieldValue)
                .where(FieldValue.form_instance_id.in_(form_instance_ids))
                .values(design_version_id=target_version_id),
            )
            counts["form_records"] = await self._update_rows(
                session,
                update(FormRecord)
                .where(FormRecord.form_instance_id.in_(form_instance_ids))
                .values(design_version_id=target_version_id),
            )
            counts["review_status"] = await self._update_rows(
                session,
                update(ReviewStatus)
                .where(ReviewStatus.form_instance_id.in_(form_instance_ids))
                .values(design_version_id=target_version_id),
            )
        else:
            counts["field_values"] = 0
            counts["form_records"] = 0
            counts["review_status"] = 0

        # 4) Polymorphic subject-scoped tables (scope_type/object_type + id-set).
        counts["sdv_status"] = await self._rebind_polymorphic(
            session,
            model=SDVStatus,
            type_column=SDVStatus.scope_type,
            id_column=SDVStatus.scope_id,
            subject_id=subject_id,
            visit_ids=visit_ids,
            form_instance_ids=form_instance_ids,
            field_value_ids=field_value_ids,
            target_version_id=target_version_id,
            subject_types=_SDV_SUBJECT_SCOPES,
            visit_types=_SDV_VISIT_SCOPES,
            form_types=_SDV_FORM_SCOPES,
            field_types=_SDV_FIELD_SCOPES,
        )
        counts["freezes_locks"] = await self._rebind_polymorphic(
            session,
            model=FreezeLock,
            type_column=FreezeLock.object_type,
            id_column=FreezeLock.object_id,
            subject_id=subject_id,
            visit_ids=visit_ids,
            form_instance_ids=form_instance_ids,
            field_value_ids=field_value_ids,
            target_version_id=target_version_id,
            subject_types=("subject",),
            visit_types=("visit",),
            form_types=("form",),
            field_types=("field",),
        )
        counts["signatures"] = await self._rebind_polymorphic(
            session,
            model=Signature,
            type_column=Signature.object_type,
            id_column=Signature.object_id,
            subject_id=subject_id,
            visit_ids=visit_ids,
            form_instance_ids=form_instance_ids,
            field_value_ids=field_value_ids,
            target_version_id=target_version_id,
            subject_types=("subject",),
            visit_types=("visit",),
            form_types=("form",),
            field_types=("field",),
        )

        return counts

    async def _rebind_polymorphic(
        self,
        session: AsyncSession,
        *,
        model: type,
        type_column,
        id_column,
        subject_id: UUID,
        visit_ids: list[UUID],
        form_instance_ids: list[UUID],
        field_value_ids: list[UUID],
        target_version_id: UUID,
        subject_types: tuple[str, ...],
        visit_types: tuple[str, ...],
        form_types: tuple[str, ...],
        field_types: tuple[str, ...],
    ) -> int:
        """Rebind rows of a polymorphic (type/id) table scoped to one subject.

        A row is subject-scoped when its (type, id) pair resolves to the
        subject's own object graph: the subject itself, one of its visit
        instances, one of its form instances, or one of its field values.
        """
        clauses = [and_(type_column.in_(subject_types), id_column == subject_id)]
        if visit_ids:
            clauses.append(and_(type_column.in_(visit_types), id_column.in_(visit_ids)))
        if form_instance_ids:
            clauses.append(and_(type_column.in_(form_types), id_column.in_(form_instance_ids)))
        if field_value_ids:
            clauses.append(and_(type_column.in_(field_types), id_column.in_(field_value_ids)))

        return await self._update_rows(
            session,
            update(model).where(or_(*clauses)).values(design_version_id=target_version_id),
        )

    @staticmethod
    async def _scalar_ids(session: AsyncSession, stmt) -> list[UUID]:
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def _update_rows(session: AsyncSession, stmt) -> int:
        """Execute a bulk UPDATE and return the affected row count.

        ``synchronize_session=False`` keeps the rebind a pure set-based UPDATE:
        it neither loads nor refreshes in-session ORM objects to match the
        change. That is both efficient and essential for the atomic failure path
        — synchronizing in-session state during the SAVEPOINT rollback would
        trigger an out-of-band refresh.
        """
        result = await session.execute(stmt.execution_options(synchronize_session=False))
        # rowcount is reliable for UPDATE on the backends used here.
        return int(result.rowcount or 0)

    # ------------------------------------------------------------------
    # Failure audit (durable across the data rollback — R8.15)
    # ------------------------------------------------------------------

    async def _audit_failure(
        self,
        session: AsyncSession,
        *,
        scope_type: str,
        scope_id: UUID,
        study_id: UUID,
        site_id: UUID | None,
        subject_id: UUID | None,
        from_version_id: UUID | None,
        to_version_id: UUID,
        actor_id: UUID,
        error: Exception,
    ) -> None:
        """Record and commit the failed upgrade attempt (R8.15).

        Precondition: the SAVEPOINT around the rebind has already rolled back,
        so the caller's session holds no uncommitted rebind mutation. This
        method writes the failure audit on the caller's session and commits it,
        making the failed-attempt record durable even though the overall upgrade
        raised an error. The affected Operational_Records are already back on
        their prior ``Design_Version`` (the SAVEPOINT rollback), so the commit
        persists only the failure audit.
        """
        try:
            await audit_service.record(
                session,
                entity_type=scope_type,
                entity_id=scope_id,
                action="version_upgrade_failed",
                study_id=study_id,
                site_id=site_id,
                subject_id=subject_id,
                actor_id=actor_id,
                field_name="design_version_id",
                old_value=str(from_version_id) if from_version_id else None,
                new_value=str(to_version_id),
                reason=f"version upgrade failed: {type(error).__name__}",
            )
            await session.commit()
        except Exception:  # pragma: no cover — never mask the original failure
            logger.exception(
                "Failed to persist version_upgrade_failed audit for %s=%s",
                scope_type,
                scope_id,
            )
            await session.rollback()


# Module-level singleton for convenience (mirrors other EDC services).
version_upgrade_service = VersionUpgradeService()
