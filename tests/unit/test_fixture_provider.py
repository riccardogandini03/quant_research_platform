"""The fixture provider exercises the real connector contract without network."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID

import pandas as pd
import pytest

from quant_raas.connectors.base import ProviderDataError
from quant_raas.connectors.fixture import FixturePriceProvider
from quant_raas.domain.enums import (
    BatchStatus,
    DataQualityFlag,
    DataUsageMode,
    PriceFailureCategory,
)
from quant_raas.domain.market import PriceBarRequest, PriceRequestItem


def _request(
    *,
    security_id: UUID,
    requested_at: datetime,
    include_missing: bool = False,
) -> PriceBarRequest:
    items = [PriceRequestItem(security_id=security_id, provider_identifier="EXAMPLE")]
    if include_missing:
        items.append(
            PriceRequestItem(
                security_id=UUID("45454545-4545-4545-8545-454545454545"),
                provider_identifier="MISSING",
            )
        )
    return PriceBarRequest(
        items=tuple(items),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 9),
        requested_at=requested_at,
    )


def test_fixture_provider_is_stable_and_reports_partial_symbols(
    security_id: UUID,
    fixed_now: datetime,
    ohlcv_frame: pd.DataFrame,
) -> None:
    provider = FixturePriceProvider(
        {"example": ohlcv_frame},
        clock=lambda: fixed_now,
    )
    request = _request(
        security_id=security_id,
        requested_at=fixed_now - timedelta(minutes=1),
        include_missing=True,
    )
    first = provider.fetch_daily_bars(request)
    second = provider.fetch_daily_bars(request)

    assert first.batch.status == BatchStatus.PARTIAL
    assert first.batch.original_source == "fixture"
    assert first.batch.usage_mode == DataUsageMode.SYNTHETIC
    assert first.batch.row_count == 6
    assert len(first.bars) == 6
    assert "MISSING" in (first.batch.error_message or "")
    assert len(first.failures) == 1
    assert first.failures[0].provider_identifier == "MISSING"
    assert first.failures[0].category == PriceFailureCategory.NO_DATA
    assert all(bar.security_id == security_id for bar in first.bars)
    assert all(bar.currency == "USD" for bar in first.bars)
    assert all(bar.source == "fixture" for bar in first.bars)
    assert all(bar.usage_mode == DataUsageMode.SYNTHETIC for bar in first.bars)
    assert first.batch.batch_id == second.batch.batch_id
    assert first.batch.request_fingerprint == second.batch.request_fingerprint
    assert first.batch.content_hash == second.batch.content_hash


def test_fixture_provider_rejects_naive_source_timestamps(
    security_id: UUID,
    fixed_now: datetime,
    ohlcv_frame: pd.DataFrame,
) -> None:
    broken = ohlcv_frame.copy()
    broken["effective_at"] = broken["session_date"]  # Deliberately timezone-naive.
    provider = FixturePriceProvider({"EXAMPLE": broken}, clock=lambda: fixed_now)
    request = _request(
        security_id=security_id,
        requested_at=fixed_now - timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="include a timezone"):
        provider.fetch_daily_bars(request)


def test_fixture_provider_excludes_generated_snapshot_clocks_from_identity(
    security_id: UUID,
    fixed_now: datetime,
    ohlcv_frame: pd.DataFrame,
) -> None:
    snapshot = ohlcv_frame.drop(columns=["effective_at", "available_at"])
    request = _request(
        security_id=security_id,
        requested_at=fixed_now - timedelta(minutes=1),
    )
    first = FixturePriceProvider(
        {"EXAMPLE": snapshot},
        clock=lambda: fixed_now,
    ).fetch_daily_bars(request)
    second = FixturePriceProvider(
        {"EXAMPLE": snapshot},
        clock=lambda: fixed_now + timedelta(days=1),
    ).fetch_daily_bars(request)

    assert first.batch.content_hash == second.batch.content_hash
    assert first.batch.batch_id == second.batch.batch_id
    assert first.bars[0].available_at != second.bars[0].available_at
    assert first.bars[0].ingested_at != second.bars[0].ingested_at
    assert all(DataQualityFlag.SNAPSHOT_ONLY in bar.quality_flags for bar in first.bars)
    assert all(DataQualityFlag.ESTIMATED_TIMESTAMP in bar.quality_flags for bar in first.bars)


def test_fixture_provider_preserves_explicit_source_timestamps(
    security_id: UUID,
    fixed_now: datetime,
    ohlcv_frame: pd.DataFrame,
) -> None:
    result = FixturePriceProvider(
        {"EXAMPLE": ohlcv_frame},
        clock=lambda: fixed_now,
    ).fetch_daily_bars(
        _request(
            security_id=security_id,
            requested_at=fixed_now - timedelta(minutes=1),
        )
    )
    first_input = ohlcv_frame.iloc[0]
    assert result.bars[0].effective_at == first_input["effective_at"]
    assert result.bars[0].available_at == first_input["available_at"]
    assert DataQualityFlag.SNAPSHOT_ONLY not in result.bars[0].quality_flags


def test_fixture_provider_rejects_a_future_request_timestamp(
    security_id: UUID,
    fixed_now: datetime,
    ohlcv_frame: pd.DataFrame,
) -> None:
    provider = FixturePriceProvider({"EXAMPLE": ohlcv_frame}, clock=lambda: fixed_now)
    request = _request(
        security_id=security_id,
        requested_at=fixed_now + timedelta(seconds=1),
    )
    with pytest.raises(
        ProviderDataError,
        match="request timestamp cannot be later than the acquisition clock",
    ):
        provider.fetch_daily_bars(request)
