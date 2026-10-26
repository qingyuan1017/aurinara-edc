"""Property-based test for design-time rule-testing side-effect freedom.

# Feature: designer-edc-refactor, Property 10: Rule testing produces no operational side effects

**Validates: Requirements 5.3, 5.5**

Property 10 (design.md): _For all_ Edit_Check_Rules and all provided test
cases, evaluating the rule returns a pass/fail verdict, creates zero
Operational_Records, and performs no execution of user-provided code
(declarative evaluation only).

The design-time rule-testing entry points live in the Designer module's
``EditCheckService`` (``app.services.designer.edit_check_service``):

  - ``test_edit_check(edit_check, test_case)`` returns a structured
    :class:`RuleTestResult` carrying ``matched``/``passed`` and a ``persisted``
    flag that is always ``False``.
  - ``test(rule, sample_data)`` is the lower-level boolean API.

Neither entry point accepts an :class:`AsyncSession` or touches any persistence
API, so a rule test can never create an Operational_Record (no FormInstance,
FieldValue, ValidationResult, or Query). This suite proves that for randomly
generated **valid declarative rules** paired with **random test-case data**:

  1. ``test_edit_check`` returns a pass/fail verdict whose ``passed`` is the
     negation of ``matched`` and whose ``persisted`` flag is ``False`` (R5.3);
  2. the verdict equals the pure declarative-DSL evaluation, i.e. evaluation is
     purely declarative and never executes user-provided code (R5.5); and
  3. counting every Operational_Record table in a real database before and
     after the call shows no change — zero operational side effects (R5.3).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from string import ascii_uppercase
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.edit_check_dsl import evaluate_rule
from app.models.designer.edit_check import EditCheck, ValidationResult
from app.models.edc.form_data import FieldValue, FormInstance
from app.models.edc.query import Query
from app.services.designer.edit_check_service import EditCheckService, RuleTestResult


@dataclass(frozen=True)
class RuleTestFixture:
    """A valid declarative rule paired with compatible test-case data."""

    rule: dict[str, Any]
    test_case: dict[str, Any]


@st.composite
def rule_test_fixtures(draw: st.DrawFn) -> RuleTestFixture:
    """Generate valid declarative leaf rules with compatible JSON test data.

    Every rule stays inside the fixed JSON DSL (no expression text, no callable
    values), and every test case is plain JSON data — the inputs an authorized
    designer could submit through the test API.
    """
    operator = draw(
        st.sampled_from(
            (
                "is_null",
                "not_null",
                "==",
                "!=",
                ">",
                ">=",
                "<",
                "<=",
                "in",
                "not_in",
                "matches",
                "before",
                "after",
                "within_days",
            )
        )
    )

    if operator in {"is_null", "not_null"}:
        value = draw(st.one_of(st.none(), st.integers(-100, 100)))
        return RuleTestFixture(
            rule={"field": "value", "operator": operator},
            test_case={"value": value},
        )

    if operator in {">", ">=", "<", "<="}:
        threshold = draw(st.integers(-100, 100))
        value = draw(st.integers(-100, 100))
        return RuleTestFixture(
            rule={"field": "value", "operator": operator, "value": threshold},
            test_case={"value": value},
        )

    if operator in {"in", "not_in"}:
        choices = draw(st.lists(st.integers(-20, 20), min_size=1, max_size=8, unique=True))
        value = draw(st.integers(-20, 20))
        return RuleTestFixture(
            rule={"field": "value", "operator": operator, "value": choices},
            test_case={"value": value},
        )

    if operator == "matches":
        # The "value" is a static regex (data, never executable); the test-case
        # value is arbitrary text — including code-like text — which must only
        # ever be pattern-matched, never executed (R5.5).
        value = draw(
            st.one_of(
                st.text(alphabet=ascii_uppercase, min_size=0, max_size=8),
                st.sampled_from(
                    (
                        "__import__('os').system('echo hi')",
                        "eval('1+1')",
                        "{{7*7}}",
                        "'; DROP TABLE edit_checks; --",
                    )
                ),
            )
        )
        return RuleTestFixture(
            rule={"field": "value", "operator": operator, "value": r"[A-Z]{1,5}"},
            test_case={"value": value},
        )

    if operator in {"before", "after"}:
        left = draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))
        right = draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))
        return RuleTestFixture(
            rule={"field": "value", "operator": operator, "value": right.isoformat()},
            test_case={"value": left.isoformat()},
        )

    # ``within_days`` accepts a numeric test value as a compact valid case.
    days = draw(st.integers(0, 30))
    value = draw(st.integers(-60, 60))
    return RuleTestFixture(
        rule={"field": "value", "operator": operator, "value": days},
        test_case={"value": value},
    )


@st.composite
def boolean_rule_fixtures(draw: st.DrawFn) -> RuleTestFixture:
    """Combine leaf fixtures under a random boolean node (and/or/not)."""
    connector = draw(st.sampled_from(("and", "or", "not")))
    if connector == "not":
        leaf = draw(rule_test_fixtures())
        return RuleTestFixture(rule={"not": leaf.rule}, test_case=leaf.test_case)

    leaves = draw(st.lists(rule_test_fixtures(), min_size=2, max_size=4))
    merged_case: dict[str, Any] = {}
    children: list[dict[str, Any]] = []
    for index, leaf in enumerate(leaves):
        # Namespace each leaf's field so merged test cases stay well-defined.
        field = f"value{index}"
        rule = {**leaf.rule, "field": field}
        children.append(rule)
        merged_case[field] = leaf.test_case["value"]
    return RuleTestFixture(rule={connector: children}, test_case=merged_case)


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provide a real SQLite session for checking Operational_Record counts."""
    import app.models  # Register every ORM relationship first.

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _operational_record_counts(session: AsyncSession) -> dict[str, int]:
    """Count every Operational_Record a rule test must never create (R5.3)."""
    models = {
        "form_instances": FormInstance,
        "field_values": FieldValue,
        "validation_results": ValidationResult,
        "queries": Query,
    }
    return {
        name: int(await session.scalar(select(func.count()).select_from(model)))
        for name, model in models.items()
    }


