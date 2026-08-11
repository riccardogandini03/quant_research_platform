"""Canonical event contracts used by earnings and macro event studies."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from quant_raas.common.clock import UtcDatetime
from quant_raas.domain.base import DomainModel
from quant_raas.domain.enums import DataQualityFlag, EventType


class CompanyEvent(DomainModel):
    """Timestamped event whose market interpretation must be session-aware."""

    event_id: UUID = Field(default_factory=uuid4)
    security_id: UUID | None = None
    event_type: EventType
    title: str = Field(min_length=1, max_length=500)
    effective_at: UtcDatetime
    available_at: UtcDatetime
    ingested_at: UtcDatetime
    source: str = Field(min_length=1, max_length=80)
    source_record_id: str = Field(min_length=1, max_length=256)
    ingestion_batch_id: UUID
    payload: dict[str, Any] = Field(default_factory=dict)
    quality_flags: tuple[DataQualityFlag, ...] = ()

    @model_validator(mode="after")
    def validate_event_timing(self) -> CompanyEvent:
        # A scheduled event may be published and ingested before it occurs.
        if self.available_at > self.ingested_at:
            raise ValueError("available_at cannot be later than ingested_at")
        return self
