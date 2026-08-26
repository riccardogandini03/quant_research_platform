"""Strict file-backed daily-price provider contracts."""

from __future__ import annotations

import traceback
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pandas as pd
import pytest

from quant_raas.connectors.base import ProviderDataError, ProviderNotConfigured
from quant_raas.connectors.file import FilePriceProvider
from quant_raas.domain.enums import (
    BatchStatus,
    DataQualityFlag,
    DataUsageMode,
    PriceFailureCategory,
)
from quant_raas.domain.market import PriceBarRequest, PriceRequestItem

SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
MISSING_SECURITY_ID = UUID("22222222-2222-4222-8222-222222222222")
REQUESTED_AT = datetime(2024, 1, 10, 21, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2024, 1, 10, 22, 0, tzinfo=UTC)


@pytest.fixture
def price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "provider_identifier": ["EXAMPLE.O", "EXAMPLE.O", "OTHER.O", "EXAMPLE.O"],
            "session_date": ["2024-01-08", "2024-01-09", "2024-01-09", "2024-01-07"],
            "open": [100.0, 101.0, 200.0, 99.0],
            "high": [102.0, 103.0, 202.0, 101.0],
            "low": [99.0, 100.0, 199.0, 98.0],
            "close": [101.0, 102.0, 201.0, 100.0],
            "volume": [1_000.0, 1_100.0, 2_000.0, 900.0],
            "currency": ["usd", "USD", "EUR", "USD"],
        }
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> Path:
    frame.to_csv(path, index=False)
    return path


def _request(*identifiers: str) -> PriceBarRequest:
    security_ids = (SECURITY_ID, MISSING_SECURITY_ID)
    return PriceBarRequest(
        items=tuple(
            PriceRequestItem(security_id=security_ids[index], provider_identifier=identifier)
            for index, identifier in enumerate(identifiers)
        ),
        start_date=date(2024, 1, 8),
        end_date=date(2024, 1, 9),
        requested_at=REQUESTED_AT,
    )


def _provider(
    path: Path,
    *,
    source: str = "user_export",
    usage_mode: DataUsageMode = DataUsageMode.USER_SUPPLIED,
    completed_at: datetime = COMPLETED_AT,
) -> FilePriceProvider:
    return FilePriceProvider(
        path,
        source=source,
        usage_mode=usage_mode,
        clock=lambda: completed_at,
    )


