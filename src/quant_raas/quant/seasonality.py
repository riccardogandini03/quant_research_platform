"""Calendar-effect research with boundary, sample-size, HAC, and FDR controls."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

from quant_raas.quant.statistics import (
    benjamini_hochberg,
    descriptive_statistics,
    mean_test_hac,
)


@dataclass(frozen=True, slots=True)
class SeasonalityResult:
    """Underlying period returns and their cross-period summary."""

    period_returns: pd.Series
    summary: pd.DataFrame


def _daily_returns(values: pd.Series) -> pd.Series[float]:
    if not isinstance(values.index, pd.DatetimeIndex):
        raise TypeError("returns must use a DatetimeIndex")
    if values.index.has_duplicates or not values.index.is_monotonic_increasing:
        raise ValueError("returns index must be sorted and unique")
    return cast(
        "pd.Series[float]",
        pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan),
    )


def compound_period_returns(
    daily_returns: pd.Series,
    *,
    frequency: str = "M",
    minimum_observations: int = 15,
    exclude_boundary_periods: bool = True,
) -> pd.Series:
    """Compound daily simple returns by calendar period.

    Boundary periods are excluded by default because a generic daily index
    cannot prove that its first/last calendar period is complete.  Internal
    periods need at least ``minimum_observations`` finite returns.
    """

    if minimum_observations < 1:
        raise ValueError("minimum_observations must be positive")
    clean = _daily_returns(daily_returns)
    periods = cast("pd.DatetimeIndex", clean.index).to_period(frequency)
    grouped = clean.groupby(periods, sort=True)
    counts = grouped.count()
    compounded = grouped.apply(
        lambda sample: (
            float(np.prod(1.0 + sample.dropna().to_numpy(dtype=float)) - 1.0)
            if len(sample.dropna()) >= minimum_observations
            else float("nan")
        )
    )
    if exclude_boundary_periods and len(compounded) > 0:
        compounded.iloc[0] = np.nan
        if len(compounded) > 1:
            compounded.iloc[-1] = np.nan
    compounded = compounded.where(counts >= minimum_observations)
    return compounded.dropna().rename("period_return")


def _summary_table(
    values: pd.Series,
    buckets: pd.Series,
    labels: dict[int, str],
    *,
    minimum_observations: int,
    max_hac_lags: int | None,
    fdr_alpha: float,
) -> pd.DataFrame:
    columns = [
        "bucket",
        "label",
        "observations",
        "mean_return",
        "median_return",
        "sample_std",
        "win_rate",
        "standard_error",
        "confidence_lower",
        "confidence_upper",
        "p_value",
        "test_valid",
        "test_warnings",
        "q_value",
        "fdr_rejected",
    ]
    rows: list[dict[str, object]] = []
    p_values: list[float | None] = []
    for bucket, label in labels.items():
        sample = values.loc[buckets == bucket]
        description = descriptive_statistics(sample, ddof=1)
        test = mean_test_hac(
            sample,
            minimum_observations=minimum_observations,
            max_lags=max_hac_lags,
        )
        rows.append(
            {
                "bucket": bucket,
                "label": label,
                "observations": description.observations,
                "mean_return": description.mean,
                "median_return": description.median,
                "sample_std": description.standard_deviation,
                "win_rate": description.win_rate,
                "standard_error": test.standard_error,
                "confidence_lower": test.confidence_interval[0]
                if test.confidence_interval is not None
                else None,
                "confidence_upper": test.confidence_interval[1]
                if test.confidence_interval is not None
                else None,
                "p_value": test.p_value,
                "test_valid": test.valid,
                "test_warnings": test.warnings,
            }
        )
        p_values.append(test.p_value)
    fdr = benjamini_hochberg(p_values, alpha=fdr_alpha)
    for row, q_value, rejected in zip(rows, fdr.adjusted_p_values, fdr.rejected, strict=True):
        row["q_value"] = q_value
        row["fdr_rejected"] = rejected
    return pd.DataFrame(rows, columns=columns).set_index("bucket")


def monthly_seasonality(
    daily_returns: pd.Series,
    *,
    minimum_days_per_month: int = 15,
    minimum_years: int = 5,
    exclude_boundary_months: bool = True,
    max_hac_lags: int | None = 1,
    fdr_alpha: float = 0.05,
) -> SeasonalityResult:
    """Estimate calendar-month effects from complete compounded monthly returns."""

    period_returns = compound_period_returns(
        daily_returns,
        frequency="M",
        minimum_observations=minimum_days_per_month,
        exclude_boundary_periods=exclude_boundary_months,
    )
    period_index = cast("pd.PeriodIndex", period_returns.index)
    buckets = pd.Series(period_index.month, index=period_index)
    labels = {month: calendar.month_abbr[month] for month in range(1, 13)}
    summary = _summary_table(
        period_returns,
        buckets,
        labels,
        minimum_observations=minimum_years,
        max_hac_lags=max_hac_lags,
        fdr_alpha=fdr_alpha,
    )
    return SeasonalityResult(period_returns, summary)


def weekday_seasonality(
    daily_returns: pd.Series,
    *,
    minimum_observations: int = 20,
    max_hac_lags: int | None = 1,
    fdr_alpha: float = 0.05,
) -> SeasonalityResult:
    """Estimate weekday effects without treating missing returns as losing days."""

    clean = _daily_returns(daily_returns).dropna().rename("daily_return")
    date_index = cast("pd.DatetimeIndex", clean.index)
    buckets = pd.Series(date_index.dayofweek, index=date_index)
    observed = sorted(set(int(value) for value in buckets))
    labels = {day: calendar.day_name[day] for day in observed}
    summary = _summary_table(
        clean,
        buckets,
        labels,
        minimum_observations=minimum_observations,
        max_hac_lags=max_hac_lags,
        fdr_alpha=fdr_alpha,
    )
    return SeasonalityResult(clean, summary)
