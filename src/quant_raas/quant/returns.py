"""Pure return calculations with explicit financial conventions.

The functions in this module never download data, inspect the wall clock, or
change global pandas options.  Callers are responsible for supplying prices in
the desired adjustment convention (raw price return or adjusted total return).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class ReturnSummary:
    """Summary of periodic simple returns.

    Volatility uses the caller-specified ``ddof`` (sample standard deviation by
    default). ``annualized_arithmetic_return`` is mean periodic return times the
    number of periods; ``cagr`` is the realized geometric growth rate.
    """

    observations: int
    cumulative_return: float | None
    cagr: float | None
    annualized_arithmetic_return: float | None
    annualized_volatility: float | None
    sharpe_ratio: float | None
    hit_rate: float | None


def _numeric_series(values: pd.Series) -> pd.Series[float]:
    """Coerce a series to finite floats while preserving its index and name."""

    return cast(
        "pd.Series[float]",
        pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan),
    )


def _validate_time_index(values: pd.Series, *, name: str) -> None:
    if values.index.has_duplicates:
        raise ValueError(f"{name} index must be unique")
    if not values.index.is_monotonic_increasing:
        raise ValueError(f"{name} index must be sorted in increasing order")


def simple_returns(prices: pd.Series, *, periods: int = 1) -> pd.Series:
    """Calculate simple price returns without forward-filling missing prices."""

    if periods < 1:
        raise ValueError("periods must be at least one")
    _validate_time_index(prices, name="prices")
    clean = _numeric_series(prices)
    result = clean.pct_change(periods=periods, fill_method=None).replace([np.inf, -np.inf], np.nan)
    result.name = prices.name or "return"
    return result


def log_returns(prices: pd.Series, *, periods: int = 1) -> pd.Series:
    """Calculate log returns; non-positive prices produce missing values."""

    if periods < 1:
        raise ValueError("periods must be at least one")
    _validate_time_index(prices, name="prices")
    clean = _numeric_series(prices).where(lambda value: value > 0.0)
    result = cast("pd.Series[float]", np.log(clean.div(clean.shift(periods))))
    result.name = prices.name or "log_return"
    return result


def horizon_returns(
    prices: pd.Series,
    *,
    horizons: Iterable[int] = (1, 2, 5, 20, 63, 126, 252),
) -> pd.DataFrame:
    """Return a frame of trailing simple returns for each session horizon."""

    normalized = tuple(dict.fromkeys(int(horizon) for horizon in horizons))
    if not normalized or any(horizon < 1 for horizon in normalized):
        raise ValueError("horizons must contain positive integers")
    return pd.DataFrame(
        {f"return_{horizon}d": simple_returns(prices, periods=horizon) for horizon in normalized}
    )


def compound_returns(returns: pd.Series) -> float | None:
    """Compound available simple returns; return ``None`` for an empty sample."""

    clean = _numeric_series(returns).dropna()
    if clean.empty:
        return None
    return float(np.prod(1.0 + clean.to_numpy(dtype=float)) - 1.0)


def rolling_total_return(
    returns: pd.Series,
    *,
    window: int,
    min_periods: int | None = None,
) -> pd.Series:
    """Compound simple returns in trailing windows without imputing gaps."""

    if window < 1:
        raise ValueError("window must be at least one")
    required = window if min_periods is None else min_periods
    if required < 1 or required > window:
        raise ValueError("min_periods must be between one and window")
    clean = _numeric_series(returns)
    return clean.rolling(window, min_periods=required).apply(
        lambda sample: float(np.prod(1.0 + sample) - 1.0), raw=True
    )


def overnight_gap(open_prices: pd.Series, close_prices: pd.Series) -> pd.Series:
    """Calculate open-to-previous-close simple returns on aligned sessions.

    Use raw, split-consistent OHLC for an executable price gap.  Passing total-
    return-adjusted OHLC changes the economic meaning and should be explicit in
    the upstream data contract.
    """

    _validate_time_index(open_prices, name="open_prices")
    _validate_time_index(close_prices, name="close_prices")
    frame = pd.concat(
        [
            _numeric_series(open_prices).rename("open"),
            _numeric_series(close_prices).rename("close"),
        ],
        axis=1,
        join="inner",
    )
    return (
        frame["open"]
        .div(frame["close"].shift(1))
        .sub(1.0)
        .replace([np.inf, -np.inf], np.nan)
        .rename("overnight_gap")
    )


def intraday_return(open_prices: pd.Series, close_prices: pd.Series) -> pd.Series:
    """Calculate same-session close-to-open simple returns."""

    _validate_time_index(open_prices, name="open_prices")
    _validate_time_index(close_prices, name="close_prices")
    frame = pd.concat(
        [
            _numeric_series(open_prices).rename("open"),
            _numeric_series(close_prices).rename("close"),
        ],
        axis=1,
        join="inner",
    )
    return (
        frame["close"]
        .div(frame["open"])
        .sub(1.0)
        .replace([np.inf, -np.inf], np.nan)
        .rename("intraday_return")
    )


def relative_return(asset_returns: pd.Series, benchmark_returns: pd.Series) -> pd.Series:
    """Calculate exact one-period relative return as gross-return ratio minus one."""

    aligned = pd.concat(
        [
            _numeric_series(asset_returns).rename("asset"),
            _numeric_series(benchmark_returns).rename("benchmark"),
        ],
        axis=1,
        join="inner",
    )
    valid = (1.0 + aligned["benchmark"]) != 0.0
    result = (1.0 + aligned["asset"]).div(1.0 + aligned["benchmark"]).sub(1.0)
    return result.where(valid).rename("relative_return")


def relative_strength_index(
    asset_returns: pd.Series,
    benchmark_returns: pd.Series,
    *,
    base: float = 1.0,
) -> pd.Series:
    """Build a wealth ratio from synchronized asset and benchmark returns."""

    if base <= 0.0:
        raise ValueError("base must be positive")
    relative = relative_return(asset_returns, benchmark_returns)
    return ((1.0 + relative).cumprod(skipna=False) * base).rename("relative_strength")


def realized_cagr(returns: pd.Series, *, periods_per_year: int = 252) -> float | None:
    """Calculate realized CAGR using observation count as elapsed periods."""

    if periods_per_year < 1:
        raise ValueError("periods_per_year must be positive")
    clean = _numeric_series(returns).dropna()
    if clean.empty:
        return None
    wealth = float(np.prod(1.0 + clean.to_numpy(dtype=float)))
    if wealth < 0.0:
        return None
    if wealth == 0.0:
        return -1.0
    years = len(clean) / periods_per_year
    return float(wealth ** (1.0 / years) - 1.0)


def annualized_arithmetic_return(
    returns: pd.Series,
    *,
    periods_per_year: int = 252,
) -> float | None:
    """Annualize the arithmetic periodic mean by simple multiplication."""

    if periods_per_year < 1:
        raise ValueError("periods_per_year must be positive")
    clean = _numeric_series(returns).dropna()
    return None if clean.empty else float(clean.mean() * periods_per_year)


def annualized_volatility(
    returns: pd.Series,
    *,
    periods_per_year: int = 252,
    ddof: int = 1,
) -> float | None:
    """Annualize periodic volatility using ``sqrt(periods_per_year)``."""

    if periods_per_year < 1:
        raise ValueError("periods_per_year must be positive")
    if ddof < 0:
        raise ValueError("ddof cannot be negative")
    clean = _numeric_series(returns).dropna()
    if len(clean) <= ddof:
        return None
    return float(clean.std(ddof=ddof) * math.sqrt(periods_per_year))


def sharpe_ratio(
    returns: pd.Series,
    *,
    periods_per_year: int = 252,
    annual_risk_free_rate: float = 0.0,
    ddof: int = 1,
) -> float | None:
    """Calculate annualized Sharpe from arithmetic excess periodic returns."""

    if annual_risk_free_rate <= -1.0:
        raise ValueError("annual_risk_free_rate must be greater than -100%")
    clean = _numeric_series(returns).dropna()
    volatility = annualized_volatility(clean, periods_per_year=periods_per_year, ddof=ddof)
    if volatility is None or volatility == 0.0:
        return None
    periodic_rf = (1.0 + annual_risk_free_rate) ** (1.0 / periods_per_year) - 1.0
    annualized_excess = float((clean.mean() - periodic_rf) * periods_per_year)
    return annualized_excess / volatility


def summarize_returns(
    returns: pd.Series,
    *,
    periods_per_year: int = 252,
    annual_risk_free_rate: float = 0.0,
    ddof: int = 1,
) -> ReturnSummary:
    """Summarize returns while excluding, rather than filling, missing values."""

    clean = _numeric_series(returns).dropna()
    if clean.empty:
        return ReturnSummary(0, None, None, None, None, None, None)
    return ReturnSummary(
        observations=len(clean),
        cumulative_return=compound_returns(clean),
        cagr=realized_cagr(clean, periods_per_year=periods_per_year),
        annualized_arithmetic_return=annualized_arithmetic_return(
            clean, periods_per_year=periods_per_year
        ),
        annualized_volatility=annualized_volatility(
            clean, periods_per_year=periods_per_year, ddof=ddof
        ),
        sharpe_ratio=sharpe_ratio(
            clean,
            periods_per_year=periods_per_year,
            annual_risk_free_rate=annual_risk_free_rate,
            ddof=ddof,
        ),
        hit_rate=float((clean > 0.0).mean()),
    )
