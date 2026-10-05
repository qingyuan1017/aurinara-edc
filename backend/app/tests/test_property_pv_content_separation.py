"""Property 6: Safety and cross-module content separation.

**Validates: Requirements 10, 11, 12, 13, 15, 23**

Feature: pv-safety-module, Task 5.3

*For any* generated PV export request, dashboard/report, Safety_Attachment,
notification, audit search, reconciliation run, and projection payload that may
carry prohibited EDC clinical or CTMS operational fields, every PV result
contains only authorized PV safety content and approved read-only projections,
no EDC clinical or CTMS operational content can be written through any PV
operation, and projected fields are excluded from PV metric calculations.

The property is exercised at two levels, both without a database server, queue,
object storage, worker, or any other external service:

  1. **Ownership boundary (pure).** The real shared ownership guard
     ``assert_pv_command_safe`` is driven with generated command payloads and
     operation names. A payload/operation that carries an EDC-owned clinical
     field, a CTMS-owned operational field, or a competing clinical/operational
     operation is rejected before any state change; a payload built only from
     approved PV safety fields and read-only canonical references is accepted.
     The same guard is the single pre-mutation gate every PV write path calls,
     so rejecting the payload here is what keeps EDC/CTMS content out of PV
     exports, filters, attachments, notifications, and audit writes
     (Requirements 11, 12, 15, 23).

  2. **Projection content + metric exclusion.** The real ``PVDashboardService``
     is driven over an in-memory SQLite database seeded with PV safety cases,
     adverse events, and approved read-only EDC projections. The property checks
     that every surfaced projected field is labeled read-only and source-owned
     (``ownership == "projected"``), carries only an approved minimized field
     name, and that the projected adverse events never change the PV safety
     metric counts — the counts stay identical whether or not any projection is
     present (Requirements 10, 13).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.models.pv.assessment import SeriousnessAssessment
from app.models.pv.coordination import (
    APPROVED_PROJECTION_FIELDS,
    EdcAeProjection,
)
from app.models.pv.safety_case import (
    AdverseEventRecord,
    CaseState,
    SafetyCase,
)
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.schemas.pv.export import PVExportFilters
from app.services.pv_dashboard_service import (
    READ_PERMISSION,
    SERIOUSNESS_NON_SERIOUS,
    SERIOUSNESS_SERIOUS,
    SERIOUSNESS_UNASSESSED,
    PVDashboardService,
)
from app.services.pv_ownership_guard import (
    CTMS_OWNED_FIELDS,
    EDC_OWNED_FIELDS,
    PVOwnershipError,
    assert_pv_command_safe,
)

# ---------------------------------------------------------------------------
# Part 1 — ownership boundary (pure guard, no I/O)
# ---------------------------------------------------------------------------

# Fields PV legitimately owns or references read-only. These must never trip the
# guard: a PV export filter, dashboard request, attachment metadata payload,
# notification payload, audit-search payload, reconciliation request, or a
# minimized projection payload is built only from these.
_ALLOWED_PV_FIELDS: tuple[str, ...] = (
    "case_identifier",
    "case_type",
    "lifecycle_state",
    "verbatim_term",
    "onset_date",
    "outcome",
    "seriousness",
    "narrative_text",
    "reason_for_change",
    "report_type",
    "destination",
    "awareness_date",
    "meddra_term",
    "whodrug_term",
    "coding_dictionary_version",
    # Read-only canonical references the guard explicitly allows.
    "study_id",
    "site_id",
    "subject_reference",
    "visit_instance_id",
    "correlation_id",
)

# A stable pool of prohibited fields drawn from the real guard allowlists so the
# generator always references fields the guard actually owns.
_EDC_FIELDS: tuple[str, ...] = tuple(sorted(EDC_OWNED_FIELDS))
_CTMS_FIELDS: tuple[str, ...] = tuple(sorted(CTMS_OWNED_FIELDS))
_PROHIBITED_FIELDS: tuple[str, ...] = _EDC_FIELDS + _CTMS_FIELDS

_scalar = st.one_of(
    st.text(max_size=12),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
    st.none(),
)


@st.composite
def _clean_pv_payload(draw) -> dict[str, object]:
    """A payload built only from approved PV/canonical fields."""

    keys = draw(
        st.lists(st.sampled_from(_ALLOWED_PV_FIELDS), min_size=0, max_size=6, unique=True)
    )
    return {key: draw(_scalar) for key in keys}


@st.composite
def _payload_with_prohibited_field(draw) -> tuple[dict[str, object], str]:
    """A payload that carries at least one prohibited EDC/CTMS field.

    Returns the payload plus the prohibited field name that was injected. The
    field may be injected at the top level or nested inside a sub-mapping/list so
    the guard's recursive scan is exercised.
    """

    base = draw(_clean_pv_payload())
    prohibited = draw(st.sampled_from(_PROHIBITED_FIELDS))
    placement = draw(st.sampled_from(["top", "nested_dict", "nested_list"]))
    value = draw(_scalar)

    if placement == "top":
        base[prohibited] = value
    elif placement == "nested_dict":
        base["safety_detail"] = {prohibited: value}
    else:  # nested_list
        base["safety_details"] = [{prohibited: value}]
    return base, prohibited


class TestOwnershipBoundaryProperty:
    """The shared guard keeps EDC/CTMS content out of every PV write path."""

    @settings(max_examples=300, deadline=None)
    @given(data=_payload_with_prohibited_field())
    def test_prohibited_field_payload_is_always_rejected(
        self, data: tuple[dict[str, object], str]
    ) -> None:
        """A PV command carrying any EDC/CTMS field is rejected before any write.

        ``assert_pv_command_safe`` is side-effect free, so a raised
        ``PVOwnershipError`` is exactly the "no state changes" guarantee: the PV
        service never opens its mutation transaction for a rejected command.
        """

        payload, _prohibited = data
        with pytest.raises(PVOwnershipError):
            assert_pv_command_safe(payload, operation="create_pv_export")

    @settings(max_examples=200, deadline=None)
    @given(payload=_clean_pv_payload())
    def test_clean_pv_payload_is_accepted(self, payload: dict[str, object]) -> None:
        """A payload built only from PV/canonical fields passes the guard."""

        # Must not raise for any PV operation name.
        assert_pv_command_safe(payload, operation="create_pv_export")
        assert_pv_command_safe(payload, operation="upload_safety_attachment")
        assert_pv_command_safe(payload, operation="run_reconciliation")

    @settings(max_examples=200, deadline=None)
    @given(
        clean=_clean_pv_payload(),
        edc_op=st.sampled_from(
            sorted(
                {
                    "create_subject",
                    "allocate_subject",
                    "update_field_value",
                    "create_query",
                    "freeze_clinical_record",
                    "sign_clinical_record",
                    "upload_clinical_attachment",
                    "create_clinical_export",
                }
            )
        ),
        ctms_op=st.sampled_from(
            sorted(
                {
                    "create_operational_site",
                    "update_enrollment",
                    "assign_task",
                    "upload_operational_attachment",
                    "create_operational_export",
                }
            )
        ),
    )
    def test_competing_operations_are_rejected_even_with_clean_payload(
        self, clean: dict[str, object], edc_op: str, ctms_op: str
    ) -> None:
        """A competing EDC/CTMS operation is rejected regardless of payload.

        Even an otherwise-clean payload cannot smuggle an EDC clinical or CTMS
        operational write through a PV operation (Requirement 23.4, 23.5).
        """

        with pytest.raises(PVOwnershipError):
            assert_pv_command_safe(clean, operation=edc_op)
        with pytest.raises(PVOwnershipError):
            assert_pv_command_safe(clean, operation=ctms_op)

    @settings(max_examples=200, deadline=None)
    @given(
        site_id=st.uuids(),
        subject=st.uuids(),
        prohibited=st.sampled_from(_PROHIBITED_FIELDS),
    )
    def test_export_filters_reject_prohibited_dimensions(
        self, site_id: UUID, subject: UUID, prohibited: str
    ) -> None:
        """PV export filters accept only PV safety dimensions.

        The ``PVExportFilters`` contract forbids extra fields, so an EDC/CTMS
        field can never become an export filter dimension (Requirement 12.6). A
        request built only from PV dimensions validates successfully.
        """

        # A prohibited dimension is rejected by the contract (extra="forbid").
        with pytest.raises(ValueError):
            PVExportFilters.model_validate(
                {"site_id": str(site_id), prohibited: "x"}
            )

        # A PV-only filter set validates.
        filters = PVExportFilters.model_validate(
            {"site_id": str(site_id), "subject_reference": str(subject)}
        )
        assert filters.site_id == site_id
        assert filters.subject_reference == subject


# ---------------------------------------------------------------------------
# Part 2 — projection content + metric exclusion (real dashboard, SQLite)
# ---------------------------------------------------------------------------

_STUDY = UUID(int=0x5AFE)
_SITE = UUID(int=0x51E0)
_NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)


async def _make_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


class _ScopedUser:
    def __init__(self, scope: AuthorizationScope) -> None:
        self.authorization_scope = scope


def _study_scope() -> AuthorizationScope:
    return AuthorizationScope(
        grants=[PermissionGrant(permission_code=READ_PERMISSION, study_id=_STUDY)]
    )


async def _add_case(
    session: AsyncSession, *, state: CaseState
) -> SafetyCase:
    case = SafetyCase(
        case_identifier=f"CASE-{uuid4().hex[:10]}",
        study_id=_STUDY,
        site_id=_SITE,
        subject_reference=uuid4(),
        case_type="Adverse Event",
        lifecycle_state=state.value,
    )
    session.add(case)
    await session.flush()
    return case


async def _add_ae(
    session: AsyncSession, case: SafetyCase, *, serious: bool | None
) -> None:
    ae = AdverseEventRecord(
        case_id=case.id,
        verbatim_term="Headache",
        onset_date=date(2024, 1, 1),
        outcome="Recovered",
    )
    session.add(ae)
    await session.flush()
    if serious is not None:
        session.add(
            SeriousnessAssessment(
                ae_id=ae.id,
                serious=serious,
                criteria=["death"] if serious else [],
            )
        )
        await session.flush()


async def _add_projection(session: AsyncSession, *, status: str) -> None:
    """Seed an approved read-only EDC adverse-event projection."""

    session.add(
        EdcAeProjection(
            source_module="EDC",
            source_record_id=uuid4(),
            source_version="1",
            rule_version=1,
            idempotency_key=uuid4().hex,
            projected_at=_NOW,
            payload_fingerprint="fp",
            projection_status=status,
            study_id=_STUDY,
            site_id=_SITE,
            subject_reference=uuid4(),
            verbatim_term="Nausea",
            onset_date=date(2024, 2, 2),
            seriousness="serious",
            correlation_id="corr",
        )
    )
    await session.flush()


# Each generated case is (lifecycle state, seriousness of its single AE).
_serious = st.sampled_from([True, False, None])
_state = st.sampled_from(list(CaseState))
_cases = st.lists(st.tuples(_state, _serious), min_size=0, max_size=6)
# How many approved Current projections to add on top of the PV records.
_projection_count = st.integers(min_value=0, max_value=4)


@pytest.mark.asyncio
class TestProjectionSeparationProperty:
    """Projections are read-only, source-labeled, and metric-excluded."""

    @settings(
        max_examples=120,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(cases=_cases, current_projections=_projection_count, stale_projections=_projection_count)
    async def test_projections_are_readonly_labeled_and_excluded_from_metrics(
        self,
        cases: list[tuple[CaseState, bool | None]],
        current_projections: int,
        stale_projections: int,
    ) -> None:
        session, engine = await _make_session()
        try:
            # Seed PV safety records.
            for state, serious in cases:
                case = await _add_case(session, state=state)
                await _add_ae(session, case, serious=serious)

            # Compute the PV-only metric baseline BEFORE any projection exists.
            service = PVDashboardService()
            user = _ScopedUser(_study_scope())
            baseline = await service.study_dashboard(
                session, _STUDY, user, now=_NOW
            )

            # Now add approved Current projections (and some Stale ones that must
            # never be surfaced) and recompute.
            for _ in range(current_projections):
                await _add_projection(session, status="Current")
            for _ in range(stale_projections):
                await _add_projection(session, status="Stale")

            after = await service.study_dashboard(session, _STUDY, user, now=_NOW)

            # Metric exclusion: projected adverse events never change any PV
            # safety metric count (Requirements 10, 13.5).
            assert after.case_counts_by_status == baseline.case_counts_by_status
            assert (
                after.adverse_event_counts_by_seriousness
                == baseline.adverse_event_counts_by_seriousness
            )
            assert after.report_counts_by_status == baseline.report_counts_by_status
            assert after.reporting_compliance == baseline.reporting_compliance

            # The seriousness counts derive only from PV records, never from the
            # "serious" projections just added.
            expected_serious = sum(1 for _s, ser in cases if ser is True)
            expected_non_serious = sum(1 for _s, ser in cases if ser is False)
            expected_unassessed = sum(1 for _s, ser in cases if ser is None)
            counts = after.adverse_event_counts_by_seriousness
            assert counts.get(SERIOUSNESS_SERIOUS, 0) == expected_serious
            assert counts.get(SERIOUSNESS_NON_SERIOUS, 0) == expected_non_serious
            assert counts.get(SERIOUSNESS_UNASSESSED, 0) == expected_unassessed

            # Only Current projections are surfaced, one entry per approved
            # minimized field, each labeled read-only and source-owned.
            assert len(after.projected_fields) == current_projections * len(
                APPROVED_PROJECTION_FIELDS
            )
            for field in after.projected_fields:
                assert field.read_only is True
                assert field.ownership == "projected"
                assert field.field_name in APPROVED_PROJECTION_FIELDS
                assert field.source_module == "EDC"
        finally:
            await session.close()
            await engine.dispose()
