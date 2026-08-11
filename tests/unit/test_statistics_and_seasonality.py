"""Statistical tests report invalidity explicitly and control repeated tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_raas.quant.seasonality import compound_period_returns, weekday_seasonality
from quant_raas.quant.statistics import (
    benjamini_hochberg,
    block_bootstrap_mean,
    descriptive_statistics,
    mean_test_hac,
    mean_test_iid,
)


def test_descriptive_statistics_exclude_missing_and_non_finite_values() -> None:
    result = descriptive_statistics([0.10, -0.10, np.nan, np.inf])
    assert result.observations == 2
    assert result.mean == pytest.approx(0.0)
    assert result.median == pytest.approx(0.0)
    assert result.win_rate == pytest.approx(0.5)


def test_mean_tests_never_present_tiny_or_zero_variance_samples_as_valid() -> None:
    too_small = mean_test_iid([0.01, -0.01], minimum_observations=3)
    assert not too_small.valid
    assert too_small.p_value is None
    assert too_small.warnings == ("insufficient_observations",)

    # Economically constant decimal returns must be rejected even when their
    # binary representation leaves machine-scale variance after summation.
    iid_zero_variance = mean_test_iid([0.01] * 20, minimum_observations=20)
    hac_zero_variance = mean_test_hac([0.01] * 20, minimum_observations=20)
    for result in (iid_zero_variance, hac_zero_variance):
        assert not result.valid
        assert result.warnings == ("zero_sample_variance",)


def test_hac_and_block_bootstrap_are_reproducible_on_known_sample() -> None:
    values = pd.Series([0.0, 0.125] * 15)
    hac = mean_test_hac(values, minimum_observations=20, max_lags=1)
    assert hac.valid
    assert hac.observations == 30
    assert hac.estimate == pytest.approx(0.0625)
    assert hac.standard_error is not None and hac.standard_error > 0.0

    first = block_bootstrap_mean(
        values,
        block_size=2,
        resamples=200,
        minimum_observations=20,
        seed=7,
    )
    second = block_bootstrap_mean(
        values,
        block_size=2,
        resamples=200,
        minimum_observations=20,
        seed=7,
    )
    assert first == second
    assert first.valid
    assert first.estimate == pytest.approx(0.0625)
    assert first.confidence_interval is not None
    assert first.confidence_interval[0] <= first.estimate <= first.confidence_interval[1]


def test_benjamini_hochberg_preserves_input_order_and_missing_values() -> None:
    result = benjamini_hochberg([0.01, 0.04, 0.03, None], alpha=0.05)
    assert result.adjusted_p_values[:3] == pytest.approx((0.03, 0.04, 0.04))
    assert result.adjusted_p_values[3] is None
    assert result.rejected == (True, True, True, False)
    assert result.hypotheses == 3


def test_calendar_period_returns_compound_within_each_month() -> None:
    index = pd.bdate_range("2024-01-01", "2024-02-29")
    daily = pd.Series(np.where(index.month == 1, 0.01, -0.01), index=index)
    monthly = compound_period_returns(
        daily,
        frequency="M",
        minimum_observations=15,
        exclude_boundary_periods=False,
    )
    january_days = int((index.month == 1).sum())
    february_days = int((index.month == 2).sum())
    assert monthly.loc[pd.Period("2024-01", freq="M")] == pytest.approx(1.01**january_days - 1.0)
    assert monthly.loc[pd.Period("2024-02", freq="M")] == pytest.approx(0.99**february_days - 1.0)


def test_weekday_seasonality_does_not_count_missing_return_as_a_loss() -> None:
    index = pd.bdate_range("2024-01-01", periods=10)
    returns = pd.Series(0.01, index=index)
    returns.iloc[0] = np.nan  # One of two Mondays is unavailable, not a losing day.
    result = weekday_seasonality(returns, minimum_observations=2, max_hac_lags=0)
    assert int(result.summary["observations"].sum()) == 9
    assert result.summary.loc[0, "observations"] == 1
    assert not bool(result.summary.loc[0, "test_valid"])
