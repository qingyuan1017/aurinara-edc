"""Property-based tests for audit search filter construction.

**Validates: Requirements 18.5**

Uses Hypothesis to verify that AuditService.search() correctly applies all
non-None filters as WHERE clauses and ignores None-valued filters. Since we
don't have a live DB, we mock the session and inspect the constructed query
to verify filter application logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings, strategies as st
from sqlalchemy import BinaryExpression

from app.core.audit import AuditService
from app.models.audit import AuditEvent
from app.schemas.audit import AuditSearchFilters


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

uuid_strategy = st.uuids()

entity_type_strategy = st.sampled_from([
    "subject", "form_instance", "study", "site", "visit_instance",
    "form_record", "field_value", "query", "user", "role",
])

action_strategy = st.sampled_from([
    "create", "update", "delete", "submit", "sign",
    "freeze", "lock", "unlock", "review", "sdv",
])

field_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=50,
)

# Datetime strategy: reasonable clinical trial date range
datetime_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(UTC),
)


@st.composite
def audit_search_filters_strategy(draw):
    """Generate arbitrary AuditSearchFilters with random combinations of fields.

    Each field is independently either None or a valid random value, producing
    a wide variety of filter combinations (all None, all set, mixed).
    """
    actor_id = draw(st.one_of(st.none(), uuid_strategy))
    entity_type = draw(st.one_of(st.none(), entity_type_strategy))
    entity_id = draw(st.one_of(st.none(), uuid_strategy))
    study_id = draw(st.one_of(st.none(), uuid_strategy))
    site_id = draw(st.one_of(st.none(), uuid_strategy))
    subject_id = draw(st.one_of(st.none(), uuid_strategy))
    field_name = draw(st.one_of(st.none(), field_name_strategy))
    request_id = draw(st.one_of(st.none(), uuid_strategy))
    action = draw(st.one_of(st.none(), action_strategy))

    # For date_from and date_to, ensure date_from <= date_to when both set
    date_from = draw(st.one_of(st.none(), datetime_strategy))
    date_to = draw(st.one_of(st.none(), datetime_strategy))
    if date_from is not None and date_to is not None and date_from > date_to:
        date_from, date_to = date_to, date_from

    return AuditSearchFilters(
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        study_id=study_id,
        site_id=site_id,
        subject_id=subject_id,
        field_name=field_name,
        date_from=date_from,
        date_to=date_to,
        request_id=request_id,
        action=action,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Mapping from filter field name to the corresponding AuditEvent column name
FILTER_TO_COLUMN = {
    "actor_id": "actor_id",
    "entity_type": "entity_type",
    "entity_id": "entity_id",
    "study_id": "study_id",
    "site_id": "site_id",
    "subject_id": "subject_id",
    "field_name": "field_name",
    "action": "action",
    "request_id": "request_id",
    "date_from": "timestamp",
    "date_to": "timestamp",
}


def count_non_none_filters(filters: AuditSearchFilters) -> int:
    """Count how many filter fields are set (non-None)."""
    count = 0
    for field_name in FILTER_TO_COLUMN:
        value = getattr(filters, field_name)
        if value is not None:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Property 20: Audit search matches its filters
# ---------------------------------------------------------------------------


class TestAuditSearchFilterProperties:
    """Property-based tests for audit search filter application.

    **Validates: Requirements 18.5**
    """

    @settings(max_examples=150)
    @given(filters=audit_search_filters_strategy())
    def test_filters_model_accepts_arbitrary_valid_combinations(
        self, filters: AuditSearchFilters
    ):
        """AuditSearchFilters model correctly accepts all valid filter combinations.

        Any combination of None/non-None values for all filter fields is
        a valid AuditSearchFilters instance.
        """
        # The model should always be constructible from valid inputs
        assert isinstance(filters, AuditSearchFilters)

        # Verify round-trip: all fields are accessible
        for field_name in FILTER_TO_COLUMN:
            # Should not raise
            getattr(filters, field_name)

    @settings(max_examples=150)
    @given(filters=audit_search_filters_strategy())
    @pytest.mark.asyncio
    async def test_non_none_filters_produce_where_clauses(
        self, filters: AuditSearchFilters
    ):
        """Only non-None filters should produce WHERE clauses in the query.

        We intercept the query passed to `paginate` and count the number of
        WHERE clause elements. Each non-None filter should add exactly one
        constraint.
        """
        service = AuditService()
        mock_session = AsyncMock()

        captured_query = {}

        async def fake_paginate(session, query, params):
            """Capture the query for inspection."""
            captured_query["query"] = query
            # Return a minimal paginated response
            from app.schemas.base import PaginatedResponse

            return PaginatedResponse(items=[], page=1, page_size=25, total=0)

        with patch("app.core.audit.paginate", side_effect=fake_paginate):
            await service.search(session=mock_session, filters=filters)

        # Extract the WHERE clause from the captured query
        query = captured_query["query"]
        whereclause = query.whereclause

        expected_count = count_non_none_filters(filters)

        if expected_count == 0:
            # No filters -> no WHERE clause
            assert whereclause is None, (
                "Expected no WHERE clause when all filters are None"
            )
        else:
            assert whereclause is not None, (
                f"Expected WHERE clause with {expected_count} non-None filters"
            )
            # Count the clauses: SQLAlchemy AND-chains BooleanClauseList
            # When there's only one filter, it's a direct BinaryExpression
            # When there are multiple, they're joined with AND
            if hasattr(whereclause, "clauses"):
                actual_count = len(list(whereclause.clauses))
            else:
                # Single clause (BinaryExpression)
                actual_count = 1

            assert actual_count == expected_count, (
                f"Expected {expected_count} WHERE clauses for non-None filters, "
                f"got {actual_count}"
            )

    @settings(max_examples=150)
    @given(filters=audit_search_filters_strategy())
    @pytest.mark.asyncio
    async def test_search_handles_all_filter_combinations_without_error(
        self, filters: AuditSearchFilters
    ):
        """AuditService.search() handles all filter combinations without raising."""
        service = AuditService()
        mock_session = AsyncMock()

        async def fake_paginate(session, query, params):
            from app.schemas.base import PaginatedResponse

            return PaginatedResponse(items=[], page=1, page_size=25, total=0)

        with patch("app.core.audit.paginate", side_effect=fake_paginate):
            # Should not raise for any valid filter combination
            result = await service.search(session=mock_session, filters=filters)

        # Result should always be a PaginatedResponse
        from app.schemas.base import PaginatedResponse

        assert isinstance(result, PaginatedResponse)

    @settings(max_examples=150)
    @given(filters=audit_search_filters_strategy())
    @pytest.mark.asyncio
    async def test_none_filters_do_not_add_constraints(
        self, filters: AuditSearchFilters
    ):
        """Filters with None values must not add any WHERE constraints.

        We verify that the number of WHERE clauses exactly matches the number
        of non-None filter fields — meaning None fields contribute zero clauses.
        """
        service = AuditService()
        mock_session = AsyncMock()

        captured_query = {}

        async def fake_paginate(session, query, params):
            captured_query["query"] = query
            from app.schemas.base import PaginatedResponse

            return PaginatedResponse(items=[], page=1, page_size=25, total=0)

        with patch("app.core.audit.paginate", side_effect=fake_paginate):
            await service.search(session=mock_session, filters=filters)

        query = captured_query["query"]
        whereclause = query.whereclause

        # Count None fields
        none_count = sum(
            1 for field_name in FILTER_TO_COLUMN
            if getattr(filters, field_name) is None
        )
        non_none_count = len(FILTER_TO_COLUMN) - none_count

        if non_none_count == 0:
            assert whereclause is None
        else:
            if hasattr(whereclause, "clauses"):
                actual_clauses = len(list(whereclause.clauses))
            else:
                actual_clauses = 1
            # The number of actual clauses should equal non-None fields,
            # proving that None fields added nothing.
            assert actual_clauses == non_none_count
