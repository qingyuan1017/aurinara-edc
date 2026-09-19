"""Property coverage for non-persistent edit-check testing.

# Feature: clinical-edc-system, Property 24: Edit-check test does not persist clinical data
**Validates: Requirements 12.4**

For every generated valid edit-check condition and sample payload, the
EditCheckService.test API returns the expected boolean outcome while leaving
clinical data, validation results, queries, and audit events unchanged.
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
from app.models.audit import AuditEvent
from app.models.edit_check import ValidationResult
from app.models.form_data import FieldValue, FormInstance
from app.models.query import Query
from app.services.edit_check_service import EditCheckService


@dataclass(frozen=True)
class EditCheckTestCase:
    rule: dict[str, Any]
    sample_data: dict[str, Any]


@st.composite
def edit_check_test_cases(draw: st.DrawFn) -> EditCheckTestCase:
    """Generate valid leaf rules with compatible JSON sample data."""
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
        return EditCheckTestCase(
            rule={"field": "value", "operator": operator},
            sample_data={"value": value},
        )

    if operator in {">", ">=", "<", "<="}:
        threshold = draw(st.integers(-100, 100))
        value = draw(st.integers(-100, 100))
        return EditCheckTestCase(
            rule={"field": "value", "operator": operator, "value": threshold},
            sample_data={"value": value},
        )

    if operator in {"in", "not_in"}:
        choices = draw(st.lists(st.integers(-20, 20), min_size=1, max_size=8, unique=True))
        value = draw(st.integers(-20, 20))
        return EditCheckTestCase(
            rule={"field": "value", "operator": operator, "value": choices},
            sample_data={"value": value},
        )

    if operator == "matches":
        value = draw(st.text(alphabet=ascii_uppercase, min_size=0, max_size=8))
        return EditCheckTestCase(
            rule={"field": "value", "operator": operator, "value": r"[A-Z]{1,5}"},
            sample_data={"value": value},
        )

    if operator in {"before", "after"}:
        left = draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))
        right = draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))
        return EditCheckTestCase(
            rule={"field": "value", "operator": operator, "value": right.isoformat()},
            sample_data={"value": left.isoformat()},
        )

    # ``within_days`` accepts numeric sample values as a compact valid case.
    days = draw(st.integers(0, 30))
    value = draw(st.integers(-60, 60))
    return EditCheckTestCase(
        rule={"field": "value", "operator": operator, "value": days},
        sample_data={"value": value},
    )


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provide a real SQLite session for checking all non-persistence targets."""
    import app.models  # noqa: F401  # Register every ORM relationship first.

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _side_effect_counts(session: AsyncSession) -> dict[str, int]:
    """Count every persistence target that a non-persistent test must not touch."""
    models = {
        "form_instances": FormInstance,
        "field_values": FieldValue,
        "validation_results": ValidationResult,
        "queries": Query,
        "audit_events": AuditEvent,
    }
    return {
        name: int(await session.scalar(select(func.count()).select_from(model)))
        for name, model in models.items()
    }


class TestEditCheckTestWithoutPersistProperty:
    """Property 24: testing a rule is read-only for clinical persistence."""

    @settings(
        max_examples=120,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(case=edit_check_test_cases())
    @pytest.mark.asyncio
    async def test_test_returns_outcome_without_persisting_side_effects(
        self, case: EditCheckTestCase, db_session: AsyncSession
    ) -> None:
        service = EditCheckService()
        before = await _side_effect_counts(db_session)

        outcome = service.test(case.rule, case.sample_data)

        after = await _side_effect_counts(db_session)
        assert isinstance(outcome, bool)
        assert outcome == evaluate_rule(case.rule, case.sample_data)
        assert before == after
        assert after == {
            "form_instances": 0,
            "field_values": 0,
            "validation_results": 0,
            "queries": 0,
            "audit_events": 0,
        }
