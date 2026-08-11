"""Coverage and holdings contracts.

Coverage is deliberately separate from holdings: a PM can research a security
without owning it, and portfolio weight changes priority rather than intrinsic
research materiality.
"""

from __future__ import annotations

from decimal import Decimal
from math import isfinite
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from quant_raas.common.clock import UtcDatetime, utc_now
from quant_raas.domain.base import DomainModel
from quant_raas.domain.enums import IdentifierScheme
from quant_raas.domain.security import SecurityReference


class HoldingUploadRow(DomainModel):
    """Validated representation of one row in a holdings CSV."""

    identifier: str = Field(min_length=1, max_length=128)
    weight: Decimal
    thesis_id: str | None = Field(default=None, max_length=128)
    benchmark: str | None = Field(default=None, max_length=128)
    identifier_scheme: IdentifierScheme | None = None
    provider: str | None = Field(default=None, max_length=80)
    exchange_mic: str | None = Field(default=None, min_length=4, max_length=4)

    _normalize_identifier = field_validator("identifier")(lambda value: value.upper())
    _normalize_provider = field_validator("provider")(
        lambda value: value.lower() if value else None
    )
    _normalize_mic = field_validator("exchange_mic")(lambda value: value.upper() if value else None)
    _normalize_benchmark = field_validator("benchmark")(
        lambda value: value.upper() if value else None
    )

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, value: Decimal) -> Decimal:
        # Negative weights are valid for research on short books. Bounds are a
        # guard against percent-versus-decimal upload mistakes, not leverage.
        if not isfinite(float(value)) or abs(value) > Decimal("10"):
            raise ValueError("weight must be finite and expressed as a decimal")
        return value

    def security_reference(self) -> SecurityReference:
        return SecurityReference(
            identifier=self.identifier,
            scheme=self.identifier_scheme,
            provider=self.provider,
            exchange_mic=self.exchange_mic,
        )


class CoverageUploadRow(DomainModel):
    """Validated representation of one row in a coverage CSV."""

    identifier: str = Field(min_length=1, max_length=128)
    thesis_id: str | None = Field(default=None, max_length=128)
    benchmark: str | None = Field(default=None, max_length=128)
    peer_group: str | None = Field(default=None, max_length=160)
    identifier_scheme: IdentifierScheme | None = None
    provider: str | None = Field(default=None, max_length=80)
    exchange_mic: str | None = Field(default=None, min_length=4, max_length=4)

    _normalize_identifier = field_validator("identifier")(lambda value: value.upper())
    _normalize_provider = field_validator("provider")(
        lambda value: value.lower() if value else None
    )
    _normalize_mic = field_validator("exchange_mic")(lambda value: value.upper() if value else None)
    _normalize_benchmark = field_validator("benchmark")(
        lambda value: value.upper() if value else None
    )

    def security_reference(self) -> SecurityReference:
        return SecurityReference(
            identifier=self.identifier,
            scheme=self.identifier_scheme,
            provider=self.provider,
            exchange_mic=self.exchange_mic,
        )


class PortfolioSnapshot(DomainModel):
    """Immutable holdings observation supplied by a PM."""

    snapshot_id: UUID = Field(default_factory=uuid4)
    portfolio_name: str = Field(min_length=1, max_length=160)
    as_of: UtcDatetime
    created_at: UtcDatetime = Field(default_factory=utc_now)
    source_name: str | None = Field(default=None, max_length=260)
    source_hash: str | None = Field(default=None, min_length=16, max_length=128)

    @model_validator(mode="after")
    def validate_timing(self) -> PortfolioSnapshot:
        if self.created_at < self.as_of:
            raise ValueError("created_at cannot precede the snapshot as_of time")
        return self


class PortfolioPosition(DomainModel):
    """One contextual holding within an immutable portfolio snapshot."""

    position_id: UUID = Field(default_factory=uuid4)
    snapshot_id: UUID
    security_id: UUID
    weight: Decimal
    thesis_id: str | None = Field(default=None, max_length=128)
    benchmark_security_id: UUID | None = None
    source_identifier: str = Field(min_length=1, max_length=128)

    @field_validator("weight")
    @classmethod
    def validate_position_weight(cls, value: Decimal) -> Decimal:
        if not isfinite(float(value)) or abs(value) > Decimal("10"):
            raise ValueError("weight must be finite and expressed as a decimal")
        return value


class CoverageList(DomainModel):
    """A named research universe, independent of a portfolio snapshot."""

    coverage_list_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=160)
    created_at: UtcDatetime = Field(default_factory=utc_now)
    description: str | None = Field(default=None, max_length=1000)


class CoverageMember(DomainModel):
    """Temporal membership of one security in a coverage list."""

    membership_id: UUID = Field(default_factory=uuid4)
    coverage_list_id: UUID
    security_id: UUID
    added_at: UtcDatetime
    removed_at: UtcDatetime | None = None
    thesis_id: str | None = Field(default=None, max_length=128)
    benchmark_security_id: UUID | None = None
    peer_group: str | None = Field(default=None, max_length=160)
    source_identifier: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_membership_interval(self) -> CoverageMember:
        if self.removed_at is not None and self.removed_at <= self.added_at:
            raise ValueError("removed_at must be later than added_at")
        return self