def test_file_columns_are_case_insensitive_and_default_source_record_id_is_deterministic(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    mixed_case = price_frame.iloc[:2].rename(
        columns={column: f" {column.upper()} " for column in price_frame.columns}
    )
    result = _provider(_write_csv(tmp_path / "prices.csv", mixed_case)).fetch_daily_bars(
        _request("EXAMPLE.O")
    )

    assert [bar.source_record_id for bar in result.bars] == [
        "user_export:EXAMPLE.O:2024-01-08:file_daily_price_v1",
        "user_export:EXAMPLE.O:2024-01-09:file_daily_price_v1",
    ]
    assert [bar.currency for bar in result.bars] == ["USD", "USD"]


def test_casefolded_column_collisions_are_rejected(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    colliding = price_frame.iloc[:1].assign(STRASSE="first", straße="second")

    with pytest.raises(
        ProviderDataError,
        match="price file contains duplicate normalized columns",
    ):
        _provider(_write_csv(tmp_path / "prices.csv", colliding)).fetch_daily_bars(
            _request("EXAMPLE.O")
        )


def test_duplicate_csv_header_is_rejected_before_pandas_can_mangle_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "duplicate-header.csv"
    path.write_text(
        "provider_identifier,session_date,open,high,low,close,volume,currency,currency\n"
        "EXAMPLE.O,2024-01-08,100,102,99,101,1000,USD,EUR\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ProviderDataError,
        match="price file contains duplicate normalized columns",
    ):
        _provider(path).fetch_daily_bars(_request("EXAMPLE.O"))


def test_file_provider_preserves_original_source_and_usage_mode(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    result = _provider(
        _write_csv(tmp_path / "prices.csv", price_frame),
        source=" Vendor_Export ",
    ).fetch_daily_bars(_request("EXAMPLE.O"))

    assert result.batch.provider == "file"
    assert result.batch.original_source == "vendor_export"
    assert result.batch.usage_mode == DataUsageMode.USER_SUPPLIED
    assert {bar.source for bar in result.bars} == {"vendor_export"}
    assert {bar.usage_mode for bar in result.bars} == {DataUsageMode.USER_SUPPLIED}


def test_lseg_file_requires_research_only_usage(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ProviderNotConfigured,
        match="an LSEG-derived file must use research_only handling",
    ):
        _provider(tmp_path / "prices.csv", source=" LSEG ")


def test_duplicate_selected_identifier_dates_are_rejected_before_normalization(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    duplicate = pd.concat([price_frame.iloc[[0]], price_frame.iloc[[0]]], ignore_index=True)
    path = _write_csv(tmp_path / "prices.csv", duplicate)

    with pytest.raises(ProviderDataError, match="duplicate provider_identifier/session_date rows"):
        _provider(path).fetch_daily_bars(_request("EXAMPLE.O"))


def test_unrequested_and_out_of_range_rows_are_ignored(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    irrelevant = price_frame.copy()
    irrelevant["close"] = irrelevant["close"].astype(object)
    irrelevant.loc[2:, "close"] = "not-a-price"
    result = _provider(_write_csv(tmp_path / "prices.csv", irrelevant)).fetch_daily_bars(
        _request("EXAMPLE.O")
    )

    assert [(bar.provider_identifier, bar.session_date) for bar in result.bars] == [
        ("EXAMPLE.O", date(2024, 1, 8)),
        ("EXAMPLE.O", date(2024, 1, 9)),
    ]


def test_requested_identifier_without_rows_is_a_no_data_failure(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    result = _provider(_write_csv(tmp_path / "prices.csv", price_frame)).fetch_daily_bars(
        _request("EXAMPLE.O", "MISSING.O")
    )

    assert result.batch.status == BatchStatus.PARTIAL
    assert result.failures[0].provider_identifier == "MISSING.O"
    assert result.failures[0].category == PriceFailureCategory.NO_DATA


def test_all_missing_items_return_a_persistable_failed_batch_with_original_source(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    result = _provider(
        _write_csv(tmp_path / "prices.csv", price_frame),
        source="lseg",
        usage_mode=DataUsageMode.RESEARCH_ONLY,
    ).fetch_daily_bars(_request("MISSING.O"))

    assert result.batch.status == BatchStatus.FAILED
    assert result.batch.original_source == "lseg"
    assert result.batch.row_count == 0
    assert result.bars == ()
    assert result.failures[0].category == PriceFailureCategory.NO_DATA


def test_unsupported_suffix_missing_columns_and_malformed_csv_raise_fixed_data_errors(
    tmp_path: Path,
    price_frame: pd.DataFrame,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ProviderDataError, match=r"^price file must use \.csv or \.parquet$"):
        _provider(tmp_path / "prices.txt").fetch_daily_bars(_request("EXAMPLE.O"))

    missing_path = _write_csv(tmp_path / "missing.csv", price_frame.drop(columns="currency"))
    with pytest.raises(ProviderDataError, match="price file is missing required columns: currency"):
        _provider(missing_path).fetch_daily_bars(_request("EXAMPLE.O"))

    sentinel = "private parser detail"

    def broken_read_csv(*args: object, **kwargs: object) -> pd.DataFrame:
        raise pd.errors.ParserError(sentinel)

    malformed_path = _write_csv(tmp_path / "malformed.csv", price_frame)
    monkeypatch.setattr(pd, "read_csv", broken_read_csv)
    with pytest.raises(
        ProviderDataError,
        match=r"^CSV price file could not be read$",
    ) as caught:
        _provider(malformed_path).fetch_daily_bars(_request("EXAMPLE.O"))
    assert sentinel not in str(caught.value)
    assert sentinel not in "".join(traceback.format_exception(caught.value))


def test_invalid_session_date_raises_fixed_provider_data_error(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    sentinel = "2024-01-09 private parser detail"
    invalid = price_frame.iloc[:2].copy()
    invalid.loc[1, "session_date"] = sentinel

    with pytest.raises(
        ProviderDataError,
        match=r"^price file session_date failed validation$",
    ) as caught:
        _provider(_write_csv(tmp_path / "prices.csv", invalid)).fetch_daily_bars(
            _request("EXAMPLE.O")
        )
    assert sentinel not in str(caught.value)
    assert sentinel not in "".join(traceback.format_exception(caught.value))


def test_missing_adjusted_close_column_copies_close_and_marks_all_rows_unadjusted(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    result = _provider(_write_csv(tmp_path / "prices.csv", price_frame)).fetch_daily_bars(
        _request("EXAMPLE.O")
    )

    assert all(bar.adjusted_close == bar.close for bar in result.bars)
    assert all(bar.adjustment_factor == pytest.approx(1.0) for bar in result.bars)
    assert all(DataQualityFlag.UNADJUSTED in bar.quality_flags for bar in result.bars)
    assert all(bar.total_return_factor is None for bar in result.bars)


def test_missing_timestamps_use_completion_and_conservative_flags(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    with_adjustment = price_frame.assign(adjusted_close=price_frame["close"] - 0.5)
    result = _provider(_write_csv(tmp_path / "prices.csv", with_adjustment)).fetch_daily_bars(
        _request("EXAMPLE.O")
    )

    assert all(bar.available_at == COMPLETED_AT for bar in result.bars)
    assert all(bar.ingested_at == COMPLETED_AT for bar in result.bars)
    assert all(
        bar.quality_flags
        == (
            DataQualityFlag.ESTIMATED_TIMESTAMP,
            DataQualityFlag.SNAPSHOT_ONLY,
        )
        for bar in result.bars
    )


def test_aware_source_timestamps_are_preserved_and_affect_content_identity(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    authoritative = price_frame.iloc[:1].assign(
        adjusted_close=100.5,
        effective_at="2024-01-08T21:00:00+01:00",
        available_at="2024-01-08T21:05:00+01:00",
        source_record_id="vendor-row-1",
    )
    changed_availability = authoritative.assign(available_at="2024-01-08T21:06:00+01:00")
    first = _provider(_write_csv(tmp_path / "first.csv", authoritative)).fetch_daily_bars(
        _request("EXAMPLE.O")
    )
    second = _provider(_write_csv(tmp_path / "second.csv", changed_availability)).fetch_daily_bars(
        _request("EXAMPLE.O")
    )

    assert first.bars[0].effective_at == datetime(2024, 1, 8, 20, 0, tzinfo=UTC)
    assert first.bars[0].available_at == datetime(2024, 1, 8, 20, 5, tzinfo=UTC)
    assert first.bars[0].source_record_id == "vendor-row-1"
    assert DataQualityFlag.ESTIMATED_TIMESTAMP not in first.bars[0].quality_flags
    assert DataQualityFlag.SNAPSHOT_ONLY not in first.bars[0].quality_flags
    assert first.batch.content_hash != second.batch.content_hash
    assert first.batch.batch_id != second.batch.batch_id


@pytest.mark.parametrize("column", ["effective_at", "available_at"])
def test_naive_effective_or_available_timestamp_is_rejected(
    tmp_path: Path,
    price_frame: pd.DataFrame,
    column: str,
) -> None:
    invalid = price_frame.iloc[:1].assign(
        effective_at="2024-01-08T21:00:00+00:00",
        available_at="2024-01-08T21:05:00+00:00",
    )
    invalid.loc[:, column] = "2024-01-08T21:00:00"

    with pytest.raises(
        ProviderDataError,
        match=rf"^{column} must include an explicit timezone$",
    ):
        _provider(_write_csv(tmp_path / "prices.csv", invalid)).fetch_daily_bars(
            _request("EXAMPLE.O")
        )


def test_invalid_timestamp_text_raises_fixed_provider_data_error(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    sentinel = "private timestamp parser detail"
    invalid = price_frame.iloc[:1].assign(effective_at=sentinel)

    with pytest.raises(
        ProviderDataError,
        match=r"^price file timestamps failed validation$",
    ) as caught:
        _provider(_write_csv(tmp_path / "prices.csv", invalid)).fetch_daily_bars(
            _request("EXAMPLE.O")
        )
    assert sentinel not in str(caught.value)
    assert sentinel not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("close", "private numeric conversion detail"),
        ("currency", "US"),
        ("source_record_id", "x" * 257),
    ],
)
def test_invalid_numeric_or_normalized_schema_raises_fixed_provider_data_error(
    tmp_path: Path,
    price_frame: pd.DataFrame,
    column: str,
    invalid_value: str,
) -> None:
    invalid = price_frame.iloc[:1].copy()
    invalid[column] = invalid_value

    with pytest.raises(
        ProviderDataError,
        match=r"^price file failed daily-price validation$",
    ) as caught:
        _provider(_write_csv(tmp_path / "prices.csv", invalid)).fetch_daily_bars(
            _request("EXAMPLE.O")
        )
    assert invalid_value not in str(caught.value)
    assert invalid_value not in "".join(traceback.format_exception(caught.value))


def test_csv_and_parquet_equivalent_values_have_identical_content_hash_and_batch_id(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    equivalent = price_frame.iloc[:2].assign(
        adjusted_close=[100.5, 101.5],
        effective_at=[
            "2024-01-08T20:00:00+00:00",
            "2024-01-09T20:00:00+00:00",
        ],
        available_at=[
            "2024-01-08T20:05:00+00:00",
            "2024-01-09T20:05:00+00:00",
        ],
        source_record_id=["vendor-row-1", "vendor-row-2"],
    )
    csv_path = _write_csv(tmp_path / "prices.csv", equivalent)
    parquet_path = tmp_path / "prices.parquet"
    equivalent.to_parquet(parquet_path, index=False)

    csv_result = _provider(csv_path).fetch_daily_bars(_request("EXAMPLE.O"))
    parquet_result = _provider(parquet_path).fetch_daily_bars(_request("EXAMPLE.O"))

    assert csv_result.batch.content_hash == parquet_result.batch.content_hash
    assert csv_result.batch.batch_id == parquet_result.batch.batch_id


def test_leading_zero_contract_text_is_preserved_and_csv_parquet_identity_matches(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    textual = price_frame.iloc[:1].assign(
        provider_identifier="001",
        source_record_id="000007",
    )
    csv_path = _write_csv(tmp_path / "textual.csv", textual)
    parquet_path = tmp_path / "textual.parquet"
    textual.to_parquet(parquet_path, index=False)

    csv_result = _provider(csv_path).fetch_daily_bars(_request("001"))
    parquet_result = _provider(parquet_path).fetch_daily_bars(_request("001"))

    assert csv_result.bars[0].provider_identifier == "001"
    assert csv_result.bars[0].source_record_id == "000007"
    assert parquet_result.bars[0].provider_identifier == "001"
    assert parquet_result.bars[0].source_record_id == "000007"
    assert csv_result.batch.content_hash == parquet_result.batch.content_hash
    assert csv_result.batch.batch_id == parquet_result.batch.batch_id


def test_csv_preserves_contract_text_that_matches_default_missing_tokens(
    tmp_path: Path,
    price_frame: pd.DataFrame,
) -> None:
    textual = price_frame.iloc[:1].assign(
        provider_identifier="NA",
        source_record_id="NULL",
    )
    path = _write_csv(tmp_path / "textual.csv", textual)

    result = _provider(path).fetch_daily_bars(_request("NA"))

    assert result.bars[0].provider_identifier == "NA"
    assert result.bars[0].source_record_id == "NULL"


def test_missing_parquet_engine_raises_not_configured_without_csv_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_engine(*args: object, **kwargs: object) -> pd.DataFrame:
        raise ImportError("private dependency detail")

    def forbidden_csv(*args: object, **kwargs: object) -> pd.DataFrame:
        pytest.fail("Parquet input fell back to CSV parsing")

    monkeypatch.setattr(pd, "read_parquet", missing_engine)
    monkeypatch.setattr(pd, "read_csv", forbidden_csv)

    with pytest.raises(
        ProviderNotConfigured,
        match=r"^Install the 'parquet' extra to read Parquet price files$",
    ):
        _provider(tmp_path / "prices.parquet").fetch_daily_bars(_request("EXAMPLE.O"))


def test_malformed_parquet_raises_fixed_provider_data_error_without_csv_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "private parquet parser detail"
    path = tmp_path / "malformed.parquet"
    path.write_bytes(sentinel.encode())

    def forbidden_csv(*args: object, **kwargs: object) -> pd.DataFrame:
        pytest.fail("Parquet input fell back to CSV parsing")

    monkeypatch.setattr(pd, "read_csv", forbidden_csv)
    with pytest.raises(
        ProviderDataError,
        match=r"^Parquet price file could not be read$",
    ) as caught:
        _provider(path).fetch_daily_bars(_request("EXAMPLE.O"))
    assert sentinel not in str(caught.value)
    assert sentinel not in "".join(traceback.format_exception(caught.value))
