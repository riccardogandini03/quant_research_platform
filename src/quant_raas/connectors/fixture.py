"""Deterministic, network-free provider used by demos and integration tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time
from typing import Any, cast

import numpy as np
import pandas as pd

from quant_raas.common.clock import utc_now
from quant_raas.connectors.base import batch_key, fingerprint_request, stable_batch_id
from quant_raas.domain.enums import BatchStatus, DataQualityFlag
from quant_raas.domain.market import IngestionBatch, PriceBar, PriceBarRequest, PriceIngestionResult
from quant_raas.normalization.price_bars import normalize_price_frame


class FixturePriceProvider:
    """Serve caller-owned frames through the same contract as live providers.

    Mapping keys are provider identifiers, not canonical security IDs. Frames
    may include precise ``effective_at``/``available_at`` timestamps; otherwise
    conservative UTC placeholders are marked as estimated.
    """

    name = "fixture"

    def __init__(
        self,
        frames: Mapping[str, pd.DataFrame],
        *,
        clock: Callable[[], datetime] = utc_now,
        default_currency: str = "USD",
    ) -> None:
        self._frames = {key.upper(): value.copy() for key, value in frames.items()}
        self._clock = clock
        self._default_currency = default_currency.upper()

    def fetch_daily_bars(self, request: PriceBarRequest) -> PriceIngestionResult:
        # An injected test clock can equal the request clock; `max` also protects
        # the lineage invariant from small wall-clock skew between components.
        started_at = max(self._clock(), request.requested_at)
        batch_id = stable_batch_id(self.name, request)
        bars: list[PriceBar] = []
        missing_items: list[str] = []

        for item in request.items:
            frame = self._frames.get(item.provider_identifier.upper())
            if frame is None:
                missing_items.append(item.provider_identifier)
                continue
            normalized, report = normalize_price_frame(frame)
            selected = normalized.loc[
                (normalized["session_date"].dt.date >= request.start_date)
                & (normalized["session_date"].dt.date <= request.end_date)
            ]
            for row in selected.to_dict(orient="records"):
                session_date = pd.Timestamp(row["session_date"]).date()
                estimated_effective = datetime.combine(session_date, time.min, tzinfo=UTC)
                effective_at = _coerce_timestamp(row.get("effective_at"), estimated_effective)
                available_at = _coerce_timestamp(row.get("available_at"), effective_at)
                flags = (
                    []
                    if row.get("effective_at") is not None
                    else [DataQualityFlag.ESTIMATED_TIMESTAMP]
                )
                if "adjusted_close was unavailable" in " ".join(report.warnings):
                    flags.append(DataQualityFlag.UNADJUSTED)
                close = float(row["close"])
                adjusted_close = float(row["adjusted_close"])
                bars.append(
                    PriceBar(
                        security_id=item.security_id,
                        session_date=session_date,
                        effective_at=effective_at,
                        available_at=available_at,
                        ingested_at=started_at,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=close,
                        adjusted_close=adjusted_close,
                        volume=float(row["volume"]),
                        currency=str(row.get("currency") or self._default_currency),
                        adjustment_factor=adjusted_close / close,
                        source=self.name,
                        source_record_id=f"{item.provider_identifier}:{session_date.isoformat()}",
                        provider_identifier=item.provider_identifier,
                        ingestion_batch_id=batch_id,
                        quality_flags=tuple(flags),
                    )
                )

        completed_at = max(self._clock(), started_at)
        status = BatchStatus.PARTIAL if missing_items else BatchStatus.SUCCEEDED
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
            error_message=(
                f"No fixture frame for: {', '.join(sorted(missing_items))}"
                if missing_items
                else None
            ),
        )
        return PriceIngestionResult(batch=batch, bars=tuple(bars))


def _coerce_timestamp(value: object, default: datetime) -> datetime:
    # Pandas stubs intentionally reject ``object`` even though values originate
    # from a heterogeneous DataFrame row. Keep the cast at this adapter edge.
    if value is None or (not isinstance(value, str) and bool(pd.isna(cast(Any, value)))):
        return default
    timestamp_value = cast(str | int | float | date | datetime | np.datetime64, value)
    parsed = pd.Timestamp(timestamp_value)
    if parsed.tzinfo is None:
        raise ValueError("fixture timestamps must include a timezone")
    return parsed.tz_convert("UTC").to_pydatetime()
