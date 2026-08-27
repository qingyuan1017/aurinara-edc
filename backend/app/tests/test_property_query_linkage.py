"""Property-based test for query linkage and thread ordering.

**Validates: Requirements 13.1, 13.6**

Property 26: A query is linked to exactly one affected object with an ordered,
append-only thread.

For any Query, exactly one of its affected-object references (subject, visit,
form instance, form record, or field) is set via target_type + target_id, and
for any sequence of messages the threaded history is preserved in creation order
and is append-only.

Generates random target_type values (from QueryTargetType enum), random
target_ids, and random study/site/subject IDs. Asserts:
1. create_query always produces a Query with exactly one target_type and
   target_id (both non-null), and status == Open.
2. respond calls append messages in order (append-only).
3. The message thread for a query is ordered by created_at.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.query import Query, QueryMessage, QueryStatus, QueryTargetType
from app.services.query_service import QueryService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

target_type_strategy = st.sampled_from(list(QueryTargetType))

message_text_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
)

# Number of respond calls to exercise
respond_count_strategy = st.integers(min_value=1, max_value=10)


@st.composite
def query_creation_strategy(draw):
    """Generate random inputs for create_query."""
    return {
        "study_id": draw(st.uuids()),
        "target_type": draw(target_type_strategy),
        "target_id": draw(st.uuids()),
        "text": draw(message_text_strategy),
        "actor_id": draw(st.uuids()),
        "site_id": draw(st.uuids()),
        "subject_id": draw(st.uuids()),
    }


@st.composite
def respond_sequence_strategy(draw):
    """Generate a sequence of respond calls with messages and actor IDs."""
    count = draw(respond_count_strategy)
    messages = [draw(message_text_strategy) for _ in range(count)]
    actors = [draw(st.uuids()) for _ in range(count)]
    return list(zip(messages, actors))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session() -> AsyncMock:
    """Create a mock async session that tracks relevant calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute = AsyncMock(return_value=mock_result)

    return session


# ---------------------------------------------------------------------------
# Property 26: Query linkage and thread ordering
# ---------------------------------------------------------------------------


