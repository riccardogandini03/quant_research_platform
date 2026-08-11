"""Validated specifications accepted by the initial backtest engine."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CrossSectionalBacktestSpec(BaseModel):
    """A constrained, auditable cross-sectional long/short test.

    The engine intentionally accepts a narrow schema.  This same schema can be
    emitted by a future natural-language assistant without allowing arbitrary
    code execution.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_name: str = Field(min_length=1)
    start: datetime
    end: datetime
    quantiles: int = Field(default=5, ge=2, le=20)
    direction: Literal["high", "low"] = "high"
    rebalance: Literal["daily", "weekly", "monthly"] = "weekly"
    transaction_cost_bps: float = Field(default=20.0, ge=0.0, le=1_000.0)
    minimum_names: int = Field(default=20, ge=4)
    periods_per_year: int = Field(default=252, ge=1)

    @field_validator("start", "end")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Reject naive cutoffs because availability depends on an exact instant."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("backtest timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> CrossSectionalBacktestSpec:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self
