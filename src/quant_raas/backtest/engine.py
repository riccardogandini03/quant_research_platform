"""Initial cross-sectional screen backtest with explicit PIT controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

from quant_raas.backtest.costs import linear_cost, portfolio_turnover
from quant_raas.backtest.execution import lag_positions, portfolio_returns
from quant_raas.backtest.metrics import PerformanceMetrics, summarize_performance
from quant_raas.backtest.models import CrossSectionalBacktestSpec
from quant_raas.backtest.validation import (
    assert_available_by_decision,
    normalize_utc,
    require_columns,
)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Auditable outputs retained together rather than a single Sharpe ratio."""

    returns: pd.DataFrame
    weights: pd.DataFrame
    metrics: PerformanceMetrics
    skipped_dates: tuple[pd.Timestamp, ...]


class CrossSectionalBacktestEngine:
    """Test a feature by buying one tail and shorting the opposite tail."""

    def run(
        self,
        feature_panel: pd.DataFrame,
        asset_returns: pd.DataFrame,
        spec: CrossSectionalBacktestSpec,
    ) -> BacktestResult:
        """Run a lagged equal-weight quantile backtest.

        ``feature_panel`` must contain one point-in-time row per security and
        decision instant.  ``asset_returns`` is a wide date x security frame of
        next-period returns.  Targets are lagged once before they earn returns.
        """

        require_columns(
            feature_panel,
            ["decision_at", "available_at", "security_id", "feature_name", "value"],
        )
        assert_available_by_decision(feature_panel)

        panel = feature_panel.loc[feature_panel["feature_name"] == spec.feature_name].copy()
        panel["decision_at"] = normalize_utc(panel["decision_at"], name="decision_at")
        panel = panel.loc[
            (panel["decision_at"] >= pd.Timestamp(spec.start).tz_convert("UTC"))
            & (panel["decision_at"] <= pd.Timestamp(spec.end).tz_convert("UTC"))
        ]
        panel["value"] = pd.to_numeric(panel["value"], errors="coerce")
        panel = panel.replace([np.inf, -np.inf], np.nan).dropna(subset=["value"])

        if spec.rebalance != "daily" and not panel.empty:
            # Select the last decision available in each UTC week/month.  String
            # keys avoid pandas dropping timezone information via PeriodIndex.
            period_key = (
                panel["decision_at"].dt.strftime("%G-%V")
                if spec.rebalance == "weekly"
                else panel["decision_at"].dt.strftime("%Y-%m")
            )
            selected = panel.groupby(period_key, sort=True)["decision_at"].transform("max")
            panel = panel.loc[panel["decision_at"] == selected]

        rows: dict[pd.Timestamp, pd.Series] = {}
        skipped: list[pd.Timestamp] = []
        for decision_at, cross_section in panel.groupby("decision_at", sort=True):
            # `normalize_utc` guarantees Timestamp group keys; pandas' stubs use
            # a deliberately broad scalar union for generic groupby results.
            decision_timestamp = cast(pd.Timestamp, decision_at)
            # Duplicate security values at one decision time are ambiguous and
            # usually indicate an upstream vintage-selection error.
            if cross_section["security_id"].duplicated().any():
                raise ValueError(f"duplicate security values at {decision_at}")
            if len(cross_section) < spec.minimum_names:
                skipped.append(decision_timestamp)
                continue

            percentile = cross_section["value"].rank(method="average", pct=True)
            tail = 1.0 / spec.quantiles
            high = cross_section.loc[percentile > 1.0 - tail, "security_id"].astype(str)
            low = cross_section.loc[percentile <= tail, "security_id"].astype(str)
            if high.empty or low.empty:
                skipped.append(decision_timestamp)
                continue

            weights = pd.Series(0.0, index=cross_section["security_id"].astype(str).unique())
            long_series, short_series = (high, low) if spec.direction == "high" else (low, high)
            long_names = [str(name) for name in long_series]
            short_names = [str(name) for name in short_series]
            weights.loc[long_names] = 1.0 / len(long_names)
            weights.loc[short_names] = -1.0 / len(short_names)
            rows[decision_timestamp] = weights

        returns = asset_returns.copy()
        returns.index = pd.to_datetime(returns.index, utc=True)
        returns = returns.sort_index().loc[
            (returns.index >= pd.Timestamp(spec.start).tz_convert("UTC"))
            & (returns.index <= pd.Timestamp(spec.end).tz_convert("UTC"))
        ]
        target_weights = pd.DataFrame.from_dict(rows, orient="index").sort_index().fillna(0.0)
        # Between rebalance dates the previous target remains in force.  The
        # one-row lag then models a close-calculated signal trading no earlier
        # than the next observed return period.
        target_weights = target_weights.reindex(returns.index).ffill().fillna(0.0)
        executable_weights = lag_positions(target_weights, periods=1)

        gross = portfolio_returns(executable_weights, returns)
        turnover = portfolio_turnover(executable_weights).reindex(gross.index).fillna(0.0)
        costs = linear_cost(turnover, spec.transaction_cost_bps)
        result_frame = pd.concat([gross, turnover, costs], axis=1)
        result_frame["net_return"] = result_frame["gross_return"] - result_frame["transaction_cost"]
        metrics = summarize_performance(
            result_frame["net_return"], periods_per_year=spec.periods_per_year
        )
        return BacktestResult(
            returns=result_frame,
            weights=executable_weights,
            metrics=metrics,
            skipped_dates=tuple(skipped),
        )
