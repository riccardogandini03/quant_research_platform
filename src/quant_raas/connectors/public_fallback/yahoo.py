"""Best-effort Yahoo adapter isolated from all quantitative calculations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

import pandas as pd

from quant_raas.common.clock import utc_now
from quant_raas.connectors.base import (
    ProviderDataError,
    ProviderNotConfigured,
    batch_key,
    fingerprint_request,
    stable_batch_id,
)
from quant_raas.domain.enums import BatchStatus, DataQualityFlag
from quant_raas.domain.market import IngestionBatch, PriceBar, PriceBarRequest, PriceIngestionResult
from quant_raas.normalization.price_bars import normalize_price_frame


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

        started_at = max(self._clock(), request.requested_at)
        batch_id = stable_batch_id(self.name, request)
        bars: list[PriceBar] = []
        failures: list[str] = []
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
                bars.extend(
                    self._normalize_item(
                        raw,
                        security_id=item.security_id,
                        provider_identifier=item.provider_identifier,
                        batch_id=batch_id,
                        ingested_at=started_at,
                    )
                )
            except Exception as error:  # Provider schemas and HTTP failures vary.
                failures.append(f"{item.provider_identifier}: {type(error).__name__}: {error}")

        completed_at = max(self._clock(), started_at)
        if failures and not bars:
            status = BatchStatus.FAILED
        elif failures:
            status = BatchStatus.PARTIAL
        else:
            status = BatchStatus.SUCCEEDED
        fingerprint = fingerprint_request(request)
        content = json.dumps(
            [
                {
                    "id": bar.source_record_id,
                    "available_at": bar.available_at.isoformat(),
                    "ohlcv": [
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.adjusted_close,
                        bar.volume,
                    ],
                }
                for bar in sorted(bars, key=lambda value: value.source_record_id)
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        batch = IngestionBatch(
            batch_id=batch_id,
            batch_key=batch_key(self.name, request),
            provider=self.name,
            dataset="daily_price_bar",
            requested_at=request.requested_at,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            request_fingerprint=fingerprint,
            content_hash=hashlib.sha256(content).hexdigest(),
            row_count=len(bars),
            error_message="; ".join(failures)[:4000] if failures else None,
        )
        return PriceIngestionResult(batch=batch, bars=tuple(bars))

    def _normalize_item(
        self,
        raw: pd.DataFrame,
        *,
        security_id: UUID,
        provider_identifier: str,
        batch_id: UUID,
        ingested_at: datetime,
    ) -> list[PriceBar]:
        if raw.empty:
            raise ProviderDataError("provider returned no rows")
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
            raise ProviderDataError("provider response has no date column")
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
        normalized, _ = normalize_price_frame(work)
        output: list[PriceBar] = []
        for row in normalized.to_dict(orient="records"):
            session_date = pd.Timestamp(row["session_date"]).date()
            # Midnight UTC is explicitly an estimated market timestamp. It is
            # conservative for availability because fetched_at is always later.
            effective_at = datetime.combine(session_date, time.min, tzinfo=UTC)
            close = float(row["close"])
            adjusted_close = float(row["adjusted_close"])
            output.append(
                PriceBar(
                    security_id=security_id,
                    session_date=session_date,
                    effective_at=effective_at,
                    available_at=ingested_at,
                    ingested_at=ingested_at,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=close,
                    adjusted_close=adjusted_close,
                    volume=float(row["volume"]),
                    currency=self._default_currency,
                    adjustment_factor=adjusted_close / close,
                    source=self.name,
                    source_record_id=f"{provider_identifier}:{session_date.isoformat()}",
                    provider_identifier=provider_identifier,
                    ingestion_batch_id=batch_id,
                    quality_flags=(
                        DataQualityFlag.ESTIMATED_TIMESTAMP,
                        DataQualityFlag.SNAPSHOT_ONLY,
                    ),
                )
            )
        return output
