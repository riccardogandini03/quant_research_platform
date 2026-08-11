"""Known-value and point-in-time tests for event and fundamental features."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from quant_raas.quant.earnings import earnings_event_features, surprise_ratio
from quant_raas.quant.estimates import (
    estimate_dispersion,
    estimate_revisions,
    latest_estimates_as_of,
    revision_breadth,
)
from quant_raas.quant.event_study import standard_event_spec
from quant_raas.quant.macro import (
    latest_macro_vintages_as_of,
    macro_surprise,
    rolling_standardized_surprise,
)


def test_earnings_surprise_uses_absolute_consensus_and_zero_is_unknown() -> None:
    result = surprise_ratio(
        pd.Series([1.10, -0.80, 1.0]),
        pd.Series([1.00, -1.00, 0.0]),
    )
    assert result.iloc[0] == pytest.approx(0.10)
    assert result.iloc[1] == pytest.approx(0.20)
    assert pd.isna(result.iloc[2])


@pytest.mark.point_in_time
def test_earnings_features_align_amc_response_and_filter_late_event_vintage() -> None:
    sessions = pd.bdate_range("2024-01-02", periods=5)
    bars = pd.DataFrame(
        {
            "open": [99.0, 101.0, 104.0, 105.0, 106.0],
            "close": [100.0, 102.0, 103.0, 106.0, 107.0],
            "volume": [100.0, 200.0, 400.0, 250.0, 300.0],
        },
        index=sessions,
    )
    events = pd.DataFrame(
        {
            "event_id": ["known", "late-vintage"],
            "event_at": [
                datetime(2024, 1, 3, 21, 30, tzinfo=UTC),
                datetime(2024, 1, 3, 21, 30, tzinfo=UTC),
            ],
            "available_at": [
                datetime(2024, 1, 3, 21, 0, tzinfo=UTC),
                datetime(2024, 1, 8, 12, 0, tzinfo=UTC),
            ],
            "timing": ["AMC", "AMC"],
            "actual_eps": [1.10, 9.0],
            "consensus_eps": [1.00, 1.0],
        }
    )
    analysis = earnings_event_features(
        bars,
        events,
        standard_event_spec(pre_sessions=1, post_sessions=1),
        as_of=datetime(2024, 1, 5, 23, 0, tzinfo=UTC),
        volume_window=2,
        volume_minimum_observations=2,
    )
    assert analysis.observations["event_id"].tolist() == ["known"]
    row = analysis.observations.iloc[0]
    assert row["response_session"] == pd.Timestamp("2024-01-04")
    assert row["event_day"] == pytest.approx(103.0 / 102.0 - 1.0)
    assert row["overnight_gap"] == pytest.approx(104.0 / 102.0 - 1.0)
    assert row["eps_surprise"] == pytest.approx(0.10)
    assert np.isfinite(row["volume_zscore"])


def _estimate_snapshots() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("A", "eps", "FY1", 100.0, "2024-01-01T12:00:00Z"),
            ("A", "eps", "FY1", 110.0, "2024-01-05T12:00:00Z"),
            ("A", "eps", "FY1", 999.0, "2024-01-10T12:00:00Z"),
        ],
        columns=["security_id", "metric", "fiscal_period", "consensus", "available_at"],
    )


@pytest.mark.point_in_time
def test_estimate_revisions_use_the_latest_vintage_at_each_cutoff() -> None:
    as_of = datetime(2024, 1, 6, 12, 0, tzinfo=UTC)
    latest = latest_estimates_as_of(_estimate_snapshots(), as_of=as_of)
    assert latest["consensus"].tolist() == [110.0]

    revisions = estimate_revisions(
        _estimate_snapshots(),
        as_of=as_of,
        lookback_days=(2, 7),
    )
    assert revisions.loc[0, "revision_2d"] == pytest.approx(0.10)
    assert pd.isna(revisions.loc[0, "revision_7d"])


def test_revision_breadth_counts_only_paired_changed_contributors() -> None:
    rows: list[tuple[str, str, str, str, float, str]] = []
    for contributor, prior, current in (
        ("raise", 100.0, 110.0),
        ("cut", 100.0, 90.0),
        ("flat", 100.0, 100.0),
    ):
        rows.extend(
            [
                ("A", "eps", "FY1", contributor, prior, "2024-01-01T00:00:00Z"),
                ("A", "eps", "FY1", contributor, current, "2024-01-20T00:00:00Z"),
            ]
        )
    rows.append(("A", "eps", "FY1", "new", 120.0, "2024-01-20T00:00:00Z"))
    snapshots = pd.DataFrame(
        rows,
        columns=[
            "security_id",
            "metric",
            "fiscal_period",
            "contributor_id",
            "estimate",
            "available_at",
        ],
    )
    result = revision_breadth(
        snapshots,
        as_of=datetime(2024, 1, 31, tzinfo=UTC),
        lookback_days=30,
    ).iloc[0]
    assert (result["raises"], result["cuts"], result["unchanged"]) == (1, 1, 1)
    assert result["contributors_paired"] == 3
    assert result["contributors_changed"] == 2
    assert result["revision_breadth"] == pytest.approx(0.0)

    dispersion = estimate_dispersion(pd.Series([1.0, 2.0, 3.0, np.nan]))
    assert dispersion.observations == 3
    assert dispersion.mean == pytest.approx(2.0)
    assert dispersion.sample_standard_deviation == pytest.approx(1.0)
    assert dispersion.coefficient_of_variation == pytest.approx(0.5)


@pytest.mark.point_in_time
def test_macro_vintages_and_surprise_standardization_are_backward_looking() -> None:
    releases = pd.DataFrame(
        [
            ("CPI", "2023-12", 3.0, "2024-01-02T12:00:00Z"),
            ("CPI", "2023-12", 9.0, "2024-01-10T12:00:00Z"),
        ],
        columns=["series_id", "period_end", "actual", "available_at"],
    )
    selected = latest_macro_vintages_as_of(
        releases,
        as_of=datetime(2024, 1, 5, tzinfo=UTC),
    )
    assert selected["actual"].tolist() == [3.0]
    assert macro_surprise(pd.Series([3.0]), pd.Series([2.5])).iloc[0] == pytest.approx(0.5)

    surprises = pd.Series([0.0, 2.0, 0.0, 2.0, 5.0])
    standardized = rolling_standardized_surprise(
        surprises,
        window=4,
        minimum_observations=4,
        lag=1,
        ddof=0,
    )
    # The current 5.0 surprise is compared with [0, 2, 0, 2], never itself.
    assert standardized.iloc[-1] == pytest.approx(4.0)
