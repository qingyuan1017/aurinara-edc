"""Study_Info_Area response schemas (R8).

Structured response models for the EDC_Module operational Study_Info_Area
surface. Several sub-areas have no dedicated backing data model yet; those
expose a stable, structured response shape (an ``available`` flag plus a typed
``items``/``config`` payload) so the operational surface boundary is explicit
and smoke-testable (task 20.3) without inventing speculative schema.

Where a sub-area is design-dependent, the read is populated from the bound
``Published_Design`` through the ``DesignConsumptionService`` (R8.14); these
schemas carry the ``design_version_id`` the data was read against so a caller
can see which design the operational config was resolved from.

Satisfies Requirements:
  - 8.1: Study Information (Study Information, Status Configuration, ID Configuration).
  - 8.2: CRF Version management (Version History, Edit Check Testing Case, Access Control).
  - 8.5: Alerts.
  - 8.8: SDR.
  - 8.9: Lab.
  - 8.10: External Data Source.
  - 8.11: Adjudication (where enabled).
  - 8.12: SAEs.
  - 8.13: Conversion, Data Validation, System Integration, eDiary, eCOA,
          Workflow, Site Payment, Translation, IRT Integration.
  - 8.14: Design-dependent config read through the Design_Consumption_Contract.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# R8.1 — Study Information
# ---------------------------------------------------------------------------


class StudyInformation(BaseModel):
    """Operational study information summary (R8.1)."""

    study_id: UUID
    study_code: str
    title: str
    sponsor: str | None = None
    phase: str | None = None
    status: str
    therapeutic_area: str | None = None
    indication: str | None = None


class StatusConfiguration(BaseModel):
    """Status Configuration for a study (R8.1).

    Reports the current status and the operational statuses reachable from it.
    """

    study_id: UUID
    current_status: str
    allowed_transitions: list[str] = Field(default_factory=list)


class IdConfiguration(BaseModel):
    """ID Configuration (subject/screening id formats) for a study (R8.1).

    Design-dependent id formatting is resolved from the bound Published_Design
    where available; absent a configured format, the structured default shape
    is returned so the surface stays stable.
    """

    study_id: UUID
    design_version_id: UUID | None = None
    subject_id_format: str | None = None
    screening_id_format: str | None = None


# ---------------------------------------------------------------------------
# R8.2 — CRF Version management
# ---------------------------------------------------------------------------


class CrfVersionHistoryEntry(BaseModel):
    """One Design_Version in a study's version history (R8.2)."""

    design_version_id: UUID
    version_number: str
    status: str
    published_at: str | None = None


class CrfVersionHistory(BaseModel):
    """Version History for a study's CRF design (R8.2)."""

    study_id: UUID
    entries: list[CrfVersionHistoryEntry] = Field(default_factory=list)


class EditCheckTestingCase(BaseModel):
    """A design-defined edit-check rule exposed for operational test review (R8.2).

    Read-only projection of the bound Published_Design's edit-check rules
    through the Design_Consumption_Contract (R8.14).
    """

    edit_check_id: UUID
    name: str
    severity: str
    is_active: bool


class EditCheckTestingCases(BaseModel):
    """Edit Check Testing Case list for a design version (R8.2)."""

    design_version_id: UUID
    cases: list[EditCheckTestingCase] = Field(default_factory=list)


class AccessControlEntry(BaseModel):
    """One design-time CRF access entry projected for operational review (R8.2)."""

    role: str
    form_definition_id: UUID | None = None
    field_definition_id: UUID | None = None
    can_read: bool
    can_write: bool


class AccessControl(BaseModel):
    """Access Control matrix for a design version (R8.2)."""

    design_version_id: UUID
    entries: list[AccessControlEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Generic sub-area surface shape (R8.5, R8.8-R8.13)
# ---------------------------------------------------------------------------


class SubAreaItem(BaseModel):
    """A single structured item within an operational sub-area surface."""

    key: str
    label: str
    detail: dict[str, Any] = Field(default_factory=dict)


class SubAreaSurface(BaseModel):
    """A structured operational sub-area surface response.

    Used by sub-areas whose operational data model is not yet established. The
    response is a stable, typed shape (never a bare ``null``) so each sub-area
    endpoint is mountable and smoke-testable as the operational surface
    boundary. ``design_version_id`` is populated for design-dependent reads
    resolved through the Design_Consumption_Contract (R8.14).
    """

    study_id: UUID | None = None
    design_version_id: UUID | None = None
    available: bool = True
    items: list[SubAreaItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# R8.3 / R8.15 — Version Upgrade (CRF Version management)
# ---------------------------------------------------------------------------


class VersionUpgradeRequest(BaseModel):
    """Request to upgrade a Subject (or a Site's subjects) to a newer design.

    ``target_design_version_id`` must identify a *published* Design_Version of
    the same study as the upgraded Subject/Site; a draft or missing target is
    rejected (R8.3).
    """

    target_design_version_id: UUID = Field(
        ..., description="Published Design_Version to rebind affected records to"
    )


class VersionUpgradeResult(BaseModel):
    """Outcome of a successful Version Upgrade rebind (R8.3).

    Reports the scope that was upgraded, the versions involved, and how many
    Operational_Records were rebound per table so the caller can confirm the
    rebind was complete.
    """

    scope_type: str = Field(..., description="One of: subject, site")
    scope_id: UUID = Field(..., description="Id of the upgraded Subject or Site")
    study_id: UUID
    from_design_version_id: UUID | None = Field(
        None,
        description=(
            "Prior bound Design_Version (None when a Site's subjects were on "
            "mixed versions)"
        ),
    )
    to_design_version_id: UUID
    rebound_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Rebound Operational_Record count per table",
    )
    rebound_total: int = Field(0, description="Total Operational_Records rebound")
