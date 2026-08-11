"""Safe conversion boundary from generated JSON to a backtest specification."""

from __future__ import annotations

from quant_raas.backtest.models import CrossSectionalBacktestSpec


def validate_backtest_spec(payload: str) -> CrossSectionalBacktestSpec:
    """Reject unknown fields and invalid assumptions through the Pydantic schema."""

    return CrossSectionalBacktestSpec.model_validate_json(payload)
