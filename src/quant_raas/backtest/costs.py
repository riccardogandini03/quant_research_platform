"""Transparent transaction-cost assumptions for research backtests."""

from __future__ import annotations

import pandas as pd


def portfolio_turnover(weights: pd.DataFrame) -> pd.Series:
    """Calculate one-way turnover as half the absolute change in weights.

    The 0.5 convention avoids counting both sides of a fully funded rebalance
    twice.  The first row assumes the strategy starts from cash.
    """

    if weights.empty:
        return pd.Series(dtype="float64", name="turnover")
    previous = weights.shift(1).fillna(0.0)
    turnover = 0.5 * weights.fillna(0.0).sub(previous).abs().sum(axis=1)
    return turnover.rename("turnover")


def linear_cost(turnover: pd.Series, basis_points: float) -> pd.Series:
    """Apply a simple proportional round-trip cost assumption."""

    if basis_points < 0:
        raise ValueError("basis_points cannot be negative")
    return (turnover * basis_points / 10_000.0).rename("transaction_cost")