_ZERO_COUNTS = {
    "form_instances": 0,
    "field_values": 0,
    "validation_results": 0,
    "queries": 0,
}


class TestRuleTestingSideEffectFreeProperty:
    """Property 10 — design-time rule testing is declarative and side-effect free.

    # Feature: designer-edc-refactor, Property 10: Rule testing produces no operational side effects

    **Validates: Requirements 5.3, 5.5**
    """

    @settings(
        max_examples=150,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(fixture=st.one_of(rule_test_fixtures(), boolean_rule_fixtures()))
    @pytest.mark.asyncio
    async def test_rule_testing_returns_verdict_without_operational_side_effects(
        self, fixture: RuleTestFixture, db_session: AsyncSession
    ) -> None:
        service = EditCheckService()
        before = await _operational_record_counts(db_session)

        # Both documented design-time entry points: the structured
        # ``test_edit_check`` and the lower-level boolean ``test``.
        result = service.test_edit_check(fixture.rule, fixture.test_case)
        boolean_outcome = service.test(fixture.rule, fixture.test_case)

        after = await _operational_record_counts(db_session)

        # (1) A pass/fail verdict is returned, with persisted always False (R5.3).
        assert isinstance(result, RuleTestResult)
        assert isinstance(result.matched, bool)
        assert isinstance(result.passed, bool)
        assert result.passed is (not result.matched)
        assert result.persisted is False
        # Ad-hoc rule-JSON tests carry no persisted EditCheck identity.
        assert result.edit_check_id is None

        # (2) Evaluation is purely declarative — the verdict equals the safe DSL
        #     evaluation and never executes user-provided code (R5.5).
        expected = evaluate_rule(fixture.rule, fixture.test_case)
        assert result.matched is expected
        assert result.outcome is expected
        assert boolean_outcome is expected

        # (3) Zero Operational_Records created; counts are unchanged (R5.3).
        assert before == _ZERO_COUNTS
        assert after == before

    @settings(
        max_examples=150,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(fixture=rule_test_fixtures())
    @pytest.mark.asyncio
    async def test_test_edit_check_with_persisted_edit_check_is_side_effect_free(
        self, fixture: RuleTestFixture, db_session: AsyncSession
    ) -> None:
        """A persisted-but-unsaved EditCheck tests without any side effects.

        Passing a real :class:`EditCheck` entity exercises the branch that reads
        ``rule_json`` and reports ``edit_check_id``; the entity is never added to
        a session, so no Operational_Record is created (R5.3) and evaluation
        remains purely declarative (R5.5).
        """
        service = EditCheckService()
        edit_check = EditCheck(
            study_version_id=None,
            name="property-rule",
            rule_json=fixture.rule,
            severity="error",
            is_active=True,
        )
        before = await _operational_record_counts(db_session)

        result = service.test_edit_check(edit_check, fixture.test_case)

        after = await _operational_record_counts(db_session)

        expected = evaluate_rule(fixture.rule, fixture.test_case)
        assert result.matched is expected
        assert result.passed is (not expected)
        assert result.persisted is False
        assert result.edit_check_id == edit_check.id
        assert before == _ZERO_COUNTS
        assert after == before
