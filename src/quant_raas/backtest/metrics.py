"""Known-convention performance metrics for research reports."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    observations: int
    cumulative_return: float
    cagr: float
    annualized_volatility: float
    sharpe: float | None
    max_drawdown: float
    hit_rate: float


def maximum_drawdown(returns: pd.Series) -> float:
    """Return the worst peak-to-trough loss from a periodic return series."""

    clean = returns.dropna().astype(float)
    if clean.empty:
        return float("nan")
    wealth = (1.0 + clean).cumprod()
    drawdown = wealth.div(wealth.cummax()).sub(1.0)
    return float(drawdown.min())


def summarize_performance(
    returns: pd.Series,
    *,
    periods_per_year: int = 252,
    annual_risk_free_rate: float = 0.0,
) -> PerformanceMetrics:
    """Summarize periodic returns using sample volatility (``ddof=1``)."""

    clean = returns.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    n_obs = int(clean.size)
    if n_obs == 0:
        return PerformanceMetrics(
            0, float("nan"), float("nan"), float("nan"), None, float("nan"), float("nan")
        )

    gross_growth = cast(float, (1.0 + clean).prod())
    cumulative = float(gross_growth - 1.0)
    years = n_obs / periods_per_year
    ending_wealth = max(0.0, 1.0 + cumulative)
    cagr = ending_wealth ** (1.0 / years) - 1.0 if years > 0 and ending_wealth > 0 else -1.0
    volatility = (
        float(clean.std(ddof=1) * math.sqrt(periods_per_year)) if n_obs > 1 else float("nan")
    )
    periodic_rf = (1.0 + annual_risk_free_rate) ** (1.0 / periods_per_year) - 1.0
    if not np.isfinite(volatility) or volatility == 0.0:
        sharpe = None
    else:
        sharpe = float((clean.mean() - periodic_rf) * periods_per_year / volatility)
    return PerformanceMetrics(
        observations=n_obs,
        cumulative_return=cumulative,
        cagr=float(cagr),
        annualized_volatility=volatility,
        sharpe=sharpe,
        max_drawdown=maximum_drawdown(clean),
        hit_rate=float((clean > 0.0).mean()),
    )
