"""Property 7: Regulatory clock correctness.

**Validates: Requirements 8, 13**

Feature: pv-safety-module, Task 4.2

*For any* generated Awareness_Date, reporting-timeline day count (including the
0/1/90/91 boundaries), current-date offset, and Regulatory_Report status:

  1. ``compute_clock`` returns a due date equal to the Awareness_Date plus the
     configured whole number of calendar days in UTC, counting the
     Awareness_Date as day zero, exactly when ``timeline_days`` is a whole
     number between 1 and 90 inclusive; any other value (0, 91, negatives,
     booleans, non-integers) is rejected with a ``ValidationError`` carrying the
     ``INVALID_TIMELINE_DAYS`` reason and produces no due date (Requirement 8.3).
  2. ``is_overdue`` returns true exactly when the current UTC date is later than
     the Regulatory_Clock due date and the report status is not Submitted,
     Acknowledged, or Cancelled (Requirements 8.6, 13.2).

``compute_clock`` and ``is_overdue`` are pure, deterministic functions with no
I/O, so they are exercised directly with no database server, queue, object
storage, or other external service. Each property runs at least 100 examples.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import ValidationError
from app.core.pv import ReportStatus
from app.models.pv.regulatory import TIMELINE_DAYS_MAX, TIMELINE_DAYS_MIN
from app.services.regulatory_reporting_service import regulatory_reporting_service

# ReportStatus values that stop the expedited clock (Requirement 8.6).
_CLOCK_STOPPED_STATUSES = frozenset(
    {ReportStatus.SUBMITTED, ReportStatus.ACKNOWLEDGED, ReportStatus.CANCELLED}
)

# Generators -----------------------------------------------------------------

# Awareness_Dates across a wide but bounded calendar range so that adding up to
# 90 days never overflows the supported date range.
_awareness_dates = st.dates(
    min_value=date(1970, 1, 1), max_value=date(2200, 1, 1)
)

# Valid whole-day timelines: 1..90 inclusive, with the 1 and 90 boundaries
# always represented by Hypothesis's boundary bias.
_valid_timelines = st.integers(
    min_value=TIMELINE_DAYS_MIN, max_value=TIMELINE_DAYS_MAX
)

# Invalid whole-day timelines centered on the 0 and 91 boundaries plus a wider
# out-of-range band and explicit boundary examples.
_invalid_timelines = st.one_of(
    st.just(0),
    st.just(TIMELINE_DAYS_MAX + 1),  # 91
    st.integers(max_value=TIMELINE_DAYS_MIN - 1),  # <= 0
    st.integers(min_value=TIMELINE_DAYS_MAX + 1),  # >= 91
)

# Non-integer / boolean timelines that must also be rejected.
_non_integer_timelines = st.one_of(
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=5),
    st.none(),
)

_report_statuses = st.sampled_from(list(ReportStatus))

# Current-date offsets relative to the due date, biased around the boundary
# (offset 0 = due date exactly, negative = before, positive = after).
_current_offsets = st.integers(min_value=-5, max_value=5)


# Property 7a: compute_clock produces the correct UTC due date -----------------


@settings(max_examples=200)
@given(awareness_date=_awareness_dates, timeline_days=_valid_timelines)
def test_compute_clock_adds_whole_days_with_awareness_as_day_zero(
    awareness_date: date, timeline_days: int
) -> None:
    """A valid timeline yields Awareness_Date + timeline_days calendar days."""

    due_date = regulatory_reporting_service.compute_clock(
        awareness_date, timeline_days
    )

    assert due_date == awareness_date + timedelta(days=timeline_days)
    # Awareness_Date counts as day zero: the due date is strictly later.
    assert due_date > awareness_date
    assert (due_date - awareness_date).days == timeline_days


@settings(max_examples=200)
@given(awareness_date=_awareness_dates, timeline_days=_invalid_timelines)
def test_compute_clock_rejects_out_of_range_timelines(
    awareness_date: date, timeline_days: int
) -> None:
    """0, 91, and any other out-of-range whole-day timeline is rejected."""

    with pytest.raises(ValidationError) as exc_info:
        regulatory_reporting_service.compute_clock(awareness_date, timeline_days)

    assert exc_info.value.details.get("reason") == "INVALID_TIMELINE_DAYS"


@settings(max_examples=200)
@given(awareness_date=_awareness_dates, timeline_days=_non_integer_timelines)
def test_compute_clock_rejects_non_integer_timelines(
    awareness_date: date, timeline_days: object
) -> None:
    """Booleans, floats, strings, and None are not whole-day timelines."""

    with pytest.raises(ValidationError) as exc_info:
        regulatory_reporting_service.compute_clock(awareness_date, timeline_days)  # type: ignore[arg-type]

    assert exc_info.value.details.get("reason") == "INVALID_TIMELINE_DAYS"


# Property 7b: is_overdue matches the overdue predicate ------------------------


@settings(max_examples=300)
@given(
    awareness_date=_awareness_dates,
    timeline_days=_valid_timelines,
    offset=_current_offsets,
    status=_report_statuses,
)
def test_is_overdue_matches_date_and_status_predicate(
    awareness_date: date,
    timeline_days: int,
    offset: int,
    status: ReportStatus,
) -> None:
    """Overdue iff today_utc is past the due date and the clock is running."""

    due_date = regulatory_reporting_service.compute_clock(
        awareness_date, timeline_days
    )
    today_utc = due_date + timedelta(days=offset)

    result = regulatory_reporting_service.is_overdue(due_date, status, today_utc)

    expected = today_utc > due_date and status not in _CLOCK_STOPPED_STATUSES
    assert result is expected


@settings(max_examples=200)
@given(
    awareness_date=_awareness_dates,
    timeline_days=_valid_timelines,
    days_past=st.integers(min_value=1, max_value=365),
    status=st.sampled_from(list(_CLOCK_STOPPED_STATUSES)),
)
def test_is_overdue_is_false_for_clock_stopped_statuses(
    awareness_date: date,
    timeline_days: int,
    days_past: int,
    status: ReportStatus,
) -> None:
    """A Submitted/Acknowledged/Cancelled report is never overdue."""

    due_date = regulatory_reporting_service.compute_clock(
        awareness_date, timeline_days
    )
    today_utc = due_date + timedelta(days=days_past)

    assert regulatory_reporting_service.is_overdue(due_date, status, today_utc) is False


@settings(max_examples=200)
@given(
    awareness_date=_awareness_dates,
    timeline_days=_valid_timelines,
    status=st.sampled_from(
        [s for s in ReportStatus if s not in _CLOCK_STOPPED_STATUSES]
    ),
)
def test_is_overdue_is_false_on_due_date_for_running_clock(
    awareness_date: date,
    timeline_days: int,
    status: ReportStatus,
) -> None:
    """On the due date itself the report is on time, not overdue."""

    due_date = regulatory_reporting_service.compute_clock(
        awareness_date, timeline_days
    )

    # today == due_date is not "later than" the due date.
    assert regulatory_reporting_service.is_overdue(due_date, status, due_date) is False
    # One day after is overdue for a running clock.
    assert (
        regulatory_reporting_service.is_overdue(
            due_date, status, due_date + timedelta(days=1)
        )
        is True
    )
