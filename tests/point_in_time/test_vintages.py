"""Point-in-time invariants shared by live research and historical simulation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from quant_raas.backtest.universe import members_as_of
from quant_raas.backtest.validation import (
    PointInTimeViolation,
    assert_available_by_decision,
    latest_vintage_as_of,
)
from quant_raas.normalization.snapshots import select_snapshots_as_of

pytestmark = pytest.mark.point_in_time


def _vintages() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("A", "eps", "2023-12-31", 100.0, "2024-01-02T12:00:00Z"),
            # Same old period, but this revision was published after the cutoff.
            ("A", "eps", "2023-12-31", 110.0, "2024-01-10T12:00:00Z"),
            ("B", "eps", "2023-12-31", 50.0, "2024-01-08T12:00:00Z"),
        ],
        columns=["security_id", "metric", "period_end", "value", "available_at"],
    )


def test_latest_vintage_uses_availability_not_reporting_period() -> None:
    cutoff = datetime(2024, 1, 5, 12, 0, tzinfo=UTC)
    selected = latest_vintage_as_of(
        _vintages(),
        as_of=cutoff,
        keys=["security_id", "metric", "period_end"],
    )
    assert selected[["security_id", "value"]].to_dict(orient="records") == [
        {"security_id": "A", "value": 100.0}
    ]

    normalized = select_snapshots_as_of(
        _vintages(),
        as_of=cutoff,
        entity_columns=["security_id", "metric", "period_end"],
    )
    assert normalized[["security_id", "value"]].to_dict(orient="records") == [
        {"security_id": "A", "value": 100.0}
    ]


def test_future_only_observation_returns_no_data_instead_of_latest() -> None:
    cutoff = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    selected = latest_vintage_as_of(
        _vintages(),
        as_of=cutoff,
        keys=["security_id", "metric", "period_end"],
    )
    assert selected.empty


def test_decision_validation_reports_future_rows() -> None:
    panel = pd.DataFrame(
        {
            "decision_at": ["2024-01-05T12:00:00Z", "2024-01-05T12:00:00Z"],
            "available_at": ["2024-01-05T11:00:00Z", "2024-01-05T12:00:01Z"],
        }
    )
    with pytest.raises(PointInTimeViolation, match="1 rows were unavailable"):
        assert_available_by_decision(panel)


def test_universe_membership_uses_half_open_effective_intervals() -> None:
    membership = pd.DataFrame(
        {
            "security_id": ["OLD", "NEW", "OPEN"],
            "valid_from": [
                "2020-01-01T00:00:00Z",
                "2024-01-01T00:00:00Z",
                "2020-01-01T00:00:00Z",
            ],
            "valid_to": ["2024-01-01T00:00:00Z", None, None],
        }
    )
    at_boundary = datetime(2024, 1, 1, tzinfo=UTC)
    assert members_as_of(membership, at_boundary) == {"NEW", "OPEN"}


@settings(derandomize=True, max_examples=50, deadline=None)
@given(
    future_values=st.lists(
        st.floats(min_value=-1_000, max_value=1_000, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=20,
    )
)
def test_adding_arbitrary_future_vintages_cannot_change_past_result(
    future_values: list[float],
) -> None:
    cutoff = datetime(2024, 1, 5, 12, 0, tzinfo=UTC)
    base = _vintages().iloc[[0]].copy()
    rows = [
        {
            "security_id": "A",
            "metric": "eps",
            "period_end": "2023-12-31",
            "value": value,
            "available_at": cutoff + timedelta(days=1, minutes=index),
        }
        for index, value in enumerate(future_values)
    ]
    extended = pd.concat([base, pd.DataFrame(rows)], ignore_index=True)
    keys = ["security_id", "metric", "period_end"]
    expected = latest_vintage_as_of(base, as_of=cutoff, keys=keys)
    actual = latest_vintage_as_of(extended, as_of=cutoff, keys=keys)
    pd.testing.assert_frame_equal(actual, expected)
