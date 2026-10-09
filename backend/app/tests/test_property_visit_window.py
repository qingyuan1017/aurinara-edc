"""Property-based test for Visit_Definition window validity (round-trip subset).

# Feature: designer-edc-refactor, Property 9: Designer definition persistence round-trip

**Validates: Requirements 4.1, 4.2, 4.4, 4.6, 4.7, 4.8**

This file is the **visit-definition / window-validity subset** of Property 9. The
broader Property 9 round-trip across every Designer_Definition kind is written by
task 7.6 (``test_property_designer_round_trip`` or equivalent); this file stays
scoped to visit definitions and their window bounds so the two tests do not
overlap.

Property 9 (design.md): _For all_ valid Designer_Definitions (visit definitions
included), persisting then reading the definition back through the Designer
module yields values equal to those submitted.

Focused here on the window-validity slice of the acceptance criteria:

  - R4.2: A Visit_Definition persists name (1-100), visit number (1-9999),
          integer target day (0-99999), and integer lower/upper window bounds
          (0-99999) where the lower bound is no greater than the upper bound.
  - R4.3: A Visit_Definition whose lower window bound exceeds its upper window
          bound is rejected, nothing is persisted, and the error identifies the
          invalid window. (Exercised as the invalid-window branch of the
          strategy; R4.3 is a boundary/error criterion within Property 9.)

The strategy embeds **both** valid windows (lower <= upper, which must round-trip)
and invalid windows (inverted, which must be rejected with nothing persisted) so a
single property covers the accept and reject paths together.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.core.exceptions import ValidationError
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import Study, StudyStatus
from app.schemas.designer.visit import (
    TARGET_DAY_MAX,
    TARGET_DAY_MIN,
    VISIT_NUMBER_MAX,
    VISIT_NUMBER_MIN,
    WINDOW_BOUND_MAX,
    WINDOW_BOUND_MIN,
    VisitDefinitionCreate,
)
from app.services.designer.visit_definition_service import VisitDefinitionService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Names constrained to the valid 1-100 character window (R4.2). Boundary lengths
# 1 and 100 are emphasised so the strategy exercises the inclusive edges.
_names = st.one_of(
    st.text(
        alphabet=st.characters(categories=("L", "N", "P", "Zs")),
        min_size=1,
        max_size=100,
    ).filter(lambda value: 1 <= len(value) <= 100),
    st.just("V"),  # minimum length
    st.just("v" * 100),  # maximum length
)

_visit_numbers = st.integers(min_value=VISIT_NUMBER_MIN, max_value=VISIT_NUMBER_MAX)
_visit_types = st.sampled_from(["scheduled", "unscheduled", "screening"])
_target_days = st.one_of(
    st.none(),
    st.integers(min_value=TARGET_DAY_MIN, max_value=TARGET_DAY_MAX),
)
_window_bounds = st.integers(min_value=WINDOW_BOUND_MIN, max_value=WINDOW_BOUND_MAX)
_display_orders = st.integers(min_value=0, max_value=9999)
_booleans = st.booleans()


@st.composite
def _valid_visit_definitions(draw: st.DrawFn) -> VisitDefinitionCreate:
    """A schema-valid Visit_Definition with a consistent (lower <= upper) window.

    Because the schema constrains both window offsets to be >= 0, any pair of
    schema-valid offsets already yields a window whose lower edge
    (``-window_before``) is no greater than its upper edge (``+window_after``).
    One or both bounds may be omitted (open window) to exercise the optional
    paths too.
    """
    window_before = draw(st.one_of(st.none(), _window_bounds))
    window_after = draw(st.one_of(st.none(), _window_bounds))
    return VisitDefinitionCreate(
        name=draw(_names),
        visit_number=draw(_visit_numbers),
        visit_type=draw(_visit_types),
        target_day=draw(_target_days),
        window_before=window_before,
        window_after=window_after,
        display_order=draw(_display_orders),
        is_required=draw(_booleans),
    )


@st.composite
def _inverted_visit_definitions(draw: st.DrawFn) -> VisitDefinitionCreate:
    """An inverted-window Visit_Definition the service must reject (R4.3).

    The acceptable window is ``[target_day - window_before, target_day +
    window_after]``; the lower edge is ``-window_before`` and the upper edge is
    ``+window_after``. The window is inverted when ``-window_before >
    window_after``, which requires a *negative* ``window_before``. The create
    schema forbids negative bounds, so a genuinely inverted window can only be
    constructed by bypassing schema validation via ``model_construct`` — the
    service's own window guard is the layer under test here.
    """
    # Choose edges so the lower edge strictly exceeds the upper edge.
    window_after = draw(st.integers(min_value=0, max_value=WINDOW_BOUND_MAX))
    # window_before negative with magnitude large enough to invert the window:
    #   lower_edge = -window_before > window_after  =>  window_before < -window_after
    window_before = draw(
        st.integers(min_value=-WINDOW_BOUND_MAX, max_value=-(window_after + 1))
    )
    return VisitDefinitionCreate.model_construct(
        name=draw(_names),
        visit_number=draw(_visit_numbers),
        visit_type=draw(_visit_types),
        target_day=draw(_target_days),
        window_before=window_before,
        window_after=window_after,
        display_order=draw(_display_orders),
        is_required=draw(_booleans),
    )


# One strategy embedding both the valid and invalid window cases, tagged so the
# property body can branch on the expected outcome.
visit_definition_cases = st.one_of(
    _valid_visit_definitions().map(lambda data: ("valid", data)),
    _inverted_visit_definitions().map(lambda data: ("invalid", data)),
)


# ---------------------------------------------------------------------------
# In-memory async session helpers
# ---------------------------------------------------------------------------


async def _make_draft_version(session: AsyncSession) -> StudyVersion:
    """Create a Study and a draft Design_Version to own the visit definition."""
    study = Study(
        study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
        title="Visit Window Property Study",
        status=StudyStatus.draft,
        created_by=uuid.uuid4(),
    )
    session.add(study)
    await session.flush()

    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
    )
    session.add(version)
    await session.flush()
    return version


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


@given(case=visit_definition_cases)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@pytest.mark.asyncio
async def test_visit_window_validity_round_trip(
    case: tuple[str, VisitDefinitionCreate],
) -> None:
    """Valid windows round-trip; inverted windows are rejected with nothing saved.

    Validates Property 9 for the visit-definition subset (R4.1, R4.2, R4.4, R4.6-
    R4.8), with the inverted-window rejection covering the R4.3 boundary.
    """
    kind, data = case
    service = VisitDefinitionService()
    actor_id = uuid.uuid4()

    # A fresh in-memory database per example keeps the examples independent.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            version = await _make_draft_version(session)
            version_id = version.id

            if kind == "valid":
                definition = await service.define_visit(
                    session, version, data, actor_id
                )
                definition_id = definition.id

                # The in-memory instance mirrors every submitted field (R4.2).
                assert definition.study_version_id == version_id
                assert definition.name == data.name
                assert definition.visit_number == data.visit_number
                assert definition.visit_type == data.visit_type
                assert definition.target_day == data.target_day
                assert definition.window_before == data.window_before
                assert definition.window_after == data.window_after
                assert definition.display_order == data.display_order
                assert definition.is_required == data.is_required

                await session.commit()
            else:
                # An inverted window is rejected and the error names the window
                # (R4.3) — the lower bound exceeding the upper bound.
                with pytest.raises(ValidationError) as exc_info:
                    await service.define_visit(session, version, data, actor_id)

                details = exc_info.value.details
                assert details["window_before"] == data.window_before
                assert details["window_after"] == data.window_after
                assert details["visit_name"] == data.name

                # Nothing is persisted on rejection (R4.3 — persist nothing).
                count = (
                    await session.execute(
                        select(func.count()).select_from(VisitDefinition)
                    )
                ).scalar_one()
                assert count == 0
                return

        # Round-trip through a *fresh* session read: persisted values equal those
        # submitted (Property 9 — persistence round-trip). Reading only the mapped
        # columns avoids triggering the ``selectin`` relationship load.
        async with factory() as read_session:
            stored = (
                await read_session.execute(
                    select(VisitDefinition).where(VisitDefinition.id == definition_id)
                )
            ).scalar_one()
            assert stored.study_version_id == version_id
            assert stored.name == data.name
            assert stored.visit_number == data.visit_number
            assert stored.visit_type == data.visit_type
            assert stored.target_day == data.target_day
            assert stored.window_before == data.window_before
            assert stored.window_after == data.window_after
            assert stored.display_order == data.display_order
            assert stored.is_required == data.is_required
    finally:
        await engine.dispose()
