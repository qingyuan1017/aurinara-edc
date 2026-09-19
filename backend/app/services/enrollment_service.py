"""CTMS enrollment planning and operational subject milestone service.

This service deliberately keeps CTMS enrollment state separate from the EDC
clinical subject registry.  All subject references are resolved by canonical
EDC UUID and every cross-module status projection is an explicit, minimized,
versioned rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module, ensure_utc, utc_now
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.models.ctms.coordination import CTMSOutbox
from app.models.ctms.enrollment import (
    EnrollmentTarget,
    EnrollmentTargetStatus,
    EnrollmentTargetType,
    OperationalMilestone,
    OperationalSubjectStatus,
)
from app.models.identity import User, UserStatus
from app.models.subject import Subject
from app.schemas.ctms.enrollment import EnrollmentTargetCreate, OperationalMilestoneCreate
from app.services.ctms_identity_service import CanonicalIdentityResolver
from app.services.ctms_ownership_guard import assert_ctms_command_safe
from app.services.status_ownership_rule_service import (
    StatusOwnershipRuleService,
    status_ownership_rule_service,
)


class ProjectionTarget(StrEnum):
    """Allowed destination for an approved subject status projection."""

    CTMS = "CTMS"
    EDC = "EDC"


@dataclass(frozen=True, slots=True)
class SubjectStatusOwnershipRule:
    """Versioned status ownership and projection policy.

    The rule is intentionally small until the general ownership-rule
    persistence task lands.  It still enforces the same safety properties at
    command acceptance: one authority, an explicit projection target, and an
    active version.
    """

    edc_status: str
    ctms_status: OperationalSubjectStatus
    rule_version: int = 1
    authoritative_module: Module = Module.EDC
    projection_target: ProjectionTarget = ProjectionTarget.CTMS
    active: bool = True
    writable_module: Module = Module.EDC

    def permits_projection(self) -> bool:
        return (
            self.active
            and self.rule_version > 0
            and self.authoritative_module is Module.EDC
            and self.projection_target is ProjectionTarget.CTMS
        )


# Friendly specification-compatible name for consumers that use the generic
# ownership terminology before the persisted rule service is introduced.
StatusOwnershipRule = SubjectStatusOwnershipRule


_ALLOWED_TARGET_TRANSITIONS: dict[EnrollmentTargetStatus, set[EnrollmentTargetStatus]] = {
    EnrollmentTargetStatus.draft: {
        EnrollmentTargetStatus.active,
        EnrollmentTargetStatus.cancelled,
    },
    EnrollmentTargetStatus.active: {
        EnrollmentTargetStatus.met,
        EnrollmentTargetStatus.expired,
        EnrollmentTargetStatus.cancelled,
    },
    EnrollmentTargetStatus.met: set(),
    EnrollmentTargetStatus.expired: set(),
    EnrollmentTargetStatus.cancelled: set(),
}


class EnrollmentService:
    """Own CTMS targets/milestones without owning EDC clinical records."""

    def __init__(
        self,
        status_rules: Mapping[str, SubjectStatusOwnershipRule | str] | None = None,
        *,
        rule_service: StatusOwnershipRuleService | None = None,
    ) -> None:
        self._status_rules: dict[str, SubjectStatusOwnershipRule] = {}
        self._rule_service = rule_service or status_ownership_rule_service
        for edc_status, rule in (status_rules or {}).items():
            self.configure_status_projection(edc_status, rule)

    # ------------------------------------------------------------------
    # Enrollment targets
    # ------------------------------------------------------------------

    async def create_enrollment_target(
        self,
        session: AsyncSession,
        data: EnrollmentTargetCreate,
        actor_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> EnrollmentTarget:
        """Persist one study/site planning target after canonical scope checks."""

        payload = data.model_dump(mode="json")
        assert_ctms_command_safe(payload, operation="create_enrollment_target")
        await self._resolve_study_and_site(session, data.study_id, data.site_id)
        await self._require_active_user(session, data.owner_id)

        correlation = correlation_id or str(uuid4())
        target = EnrollmentTarget(
            study_id=data.study_id,
            site_id=data.site_id,
            target_type=EnrollmentTargetType(data.target_type),
            target_quantity=data.target_quantity,
            planning_period_start=ensure_utc(data.planning_period_start),
            planning_period_end=ensure_utc(data.planning_period_end),
            dimension=dict(data.dimension),
            owner_id=data.owner_id,
            status=EnrollmentTargetStatus(data.status),
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=self._uuid_correlation(correlation),
        )
        session.add(target)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="enrollment_target",
            entity_id=target.id,
            action="create",
            module=Module.CTMS,
            actor_id=actor_id,
            study_id=target.study_id,
            site_id=target.site_id,
            correlation_id=correlation,
            changed_fields=[
                "study_id",
                "site_id",
                "target_type",
                "target_quantity",
                "planning_period",
                "owner_id",
                "status",
            ],
        )
        return target

    # Common aliases used by routes and service consumers.
    create_target = create_enrollment_target

    async def get_enrollment_target(
        self, session: AsyncSession, target_id: UUID
    ) -> EnrollmentTarget:
        result = await session.execute(
            select(EnrollmentTarget).where(
                EnrollmentTarget.id == target_id,
                EnrollmentTarget.deleted_at.is_(None),
            )
        )
        target = result.scalars().first()
        if target is None:
            raise NotFoundError(
                "Enrollment target not found",
                {"reason": "RECORD_NOT_FOUND", "target_id": str(target_id)},
            )
        return target

    get_target = get_enrollment_target

    async def transition_target_status(
        self,
        session: AsyncSession,
        target: EnrollmentTarget,
        status: EnrollmentTargetStatus,
        actor_id: UUID,
        *,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> EnrollmentTarget:
        """Apply the target lifecycle without changing its scope or dimensions."""

        assert_ctms_command_safe({"status": status.value}, operation="transition_target_status")
        next_status = EnrollmentTargetStatus(status)
        current_status = EnrollmentTargetStatus(target.status)
        if next_status not in _ALLOWED_TARGET_TRANSITIONS[current_status]:
            raise BusinessRuleError(
                "Invalid enrollment target status transition",
                {
                    "reason": "INVALID_STATUS_TRANSITION",
                    "current_status": current_status.value,
                    "target_status": next_status.value,
                },
            )
        old_status = current_status.value
        target.status = next_status
        target.updated_by = actor_id
        target.updated_at = utc_now()
        await session.flush()
        correlation = correlation_id or str(uuid4())
        await audit_service.record(
            session,
            entity_type="enrollment_target",
            entity_id=target.id,
            action="status_transition",
            module=Module.CTMS,
            actor_id=actor_id,
            study_id=target.study_id,
            site_id=target.site_id,
            field_name="status",
            old_value=old_status,
            new_value=next_status.value,
            reason=reason,
            correlation_id=correlation,
        )
        return target

    update_target_status = transition_target_status

    async def list_enrollment_targets(
        self,
        session: AsyncSession,
        study_id: UUID,
        *,
        site_id: UUID | None = None,
        status: EnrollmentTargetStatus | None = None,
    ) -> list[EnrollmentTarget]:
        """Return in-scope, non-deleted CTMS targets."""

        statement = select(EnrollmentTarget).where(
            EnrollmentTarget.study_id == study_id,
            EnrollmentTarget.deleted_at.is_(None),
        )
        if site_id is not None:
            statement = statement.where(EnrollmentTarget.site_id == site_id)
        if status is not None:
            statement = statement.where(EnrollmentTarget.status == status)
        statement = statement.order_by(EnrollmentTarget.planning_period_start)
        result = await session.execute(statement)
        return list(result.scalars().all())

    list_targets = list_enrollment_targets

    # ------------------------------------------------------------------
    # Operational milestones
    # ------------------------------------------------------------------

    async def record_operational_milestone(
        self,
        session: AsyncSession,
        data: OperationalMilestoneCreate,
        actor_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> OperationalMilestone:
        """Record CTMS progress for an existing canonical EDC subject.

        This method only adds an ``OperationalMilestone``.  It intentionally
        does not call ``SubjectService`` or assign anything on the EDC Subject.
        """

        payload = data.model_dump(mode="json")
        assert_ctms_command_safe(payload, operation="record_operational_milestone")
        await self._resolve_study_and_site(session, data.study_id, data.site_id)

        resolver = CanonicalIdentityResolver(session)
        identity = await resolver.resolve_subject(
            data.subject_id,
            study_id=data.study_id,
            site_id=data.site_id,
        )
        subject = await self._load_subject(session, identity.id)
        subject_site_id = subject.site_id
        if data.site_id is not None and subject_site_id != data.site_id:
            raise ConflictError(
                "Subject reference is outside the requested site",
                {"reason": "REFERENCE_SCOPE_MISMATCH"},
            )
        if subject.deleted_at is not None:
            raise NotFoundError(
                "Canonical Subject reference was withdrawn or deleted",
                {"reason": "RECORD_NOT_FOUND", "entity_type": "Subject"},
            )
        current_status = str(getattr(subject.status, "value", subject.status))
        requested_status = OperationalSubjectStatus(data.status)
        if current_status == OperationalSubjectStatus.withdrawn.value and requested_status is not OperationalSubjectStatus.withdrawn:
            raise ConflictError(
                "A withdrawn subject cannot receive another operational milestone",
                {"reason": "WITHDRAWN_SUBJECT_REFERENCE"},
            )

        correlation = correlation_id or str(uuid4())
        milestone = OperationalMilestone(
            study_id=data.study_id,
            site_id=data.site_id or subject_site_id,
            subject_id=identity.id,
            approved_pseudonym=data.approved_pseudonym,
            approved_reference=data.approved_reference,
            milestone_type=data.milestone_type,
            milestone_date=ensure_utc(data.milestone_date),
            status=requested_status,
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=self._uuid_correlation(correlation),
        )
        session.add(milestone)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="operational_milestone",
            entity_id=milestone.id,
            action="create",
            module=Module.CTMS,
            actor_id=actor_id,
            study_id=milestone.study_id,
            site_id=milestone.site_id,
            subject_id=milestone.subject_id,
            correlation_id=correlation,
            changed_fields=[
                "subject_id",
                "approved_pseudonym",
                "approved_reference",
                "milestone_type",
                "milestone_date",
                "status",
            ],
        )
        return milestone

    create_operational_milestone = record_operational_milestone
    record_milestone = record_operational_milestone

    async def list_operational_milestones(
        self,
        session: AsyncSession,
        study_id: UUID,
        *,
        site_id: UUID | None = None,
        subject_id: UUID | None = None,
        status: OperationalSubjectStatus | None = None,
    ) -> list[OperationalMilestone]:
        """Return only CTMS operational milestones in the requested scope."""

        statement = select(OperationalMilestone).where(
            OperationalMilestone.study_id == study_id,
            OperationalMilestone.deleted_at.is_(None),
        )
        if site_id is not None:
            statement = statement.where(OperationalMilestone.site_id == site_id)
        if subject_id is not None:
            statement = statement.where(OperationalMilestone.subject_id == subject_id)
        if status is not None:
            statement = statement.where(OperationalMilestone.status == status)
        statement = statement.order_by(OperationalMilestone.milestone_date)
        result = await session.execute(statement)
        return list(result.scalars().all())

    list_milestones = list_operational_milestones

    # ------------------------------------------------------------------
    # Explicit EDC -> CTMS status projection
    # ------------------------------------------------------------------

    def configure_status_projection(
        self,
        edc_status: str,
        rule: SubjectStatusOwnershipRule | str,
        *,
        rule_version: int = 1,
        active: bool = True,
    ) -> SubjectStatusOwnershipRule:
        """Register an explicit minimized EDC status projection rule."""

        if isinstance(rule, str):
            rule = SubjectStatusOwnershipRule(
                edc_status=edc_status,
                ctms_status=OperationalSubjectStatus(rule),
                rule_version=rule_version,
                active=active,
            )
        elif rule.edc_status != edc_status:
            raise ValidationError(
                "Status ownership rule key does not match its EDC status",
                {"reason": "RULE_STATUS_MISMATCH"},
            )
        if rule.rule_version < 1:
            raise ValidationError(
                "Status ownership rule version must be positive",
                {"reason": "INVALID_RULE_VERSION"},
            )
        self._status_rules[edc_status] = rule
        # Keep the command-acceptance path on the shared ownership compiler;
        # persistence-backed coordination consumers use the same compiler.
        self._rule_service.register_runtime_rule(edc_status, rule)
        return rule

    register_status_projection = configure_status_projection

    def status_ownership_allows_projection(self, edc_status: str) -> bool:
        """Return whether an active rule explicitly permits CTMS projection."""

        rule = self._status_rules.get(edc_status)
        return (
            rule is not None
            and rule.permits_projection()
            and self._rule_service.runtime_rule("Subject", edc_status) is not None
        )

    async def project_edc_subject_status(
        self,
        session: AsyncSession,
        subject_id: UUID,
        edc_status: str,
        *,
        approved_pseudonym: str | None = None,
        source_version: str | None = None,
        correlation_id: str | None = None,
    ) -> CTMSOutbox | None:
        """Publish only an explicitly configured, minimized status projection.

        An absent or inactive rule is a deliberate CTMS-only outcome: no EDC
        status write and no coordination event are produced.
        """

        assert_ctms_command_safe(
            {
                "subject_id": subject_id,
                "approved_pseudonym": approved_pseudonym,
                "status": edc_status,
            },
            operation="project_edc_subject_status",
        )
        rule = self._status_rules.get(edc_status)
        compiled_rule = self._rule_service.runtime_rule("Subject", edc_status)
        if rule is None or not rule.permits_projection() or compiled_rule is None:
            return None

        resolver = CanonicalIdentityResolver(session)
        identity = await resolver.resolve_subject(subject_id)
        subject = await self._load_subject(session, identity.id)
        current_status = str(getattr(subject.status, "value", subject.status))
        if current_status != edc_status:
            raise ConflictError(
                "EDC subject status is not current",
                {"reason": "STALE_SOURCE_STATUS"},
            )
        if approved_pseudonym is not None and not approved_pseudonym.strip():
            raise ValidationError(
                "Approved pseudonym must not be blank",
                {"reason": "INVALID_APPROVED_REFERENCE"},
            )

        correlation = correlation_id or str(uuid4())
        event_id = uuid4()
        payload = {
            "subject_id": str(identity.id),
            "approved_pseudonym": approved_pseudonym,
            "status": rule.ctms_status.value,
            "source_version": source_version or self._source_version(subject),
            "rule_version": rule.rule_version,
        }
        validated_projection = self._rule_service.validate_payload(compiled_rule, payload)
        payload = validated_projection.payload
        payload["rule_version"] = rule.rule_version
        event = CTMSOutbox(
            event_id=event_id,
            aggregate_type="Subject",
            aggregate_id=identity.id,
            event_type="EDC_SUBJECT_STATUS_PROJECTION",
            module=Module.EDC.value,
            correlation_id=correlation,
            payload_json=payload,
        )
        session.add(event)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="subject_status_projection",
            entity_id=identity.id,
            action="projection_accepted",
            module=Module.CTMS,
            actor_kind="worker",
            correlation_id=correlation,
            source_module=Module.EDC,
            target_module=Module.CTMS,
            source_record_id=identity.id,
            target_record_id=identity.id,
            study_id=subject.study_id,
            site_id=subject.site_id,
            subject_id=identity.id,
            changed_fields=["subject_id", "approved_pseudonym", "status", "source_version"],
        )
        return event

    publish_edc_subject_status = project_edc_subject_status

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    async def _resolve_study_and_site(
        self,
        session: AsyncSession,
        study_id: UUID,
        site_id: UUID | None,
    ) -> None:
        resolver = CanonicalIdentityResolver(session)
        await resolver.resolve_study(study_id)
        if site_id is not None:
            await resolver.resolve_site(site_id, study_id=study_id)

    async def _require_active_user(
        self, session: AsyncSession, user_id: UUID | None
    ) -> None:
        if user_id is None:
            return
        result = await session.execute(
            select(User).where(User.id == user_id, User.status == UserStatus.active)
        )
        if result.scalars().first() is None:
            raise ValidationError(
                "Owner must be an active user",
                {"reason": "ACTIVE_USER_REQUIRED", "owner_id": str(user_id)},
            )

    async def _load_subject(self, session: AsyncSession, subject_id: UUID) -> Subject:
        result = await session.execute(
            select(Subject).where(Subject.id == subject_id)
        )
        rows = list(result.scalars().all())
        if not rows:
            raise NotFoundError(
                "Canonical Subject reference was not found",
                {"reason": "RECORD_NOT_FOUND", "entity_type": "Subject"},
            )
        if len(rows) != 1:
            raise ConflictError(
                "Canonical Subject reference is ambiguous",
                {"reason": "AMBIGUOUS_REFERENCE", "entity_type": "Subject"},
            )
        return rows[0]

    @staticmethod
    def _source_version(subject: Subject) -> str:
        updated_at = getattr(subject, "updated_at", None)
        if isinstance(updated_at, datetime):
            return ensure_utc(updated_at).isoformat()
        return str(updated_at or getattr(subject, "created_at", "unknown"))

    @staticmethod
    def _uuid_correlation(correlation_id: str) -> UUID:
        try:
            return UUID(correlation_id)
        except (ValueError, AttributeError):
            return uuid4()


# Module-level singleton for route/service consumers.
enrollment_service = EnrollmentService()

__all__ = [
    "EnrollmentService",
    "ProjectionTarget",
    "StatusOwnershipRule",
    "SubjectStatusOwnershipRule",
    "enrollment_service",
]
