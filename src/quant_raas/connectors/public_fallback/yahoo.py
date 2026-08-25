"""Best-effort Yahoo adapter isolated from all quantitative calculations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

import pandas as pd

from quant_raas.common.clock import utc_now
from quant_raas.connectors.base import (
    ProviderDataError,
    ProviderError,
    ProviderNotConfigured,
    acquisition_started_at,
    require_utc,
)
from quant_raas.domain.enums import DataQualityFlag, DataUsageMode, PriceFailureCategory
from quant_raas.domain.market import (
    PriceBarRequest,
    PriceIngestionResult,
    PriceItemFailure,
)
from quant_raas.normalization.price_bars import normalize_price_frame
from quant_raas.normalization.price_content import (
    NormalizedPriceRow,
    build_price_ingestion_result,
    date_key_effective_at,
)

YAHOO_PRICE_FIELD_MAP_VERSION = "yahoo_daily_price_v1"


class YahooFinancePriceProvider:
    """Fetch adjusted daily history from yfinance when explicitly enabled.

    Yahoo is a development fallback, not a point-in-time or authoritative feed.
    Its daily index has no exact publication timestamp, so normalized bars carry
    ``ESTIMATED_TIMESTAMP`` and must not be used for vintage-sensitive tests.
    """

    name = "yahoo"

    def __init__(
        self,
        *,
        enabled: bool = False,
        clock: Callable[[], datetime] = utc_now,
        default_currency: str = "USD",
    ) -> None:
        self._enabled = enabled
        self._clock = clock
        self._default_currency = default_currency.upper()

    def fetch_daily_bars(self, request: PriceBarRequest) -> PriceIngestionResult:
        if not self._enabled:
            raise ProviderNotConfigured(
                "Yahoo fallback is disabled; choose QUANT_RAAS_MARKET_DATA_PROVIDER=yahoo "
                "and install the public-data extra only for prototype use"
            )
        try:
            import yfinance as yf
        except ImportError as error:
            raise ProviderNotConfigured(
                "Install the 'public-data' extra to enable the Yahoo fallback"
            ) from error

        started_at = acquisition_started_at(request, self._clock())
        rows: list[NormalizedPriceRow] = []
        failures: list[PriceItemFailure] = []
        for item in request.items:
            try:
                raw = yf.download(
                    item.provider_identifier,
                    start=request.start_date.isoformat(),
                    # yfinance treats end as exclusive; the domain request does not.
                    end=(request.end_date + timedelta(days=1)).isoformat(),
                    auto_adjust=False,
                    actions=False,
                    progress=False,
                    threads=False,
                )
            except Exception:
                raise ProviderError("Yahoo price request failed") from None
            try:
                if raw.empty:
                    failures.append(_no_data_failure(item.provider_identifier))
                    continue
                rows.extend(
                    self._normalize_item(
                        raw,
                        security_id=item.security_id,
                        provider_identifier=item.provider_identifier,
                    )
                )
            except Exception:
                raise ProviderDataError("Yahoo response failed daily-price validation") from None

        completed_at = max(
            require_utc(self._clock(), field_name="acquisition clock"),
            started_at,
        )
        return build_price_ingestion_result(
            provider=self.name,
            original_source=self.name,
            dataset="daily_price_bar",
            request=request,
            field_map_version=YAHOO_PRICE_FIELD_MAP_VERSION,
            usage_mode=DataUsageMode.PUBLIC,
            rows=tuple(rows),
            failures=tuple(failures),
            started_at=started_at,
            completed_at=completed_at,
        )

    def _normalize_item(
        self,
        raw: pd.DataFrame,
        *,
        security_id: UUID,
        provider_identifier: str,
    ) -> list[NormalizedPriceRow]:
        work = raw.copy()
        if isinstance(work.columns, pd.MultiIndex):
            # For a one-symbol request, take the OHLC field level regardless of
            # whether yfinance places ticker first or second.
            known = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
            work.columns = [
                next((str(part) for part in column if str(part) in known), str(column[0]))
                for column in work.columns
            ]
        work = work.reset_index()
        date_column = next(
            (name for name in work.columns if str(name).lower() in {"date", "datetime"}), None
        )
        if date_column is None:
            raise ValueError("Yahoo response has no date column")
        work = work.rename(
            columns={
                date_column: "session_date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adjusted_close",
                "Volume": "volume",
            }
        )
        normalized, report = normalize_price_frame(work)
        output: list[NormalizedPriceRow] = []
        for row in normalized.to_dict(orient="records"):
            session_date = pd.Timestamp(row["session_date"]).date()
            close = float(row["close"])
            adjusted_close = float(row["adjusted_close"])
            flags = [DataQualityFlag.ESTIMATED_TIMESTAMP]
            if "adjusted_close was unavailable" in " ".join(report.warnings):
                flags.append(DataQualityFlag.UNADJUSTED)
            output.append(
                NormalizedPriceRow(
                    security_id=security_id,
                    provider_identifier=provider_identifier,
                    source_record_id=(f"yahoo:{provider_identifier}:{session_date.isoformat()}"),
                    session_date=session_date,
                    effective_at=date_key_effective_at(session_date),
                    source_available_at=None,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=close,
                    adjusted_close=adjusted_close,
                    volume=float(row["volume"]),
                    currency=self._default_currency,
                    adjustment_factor=adjusted_close / close,
                    total_return_factor=None,
                    source=self.name,
                    usage_mode=DataUsageMode.PUBLIC,
                    quality_flags=tuple(flags),
                    field_map_version=YAHOO_PRICE_FIELD_MAP_VERSION,
                )
            )
        return output


def _no_data_failure(provider_identifier: str) -> PriceItemFailure:
    return PriceItemFailure(
        provider_identifier=provider_identifier,
        category=PriceFailureCategory.NO_DATA,
        message=f"{provider_identifier}: no Yahoo daily-price data",
    )
