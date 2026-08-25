"""Deterministic, network-free provider used by demos and integration tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd

from quant_raas.common.clock import utc_now
from quant_raas.connectors.base import acquisition_started_at, require_utc
from quant_raas.domain.enums import DataQualityFlag, DataUsageMode, PriceFailureCategory
from quant_raas.domain.market import (
    PriceBarRequest,
    PriceIngestionResult,
    PriceItemFailure,
)
from quant_raas.normalization.price_bars import normalize_price_frame

if TYPE_CHECKING:
    from quant_raas.normalization.price_content import NormalizedPriceRow

FIXTURE_PRICE_FIELD_MAP_VERSION = "fixture_daily_price_v1"


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
        from quant_raas.normalization.price_content import (
            NormalizedPriceRow,
            build_price_ingestion_result,
            date_key_effective_at,
        )

        started_at = acquisition_started_at(request, self._clock())
        rows: list[NormalizedPriceRow] = []
        failures: list[PriceItemFailure] = []

        for item in request.items:
            frame = self._frames.get(item.provider_identifier.upper())
            if frame is None:
                failures.append(_no_data_failure(item.provider_identifier))
                continue
            normalized, report = normalize_price_frame(frame)
            selected = normalized.loc[
                (normalized["session_date"].dt.date >= request.start_date)
                & (normalized["session_date"].dt.date <= request.end_date)
            ]
            if selected.empty:
                failures.append(_no_data_failure(item.provider_identifier))
                continue
            for row in selected.to_dict(orient="records"):
                session_date = pd.Timestamp(row["session_date"]).date()
                source_effective_at = _optional_timestamp(row.get("effective_at"))
                effective_at = source_effective_at or date_key_effective_at(session_date)
                source_available_at = _optional_timestamp(row.get("available_at"))
                flags: list[DataQualityFlag] = []
                if source_effective_at is None:
                    flags.append(DataQualityFlag.ESTIMATED_TIMESTAMP)
                if "adjusted_close was unavailable" in " ".join(report.warnings):
                    flags.append(DataQualityFlag.UNADJUSTED)
                close = float(row["close"])
                adjusted_close = float(row["adjusted_close"])
                rows.append(
                    NormalizedPriceRow(
                        security_id=item.security_id,
                        provider_identifier=item.provider_identifier,
                        source_record_id=(
                            f"fixture:{item.provider_identifier}:{session_date.isoformat()}"
                        ),
                        session_date=session_date,
                        effective_at=effective_at,
                        source_available_at=source_available_at,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=close,
                        adjusted_close=adjusted_close,
                        volume=float(row["volume"]),
                        currency=str(row.get("currency") or self._default_currency),
                        adjustment_factor=adjusted_close / close,
                        total_return_factor=None,
                        source=self.name,
                        usage_mode=DataUsageMode.SYNTHETIC,
                        quality_flags=tuple(flags),
                        field_map_version=FIXTURE_PRICE_FIELD_MAP_VERSION,
                    )
                )

        completed_at = max(
            require_utc(self._clock(), field_name="acquisition clock"),
            started_at,
        )
        return build_price_ingestion_result(
            provider=self.name,
            original_source=self.name,
            dataset="daily_price_bar",
            request=request,
            field_map_version=FIXTURE_PRICE_FIELD_MAP_VERSION,
            usage_mode=DataUsageMode.SYNTHETIC,
            rows=tuple(rows),
            failures=tuple(failures),
            started_at=started_at,
            completed_at=completed_at,
        )


def _no_data_failure(provider_identifier: str) -> PriceItemFailure:
    return PriceItemFailure(
        provider_identifier=provider_identifier,
        category=PriceFailureCategory.NO_DATA,
        message=f"{provider_identifier}: no fixture data",
    )


def _optional_timestamp(value: object) -> datetime | None:
    # Pandas stubs intentionally reject ``object`` even though values originate
    # from a heterogeneous DataFrame row. Keep the cast at this adapter edge.
    if value is None or (not isinstance(value, str) and bool(pd.isna(cast(Any, value)))):
        return None
    timestamp_value = cast(str | int | float | date | datetime | np.datetime64, value)
    parsed = pd.Timestamp(timestamp_value)
    if parsed.tzinfo is None:
        raise ValueError("fixture timestamps must include a timezone")
    return parsed.tz_convert("UTC").to_pydatetime()
