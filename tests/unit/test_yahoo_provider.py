"""Yahoo adapter behavior without network access or the optional dependency."""

from __future__ import annotations

import sys
import traceback
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pandas as pd
import pytest

from quant_raas.connectors.base import ProviderDataError, ProviderError
from quant_raas.connectors.public_fallback.yahoo import YahooFinancePriceProvider
from quant_raas.domain.enums import (
    BatchStatus,
    DataQualityFlag,
    DataUsageMode,
    PriceFailureCategory,
)
from quant_raas.domain.market import PriceBarRequest, PriceRequestItem

SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
REQUESTED_AT = datetime(2024, 1, 10, 9, 0, tzinfo=UTC)
ACQUIRED_AT = datetime(2024, 1, 10, 10, 0, tzinfo=UTC)


def _request() -> PriceBarRequest:
    return PriceBarRequest(
        items=(
            PriceRequestItem(
                security_id=SECURITY_ID,
                provider_identifier="EXAMPLE.O",
            ),
        ),
        start_date=date(2024, 1, 8),
        end_date=date(2024, 1, 9),
        requested_at=REQUESTED_AT,
    )


def _valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [100.5],
            "Volume": [1_000.0],
        },
        index=pd.DatetimeIndex(["2024-01-09"], name="Date"),
    )


def _install_yfinance(
    monkeypatch: pytest.MonkeyPatch,
    download: Any,
) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))


def test_yahoo_provider_builds_public_snapshot_content_stably(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def download(symbol: str, **kwargs: object) -> pd.DataFrame:
        calls.append({"symbol": symbol, **kwargs})
        return _valid_frame()

    _install_yfinance(monkeypatch, download)
    first = YahooFinancePriceProvider(
        enabled=True,
        clock=lambda: ACQUIRED_AT,
    ).fetch_daily_bars(_request())
    second = YahooFinancePriceProvider(
        enabled=True,
        clock=lambda: ACQUIRED_AT + timedelta(days=1),
    ).fetch_daily_bars(_request())

    assert calls[0] == {
        "symbol": "EXAMPLE.O",
        "start": "2024-01-08",
        "end": "2024-01-10",
        "auto_adjust": False,
        "actions": False,
        "progress": False,
        "threads": False,
    }
    assert first.batch.provider == "yahoo"
    assert first.batch.original_source == "yahoo"
    assert first.batch.usage_mode == DataUsageMode.PUBLIC
    assert first.batch.status == BatchStatus.SUCCEEDED
    assert first.batch.content_hash == second.batch.content_hash
    assert first.batch.batch_id == second.batch.batch_id
    assert first.bars[0].available_at != second.bars[0].available_at
    assert first.bars[0].source == "yahoo"
    assert first.bars[0].usage_mode == DataUsageMode.PUBLIC
    assert first.bars[0].quality_flags == (
        DataQualityFlag.ESTIMATED_TIMESTAMP,
        DataQualityFlag.SNAPSHOT_ONLY,
    )


def test_yahoo_empty_response_is_typed_no_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_yfinance(monkeypatch, lambda *args, **kwargs: pd.DataFrame())
    result = YahooFinancePriceProvider(
        enabled=True,
        clock=lambda: ACQUIRED_AT,
    ).fetch_daily_bars(_request())

    assert result.bars == ()
    assert result.batch.status == BatchStatus.FAILED
    assert len(result.failures) == 1
    assert result.failures[0].provider_identifier == "EXAMPLE.O"
    assert result.failures[0].category == PriceFailureCategory.NO_DATA
    assert result.failures[0].message == "EXAMPLE.O: no Yahoo daily-price data"


def test_yahoo_malformed_nonempty_response_raises_sanitized_data_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "MALFORMED-YAHOO-SENTINEL"

    class MalformedFrame(pd.DataFrame):
        @property
        def _constructor(self) -> type[MalformedFrame]:
            return MalformedFrame

        def reset_index(self, *args: object, **kwargs: object) -> pd.DataFrame:
            raise RuntimeError(sentinel)

    malformed = MalformedFrame({"Close": [101.0]})
    _install_yfinance(monkeypatch, lambda *args, **kwargs: malformed)
    with pytest.raises(
        ProviderDataError,
        match=r"^Yahoo response failed daily-price validation$",
    ) as exc_info:
        YahooFinancePriceProvider(
            enabled=True,
            clock=lambda: ACQUIRED_AT,
        ).fetch_daily_bars(_request())

    error = exc_info.value
    assert sentinel not in str(error)
    assert sentinel not in "".join(traceback.format_exception(error))


def test_yahoo_downloader_exception_raises_sanitized_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "YAHOO-DOWNLOAD-SENTINEL"

    def download(*args: object, **kwargs: object) -> pd.DataFrame:
        raise RuntimeError(sentinel)

    _install_yfinance(monkeypatch, download)
    with pytest.raises(
        ProviderError,
        match=r"^Yahoo price request failed$",
    ) as exc_info:
        YahooFinancePriceProvider(
            enabled=True,
            clock=lambda: ACQUIRED_AT,
        ).fetch_daily_bars(_request())

    error = exc_info.value
    assert type(error) is ProviderError
    assert sentinel not in str(error)
    assert sentinel not in "".join(traceback.format_exception(error))
