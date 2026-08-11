"""Transparent factor-feature and exposure calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

from quant_raas.quant.anomalies import fit_abnormal_return_model


@dataclass(frozen=True, slots=True)
class NormalizedFactor:
    """Cross-sectional factor stages retained for auditability."""

    raw: pd.Series
    winsorized: pd.Series
    zscore: pd.Series
    percentile: pd.Series


def _numeric(values: pd.Series) -> pd.Series[float]:
    return cast(
        "pd.Series[float]",
        pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan),
    )


def winsorize_cross_section(
    values: pd.Series,
    *,
    lower_quantile: float = 0.01,
    upper_quantile: float = 0.99,
    minimum_observations: int = 5,
) -> pd.Series:
    """Clip a cross-section to observed quantiles without imputing missing names."""

    if not 0.0 <= lower_quantile < upper_quantile <= 1.0:
        raise ValueError("winsorization quantiles must satisfy 0 <= lower < upper <= 1")
    if minimum_observations < 1:
        raise ValueError("minimum_observations must be positive")
    clean = _numeric(values)
    finite = clean.dropna()
    if len(finite) < minimum_observations:
        return pd.Series(np.nan, index=values.index, name=values.name, dtype="float64")
    lower, upper = finite.quantile([lower_quantile, upper_quantile])
    return clean.clip(lower=float(lower), upper=float(upper))


def cross_sectional_zscore(
    values: pd.Series,
    *,
    groups: pd.Series | None = None,
    ddof: int = 0,
    minimum_observations: int = 5,
) -> pd.Series:
    """Calculate overall or group-neutral z-scores.

    Cross-sectional normalization uses population ``ddof=0`` by default.  A
    group with too few names or zero dispersion remains missing.
    """

    if ddof < 0 or minimum_observations <= ddof:
        raise ValueError("minimum_observations must exceed non-negative ddof")
    clean = _numeric(values)

    def score(group: pd.Series) -> pd.Series:
        available = group.dropna()
        result = pd.Series(np.nan, index=group.index, dtype="float64")
        if len(available) < minimum_observations:
            return result
        scale = float(available.std(ddof=ddof))
        if not np.isfinite(scale) or scale == 0.0:
            return result
        result.loc[available.index] = (available - float(available.mean())) / scale
        return result

    if groups is None:
        scored = score(clean)
    else:
        aligned_groups = groups.reindex(clean.index)
        scored = pd.Series(np.nan, index=clean.index, dtype="float64")
        for group_value in aligned_groups.dropna().unique():
            members = aligned_groups.index[aligned_groups.eq(group_value).fillna(False)]
            scored.loc[members] = score(clean.loc[members])
    return scored.rename(f"{values.name or 'factor'}_zscore")


def normalize_factor(
    values: pd.Series,
    *,
    groups: pd.Series | None = None,
    lower_quantile: float = 0.01,
    upper_quantile: float = 0.99,
    ddof: int = 0,
    minimum_observations: int = 5,
) -> NormalizedFactor:
    """Winsorize, standardize, and rank a cross-sectional factor."""

    raw = _numeric(values)
    raw.name = values.name or "factor"
    winsorized = winsorize_cross_section(
        raw,
        lower_quantile=lower_quantile,
        upper_quantile=upper_quantile,
        minimum_observations=minimum_observations,
    ).rename(f"{raw.name}_winsorized")
    zscore = cross_sectional_zscore(
        winsorized,
        groups=groups,
        ddof=ddof,
        minimum_observations=minimum_observations,
    )
    percentile = winsorized.rank(method="average", pct=True, na_option="keep").rename(
        f"{raw.name}_percentile"
    )
    return NormalizedFactor(raw, winsorized, zscore, percentile)


def momentum_12_1(
    prices: pd.Series,
    *,
    lookback_sessions: int = 252,
    skip_recent_sessions: int = 21,
) -> pd.Series:
    """Calculate classic trailing momentum excluding the most recent month."""

    if lookback_sessions <= skip_recent_sessions or skip_recent_sessions < 0:
        raise ValueError("lookback must exceed a non-negative skip period")
    clean = _numeric(prices).where(lambda value: value > 0.0)
    return (
        clean.shift(skip_recent_sessions)
        .div(clean.shift(lookback_sessions))
        .sub(1.0)
        .rename("momentum_12_1")
    )


def short_term_reversal(prices: pd.Series, *, horizon_sessions: int = 21) -> pd.Series:
    """Return the negative trailing price return as a reversal exposure."""

    if horizon_sessions < 1:
        raise ValueError("horizon_sessions must be positive")
    clean = _numeric(prices).where(lambda value: value > 0.0)
    return (
        clean.pct_change(horizon_sessions, fill_method=None).mul(-1.0).rename("short_term_reversal")
    )


def rolling_beta(
    asset_returns: pd.Series,
    benchmark_returns: pd.Series,
    *,
    window: int = 126,
    minimum_observations: int = 63,
    lag: int = 1,
) -> pd.Series:
    """Estimate beta from a trailing window ending ``lag`` rows before each date."""

    if window < 2 or not 2 <= minimum_observations <= window or lag < 0:
        raise ValueError("invalid window, minimum_observations, or lag")
    if (
        asset_returns.index.has_duplicates
        or benchmark_returns.index.has_duplicates
        or not asset_returns.index.is_monotonic_increasing
        or not benchmark_returns.index.is_monotonic_increasing
    ):
        raise ValueError("return indices must be sorted and unique")
    aligned = pd.concat(
        [
            _numeric(asset_returns).rename("asset"),
            _numeric(benchmark_returns).reindex(asset_returns.index).rename("benchmark"),
        ],
        axis=1,
    ).shift(lag)
    covariance = (
        aligned["asset"]
        .rolling(window, min_periods=minimum_observations)
        .cov(aligned["benchmark"], ddof=1)
    )
    variance = aligned["benchmark"].rolling(window, min_periods=minimum_observations).var(ddof=1)
    return covariance.div(variance.where(variance > 0.0)).rename("rolling_beta")


def rolling_factor_exposures(
    asset_returns: pd.Series,
    factor_returns: pd.DataFrame,
    *,
    window: int = 126,
    minimum_observations: int = 63,
) -> pd.DataFrame:
    """Return rolling OLS coefficients fitted exclusively through ``t-1``."""

    return fit_abnormal_return_model(
        asset_returns,
        factor_returns,
        window=window,
        minimum_observations=minimum_observations,
    ).coefficients


def residual_momentum(
    residual_returns: pd.Series,
    *,
    window: int = 20,
    minimum_observations: int | None = None,
) -> pd.Series:
    """Compound residual returns over a trailing session window."""

    if window < 1:
        raise ValueError("window must be positive")
    required = window if minimum_observations is None else minimum_observations
    if not 1 <= required <= window:
        raise ValueError("minimum_observations must be in [1, window]")
    clean = _numeric(residual_returns)
    return (
        clean.rolling(window, min_periods=required)
        .apply(lambda sample: float(np.prod(1.0 + sample) - 1.0), raw=True)
        .rename("residual_momentum")
    )
