"""Security-level risk diagnostics with explicit loss and variance conventions."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant_raas.quant.returns import annualized_volatility


@dataclass(frozen=True, slots=True)
class BetaEstimate:
    """OLS market-model estimate with a periodic intercept."""

    observations: int
    alpha: float | None
    beta: float | None
    correlation: float | None
    r_squared: float | None


@dataclass(frozen=True, slots=True)
class RiskSummary:
    """Compact risk diagnostics; VaR and ES are positive loss magnitudes."""

    observations: int
    annualized_volatility: float | None
    annualized_downside_deviation: float | None
    maximum_drawdown: float | None
    value_at_risk: float | None
    expected_shortfall: float | None


def _clean(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def rolling_volatility(
    returns: pd.Series,
    *,
    window: int = 63,
    min_periods: int | None = None,
    periods_per_year: int = 252,
    ddof: int = 1,
) -> pd.Series:
    """Trailing annualized volatility using sample ``ddof=1`` by default."""

    if window < 1 or periods_per_year < 1 or ddof < 0:
        raise ValueError("window/periods_per_year must be positive and ddof non-negative")
    required = window if min_periods is None else min_periods
    if required <= ddof or required > window:
        raise ValueError("min_periods must exceed ddof and not exceed window")
    clean = pd.to_numeric(returns, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return (
        clean.rolling(window, min_periods=required)
        .std(ddof=ddof)
        .mul(math.sqrt(periods_per_year))
        .rename("annualized_volatility")
    )


def downside_deviation(
    returns: pd.Series,
    *,
    target_return: float = 0.0,
    periods_per_year: int = 252,
    ddof: int = 0,
) -> float | None:
    """Annualized lower partial deviation around a periodic target.

    The denominator is ``N - ddof`` across all finite observations, including
    observations above the target whose downside contribution is zero.
    """

    if periods_per_year < 1 or ddof < 0:
        raise ValueError("periods_per_year must be positive and ddof non-negative")
    clean = _clean(returns)
    if len(clean) <= ddof:
        return None
    downside = np.minimum(clean.to_numpy(dtype=float) - target_return, 0.0)
    denominator = len(downside) - ddof
    return float(
        math.sqrt(float(np.square(downside).sum()) / denominator) * math.sqrt(periods_per_year)
    )


def maximum_drawdown(returns: pd.Series) -> float | None:
    """Return the worst peak-to-trough simple loss as a negative number."""

    clean = _clean(returns)
    if clean.empty:
        return None
    wealth = np.concatenate([[1.0], np.cumprod(1.0 + clean.to_numpy(dtype=float))])
    peaks = np.maximum.accumulate(wealth)
    return float(np.min(wealth / peaks - 1.0))


def historical_value_at_risk(returns: pd.Series, *, confidence: float = 0.95) -> float | None:
    """Return non-negative historical VaR loss at the requested confidence."""

    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")
    clean = _clean(returns)
    if clean.empty:
        return None
    cutoff = float(clean.quantile(1.0 - confidence))
    return max(0.0, -cutoff)


def historical_expected_shortfall(
    returns: pd.Series,
    *,
    confidence: float = 0.95,
) -> float | None:
    """Return average non-negative loss in the historical VaR tail."""

    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")
    clean = _clean(returns)
    if clean.empty:
        return None
    cutoff = float(clean.quantile(1.0 - confidence))
    tail = clean.loc[clean <= cutoff]
    return None if tail.empty else max(0.0, -float(tail.mean()))


def beta_estimate(asset_returns: pd.Series, benchmark_returns: pd.Series) -> BetaEstimate:
    """Estimate an intercept and beta from synchronized finite observations."""

    aligned = (
        pd.concat(
            [
                pd.to_numeric(asset_returns, errors="coerce").rename("asset"),
                pd.to_numeric(benchmark_returns, errors="coerce").rename("benchmark"),
            ],
            axis=1,
            join="inner",
        )
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    n_obs = len(aligned)
    if n_obs < 2:
        return BetaEstimate(n_obs, None, None, None, None)
    benchmark_variance = float(aligned["benchmark"].var(ddof=1))
    if not np.isfinite(benchmark_variance) or benchmark_variance == 0.0:
        return BetaEstimate(n_obs, None, None, None, None)
    covariance = float(aligned["asset"].cov(aligned["benchmark"], ddof=1))
    beta = covariance / benchmark_variance
    alpha = float(aligned["asset"].mean() - beta * aligned["benchmark"].mean())
    raw_correlation = float(aligned["asset"].corr(aligned["benchmark"]))
    if not np.isfinite(raw_correlation):
        return BetaEstimate(n_obs, alpha, beta, None, None)
    return BetaEstimate(n_obs, alpha, beta, raw_correlation, raw_correlation**2)


def summarize_risk(
    returns: pd.Series,
    *,
    periods_per_year: int = 252,
    confidence: float = 0.95,
    volatility_ddof: int = 1,
    downside_ddof: int = 0,
) -> RiskSummary:
    """Create a missing-aware risk summary from periodic simple returns."""

    clean = _clean(returns)
    return RiskSummary(
        observations=len(clean),
        annualized_volatility=annualized_volatility(
            clean, periods_per_year=periods_per_year, ddof=volatility_ddof
        ),
        annualized_downside_deviation=downside_deviation(
            clean, periods_per_year=periods_per_year, ddof=downside_ddof
        ),
        maximum_drawdown=maximum_drawdown(clean),
        value_at_risk=historical_value_at_risk(clean, confidence=confidence),
        expected_shortfall=historical_expected_shortfall(clean, confidence=confidence),
    )
