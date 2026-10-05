"""PV MedDRA/WHODrug coding persistence (Phase 2).

Coding assignments standardize an ``Adverse_Event_Record`` verbatim term
(MedDRA) or a reported product (WHODrug) against a versioned dictionary. Each
assignment retains the ``Coding_Dictionary_Version`` used and the assigning
actor and timestamp. Recoding never mutates a prior assignment: a new row is
created and a traceability link records the prior-to-new relationship, so the
prior coding and its dictionary version remain immutable.

Every record uses a UUID primary key, UTC ``TIMESTAMPTZ`` columns,
actor/correlation metadata, and soft-deletion/retention columns provided by
:mod:`app.models.pv.common`. Coding rows reference PV-owned records only; no PV
table copies or mutates an EDC clinical payload.
"""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.pv.common import PVBase

# Partial-index predicate that excludes soft-deleted rows (Requirement 17.5).
_NOT_DELETED = text("deleted_at IS NULL")


class CodingSystem(enum.StrEnum):
    """The controlled terminology a coding assignment draws from."""

    MEDDRA = "MedDRA"
    WHODRUG = "WHODrug"


_CODING_SYSTEM_VALUES = "','".join(system.value for system in CodingSystem)


class CodingDictionaryVersion(PVBase):
    """A named, versioned coding dictionary release available to PV.

    A coding assignment must reference an ``available`` version of the correct
    ``coding_system``; a missing or unavailable version is rejected by the
    ``Coding_Service`` before any coding is persisted (Requirement 6.4). The
    ``(coding_system, version)`` pair is unique among live rows.
    """

    __tablename__ = "pv_coding_dictionary_versions"

    coding_system: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index(
            "uq_pv_coding_dictionary_versions_system_version",
            "coding_system",
            "version",
            unique=True,
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_coding_dictionary_versions_system",
            "coding_system",
            "available",
            postgresql_where=_NOT_DELETED,
        ),
    )


class _CodingBase(PVBase):
    """Shared columns for a MedDRA or WHODrug coding assignment.

    ``dictionary_version`` is the exact ``Coding_Dictionary_Version`` string used
    at assignment time and is retained immutably. ``prior_coding_id`` is the
    traceability link from a superseding recode to the prior assignment; a
    recode creates a new row referencing the prior one and never edits it
    (Requirement 6.5).
    """

    __abstract__ = True

    term_id: Mapped[str] = mapped_column(String(100), nullable=False)
    term_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dictionary_version: Mapped[str] = mapped_column(String(50), nullable=False)
    assigned_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MedDraCoding(_CodingBase):
    """A MedDRA coding of an Adverse_Event_Record verbatim term."""

    __tablename__ = "pv_meddra_codings"

    ae_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("pv_adverse_event_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    prior_coding_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("pv_meddra_codings.id", ondelete="RESTRICT"), nullable=True
    )

    adverse_event = relationship("AdverseEventRecord", lazy="selectin")
    prior_coding = relationship(
        "MedDraCoding", remote_side="MedDraCoding.id", lazy="selectin"
    )

    __table_args__ = (
        Index(
            "ix_pv_meddra_codings_ae",
            "ae_id",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_meddra_codings_prior",
            "prior_coding_id",
            postgresql_where=_NOT_DELETED,
        ),
    )


class WhoDrugCoding(_CodingBase):
    """A WHODrug coding of a reported product."""

    __tablename__ = "pv_whodrug_codings"

    product_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    prior_coding_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("pv_whodrug_codings.id", ondelete="RESTRICT"), nullable=True
    )

    prior_coding = relationship(
        "WhoDrugCoding", remote_side="WhoDrugCoding.id", lazy="selectin"
    )

    __table_args__ = (
        Index(
            "ix_pv_whodrug_codings_product",
            "product_id",
            postgresql_where=_NOT_DELETED,
        ),
        Index(
            "ix_pv_whodrug_codings_prior",
            "prior_coding_id",
            postgresql_where=_NOT_DELETED,
        ),
    )


__all__ = [
    "CodingDictionaryVersion",
    "CodingSystem",
    "MedDraCoding",
    "WhoDrugCoding",
]
