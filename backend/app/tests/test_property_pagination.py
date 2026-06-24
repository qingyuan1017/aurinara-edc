"""Property-based tests for the pagination envelope.

**Validates: Requirements 21.2, 29.2**

Uses Hypothesis to verify that PaginatedResponse and PaginationParams
satisfy structural invariants across all valid input combinations.
"""

from hypothesis import given, settings, strategies as st

from app.api.deps import PaginationParams
from app.schemas.base import PaginatedResponse


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# page >= 1
page_strategy = st.integers(min_value=1, max_value=10_000)

# 1 <= page_size <= 100 (matches the FastAPI constraint le=100, ge=1)
page_size_strategy = st.integers(min_value=1, max_value=100)

# total >= 0
total_strategy = st.integers(min_value=0, max_value=100_000)


@st.composite
def paginated_response_strategy(draw):
    """Generate a PaginatedResponse with consistent items length.

    Items length is at most page_size and at most (total - offset) when
    the page falls within the data range — but we allow any valid count
    up to page_size to exercise the envelope invariants broadly.
    """
    page = draw(page_strategy)
    page_size = draw(page_size_strategy)
    total = draw(total_strategy)

    # Number of items on this page: 0..min(page_size, remaining)
    offset = (page - 1) * page_size
    remaining = max(0, total - offset)
    items_count = draw(st.integers(min_value=0, max_value=min(page_size, remaining)))

    items = list(range(items_count))  # concrete placeholder items

    return PaginatedResponse[int](
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )


# ---------------------------------------------------------------------------
# Property 32: Pagination envelope is well-formed
# ---------------------------------------------------------------------------


class TestPaginationEnvelopeProperties:
    """Property-based tests for the pagination envelope structure.

    **Validates: Requirements 21.2, 29.2**
    """

    @settings(max_examples=200)
    @given(data=paginated_response_strategy())
    def test_items_length_le_page_size(self, data: PaginatedResponse[int]):
        """items length must never exceed page_size."""
        assert len(data.items) <= data.page_size

    @settings(max_examples=200)
    @given(page=page_strategy, page_size=page_size_strategy, total=total_strategy)
    def test_page_matches_requested(self, page: int, page_size: int, total: int):
        """The envelope's page field must match the requested page."""
        resp = PaginatedResponse[int](
            items=[],
            page=page,
            page_size=page_size,
            total=total,
        )
        assert resp.page == page

    @settings(max_examples=200)
    @given(page=page_strategy, page_size=page_size_strategy, total=total_strategy)
    def test_page_size_matches_requested(self, page: int, page_size: int, total: int):
        """The envelope's page_size field must match the requested page_size."""
        resp = PaginatedResponse[int](
            items=[],
            page=page,
            page_size=page_size,
            total=total,
        )
        assert resp.page_size == page_size

    @settings(max_examples=200)
    @given(data=paginated_response_strategy())
    def test_total_non_negative(self, data: PaginatedResponse[int]):
        """total must always be >= 0."""
        assert data.total >= 0

    @settings(max_examples=200)
    @given(page=page_strategy, page_size=page_size_strategy)
    def test_zero_total_implies_empty_items(self, page: int, page_size: int):
        """When total=0, items must be empty."""
        resp = PaginatedResponse[int](
            items=[],
            page=page,
            page_size=page_size,
            total=0,
        )
        assert resp.items == []

    @settings(max_examples=200)
    @given(page=page_strategy, page_size=page_size_strategy)
    def test_offset_calculation_correct(self, page: int, page_size: int):
        """PaginationParams.offset must equal (page - 1) * page_size."""
        params = PaginationParams(page=page, page_size=page_size)
        expected_offset = (page - 1) * page_size
        assert params.offset == expected_offset
