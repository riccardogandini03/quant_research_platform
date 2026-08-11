"""Market-data, feature, and ingestion lineage contracts."""

from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from quant_raas.common.clock import UtcDatetime, utc_now
from quant_raas.domain.base import DomainModel
from quant_raas.domain.enums import (
    BarFrequency,
    BatchStatus,
    CorporateActionType,
    DataQualityFlag,
)


class PriceRequestItem(DomainModel):
    """Canonical security paired with the symbol expected by one provider."""

    security_id: UUID
    provider_identifier: str = Field(min_length=1, max_length=128)


class PriceBarRequest(DomainModel):
    """Provider-neutral request for daily bars."""

    items: tuple[PriceRequestItem, ...] = Field(min_length=1)
    start_date: date
    end_date: date
    requested_at: UtcDatetime = Field(default_factory=utc_now)
    frequency: BarFrequency = BarFrequency.DAILY

    @model_validator(mode="after")
    def validate_dates(self) -> PriceBarRequest:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")
        return self


class IngestionBatch(DomainModel):
    """Audit envelope for one reproducible provider request."""

    batch_id: UUID = Field(default_factory=uuid4)
    batch_key: str = Field(min_length=8, max_length=128)
    provider: str = Field(min_length=1, max_length=80)
    dataset: str = Field(min_length=1, max_length=80)
    requested_at: UtcDatetime
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    status: BatchStatus = BatchStatus.PENDING
    request_fingerprint: str = Field(min_length=8, max_length=128)
    content_hash: str | None = Field(default=None, min_length=8, max_length=128)
    row_count: int = Field(default=0, ge=0)
    error_message: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_batch_timing(self) -> IngestionBatch:
        if self.started_at < self.requested_at:
            raise ValueError("started_at cannot precede requested_at")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if (
            self.status in {BatchStatus.SUCCEEDED, BatchStatus.PARTIAL, BatchStatus.FAILED}
            and self.completed_at is None
        ):
            raise ValueError("terminal batches require completed_at")
        return self


class PriceBar(DomainModel):
    """One normalized bar with both market time and knowledge time.

    `effective_at` is the bar's market close, `available_at` is when the value
    first became knowable, and `ingested_at` is when this system received it.
    Keeping all three prevents a historical run from seeing a later correction.
    """

    price_bar_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    session_date: date
    frequency: BarFrequency = BarFrequency.DAILY
    effective_at: UtcDatetime
    available_at: UtcDatetime
    ingested_at: UtcDatetime
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float | None = None
    volume: float | None = Field(default=None, ge=0)
    currency: str = Field(min_length=3, max_length=3)
    adjustment_factor: float | None = Field(default=None, gt=0)
    total_return_factor: float | None = Field(default=None, gt=0)
    source: str = Field(min_length=1, max_length=80)
    source_record_id: str = Field(min_length=1, max_length=256)
    provider_identifier: str | None = Field(default=None, max_length=128)
    ingestion_batch_id: UUID
    quality_flags: tuple[DataQualityFlag, ...] = ()

    _normalize_currency = field_validator("currency")(lambda value: value.upper())

    @field_validator("open", "high", "low", "close", "adjusted_close")
    @classmethod
    def validate_price(cls, value: float | None) -> float | None:
        if value is not None and (not isfinite(value) or value < 0):
            raise ValueError("prices must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def validate_bar(self) -> PriceBar:
        if not (self.effective_at <= self.available_at <= self.ingested_at):
            raise ValueError(
                "bar timestamps must satisfy effective_at <= available_at <= ingested_at"
            )
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is below another OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is above another OHLC value")
        return self


class PriceIngestionResult(DomainModel):
    """Atomic provider response passed from a connector to ingestion."""

    batch: IngestionBatch
    bars: tuple[PriceBar, ...]


class CorporateAction(DomainModel):
    """Point-in-time corporate action used to audit adjusted return series."""

    corporate_action_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    action_type: CorporateActionType
    effective_at: UtcDatetime
    available_at: UtcDatetime
    ingested_at: UtcDatetime
    ratio: float | None = Field(default=None, gt=0)
    cash_amount: float | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source: str = Field(min_length=1, max_length=80)
    source_record_id: str = Field(min_length=1, max_length=256)
    ingestion_batch_id: UUID
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action_timing(self) -> CorporateAction:
        # Announced splits/dividends can be ingested before their effective date.
        if self.available_at > self.ingested_at:
            raise ValueError("available_at cannot be later than ingested_at")
        return self


class FeatureSnapshot(DomainModel):
    """Versioned output of a deterministic feature calculation."""

    feature_snapshot_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    feature_name: str = Field(min_length=1, max_length=160)
    feature_version: str = Field(min_length=1, max_length=80)
    effective_at: UtcDatetime
    available_at: UtcDatetime
    calculated_at: UtcDatetime
    value: Any
    unit: str | None = Field(default=None, max_length=40)
    window: str | None = Field(default=None, max_length=80)
    quality_flags: tuple[DataQualityFlag, ...] = ()
    input_evidence_ids: tuple[UUID, ...] = ()
    research_run_id: UUID
    code_version: str = Field(min_length=1, max_length=80)
    config_version: str = Field(min_length=1, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_feature_timing(self) -> FeatureSnapshot:
        if self.effective_at > self.calculated_at:
            raise ValueError("effective_at cannot be later than calculated_at")
        if self.available_at > self.calculated_at:
            raise ValueError("available_at cannot be later than calculated_at")
        return self
