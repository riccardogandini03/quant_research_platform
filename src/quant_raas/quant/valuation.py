"""Historical and peer-relative valuation diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

import numpy as np
import pandas as pd

_TimestampInput = int | float | str | date | datetime | np.datetime64


@dataclass(frozen=True, slots=True)
class ValuationDistribution:
    """Current valuation relative to its available historical distribution."""

    observations: int
    current: float | None
    median: float | None
    zscore: float | None
    percentile: float | None


@dataclass(frozen=True, slots=True)
class ValuationDecomposition:
    """Exact multiplicative decomposition of price, earnings, and multiple change."""

    price_return: float
    earnings_revision: float
    implied_multiple_return: float | None
    reconstructed_price_return: float | None


def _aware_timestamp(value: object, *, name: str) -> pd.Timestamp:
    # The public boundary accepts provider scalars; this cast records the scalar
    # contract for pandas-stubs without changing pandas' runtime coercion.
    timestamp = pd.Timestamp(cast(_TimestampInput, value))
    if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return timestamp


def historical_valuation_distribution(
    values: pd.Series,
    *,
    as_of: object | None = None,
    lookback_observations: int | None = 1_260,
    minimum_observations: int = 60,
    ddof: int = 1,
) -> ValuationDistribution:
    """Locate the latest available multiple within its trailing distribution.

    The series index is the observation's availability timestamp when ``as_of``
    is used; period-end dates alone are not a point-in-time knowledge key.
    """

    if minimum_observations <= ddof or ddof < 0:
        raise ValueError("minimum_observations must exceed non-negative ddof")
    if lookback_observations is not None and lookback_observations < minimum_observations:
        raise ValueError("lookback_observations cannot be smaller than minimum_observations")
    if not isinstance(values.index, pd.DatetimeIndex):
        raise TypeError("valuation history must use a DatetimeIndex")
    if values.index.has_duplicates or not values.index.is_monotonic_increasing:
        raise ValueError("valuation history index must be sorted and unique")
    history = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if as_of is not None:
        cutoff = _aware_timestamp(as_of, name="as_of")
        history_index = cast("pd.DatetimeIndex", history.index)
        if history_index.tz is None:
            raise ValueError("valuation history index must be timezone-aware when as_of is used")
        history = history.loc[history_index <= cutoff]
    history = history.dropna()
    if lookback_observations is not None:
        history = history.iloc[-lookback_observations:]
    current = float(history.iloc[-1]) if not history.empty else None
    if len(history) < minimum_observations or current is None:
        return ValuationDistribution(len(history), current, None, None, None)
    scale = float(history.std(ddof=ddof))
    median = float(history.median())
    zscore = (
        None
        if not np.isfinite(scale) or scale == 0.0
        else (current - float(history.mean())) / scale
    )
    percentile = float((history <= current).mean())
    return ValuationDistribution(len(history), current, median, zscore, percentile)


def peer_relative_zscore(
    value: float | None,
    peer_values: pd.Series,
    *,
    minimum_observations: int = 5,
    ddof: int = 0,
) -> float | None:
    """Standardize a value against finite peer observations."""

    if value is None or not np.isfinite(value):
        return None
    if minimum_observations <= ddof or ddof < 0:
        raise ValueError("minimum_observations must exceed non-negative ddof")
    peers = pd.to_numeric(peer_values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(peers) < minimum_observations:
        return None
    scale = float(peers.std(ddof=ddof))
    return None if scale == 0.0 else float((value - peers.mean()) / scale)


def valuation_decomposition(
    price_return: float,
    earnings_revision: float,
) -> ValuationDecomposition:
    """Infer the exact multiple return from ``(1+P)=(1+E)*(1+M)``."""

    if not np.isfinite(price_return) or not np.isfinite(earnings_revision):
        raise ValueError("returns must be finite")
    earnings_gross = 1.0 + earnings_revision
    if earnings_gross == 0.0:
        return ValuationDecomposition(price_return, earnings_revision, None, None)
    multiple_return = (1.0 + price_return) / earnings_gross - 1.0
    reconstructed = (1.0 + earnings_revision) * (1.0 + multiple_return) - 1.0
    return ValuationDecomposition(
        price_return,
        earnings_revision,
        float(multiple_return),
        float(reconstructed),
    )
