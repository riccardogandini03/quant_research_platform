"""Security-master contracts and temporal identifier mappings."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from quant_raas.common.clock import UtcDatetime, utc_now
from quant_raas.domain.base import DomainModel
from quant_raas.domain.enums import (
    BenchmarkKind,
    IdentifierScheme,
    SecurityStatus,
    SecurityType,
)


def _upper_optional(value: str | None) -> str | None:
    return value.upper() if value else None


class Security(DomainModel):
    """Canonical instrument identity independent of any vendor symbol."""

    security_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=300)
    security_type: SecurityType = SecurityType.COMMON_STOCK
    status: SecurityStatus = SecurityStatus.ACTIVE
    primary_currency: str = Field(min_length=3, max_length=3)
    exchange_mic: str | None = Field(default=None, min_length=4, max_length=4)
    exchange_timezone: str | None = Field(default=None, max_length=80)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=120)
    sector: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=160)
    first_trade_date: date | None = None
    last_trade_date: date | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)
    updated_at: UtcDatetime = Field(default_factory=utc_now)

    _normalize_currency = field_validator("primary_currency")(lambda value: value.upper())
    _normalize_mic = field_validator("exchange_mic")(_upper_optional)
    _normalize_country = field_validator("country_code")(_upper_optional)

    @field_validator("exchange_timezone")
    @classmethod
    def validate_exchange_timezone(cls, value: str | None) -> str | None:
        if value:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("exchange_timezone must be an IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Security:
        if (
            self.last_trade_date
            and self.first_trade_date
            and self.last_trade_date < self.first_trade_date
        ):
            raise ValueError("last_trade_date cannot precede first_trade_date")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self


class SecurityIdentifier(DomainModel):
    """A vendor or public identifier that is valid only for a time interval.

    Tickers are not globally unique and can be reused after delistings. Scheme,
    provider, exchange MIC, and the half-open validity interval are therefore
    part of the identity contract.
    """

    identifier_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    scheme: IdentifierScheme
    value: str = Field(min_length=1, max_length=128)
    provider: str | None = Field(default=None, max_length=80)
    exchange_mic: str | None = Field(default=None, min_length=4, max_length=4)
    valid_from: UtcDatetime
    valid_to: UtcDatetime | None = None
    is_primary: bool = False
    created_at: UtcDatetime = Field(default_factory=utc_now)

    _normalize_value = field_validator("value")(lambda value: value.strip().upper())
    _normalize_provider = field_validator("provider")(
        lambda value: value.strip().lower() if value else None
    )
    _normalize_identifier_mic = field_validator("exchange_mic")(_upper_optional)

    @model_validator(mode="after")
    def validate_interval(self) -> SecurityIdentifier:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if self.scheme == IdentifierScheme.VENDOR and not self.provider:
            raise ValueError("provider is required for vendor identifiers")
        return self


class SecurityReference(DomainModel):
    """User- or connector-supplied reference awaiting canonical resolution."""

    identifier: str = Field(min_length=1, max_length=128)
    scheme: IdentifierScheme | None = None
    provider: str | None = Field(default=None, max_length=80)
    exchange_mic: str | None = Field(default=None, min_length=4, max_length=4)

    _normalize_reference = field_validator("identifier")(lambda value: value.strip().upper())
    _normalize_reference_provider = field_validator("provider")(
        lambda value: value.strip().lower() if value else None
    )
    _normalize_reference_mic = field_validator("exchange_mic")(_upper_optional)


class BenchmarkMapping(DomainModel):
    """Temporal mapping from a security to a research benchmark."""

    mapping_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    benchmark_security_id: UUID
    kind: BenchmarkKind
    valid_from: UtcDatetime
    valid_to: UtcDatetime | None = None
    source: str = Field(default="configuration", min_length=1, max_length=80)
    config_version: str = Field(default="v0", min_length=1, max_length=80)
    created_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_mapping(self) -> BenchmarkMapping:
        if self.security_id == self.benchmark_security_id:
            raise ValueError("a security cannot benchmark itself")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        return self


class SecurityUploadRow(DomainModel):
    """Validated row used to seed or update the canonical security master."""

    security_id: UUID
    identifier: str = Field(min_length=1, max_length=128)
    identifier_scheme: IdentifierScheme
    provider: str | None = Field(default=None, max_length=80)
    name: str = Field(min_length=1, max_length=300)
    security_type: SecurityType = SecurityType.COMMON_STOCK
    status: SecurityStatus = SecurityStatus.ACTIVE
    exchange_mic: str | None = Field(default=None, min_length=4, max_length=4)
    exchange_timezone: str | None = Field(default=None, max_length=80)
    primary_currency: str = Field(min_length=3, max_length=3)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=120)
    sector: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=160)
    benchmark: str | None = Field(default=None, max_length=128)
    first_trade_date: date | None = None
    last_trade_date: date | None = None
    valid_from: UtcDatetime
    valid_to: UtcDatetime | None = None

    _normalize_upload_identifier = field_validator("identifier")(lambda value: value.upper())
    _normalize_upload_provider = field_validator("provider")(
        lambda value: value.lower() if value else None
    )
    _normalize_upload_mic = field_validator("exchange_mic")(_upper_optional)
    _normalize_upload_currency = field_validator("primary_currency")(lambda value: value.upper())
    _normalize_upload_country = field_validator("country_code")(_upper_optional)
    _normalize_upload_benchmark = field_validator("benchmark")(
        lambda value: value.upper() if value else None
    )

    @field_validator("exchange_timezone")
    @classmethod
    def validate_upload_timezone(cls, value: str | None) -> str | None:
        if value:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("exchange_timezone must be an IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_upload_row(self) -> SecurityUploadRow:
        if self.identifier_scheme == IdentifierScheme.VENDOR and not self.provider:
            raise ValueError("provider is required for vendor identifiers")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if (
            self.first_trade_date
            and self.last_trade_date
            and self.last_trade_date < self.first_trade_date
        ):
            raise ValueError("last_trade_date cannot precede first_trade_date")
        return self

    def to_security(self) -> Security:
        return Security(
            security_id=self.security_id,
            name=self.name,
            security_type=self.security_type,
            status=self.status,
            primary_currency=self.primary_currency,
            exchange_mic=self.exchange_mic,
            exchange_timezone=self.exchange_timezone,
            country_code=self.country_code,
            region=self.region,
            sector=self.sector,
            industry=self.industry,
            first_trade_date=self.first_trade_date,
            last_trade_date=self.last_trade_date,
        )

    def to_identifier(self) -> SecurityIdentifier:
        return SecurityIdentifier(
            security_id=self.security_id,
            scheme=self.identifier_scheme,
            value=self.identifier,
            provider=self.provider,
            exchange_mic=self.exchange_mic,
            valid_from=self.valid_from,
            valid_to=self.valid_to,
            is_primary=True,
        )
