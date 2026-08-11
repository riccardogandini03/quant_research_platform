"""Deterministic tests for valuation, options, and ownership diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from quant_raas.quant.options import (
    delta_risk_reversal,
    implied_realized_spread,
    put_call_ratios,
    select_target_expiry,
)
from quant_raas.quant.ownership import (
    insider_activity,
    institutional_position_change,
    latest_ownership_snapshots_as_of,
    short_interest_metrics,
)
from quant_raas.quant.valuation import (
    historical_valuation_distribution,
    peer_relative_zscore,
    valuation_decomposition,
)


@pytest.mark.point_in_time
def test_historical_valuation_excludes_future_observations() -> None:
    index = pd.date_range("2024-01-01T12:00:00Z", periods=5, freq="D")
    values = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0], index=index)
    result = historical_valuation_distribution(
        values,
        as_of=datetime(2024, 1, 4, 23, 0, tzinfo=UTC),
        lookback_observations=None,
        minimum_observations=4,
        ddof=0,
    )
    assert result.observations == 4
    assert result.current == pytest.approx(4.0)
    assert result.median == pytest.approx(2.5)
    assert result.zscore == pytest.approx((4.0 - 2.5) / np.sqrt(1.25))
    assert result.percentile == pytest.approx(1.0)


def test_peer_valuation_and_multiplicative_decomposition_are_exact() -> None:
    score = peer_relative_zscore(
        4.0,
        pd.Series([1.0, 2.0, 3.0]),
        minimum_observations=3,
        ddof=0,
    )
    assert score == pytest.approx((4.0 - 2.0) / np.sqrt(2.0 / 3.0))

    decomposition = valuation_decomposition(0.20, 0.10)
    assert decomposition.implied_multiple_return == pytest.approx(1.20 / 1.10 - 1.0)
    assert decomposition.reconstructed_price_return == pytest.approx(0.20)
    assert valuation_decomposition(0.20, -1.0).implied_multiple_return is None


@pytest.mark.point_in_time
def test_put_call_ratios_use_one_synchronized_knowable_snapshot() -> None:
    calls = pd.DataFrame(
        {
            "volume": [100.0, 9_999.0],
            "open_interest": [1_000.0, 9_999.0],
            "expiry": ["2024-02-16", "2024-02-16"],
            "available_at": ["2024-01-02T20:00:00Z", "2024-01-03T20:00:00Z"],
        }
    )
    puts = pd.DataFrame(
        {
            "volume": [150.0, 9_999.0],
            "open_interest": [1_200.0, 9_999.0],
            "expiry": ["2024-02-16", "2024-02-16"],
            "available_at": ["2024-01-02T20:00:00Z", "2024-01-03T20:00:00Z"],
        }
    )
    result = put_call_ratios(
        calls,
        puts,
        as_of=datetime(2024, 1, 2, 23, 0, tzinfo=UTC),
        expiry="2024-02-16",
    )
    assert result.status == "OK"
    assert result.put_call_volume_ratio == pytest.approx(1.5)
    assert result.put_call_open_interest_ratio == pytest.approx(1.2)
    assert result.snapshot_at == pd.Timestamp("2024-01-02T20:00:00Z")


def test_delta_matching_expiry_selection_and_volatility_spread() -> None:
    calls = pd.DataFrame(
        {
            "delta": [0.26, 0.40],
            "implied_volatility": [0.30, 0.28],
            "open_interest": [100.0, 1_000.0],
        }
    )
    puts = pd.DataFrame(
        {
            "delta": [-0.24, -0.45],
            "implied_volatility": [0.35, 0.40],
            "open_interest": [100.0, 1_000.0],
        }
    )
    reversal = delta_risk_reversal(
        calls,
        puts,
        minimum_open_interest=50.0,
    )
    assert reversal.status == "OK"
    assert reversal.call_delta == pytest.approx(0.26)
    assert reversal.put_delta == pytest.approx(-0.24)
    # The public convention is call IV minus put IV.
    assert reversal.call_minus_put_iv == pytest.approx(-0.05)

    expiry = select_target_expiry(
        ["2024-01-05", "2024-01-29", "2024-02-05"],
        as_of=datetime(2024, 1, 1, tzinfo=UTC),
        target_days=30,
        minimum_days=7,
    )
    assert expiry == pd.Timestamp("2024-01-29")
    assert implied_realized_spread(0.30, 0.20) == pytest.approx(0.10)
    assert implied_realized_spread(np.nan, 0.20) is None


@pytest.mark.point_in_time
def test_ownership_vintages_and_insider_window_exclude_future_records() -> None:
    snapshots = pd.DataFrame(
        [
            ("A", 0.10, "2024-01-05T12:00:00Z"),
            ("A", 0.90, "2024-01-11T12:00:00Z"),
        ],
        columns=["security_id", "institutional_percent", "available_at"],
    )
    selected = latest_ownership_snapshots_as_of(
        snapshots,
        as_of=datetime(2024, 1, 10, 23, 0, tzinfo=UTC),
    )
    assert selected["institutional_percent"].tolist() == [0.10]

    transactions = pd.DataFrame(
        {
            "transaction_type": [
                "open market purchase",
                "open market sale",
                "gift",
                "open market purchase",
            ],
            "value": [100.0, 40.0, 50.0, 1_000.0],
            "available_at": [
                "2024-01-05T12:00:00Z",
                "2024-01-06T12:00:00Z",
                "2024-01-07T12:00:00Z",
                "2024-01-11T12:00:00Z",
            ],
        }
    )
    activity = insider_activity(
        transactions,
        as_of=datetime(2024, 1, 10, 23, 0, tzinfo=UTC),
        lookback_days=30,
    )
    assert activity.buy_value == pytest.approx(100.0)
    assert activity.sell_value == pytest.approx(40.0)
    assert activity.net_value == pytest.approx(60.0)
    assert activity.buy_sell_ratio == pytest.approx(2.5)
    assert activity.classified_transactions == 2
    assert activity.unclassified_transactions == 1
    assert activity.status == "PARTIAL"


def test_institutional_and_short_interest_metrics_preserve_unknowns() -> None:
    institutional = institutional_position_change(
        pd.DataFrame({"share_change": [10.0, -5.0, np.nan]})
    )
    assert institutional.observations == 2
    assert institutional.mean_share_change == pytest.approx(2.5)
    assert institutional.median_share_change == pytest.approx(2.5)
    assert institutional.total_share_change == pytest.approx(5.0)
    assert institutional.status == "PARTIAL"

    short = short_interest_metrics(
        {
            "shares_short": 100.0,
            "short_percent_of_float": 0.10,
            "days_to_cover": 2.0,
            "shares_short_prior": 80.0,
        }
    )
    assert short.status == "OK"
    assert short.change_in_shares_short == pytest.approx(20.0)
    assert short.change_percent == pytest.approx(0.25)
    assert short.short_percent_of_float == pytest.approx(0.10)
