"""Property-based tests for visit window status computation.

**Validates: Requirements 8.3**

Uses Hypothesis to verify that compute_window_status correctly classifies
day offsets relative to a target day and configured window bounds.
"""

from hypothesis import given, settings, strategies as st

from app.services.visit_service import (
    WINDOW_AFTER,
    WINDOW_BEFORE,
    WINDOW_IN,
    compute_window_status,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

target_day_strategy = st.integers(min_value=1, max_value=365)
window_before_strategy = st.integers(min_value=0, max_value=30)
window_after_strategy = st.integers(min_value=0, max_value=30)
day_offset_strategy = st.integers(min_value=0, max_value=400)


# ---------------------------------------------------------------------------
# Property 13: Visit window status is computed correctly
# ---------------------------------------------------------------------------


class TestVisitWindowStatusProperties:
    """Property-based tests for compute_window_status.

    **Validates: Requirements 8.3**
    """

    @settings(max_examples=200)
    @given(
        target_day=target_day_strategy,
        window_before=window_before_strategy,
        window_after=window_after_strategy,
        day_offset=day_offset_strategy,
    )
    def test_before_window_when_offset_below_lower_bound(
        self,
        target_day: int,
        window_before: int,
        window_after: int,
        day_offset: int,
    ):
        """Returns 'before_window' when day_offset < (target_day - window_before)."""
        lower_bound = target_day - window_before

        result = compute_window_status(target_day, window_before, window_after, day_offset)

        if day_offset < lower_bound:
            assert result == WINDOW_BEFORE

    @settings(max_examples=200)
    @given(
        target_day=target_day_strategy,
        window_before=window_before_strategy,
        window_after=window_after_strategy,
        day_offset=day_offset_strategy,
    )
    def test_in_window_when_offset_within_bounds(
        self,
        target_day: int,
        window_before: int,
        window_after: int,
        day_offset: int,
    ):
        """Returns 'in_window' when (target_day - window_before) <= day_offset <= (target_day + window_after)."""
        lower_bound = target_day - window_before
        upper_bound = target_day + window_after

        result = compute_window_status(target_day, window_before, window_after, day_offset)

        if lower_bound <= day_offset <= upper_bound:
            assert result == WINDOW_IN

    @settings(max_examples=200)
    @given(
        target_day=target_day_strategy,
        window_before=window_before_strategy,
        window_after=window_after_strategy,
        day_offset=day_offset_strategy,
    )
    def test_after_window_when_offset_above_upper_bound(
        self,
        target_day: int,
        window_before: int,
        window_after: int,
        day_offset: int,
    ):
        """Returns 'after_window' when day_offset > (target_day + window_after)."""
        upper_bound = target_day + window_after

        result = compute_window_status(target_day, window_before, window_after, day_offset)

        if day_offset > upper_bound:
            assert result == WINDOW_AFTER

    @settings(max_examples=200)
    @given(
        target_day=st.none(),
        window_before=window_before_strategy | st.none(),
        window_after=window_after_strategy | st.none(),
        day_offset=day_offset_strategy | st.none(),
    )
    def test_none_target_day_returns_none(
        self,
        target_day,
        window_before,
        window_after,
        day_offset,
    ):
        """Returns None when target_day is None."""
        result = compute_window_status(target_day, window_before, window_after, day_offset)
        assert result is None

    @settings(max_examples=200)
    @given(
        target_day=target_day_strategy,
        window_before=window_before_strategy | st.none(),
        window_after=window_after_strategy | st.none(),
        day_offset=st.none(),
    )
    def test_none_day_offset_returns_none(
        self,
        target_day: int,
        window_before,
        window_after,
        day_offset,
    ):
        """Returns None when day_offset is None."""
        result = compute_window_status(target_day, window_before, window_after, day_offset)
        assert result is None
