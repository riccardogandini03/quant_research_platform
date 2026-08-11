"""Tests for lagged anomaly baselines and transparent factor calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_raas.quant.anomalies import (
    anomaly_flags,
    fit_abnormal_return_model,
    rolling_zscore,
)
from quant_raas.quant.factors import (
    cross_sectional_zscore,
    momentum_12_1,
    normalize_factor,
    residual_momentum,
    rolling_beta,
    short_term_reversal,
)


def test_rolling_zscore_uses_only_prior_observations() -> None:
    values = pd.Series([0.0, 2.0, 0.0, 2.0, 5.0], name="residual")
    score = rolling_zscore(values, window=4, min_periods=4, lag=1, ddof=0)
    # Prior history is [0, 2, 0, 2]: mean 1, population sd 1.
    assert score.iloc[-1] == pytest.approx(4.0)
    assert score.iloc[:-1].isna().all()


def test_current_return_cannot_change_its_own_factor_fit() -> None:
    index = pd.bdate_range("2024-01-02", periods=9)
    market = pd.Series(np.linspace(-0.04, 0.04, len(index)), index=index, name="market")
    baseline_asset = 0.001 + 1.5 * market
    shocked_asset = baseline_asset.copy()
    shocked_asset.iloc[-1] += 0.50
    factors = market.to_frame()

    baseline = fit_abnormal_return_model(
        baseline_asset,
        factors,
        window=8,
        minimum_observations=4,
    )
    shocked = fit_abnormal_return_model(
        shocked_asset,
        factors,
        window=8,
        minimum_observations=4,
    )
    # Both fits end at t-1, so a 50% current shock changes only the residual.
    np.testing.assert_allclose(
        baseline.coefficients.iloc[-1].to_numpy(),
        shocked.coefficients.iloc[-1].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )
    assert shocked.expected_return.iloc[-1] == pytest.approx(baseline.expected_return.iloc[-1])
    assert shocked.residual_return.iloc[-1] - baseline.residual_return.iloc[-1] == pytest.approx(
        0.50
    )
    assert shocked.coefficients.loc[index[-1], "intercept"] == pytest.approx(0.001)
    assert shocked.coefficients.loc[index[-1], "market"] == pytest.approx(1.5)


def test_anomaly_flags_preserve_missing_scores() -> None:
    flags = anomaly_flags(pd.Series([2.0, -2.1, 1.9, np.nan]), threshold=2.0)
    assert flags.iloc[:3].tolist() == [True, True, False]
    assert pd.isna(flags.iloc[3])


def test_cross_sectional_zscore_has_explicit_population_convention() -> None:
    values = pd.Series([1.0, 2.0, 3.0], index=["A", "B", "C"], name="value")
    scored = cross_sectional_zscore(values, ddof=0, minimum_observations=3)
    expected_tail = 1.0 / np.sqrt(2.0 / 3.0)
    assert scored.loc["A"] == pytest.approx(-expected_tail)
    assert scored.loc["B"] == pytest.approx(0.0)
    assert scored.loc["C"] == pytest.approx(expected_tail)


def test_momentum_and_residual_momentum_compound_exactly() -> None:
    prices = pd.Series([100.0, 110.0, 121.0])
    assert momentum_12_1(prices, lookback_sessions=2, skip_recent_sessions=1).iloc[
        -1
    ] == pytest.approx(0.10)
    residuals = pd.Series([0.10, -0.10])
    assert residual_momentum(residuals, window=2).iloc[-1] == pytest.approx(-0.01)


def test_factor_normalization_retains_auditable_stages() -> None:
    values = pd.Series([0.0, 1.0, 2.0, 100.0], index=list("ABCD"), name="factor")
    normalized = normalize_factor(
        values,
        lower_quantile=0.0,
        upper_quantile=0.75,
        ddof=0,
        minimum_observations=4,
    )
    assert normalized.raw.loc["D"] == pytest.approx(100.0)
    assert normalized.winsorized.loc["D"] == pytest.approx(26.5)
    assert normalized.zscore.mean() == pytest.approx(0.0, abs=1e-12)
    assert normalized.percentile.loc["D"] == pytest.approx(1.0)


def test_rolling_beta_and_reversal_use_only_the_declared_history() -> None:
    index = pd.bdate_range("2024-01-02", periods=5)
    market = pd.Series([0.0, 1.0, 2.0, 3.0, 100.0], index=index)
    asset = 2.0 * market
    asset.iloc[-1] = -999.0
    beta = rolling_beta(asset, market, window=4, minimum_observations=4, lag=1)
    # The current shock is outside the t-1 estimation window.
    assert beta.iloc[-1] == pytest.approx(2.0)
    assert short_term_reversal(pd.Series([100.0, 110.0]), horizon_sessions=1).iloc[
        -1
    ] == pytest.approx(-0.10)
