"""Post-migration verification module (Migration Phases 5-6).

Phase 5 of the ``Migration_Process`` **verifies** that the ownership
reassignment performed by Phase 4 was value-preserving, and Phase 6 defines the
**abort-on-data-loss** semantics that protect the pre-migration records when it
was not.

What this verifies (R11.5)
--------------------------
Given the Phase 0 :class:`~app.services.designer.migration.snapshot_service.MigrationSnapshot`,
this service captures a **fresh** post-migration snapshot and compares it
**set-by-set** against the pre-migration one. For every reassigned record set it
asserts both:

* the post-migration row **count** equals the pre-migration count, and
* the per-record order-independent value **checksum** equals the pre-migration
  checksum.

Because the refactor is a code-layer ownership change that never rewrites a
stored value (R11.1, R11.2), every count and checksum must match **exactly**.
Any difference is treated as a data-loss risk.

What this verifies (R11.3)
--------------------------
Every pre-migration **published** ``study_versions`` row must remain a
consumable ``Published_Design`` through the ``Design_Consumption_Contract``. For
each such version id this service calls
``DesignConsumptionService.get_published_design`` and confirms it resolves to a
published view. A version that no longer resolves (not found, or no longer
published) is a consumability failure and aborts verification.

Abort-on-data-loss semantics (R11.6)
------------------------------------
If **any** record set's count or checksum differs, or **any** pre-migration
published design is no longer consumable, verification **aborts**: it reports a
structured result (or raises :class:`MigrationAbortError`) that names the
failing record set(s) with their expected-vs-actual count/checksum, and the
published versions that failed to resolve.

**This verification performs no writes.** It only reads counts, stored values,
and published-design views, so "leave the pre-migration records unchanged"
(R11.6) is satisfied by construction — there is no code path here that mutates a
record. The migration *orchestration* is responsible for the transactional
guarantee: it MUST roll back (or simply never commit) the Phase 4 reassignment
when :meth:`VerificationService.verify` reports ``ok is False`` (or when
:meth:`verify_or_abort` raises), leaving the pre-migration records exactly as
they were.

Satisfies Requirements:
  - 11.3: Every pre-migration published study version remains a consumable
          Published_Design through the Design_Consumption_Contract.
  - 11.5: For every reassigned record set the post-migration count and per-record
          value checksum equal the pre-migration snapshot.
  - 11.6: Any data-loss risk aborts, leaves pre-migration records unchanged
          (read-only verification), and reports the failing record set(s).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.exceptions import DomainError
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)
from app.services.designer.migration.snapshot_service import (
    RECORD_SET_MODELS,
    MigrationSnapshot,
    SnapshotService,
    snapshot_service,
)

logger = logging.getLogger(__name__)


class FailureKind(StrEnum):
    """Why a record set failed post-migration verification."""

    #: A record set present pre-migration is missing from the fresh snapshot
    #: (or vice versa) — the snapshots do not cover the same sets.
    MISSING_SET = "missing_set"
    #: The post-migration row count differs from the pre-migration count.
    COUNT_MISMATCH = "count_mismatch"
    #: The post-migration value checksum differs from the pre-migration one.
    CHECKSUM_MISMATCH = "checksum_mismatch"


@dataclass(frozen=True)
class RecordSetFailure:
    """A single reassigned record set that failed verification (a data-loss risk)."""

    record_set: str
    kind: FailureKind
    expected_count: int | None = None
    actual_count: int | None = None
    expected_checksum: str | None = None
    actual_checksum: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "record_set": self.record_set,
            "kind": self.kind.value,
            "expected_count": self.expected_count,
            "actual_count": self.actual_count,
            "expected_checksum": self.expected_checksum,
            "actual_checksum": self.actual_checksum,
        }


@dataclass(frozen=True)
class PublishedDesignFailure:
    """A pre-migration published design that is no longer consumable (R11.3)."""

    design_version_id: UUID
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "design_version_id": str(self.design_version_id),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class VerificationResult:
    """Structured outcome of post-migration verification (R11.5, R11.6, R11.3).

    ``ok`` is true only when every reassigned record set matched the Phase 0
    snapshot (count and checksum) **and** every pre-migration published design
    remained consumable. When ``ok`` is false the migration orchestration must
    roll back / not commit the reassignment so the pre-migration records remain
    unchanged (R11.6).
    """

    ok: bool
    failing_sets: list[RecordSetFailure] = field(default_factory=list)
    published_designs_consumable: list[UUID] = field(default_factory=list)
    failing_published_designs: list[PublishedDesignFailure] = field(
        default_factory=list
    )

    @property
    def failing_set_names(self) -> list[str]:
        """The names of the record sets that failed, for operator reporting."""
        return [f.record_set for f in self.failing_sets]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "failing_sets": [f.to_dict() for f in self.failing_sets],
            "published_designs_consumable": [
                str(v) for v in self.published_designs_consumable
            ],
            "failing_published_designs": [
                f.to_dict() for f in self.failing_published_designs
            ],
        }


class MigrationAbortError(DomainError):
    """Raised by :meth:`VerificationService.verify_or_abort` on a data-loss risk.

    Carries the full :class:`VerificationResult` so the operator sees exactly
    which record set(s) and published design(s) failed. Raising this (rather than
    returning) signals the migration orchestration to roll back the reassignment
    and leave the pre-migration records unchanged (R11.6).
    """

    def __init__(self, result: VerificationResult) -> None:
        self.result = result
        super().__init__(
            "Migration aborted: post-migration verification detected a data-loss "
            "risk; pre-migration records left unchanged",
            details=result.to_dict(),
        )


class VerificationService:
    """Phase 5/6 post-migration verification — read-only and abort-on-data-loss.

    The service performs **no writes**: it captures a fresh snapshot, compares it
    against the Phase 0 snapshot, and resolves published designs through the
    read-only consumption contract. Leaving pre-migration records unchanged on
    abort (R11.6) is therefore guaranteed by construction; the migration
    orchestration must roll back / not commit the reassignment when verification
    is not ``ok``.
    """

    def __init__(
        self,
        *,
        snapshot_service: SnapshotService | None = None,
        consumption_service: DesignConsumptionService | None = None,
        record_set_models: dict[str, type[Base]] | None = None,
    ) -> None:
        self._snapshot_service = snapshot_service or _default_snapshot_service()
        self._consumption_service = (
            consumption_service or _default_consumption_service()
        )
        self._record_set_models = record_set_models or RECORD_SET_MODELS

    # ------------------------------------------------------------------
    # Count + value preservation (R11.5)
    # ------------------------------------------------------------------

    def _compare_record_sets(
        self,
        pre_migration_snapshot: MigrationSnapshot,
        post_migration_snapshot: MigrationSnapshot,
    ) -> list[RecordSetFailure]:
        """Compare every reassigned record set set-by-set (count + checksum).

        For every set the post-migration count must equal the pre-migration
        count AND the value checksum must match. Because the refactor never
        rewrites a stored value, any difference is a data-loss risk (R11.5).
        """
        failures: list[RecordSetFailure] = []
        for name in self._record_set_models:
            pre = pre_migration_snapshot.get(name)
            post = post_migration_snapshot.get(name)
            if pre is None or post is None:
                failures.append(
                    RecordSetFailure(record_set=name, kind=FailureKind.MISSING_SET)
                )
                continue
            if pre.count != post.count:
                failures.append(
                    RecordSetFailure(
                        record_set=name,
                        kind=FailureKind.COUNT_MISMATCH,
                        expected_count=pre.count,
                        actual_count=post.count,
                        expected_checksum=pre.checksum,
                        actual_checksum=post.checksum,
                    )
                )
                continue
            if pre.checksum != post.checksum:
                failures.append(
                    RecordSetFailure(
                        record_set=name,
                        kind=FailureKind.CHECKSUM_MISMATCH,
                        expected_count=pre.count,
                        actual_count=post.count,
                        expected_checksum=pre.checksum,
                        actual_checksum=post.checksum,
                    )
                )
        return failures

    # ------------------------------------------------------------------
    # Published-design consumability (R11.3)
    # ------------------------------------------------------------------

    async def _published_version_ids(self, session: AsyncSession) -> list[UUID]:
        """Return the ids of every currently-published ``study_versions`` row.

        Called after reassignment; the set must equal the pre-migration set of
        published versions because the refactor neither adds nor removes rows.
        """
        result = await session.execute(
            select(StudyVersion.id).where(
                StudyVersion.status == StudyVersionStatus.published
            )
        )
        return list(result.scalars().all())

    async def _verify_published_designs(
        self, session: AsyncSession
    ) -> tuple[list[UUID], list[PublishedDesignFailure]]:
        """Confirm every published design resolves through the consumption port.

        Each published ``study_versions`` row that existed pre-migration must
        remain a consumable ``Published_Design`` (R11.3): the consumption
        contract must return its published view (not raise). A version that fails
        to resolve is reported as a consumability failure.
        """
        consumable: list[UUID] = []
        failures: list[PublishedDesignFailure] = []
        for version_id in await self._published_version_ids(session):
            try:
                await self._consumption_service.get_published_design(
                    session, version_id
                )
            except DomainError as exc:
                failures.append(
                    PublishedDesignFailure(
                        design_version_id=version_id, reason=exc.message
                    )
                )
            else:
                consumable.append(version_id)
        return consumable, failures

    # ------------------------------------------------------------------
    # Verification entry points
    # ------------------------------------------------------------------

    async def verify(
        self,
        session: AsyncSession,
        pre_migration_snapshot: MigrationSnapshot,
    ) -> VerificationResult:
        """Verify the migration preserved every value and design (non-raising).

        Captures a fresh post-migration snapshot, compares it set-by-set against
        the Phase 0 snapshot (R11.5), and confirms every published design is
        still consumable (R11.3). Returns a :class:`VerificationResult`; it does
        **not** raise on a data-loss risk — the caller inspects ``ok`` and rolls
        back the reassignment when it is false (R11.6).

        The method performs no writes, so the pre-migration records are left
        unchanged regardless of outcome.
        """
        post_migration_snapshot = await self._snapshot_service.capture(session)
        failing_sets = self._compare_record_sets(
            pre_migration_snapshot, post_migration_snapshot
        )
        consumable, failing_designs = await self._verify_published_designs(session)

        ok = not failing_sets and not failing_designs
        result = VerificationResult(
            ok=ok,
            failing_sets=failing_sets,
            published_designs_consumable=consumable,
            failing_published_designs=failing_designs,
        )

        if ok:
            logger.info(
                "Phase 5 verification passed: %s record sets preserved, "
                "%s published designs consumable",
                len(self._record_set_models),
                len(consumable),
            )
        else:
            logger.error(
                "Phase 5 verification FAILED (data-loss risk): failing sets=%s, "
                "non-consumable designs=%s — migration must be rolled back (R11.6)",
                result.failing_set_names,
                [str(f.design_version_id) for f in failing_designs],
            )
        return result

    async def verify_or_abort(
        self,
        session: AsyncSession,
        pre_migration_snapshot: MigrationSnapshot,
    ) -> VerificationResult:
        """Verify and raise :class:`MigrationAbortError` on any data-loss risk.

        Runs :meth:`verify`; on success returns the (ok) result, on failure
        raises :class:`MigrationAbortError` carrying the structured result so the
        migration orchestration aborts, rolls back the reassignment, and leaves
        the pre-migration records unchanged while reporting the failing record
        set(s) to the operator (R11.6).
        """
        result = await self.verify(session, pre_migration_snapshot)
        if not result.ok:
            raise MigrationAbortError(result)
        return result


def _default_snapshot_service() -> SnapshotService:
    return snapshot_service


def _default_consumption_service() -> DesignConsumptionService:
    return design_consumption_service


# Module-level singleton for convenience (mirrors snapshot_service).
verification_service = VerificationService()
