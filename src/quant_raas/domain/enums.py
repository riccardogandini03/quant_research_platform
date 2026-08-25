"""Stable enumerations persisted as lowercase strings in the database."""

from enum import StrEnum


class SecurityType(StrEnum):
    COMMON_STOCK = "common_stock"
    ADR = "adr"
    ETF = "etf"
    INDEX = "index"
    OTHER = "other"


class SecurityStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELISTED = "delisted"


class IdentifierScheme(StrEnum):
    TICKER = "ticker"
    MIC_TICKER = "mic_ticker"
    ISIN = "isin"
    CUSIP = "cusip"
    SEDOL = "sedol"
    RIC = "ric"
    BBGID = "bbgid"
    FIGI = "figi"
    VENDOR = "vendor"


class BenchmarkKind(StrEnum):
    MARKET = "market"
    COUNTRY = "country"
    SECTOR = "sector"
    INDUSTRY = "industry"
    CUSTOM = "custom"


class BarFrequency(StrEnum):
    DAILY = "1d"


class BatchStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class DataUsageMode(StrEnum):
    RESEARCH_ONLY = "research_only"
    PUBLIC = "public"
    SYNTHETIC = "synthetic"
    USER_SUPPLIED = "user_supplied"
    UNVERIFIED = "unverified"


class PriceFailureCategory(StrEnum):
    NO_DATA = "no_data"
    INVALID_IDENTIFIER = "invalid_identifier"
    INVALID_CURRENCY = "invalid_currency"


class DataQualityFlag(StrEnum):
    STALE = "stale"
    MISSING = "missing"
    ESTIMATED_TIMESTAMP = "estimated_timestamp"
    UNADJUSTED = "unadjusted"
    PROVIDER_CONFLICT = "provider_conflict"
    INSUFFICIENT_HISTORY = "insufficient_history"
    SNAPSHOT_ONLY = "snapshot_only"


class CorporateActionType(StrEnum):
    SPLIT = "split"
    CASH_DIVIDEND = "cash_dividend"
    STOCK_DIVIDEND = "stock_dividend"
    SPINOFF = "spinoff"
    MERGER = "merger"
    SYMBOL_CHANGE = "symbol_change"
    OTHER = "other"


class EventType(StrEnum):
    EARNINGS = "earnings"
    GUIDANCE = "guidance"
    MACRO_RELEASE = "macro_release"
    FOMC = "fomc"
    CPI = "cpi"
    FILING = "filing"
    MANAGEMENT = "management"
    REGULATORY = "regulatory"
    OTHER = "other"


class FindingCategory(StrEnum):
    PRICE_ANOMALY = "price_anomaly"
    VOLUME_ANOMALY = "volume_anomaly"
    RISK_CHANGE = "risk_change"
    FACTOR_CHANGE = "factor_change"
    CALENDAR_EFFECT = "calendar_effect"
    EARNINGS = "earnings"
    OPTIONS = "options"
    OWNERSHIP = "ownership"
    FUNDAMENTAL = "fundamental"
    ESTIMATES = "estimates"
    VALUATION = "valuation"
    MACRO = "macro"
    OTHER = "other"


class MaterialityTier(StrEnum):
    ROUTINE = "routine"
    WATCH = "watch"
    MATERIAL = "material"
    CRITICAL = "critical"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ThesisImpact(StrEnum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class FeedbackKind(StrEnum):
    USEFUL = "useful"
    NOISE = "noise"
    ALREADY_KNOWN = "already_known"
    WRONG = "wrong"
    INVESTIGATE = "investigate"


class ThesisStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ThesisDirection(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"


class ThesisRiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InvalidationComparator(StrEnum):
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"


class ThesisSelectionStatus(StrEnum):
    SELECTED = "selected"
    NOT_KNOWN_AT_CUTOFF = "not_known_at_cutoff"
    NOT_YET_APPROVED = "not_yet_approved"
    NOT_YET_EFFECTIVE = "not_yet_effective"
    ARCHIVED_AT_CUTOFF = "archived_at_cutoff"
    EXPIRED_AT_CUTOFF = "expired_at_cutoff"


class SourceType(StrEnum):
    MARKET_DATA = "market_data"
    COMPANY_EVENT = "company_event"
    FILING = "filing"
    NEWS = "news"
    MACRO = "macro"
    FEATURE = "feature"
    USER = "user"
    OTHER = "other"
