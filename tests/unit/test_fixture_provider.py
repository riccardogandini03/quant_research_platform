"""The fixture provider exercises the real connector contract without network."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID

import pandas as pd
import pytest

from quant_raas.connectors.fixture import FixturePriceProvider
from quant_raas.domain.enums import BatchStatus
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
    assert first.batch.row_count == 6
    assert len(first.bars) == 6
    assert "MISSING" in (first.batch.error_message or "")
    assert all(bar.security_id == security_id for bar in first.bars)
    assert all(bar.currency == "USD" for bar in first.bars)
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
