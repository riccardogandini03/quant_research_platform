"""Backtest tests pin execution lag, turnover, costs, and PIT validation."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError

from quant_raas.backtest.costs import linear_cost, portfolio_turnover
from quant_raas.backtest.engine import CrossSectionalBacktestEngine
from quant_raas.backtest.models import CrossSectionalBacktestSpec
from quant_raas.backtest.validation import PointInTimeViolation


def test_turnover_is_one_way_and_cost_is_expressed_in_basis_points() -> None:
    weights = pd.DataFrame(
        [[0.5, -0.5], [-0.5, 0.5]],
        columns=["long", "short"],
    )
    turnover = portfolio_turnover(weights)
    # Entry from cash has gross change 1 and one-way turnover 0.5. Reversing both
    # legs has gross change 2 and one-way turnover 1.
    assert turnover.tolist() == pytest.approx([0.5, 1.0])
    assert linear_cost(turnover, 20.0).tolist() == pytest.approx([0.001, 0.002])


def test_backtest_spec_rejects_ambiguous_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        CrossSectionalBacktestSpec(
            feature_name="signal",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 31),
            minimum_names=4,
        )


def _backtest_inputs() -> tuple[pd.DataFrame, pd.DataFrame, CrossSectionalBacktestSpec]:
    dates = pd.date_range("2024-01-02T21:00:00Z", periods=4, freq="D")
    feature_rows = [
        {
            "decision_at": decision_at,
            "available_at": decision_at,
            "security_id": security_id,
            "feature_name": "signal",
            "value": value,
        }
        for decision_at in dates
        for security_id, value in zip(["A", "B", "C", "D"], [1.0, 2.0, 3.0, 4.0], strict=True)
    ]
    asset_returns = pd.DataFrame(
        {
            "A": [-0.01] * 4,
            "B": [-0.01] * 4,
            "C": [0.01] * 4,
            "D": [0.01] * 4,
        },
        index=dates,
    )
    spec = CrossSectionalBacktestSpec(
        feature_name="signal",
        start=dates[0].to_pydatetime(),
        end=dates[-1].to_pydatetime(),
        quantiles=2,
        direction="high",
        rebalance="daily",
        transaction_cost_bps=20.0,
        minimum_names=4,
        periods_per_year=252,
    )
    return pd.DataFrame(feature_rows), asset_returns, spec


def test_cross_sectional_engine_lags_signal_and_applies_cost_once() -> None:
    panel, asset_returns, spec = _backtest_inputs()
    result = CrossSectionalBacktestEngine().run(panel, asset_returns, spec)

    # The close-calculated signal cannot earn the first observed return.
    assert result.returns["gross_return"].tolist() == pytest.approx([0.0, 0.02, 0.02, 0.02])
    assert result.returns["turnover"].tolist() == pytest.approx([0.0, 1.0, 0.0, 0.0])
    assert result.returns["transaction_cost"].tolist() == pytest.approx([0.0, 0.002, 0.0, 0.0])
    assert result.returns["net_return"].tolist() == pytest.approx([0.0, 0.018, 0.02, 0.02])
    assert result.metrics.observations == 4
    assert result.skipped_dates == ()


@pytest.mark.point_in_time
def test_backtest_rejects_feature_unavailable_at_decision() -> None:
    panel, asset_returns, spec = _backtest_inputs()
    decision_at = pd.Timestamp(panel.at[0, "decision_at"])
    panel.at[0, "available_at"] = decision_at + timedelta(seconds=1)
    with pytest.raises(PointInTimeViolation, match="unavailable at decision time"):
        CrossSectionalBacktestEngine().run(panel, asset_returns, spec)
