"""HTTP-specific request schemas kept outside the financial domain."""

from __future__ import annotations

import math
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_raas.domain.enums import (
    FeedbackKind,
    IdentifierScheme,
    SecurityStatus,
    SecurityType,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentifierRegistration(ApiModel):
    scheme: IdentifierScheme
    value: str = Field(min_length=1)
    provider: str | None = None
    exchange_mic: str | None = Field(default=None, min_length=4, max_length=4)
    valid_from: datetime
    valid_to: datetime | None = None
    is_primary: bool = False


class SecurityRegistration(ApiModel):
    security_id: UUID | None = None
    name: str = Field(min_length=1)
    security_type: SecurityType = SecurityType.COMMON_STOCK
    status: SecurityStatus = SecurityStatus.ACTIVE
    primary_currency: str = Field(min_length=3, max_length=3)
    exchange_mic: str | None = Field(default=None, min_length=4, max_length=4)
    exchange_timezone: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    sector: str | None = None
    industry: str | None = None
    first_trade_date: date | None = None
    last_trade_date: date | None = None
    identifiers: tuple[IdentifierRegistration, ...] = Field(min_length=1)


class DailyRunRequest(ApiModel):
    coverage_list_id: UUID
    as_of: datetime
    data_cutoff_at: datetime
    lookback_calendar_days: int = Field(default=550, ge=370, le=5_000)
    source: str = "fixture"
    position_weights: dict[UUID, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_weights(self) -> DailyRunRequest:
        # NaN and infinities would poison priority scoring and can also raise
        # surprising exceptions when converted to Decimal for range checks.
        if any(not math.isfinite(weight) for weight in self.position_weights.values()):
            raise ValueError("position weights must be finite")
        if any(abs(weight) > 10.0 for weight in self.position_weights.values()):
            raise ValueError("position weights must be decimal values, not percentages")
        return self


class FeedbackRequest(ApiModel):
    feedback: FeedbackKind
    user_id: str | None = None
    comment: str | None = None
