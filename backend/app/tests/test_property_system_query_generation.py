"""Property-based test for query-severity system-query generation.

# Feature: clinical-edc-system, Property 25: Query-severity checks generate a linked system query
**Validates: Requirements 12.5**

For every matched query-severity edit check, runtime evaluation must request
exactly one system Query linked to the affected Form_Instance. Nonmatching
conditions must not request a Query.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.edit_check import EditCheck
from app.models.form_data import FormInstance
from app.models.query import QueryTargetType, QueryType
from app.services.edit_check_service import EditCheckService

# Feature: clinical-edc-system, Property 25: Query-severity checks generate a linked system query


@st.composite
def query_evaluation_scenario(draw: st.DrawFn) -> tuple[int, int, bool]:
    """Generate matching and nonmatching values for an equality query rule."""
    expected = draw(st.integers(min_value=-10**9, max_value=10**9))
    matches = draw(st.booleans())
    observed = expected if matches else expected + 1
    return expected, observed, matches


class TestSystemQueryGenerationProperty:
    """Property-based coverage for runtime query-severity generation."""

    @settings(max_examples=100, deadline=None)
    @given(scenario=query_evaluation_scenario())
    @pytest.mark.asyncio
    async def test_query_severity_creates_one_linked_query_only_when_matched(
        self, scenario: tuple[int, int, bool]
    ):
        """A match creates one linked system Query; a nonmatch creates none.

        **Validates: Requirements 12.5**
        """
        expected, observed, matches = scenario
        form_id = uuid4()
        subject_id = uuid4()
        study_id = uuid4()
        site_id = uuid4()
        actor_id = uuid4()
        form = FormInstance(
            id=form_id,
            subject_id=subject_id,
            form_definition_id=uuid4(),
            data_jsonb={"value": observed},
        )
        edit_check = EditCheck(
            id=uuid4(),
            study_version_id=uuid4(),
            name="Value must match expected value",
            description="The value does not match the expected value.",
            rule_json={"field": "value", "operator": "==", "value": expected},
            severity="query",
            is_active=True,
        )
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.get = AsyncMock(
            return_value=SimpleNamespace(study_id=study_id, site_id=site_id)
        )
        query_service = MagicMock()
        query_service.create_query = AsyncMock()
        service = EditCheckService(query_service_instance=query_service)

        with patch("app.services.edit_check_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.evaluate_edit_check(
                session,
                form,
                edit_check,
                actor_id=actor_id,
                sample_data=form.data_jsonb,
            )

        if matches:
            assert result is not None
            assert query_service.create_query.await_count == 1
            query_kwargs = query_service.create_query.call_args.kwargs
            assert query_kwargs == {
                "study_id": study_id,
                "site_id": site_id,
                "subject_id": subject_id,
                "target_type": QueryTargetType.form_instance,
                "target_id": form_id,
                "text": edit_check.description,
                "actor_id": actor_id,
                "query_type": QueryType.system,
            }
        else:
            assert result is None
            query_service.create_query.assert_not_awaited()

        # A query, when created, is linked to exactly this one affected object.
        if query_service.create_query.await_count:
            query_kwargs = query_service.create_query.call_args.kwargs
            assert isinstance(query_kwargs["target_id"], UUID)
            assert query_kwargs["target_id"] == form_id
            assert query_kwargs["target_type"] == QueryTargetType.form_instance