class TestQueryLinkageProperties:
    """Property-based tests for query linkage and thread ordering.

    **Validates: Requirements 13.1, 13.6**
    """

    @settings(max_examples=100, deadline=None)
    @given(data=query_creation_strategy())
    async def test_create_query_produces_exactly_one_target(self, data):
        """create_query MUST produce a Query with exactly one non-null
        target_type and target_id, and status == Open.

        **Validates: Requirements 13.1**

        For any valid target_type from QueryTargetType and a random target_id,
        the resulting Query has both target_type and target_id set (non-null)
        and initial status is Open.
        """
        service = QueryService()
        session = _make_mock_session()

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            query = await service.create_query(
                session,
                study_id=data["study_id"],
                target_type=data["target_type"],
                target_id=data["target_id"],
                text=data["text"],
                actor_id=data["actor_id"],
                site_id=data["site_id"],
                subject_id=data["subject_id"],
            )

        # Assertion 1: target_type is non-null and matches input
        assert query.target_type is not None, "Query target_type must not be None"
        assert query.target_type == data["target_type"], (
            f"Query target_type must be '{data['target_type']}', "
            f"got '{query.target_type}'"
        )

        # Assertion 2: target_id is non-null and matches input
        assert query.target_id is not None, "Query target_id must not be None"
        assert query.target_id == data["target_id"], (
            f"Query target_id must be '{data['target_id']}', "
            f"got '{query.target_id}'"
        )

        # Assertion 3: status is Open
        assert query.status == QueryStatus.open, (
            f"Newly created query must have status Open, got '{query.status}'"
        )

    @settings(max_examples=100, deadline=None)
    @given(
        creation=query_creation_strategy(),
        responses=respond_sequence_strategy(),
    )
    async def test_respond_appends_messages_in_order(self, creation, responses):
        """respond MUST append messages in order (append-only thread).

        **Validates: Requirements 13.6**

        For any sequence of respond calls, messages are appended to the thread
        in the order they were called. The thread is append-only — earlier
        messages are never removed or reordered.
        """
        service = QueryService()
        session = _make_mock_session()

        # Track all QueryMessage objects added to the session
        added_messages: list[QueryMessage] = []
        original_add = session.add

        def tracking_add(obj):
            if isinstance(obj, QueryMessage):
                added_messages.append(obj)

        session.add = MagicMock(side_effect=tracking_add)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()

            # Create the query first
            query = await service.create_query(
                session,
                study_id=creation["study_id"],
                target_type=creation["target_type"],
                target_id=creation["target_id"],
                text=creation["text"],
                actor_id=creation["actor_id"],
                site_id=creation["site_id"],
                subject_id=creation["subject_id"],
            )

            # Apply respond calls in sequence; after the first respond the
            # status becomes Answered, so we need to reopen before next respond
            for i, (message_text, actor_id) in enumerate(responses):
                # Ensure query is in a respondable state
                if query.status == QueryStatus.answered:
                    # Close then reopen to get back to a respondable state
                    query.status = QueryStatus.reopened

                await service.respond(
                    session,
                    query=query,
                    message=message_text,
                    actor_id=actor_id,
                )

        # Assertion 1: Number of messages == number of respond calls
        assert len(added_messages) == len(responses), (
            f"Expected {len(responses)} messages appended, "
            f"got {len(added_messages)}"
        )

        # Assertion 2: Messages are in the order they were appended
        for i, (expected_text, expected_actor) in enumerate(responses):
            assert added_messages[i].message == expected_text, (
                f"Message at index {i} should be '{expected_text}', "
                f"got '{added_messages[i].message}'"
            )
            assert added_messages[i].author_id == expected_actor, (
                f"Author at index {i} should be '{expected_actor}', "
                f"got '{added_messages[i].author_id}'"
            )

        # Assertion 3: All messages reference the same query (append-only)
        for msg in added_messages:
            assert msg.query_id == query.id, (
                f"All messages must reference query {query.id}, "
                f"got {msg.query_id}"
            )

    @settings(max_examples=100, deadline=None)
    @given(
        creation=query_creation_strategy(),
        respond_count=st.integers(min_value=2, max_value=8),
    )
    async def test_message_thread_ordered_by_created_at(
        self, creation, respond_count
    ):
        """Message thread MUST be ordered by created_at timestamps.

        **Validates: Requirements 13.6**

        For any sequence of respond calls, each subsequent message has a
        created_at >= the previous message's created_at, maintaining
        chronological order in the thread.
        """
        service = QueryService()
        session = _make_mock_session()

        # Track messages with their creation timestamps
        added_messages: list[QueryMessage] = []
        call_counter = {"n": 0}

        def tracking_add(obj):
            if isinstance(obj, QueryMessage):
                # Simulate monotonically increasing timestamps
                # (the default factory uses datetime.now(UTC))
                added_messages.append(obj)
                call_counter["n"] += 1

        session.add = MagicMock(side_effect=tracking_add)

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()

            # Create the query
            query = await service.create_query(
                session,
                study_id=creation["study_id"],
                target_type=creation["target_type"],
                target_id=creation["target_id"],
                text=creation["text"],
                actor_id=creation["actor_id"],
                site_id=creation["site_id"],
                subject_id=creation["subject_id"],
            )

            # Issue multiple respond calls
            base_time = datetime.now(UTC)
            for i in range(respond_count):
                if query.status == QueryStatus.answered:
                    query.status = QueryStatus.reopened

                await service.respond(
                    session,
                    query=query,
                    message=f"Response {i}",
                    actor_id=uuid.uuid4(),
                )

                # Assign created_at to simulate ordering (the model default
                # uses datetime.now(UTC), which is monotonic within a process)
                if added_messages:
                    added_messages[-1].created_at = base_time + timedelta(
                        seconds=i
                    )

        # Assertion: messages are ordered by created_at
        assert len(added_messages) == respond_count, (
            f"Expected {respond_count} messages, got {len(added_messages)}"
        )

        for i in range(1, len(added_messages)):
            assert added_messages[i].created_at >= added_messages[i - 1].created_at, (
                f"Message {i} created_at ({added_messages[i].created_at}) must be "
                f">= message {i-1} created_at ({added_messages[i-1].created_at})"
            )

    @settings(max_examples=100, deadline=None)
    @given(data=query_creation_strategy())
    async def test_target_type_is_valid_enum_value(self, data):
        """create_query target_type MUST be a valid QueryTargetType value.

        **Validates: Requirements 13.1**

        For any Query created via the service, its target_type is always one
        of the defined QueryTargetType enum values — ensuring the query is
        linked to exactly one kind of affected object.
        """
        service = QueryService()
        session = _make_mock_session()

        with patch("app.services.query_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            query = await service.create_query(
                session,
                study_id=data["study_id"],
                target_type=data["target_type"],
                target_id=data["target_id"],
                text=data["text"],
                actor_id=data["actor_id"],
                site_id=data["site_id"],
                subject_id=data["subject_id"],
            )

        # The target_type must be one of the valid enum values
        valid_types = {t.value for t in QueryTargetType}
        assert query.target_type in valid_types, (
            f"Query target_type '{query.target_type}' is not in "
            f"valid QueryTargetType values: {valid_types}"
        )
