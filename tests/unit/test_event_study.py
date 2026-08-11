"""Session-aware event tests with explicit before/after-market conventions."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from quant_raas.quant.event_study import (
    align_event_to_session,
    extract_event_windows,
    standard_event_spec,
)


def test_event_alignment_distinguishes_bmo_amc_and_weekend_rolls() -> None:
    sessions = pd.bdate_range("2024-01-05", periods=3)  # Fri, Mon, Tue

    before_open = align_event_to_session(
        datetime(2024, 1, 5, 13, 0, tzinfo=UTC),
        sessions,
        exchange_timezone="America/New_York",
    )
    assert before_open.timing == "BMO"
    assert before_open.response_session == pd.Timestamp("2024-01-05")

    after_close = align_event_to_session(
        datetime(2024, 1, 5, 21, 30, tzinfo=UTC),
        sessions,
        exchange_timezone="America/New_York",
    )
    assert after_close.timing == "AMC"
    assert after_close.response_session == pd.Timestamp("2024-01-08")
    assert after_close.rule == "strict_next_session_after_close_holiday_or_weekend_roll"

    weekend = align_event_to_session(
        datetime(2024, 1, 6, 17, 0, tzinfo=UTC),
        sessions,
        exchange_timezone="America/New_York",
    )
    assert weekend.response_session == pd.Timestamp("2024-01-08")
    assert weekend.rule.endswith("holiday_or_weekend_roll")


def test_standard_spec_uses_dynamic_non_overlapping_window_names() -> None:
    spec = standard_event_spec(pre_sessions=3, post_sessions=2)
    assert [(window.name, window.start, window.end) for window in spec.windows] == [
        ("pre_3d", -3, -1),
        ("event_day", 0, 0),
        ("post_2d", 1, 2),
    ]


def test_event_windows_compound_exact_inclusive_session_offsets() -> None:
    sessions = pd.bdate_range("2024-01-02", periods=5)
    returns = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05], index=sessions)
    events = pd.DataFrame(
        {
            "event_id": ["earnings-1"],
            "event_at": [datetime(2024, 1, 4, 13, 0, tzinfo=UTC)],
            "available_at": [datetime(2024, 1, 4, 12, 0, tzinfo=UTC)],
            "timing": ["BMO"],
        }
    )
    result = extract_event_windows(
        returns,
        events,
        standard_event_spec(pre_sessions=2, post_sessions=2),
        as_of=datetime(2024, 1, 8, 23, 0, tzinfo=UTC),
    )
    row = result.observations.iloc[0]
    assert row["pre_2d"] == pytest.approx(1.01 * 1.02 - 1.0)
    assert row["event_day"] == pytest.approx(0.03)
    assert row["post_2d"] == pytest.approx(1.04 * 1.05 - 1.0)
    assert bool(row["is_complete"])
    assert bool(row["is_eligible"])


def test_boundary_event_is_retained_but_marked_incomplete() -> None:
    sessions = pd.bdate_range("2024-01-02", periods=5)
    returns = pd.Series(0.01, index=sessions)
    events = pd.DataFrame(
        {
            "event_id": ["boundary"],
            "event_at": [datetime(2024, 1, 2, 13, 0, tzinfo=UTC)],
            "available_at": [datetime(2024, 1, 2, 12, 0, tzinfo=UTC)],
            "timing": ["BMO"],
        }
    )
    row = extract_event_windows(
        returns,
        events,
        standard_event_spec(pre_sessions=2, post_sessions=2),
    ).observations.iloc[0]
    assert not bool(row["pre_2d_complete"])
    assert pd.isna(row["pre_2d"])
    assert not bool(row["is_eligible"])


@pytest.mark.point_in_time
def test_event_study_filters_on_availability_not_event_date() -> None:
    sessions = pd.bdate_range("2024-01-02", periods=6)
    returns = pd.Series(0.01, index=sessions)
    events = pd.DataFrame(
        {
            "event_id": ["known", "future-vintage"],
            "event_at": [
                datetime(2024, 1, 4, 13, 0, tzinfo=UTC),
                datetime(2024, 1, 4, 13, 0, tzinfo=UTC),
            ],
            "available_at": [
                datetime(2024, 1, 3, 12, 0, tzinfo=UTC),
                datetime(2024, 1, 6, 12, 0, tzinfo=UTC),
            ],
            "timing": ["BMO", "BMO"],
        }
    )
    result = extract_event_windows(
        returns,
        events,
        standard_event_spec(pre_sessions=1, post_sessions=1),
        as_of=datetime(2024, 1, 5, 23, 0, tzinfo=UTC),
    )
    assert result.observations["event_id"].tolist() == ["known"]
