"""Study-scoped CTMS completion records.

These records contain operational metadata only. Clinical source data remains
owned by EDC and is referenced through approved projection identifiers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    return datetime.now(UTC)


class _AuditMixin:
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudyTeamAssignment(Base, _AuditMixin):
    __tablename__ = "ctms_study_team_assignments"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    staff_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ctms_managed_entities.id", ondelete="RESTRICT")
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ctms_managed_entities.id", ondelete="RESTRICT")
    )
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    assignment_type: Mapped[str] = mapped_column(String(20), nullable=False, default="Primary")
    responsibilities: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND staff_entity_id IS NULL) OR "
            "(user_id IS NULL AND staff_entity_id IS NOT NULL)",
            name="ck_ctms_study_team_one_identity",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_ctms_study_team_dates",
        ),
        Index("ix_ctms_study_team_scope", "study_id", "site_id", "active"),
        Index("ix_ctms_study_team_user_dates", "user_id", "effective_from", "effective_to"),
    )


class StudyAmendment(Base, _AuditMixin):
    __tablename__ = "ctms_study_amendments"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    amendment_number: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_module: Mapped[str] = mapped_column(String(20), nullable=False, default="PLATFORM")
    source_reference_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(100))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    effective_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="Draft")
    summary: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("study_id", "amendment_number", name="uq_ctms_study_amendment_number"),
        Index("ix_ctms_study_amendment_status", "study_id", "status", "due_date"),
    )


class StudyAmendmentImpact(Base, _AuditMixin):
    __tablename__ = "ctms_study_amendment_impacts"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    amendment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_study_amendments.id", ondelete="RESTRICT"), nullable=False
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT")
    )
    impact_area: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Open")
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    __table_args__ = (Index("ix_ctms_amendment_impact_scope", "study_id", "site_id", "status"),)


class StudyAmendmentTransition(Base):
    __tablename__ = "ctms_study_amendment_transitions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    amendment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_study_amendments.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(40), nullable=False)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    __table_args__ = (Index("ix_ctms_amendment_transition", "amendment_id", "created_at"),)


class SiteCloseoutPlan(Base, _AuditMixin):
    __tablename__ = "ctms_site_closeout_plans"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    planned_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Not Started")
    closure_reason: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("site_id", name="uq_ctms_site_closeout_site"),
        Index("ix_ctms_site_closeout_scope", "study_id", "status", "planned_date"),
    )


class SiteCloseoutItem(Base, _AuditMixin):
    __tablename__ = "ctms_site_closeout_items"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_site_closeout_plans.id", ondelete="RESTRICT"), nullable=False
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Open")
    due_date: Mapped[date | None] = mapped_column(Date)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_ctms_closeout_item_plan", "plan_id", "status"),)


class SiteCloseoutTransition(Base):
    __tablename__ = "ctms_site_closeout_transitions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_site_closeout_plans.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(30), nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RiskAssessment(Base, _AuditMixin):
    __tablename__ = "ctms_risk_assessments"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Draft")
    legacy_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    __table_args__ = (Index("ix_ctms_ract_study_status", "study_id", "status"),)


class RiskAssessmentVersion(Base):
    __tablename__ = "ctms_risk_assessment_versions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_risk_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Draft")
    rationale: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("assessment_id", "version_number", name="uq_ctms_ract_version"),
    )


class RiskItem(Base, _AuditMixin):
    __tablename__ = "ctms_risk_items"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_risk_assessment_versions.id", ondelete="RESTRICT"), nullable=False
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    probability: Mapped[int] = mapped_column(Integer, nullable=False)
    impact: Mapped[int] = mapped_column(Integer, nullable=False)
    detectability: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    mitigation: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    __table_args__ = (
        CheckConstraint(
            "probability BETWEEN 1 AND 5 AND impact BETWEEN 1 AND 5 "
            "AND detectability BETWEEN 1 AND 5",
            name="ck_ctms_risk_item_scale",
        ),
    )


class KRIDefinition(Base, _AuditMixin):
    __tablename__ = "ctms_kri_definitions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Draft")
    legacy_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    __table_args__ = (
        UniqueConstraint("study_id", "code", name="uq_ctms_kri_code"),
        Index("ix_ctms_kri_study_status", "study_id", "status"),
    )


class KRIVersion(Base):
    __tablename__ = "ctms_kri_versions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kri_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_kri_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    amber_threshold: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    red_threshold: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="above")
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    __table_args__ = (
        UniqueConstraint("kri_id", "version_number", name="uq_ctms_kri_version"),
        CheckConstraint(
            "(direction = 'above' AND red_threshold >= amber_threshold) OR "
            "(direction = 'below' AND red_threshold <= amber_threshold)",
            name="ck_ctms_kri_threshold_order",
        ),
    )


class KRIObservation(Base):
    __tablename__ = "ctms_kri_observations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kri_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_kri_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_kri_versions.id", ondelete="RESTRICT"), nullable=False
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT")
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    source_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_reference_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    __table_args__ = (Index("ix_ctms_kri_observation_scope", "study_id", "site_id", "observed_at"),)


class ProtocolDeviationFollowUp(Base, _AuditMixin):
    __tablename__ = "ctms_protocol_deviation_followups"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT")
    )
    projection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approved_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    classification: Mapped[str | None] = mapped_column(String(100))
    severity: Mapped[str | None] = mapped_column(String(30))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="New")
    action_summary: Mapped[str | None] = mapped_column(Text)
    legacy_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    __table_args__ = (
        UniqueConstraint("projection_id", name="uq_ctms_pd_projection"),
        Index("ix_ctms_pd_scope_status", "study_id", "site_id", "status"),
    )


class ICFVersion(Base, _AuditMixin):
    __tablename__ = "ctms_icf_versions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    version_code: Mapped[str] = mapped_column(String(100), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(3))
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    approved_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Approved")
    legacy_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    __table_args__ = (
        UniqueConstraint(
            "study_id", "version_code", "country_code", name="uq_ctms_icf_version_country"
        ),
    )


class ICFSiteRollout(Base, _AuditMixin):
    __tablename__ = "ctms_icf_site_rollouts"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    icf_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_icf_versions.id", ondelete="RESTRICT"), nullable=False
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Planned")
    distributed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    training_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    __table_args__ = (
        UniqueConstraint("icf_version_id", "site_id", name="uq_ctms_icf_site_rollout"),
        Index("ix_ctms_icf_rollout_scope", "study_id", "site_id", "status"),
    )


class TrackingLogDefinition(Base, _AuditMixin):
    __tablename__ = "ctms_tracking_log_definitions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Draft")


class TrackingLogDefinitionVersion(Base):
    __tablename__ = "ctms_tracking_log_definition_versions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_tracking_log_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    columns_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Draft")
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    __table_args__ = (
        UniqueConstraint(
            "definition_id", "version_number", name="uq_ctms_tracking_definition_version"
        ),
    )


class StudyTrackingLog(Base, _AuditMixin):
    __tablename__ = "ctms_study_tracking_logs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    definition_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ctms_tracking_log_definition_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Active")
    legacy_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    __table_args__ = (Index("ix_ctms_tracking_log_study", "study_id", "status"),)


class TrackingLogEntry(Base, _AuditMixin):
    __tablename__ = "ctms_tracking_log_entries"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    log_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_study_tracking_logs.id", ondelete="RESTRICT"), nullable=False
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT")
    )
    row_key: Mapped[str] = mapped_column(String(100), nullable=False)
    values_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("log_id", "row_key", name="uq_ctms_tracking_entry_key"),)


class TrackingLogEntryRevision(Base):
    __tablename__ = "ctms_tracking_log_entry_revisions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_tracking_log_entries.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    values_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    __table_args__ = (
        UniqueConstraint("entry_id", "revision_number", name="uq_ctms_tracking_entry_revision"),
    )


__all__ = [
    name
    for name in globals()
    if name.startswith(("Study", "Site", "Risk", "KRI", "Protocol", "ICF", "Tracking"))
]
