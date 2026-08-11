"""Execution conventions shared by screen simulations."""

from __future__ import annotations

import pandas as pd


def lag_positions(weights: pd.DataFrame, periods: int = 1) -> pd.DataFrame:
    """Delay target weights so a close signal cannot trade at that same close."""

    if periods < 0:
        raise ValueError("periods cannot be negative")
    return weights.shift(periods).fillna(0.0)


def portfolio_returns(weights: pd.DataFrame, asset_returns: pd.DataFrame) -> pd.Series:
    """Calculate aligned portfolio returns from already executable weights."""

    common_dates = weights.index.intersection(asset_returns.index)
    common_assets = weights.columns.intersection(asset_returns.columns)
    if common_dates.empty or common_assets.empty:
        return pd.Series(dtype="float64", name="gross_return")
    aligned_weights = weights.loc[common_dates, common_assets].fillna(0.0)
    aligned_returns = asset_returns.loc[common_dates, common_assets].fillna(0.0)
    return (aligned_weights * aligned_returns).sum(axis=1).rename("gross_return")
