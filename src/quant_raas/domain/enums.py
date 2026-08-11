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


class SourceType(StrEnum):
    MARKET_DATA = "market_data"
    COMPANY_EVENT = "company_event"
    FILING = "filing"
    NEWS = "news"
    MACRO = "macro"
    FEATURE = "feature"
    USER = "user"
    OTHER = "other"
