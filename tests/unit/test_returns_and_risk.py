"""Known-value tests for return compounding and risk conventions."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from quant_raas.quant.returns import (
    annualized_arithmetic_return,
    annualized_volatility,
    compound_returns,
    horizon_returns,
    intraday_return,
    log_returns,
    overnight_gap,
    realized_cagr,
    relative_return,
    rolling_total_return,
    sharpe_ratio,
    simple_returns,
    summarize_returns,
)
from quant_raas.quant.risk import (
    beta_estimate,
    downside_deviation,
    historical_expected_shortfall,
    historical_value_at_risk,
    maximum_drawdown,
    rolling_volatility,
    summarize_risk,
)


def test_price_returns_and_compounding_use_gross_returns_not_sums() -> None:
    index = pd.bdate_range("2024-01-02", periods=4)
    prices = pd.Series([100.0, 110.0, 99.0, 103.95], index=index, name="price")
    expected = pd.Series([np.nan, 0.10, -0.10, 0.05], index=index, name="price")

    calculated = simple_returns(prices)
    np.testing.assert_allclose(calculated.to_numpy(), expected.to_numpy(), equal_nan=True)
    assert calculated.index.equals(expected.index)
    assert log_returns(prices).iloc[-1] == pytest.approx(math.log(1.05))
    # 10% - 10% + 5% sums to 5%, but correct compounding is only 3.95%.
    assert compound_returns(expected) == pytest.approx(0.0395)
    assert rolling_total_return(expected, window=3).iloc[-1] == pytest.approx(0.0395)
    assert horizon_returns(prices, horizons=[1, 3])["return_3d"].iloc[-1] == pytest.approx(0.0395)


def test_gap_intraday_and_relative_returns_use_explicit_denominators() -> None:
    index = pd.bdate_range("2024-01-02", periods=2)
    opens = pd.Series([100.0, 110.0], index=index)
    closes = pd.Series([100.0, 121.0], index=index)
    assert overnight_gap(opens, closes).iloc[1] == pytest.approx(0.10)
    assert intraday_return(opens, closes).iloc[1] == pytest.approx(0.10)

    asset = pd.Series([0.10], index=index[:1])
    benchmark = pd.Series([0.05], index=index[:1])
    assert relative_return(asset, benchmark).iloc[0] == pytest.approx(1.10 / 1.05 - 1.0)


def test_annualization_distinguishes_arithmetic_return_cagr_and_sample_volatility() -> None:
    returns = pd.Series([0.01, -0.01])
    assert annualized_arithmetic_return(returns, periods_per_year=4) == pytest.approx(0.0)
    # Sample sd([1%, -1%]) = sqrt(0.0002); annualization multiplies by sqrt(4).
    assert annualized_volatility(returns, periods_per_year=4, ddof=1) == pytest.approx(
        math.sqrt(0.0002) * 2.0
    )
    assert realized_cagr(returns, periods_per_year=2) == pytest.approx(-0.0001)
    assert sharpe_ratio(pd.Series([0.01, 0.01])) is None


def test_return_summary_excludes_missing_and_non_finite_observations() -> None:
    summary = summarize_returns(pd.Series([0.01, np.nan, np.inf, -0.01]), periods_per_year=2)
    assert summary.observations == 2
    assert summary.cumulative_return == pytest.approx(-0.0001)
    assert summary.hit_rate == pytest.approx(0.5)


def test_drawdown_downside_deviation_and_beta_have_known_values() -> None:
    assert maximum_drawdown(pd.Series([0.10, -0.20, 0.05])) == pytest.approx(-0.20)
    # Denominator includes the positive observation as a zero downside contribution.
    assert downside_deviation(
        pd.Series([0.10, -0.20]), periods_per_year=1, ddof=0
    ) == pytest.approx(math.sqrt(0.02))

    market = pd.Series([-0.02, -0.01, 0.00, 0.01, 0.02])
    asset = 0.001 + 1.5 * market
    estimate = beta_estimate(asset, market)
    assert estimate.observations == 5
    assert estimate.alpha == pytest.approx(0.001)
    assert estimate.beta == pytest.approx(1.5)
    assert estimate.correlation == pytest.approx(1.0)
    assert estimate.r_squared == pytest.approx(1.0)


def test_tail_risk_and_rolling_volatility_use_explicit_conventions() -> None:
    returns = pd.Series([-0.10, -0.05, 0.00, 0.05, 0.10])
    # Pandas' linear 20th percentile is -6%; ES averages observations at or
    # below that cutoff, so only the -10% return belongs to the tail.
    assert historical_value_at_risk(returns, confidence=0.80) == pytest.approx(0.06)
    assert historical_expected_shortfall(returns, confidence=0.80) == pytest.approx(0.10)
    summary = summarize_risk(returns, periods_per_year=5, confidence=0.80)
    assert summary.observations == 5
    assert summary.value_at_risk == pytest.approx(0.06)
    assert summary.expected_shortfall == pytest.approx(0.10)
    assert summary.maximum_drawdown == pytest.approx(-0.145)

    rolling = rolling_volatility(
        pd.Series([0.01, -0.01]),
        window=2,
        min_periods=2,
        periods_per_year=4,
        ddof=1,
    )
    assert rolling.iloc[-1] == pytest.approx(math.sqrt(0.0002) * 2.0)
