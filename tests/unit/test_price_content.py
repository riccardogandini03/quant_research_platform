"""Canonical price content and shared connector construction contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from quant_raas.connectors.base import (
    ProviderDataError,
    acquisition_started_at,
    content_addressed_batch_identity,
)
from quant_raas.domain.enums import (
    BatchStatus,
    DataQualityFlag,
    DataUsageMode,
    PriceFailureCategory,
)
from quant_raas.domain.market import (
    PriceBarRequest,
    PriceIngestionResult,
    PriceItemFailure,
    PriceRequestItem,
)
from quant_raas.normalization.price_content import (
    NormalizedPriceContent,
    NormalizedPriceRow,
    build_price_ingestion_result,
    canonical_price_content,
    date_key_effective_at,
    hash_price_content,
)

SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
REQUESTED_AT = datetime(2024, 1, 10, 9, 0, tzinfo=UTC)


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


def _row(
    session_date: date,
    close: float,
    *,
    source_available_at: datetime | None = None,
) -> NormalizedPriceRow:
    adjusted_close = close - 0.25
    return NormalizedPriceRow(
        security_id=SECURITY_ID,
        provider_identifier="EXAMPLE.O",
        source_record_id=f"fixture:EXAMPLE.O:{session_date.isoformat()}",
        session_date=session_date,
        effective_at=date_key_effective_at(session_date),
        source_available_at=source_available_at,
        open=close - 0.5,
        high=close + 0.5,
        low=close - 1.0,
        close=close,
        adjusted_close=adjusted_close,
        volume=1_000.5,
        currency="USD",
        adjustment_factor=adjusted_close / close,
        total_return_factor=None,
        source="fixture",
        usage_mode=DataUsageMode.SYNTHETIC,
        quality_flags=(
            (DataQualityFlag.SNAPSHOT_ONLY, DataQualityFlag.ESTIMATED_TIMESTAMP)
            if source_available_at is None
            else (DataQualityFlag.ESTIMATED_TIMESTAMP,)
        ),
        field_map_version="fixture_daily_price_v1",
    )


def _failure(
    provider_identifier: str,
    category: PriceFailureCategory,
) -> PriceItemFailure:
    return PriceItemFailure(
        provider_identifier=provider_identifier,
        category=category,
        message=f"{provider_identifier}: {category.value}",
    )


def _build_result(completed_at: datetime) -> PriceIngestionResult:
    return build_price_ingestion_result(
        provider="fixture",
        original_source="fixture",
        dataset="daily_price_bar",
        request=_request(),
        field_map_version="fixture_daily_price_v1",
        usage_mode=DataUsageMode.SYNTHETIC,
        rows=(_row(date(2024, 1, 9), 101.25),),
        failures=(),
        started_at=completed_at - timedelta(seconds=1),
        completed_at=completed_at,
    )


def test_canonical_content_is_order_invariant_and_uses_float_hex() -> None:
    first = NormalizedPriceContent(
        original_source="fixture",
        rows=(
            _row(date(2024, 1, 9), 101.25),
            _row(date(2024, 1, 8), 100.5),
        ),
        failures=(
            _failure("Z.O", PriceFailureCategory.NO_DATA),
            _failure("A.O", PriceFailureCategory.INVALID_IDENTIFIER),
        ),
    )
    reordered = NormalizedPriceContent(
        original_source=first.original_source,
        rows=tuple(
            replace(row, quality_flags=tuple(reversed(row.quality_flags)))
            for row in reversed(first.rows)
        ),
        failures=tuple(reversed(first.failures)),
    )
    payload = canonical_price_content(first)
    assert payload == canonical_price_content(reordered)
    assert float(101.25).hex().encode() in payload  # noqa: UP018 - prescribed contract
    assert b'"requested_at"' not in payload
    assert b'"ingested_at"' not in payload


def test_generated_acquisition_time_does_not_change_identity() -> None:
    first = _build_result(datetime(2024, 1, 10, 10, 0, tzinfo=UTC))
    second = _build_result(datetime(2024, 1, 11, 10, 0, tzinfo=UTC))
    assert first.batch.content_hash == second.batch.content_hash
    assert first.batch.batch_id == second.batch.batch_id
    assert first.bars[0].available_at != second.bars[0].available_at


def test_source_supplied_availability_changes_identity() -> None:
    first = NormalizedPriceContent(
        original_source="fixture",
        rows=(
            _row(
                date(2024, 1, 9),
                101.25,
                source_available_at=datetime(2024, 1, 9, 21, 5, tzinfo=UTC),
            ),
        ),
    )
    second = NormalizedPriceContent(
        original_source="fixture",
        rows=(
            _row(
                date(2024, 1, 9),
                101.25,
                source_available_at=datetime(2024, 1, 9, 21, 6, tzinfo=UTC),
            ),
        ),
    )
    assert hash_price_content(first) != hash_price_content(second)


def test_all_failure_content_is_bound_to_original_source() -> None:
    failure = _failure("MISSING.O", PriceFailureCategory.NO_DATA)
    lseg_content = NormalizedPriceContent(
        original_source="lseg",
        rows=(),
        failures=(failure,),
    )
    export_content = NormalizedPriceContent(
        original_source="user_export",
        rows=(),
        failures=(failure,),
    )
    assert hash_price_content(lseg_content) != hash_price_content(export_content)

    build_arguments = {
        "provider": "file",
        "dataset": "daily_price_bar",
        "request": _request(),
        "field_map_version": "file_daily_price_v1",
        "usage_mode": DataUsageMode.USER_SUPPLIED,
        "rows": (),
        "failures": (failure,),
        "started_at": datetime(2024, 1, 10, 10, 0, tzinfo=UTC),
        "completed_at": datetime(2024, 1, 10, 10, 0, 1, tzinfo=UTC),
    }
    lseg_result = build_price_ingestion_result(original_source="lseg", **build_arguments)
    export_result = build_price_ingestion_result(original_source="user_export", **build_arguments)
    assert lseg_result.batch.batch_id != export_result.batch.batch_id
    assert lseg_result.batch.original_source == "lseg"
    assert export_result.batch.original_source == "user_export"
    assert lseg_result.batch.status == BatchStatus.FAILED


@pytest.mark.parametrize("original_source", ["", "   ", "x" * 81])
def test_original_source_must_contain_one_to_eighty_characters(
    original_source: str,
) -> None:
    content = NormalizedPriceContent(original_source=original_source, rows=())
    with pytest.raises(
        ProviderDataError,
        match="original source must contain 1 to 80 characters",
    ):
        hash_price_content(content)


@pytest.mark.parametrize(
    "changed_row",
    [
        replace(_row(date(2024, 1, 9), 101.25), close=101.5),
        replace(_row(date(2024, 1, 9), 101.25), currency="EUR"),
        replace(_row(date(2024, 1, 9), 101.25), source="user_export"),
        replace(
            _row(date(2024, 1, 9), 101.25),
            usage_mode=DataUsageMode.USER_SUPPLIED,
        ),
        replace(
            _row(date(2024, 1, 9), 101.25),
            field_map_version="fixture_daily_price_v2",
        ),
    ],
)
def test_each_stable_row_dimension_changes_content_hash(
    changed_row: NormalizedPriceRow,
) -> None:
    baseline = NormalizedPriceContent(
        original_source="fixture",
        rows=(_row(date(2024, 1, 9), 101.25),),
    )
    changed = NormalizedPriceContent(original_source="fixture", rows=(changed_row,))
    assert hash_price_content(baseline) != hash_price_content(changed)


@pytest.mark.parametrize(
    "changed_failure",
    [
        _failure("OTHER.O", PriceFailureCategory.NO_DATA),
        _failure("MISSING.O", PriceFailureCategory.INVALID_IDENTIFIER),
    ],
)
def test_each_stable_failure_dimension_changes_content_hash(
    changed_failure: PriceItemFailure,
) -> None:
    baseline = NormalizedPriceContent(
        original_source="fixture",
        rows=(),
        failures=(_failure("MISSING.O", PriceFailureCategory.NO_DATA),),
    )
    changed = replace(baseline, failures=(changed_failure,))
    assert hash_price_content(baseline) != hash_price_content(changed)


@pytest.mark.parametrize(
    ("dimension", "changed_value"),
    [
        ("provider", "file"),
        ("dataset", "weekly_price_bar"),
        ("request_fingerprint", "request-b"),
        ("field_map_version", "fixture_daily_price_v2"),
        ("usage_mode", DataUsageMode.USER_SUPPLIED),
        ("content_hash", "content-b"),
    ],
)
def test_each_stable_batch_dimension_changes_identity(
    dimension: str,
    changed_value: str | DataUsageMode,
) -> None:
    arguments: dict[str, str | DataUsageMode] = {
        "provider": "fixture",
        "dataset": "daily_price_bar",
        "request_fingerprint": "request-a",
        "field_map_version": "fixture_daily_price_v1",
        "usage_mode": DataUsageMode.SYNTHETIC,
        "content_hash": "content-a",
    }
    baseline = content_addressed_batch_identity(**arguments)  # type: ignore[arg-type]
    arguments[dimension] = changed_value
    changed = content_addressed_batch_identity(**arguments)  # type: ignore[arg-type]
    assert changed != baseline


def test_shared_builder_normalizes_rows_and_constructs_domain_bars() -> None:
    flags = (
        DataQualityFlag.ESTIMATED_TIMESTAMP,
        DataQualityFlag.ESTIMATED_TIMESTAMP,
    )
    later = replace(
        _row(date(2024, 1, 9), 101.25),
        quality_flags=flags,
        source_record_id="fixture:second",
    )
    earlier = replace(
        _row(date(2024, 1, 8), 100.5),
        quality_flags=flags,
        source_record_id="fixture:first",
    )
    result = build_price_ingestion_result(
        provider="fixture",
        original_source=" Fixture ",
        dataset="daily_price_bar",
        request=_request(),
        field_map_version="fixture_daily_price_v1",
        usage_mode=DataUsageMode.SYNTHETIC,
        rows=(later, earlier),
        failures=(),
        started_at=datetime(2024, 1, 10, 10, 0, tzinfo=UTC),
        completed_at=datetime(2024, 1, 10, 10, 0, 1, tzinfo=UTC),
    )
    assert [bar.source_record_id for bar in result.bars] == [
        "fixture:first",
        "fixture:second",
    ]
    assert all(
        bar.quality_flags
        == (
            DataQualityFlag.ESTIMATED_TIMESTAMP,
            DataQualityFlag.SNAPSHOT_ONLY,
        )
        for bar in result.bars
    )
    assert all(bar.available_at == result.batch.completed_at for bar in result.bars)
    assert all(bar.ingested_at == result.batch.completed_at for bar in result.bars)
    assert all(bar.ingestion_batch_id == result.batch.batch_id for bar in result.bars)
    assert result.batch.original_source == "fixture"
    assert result.batch.status == BatchStatus.SUCCEEDED


@pytest.mark.parametrize(
    "rows",
    [
        (
            _row(date(2024, 1, 8), 100.5),
            replace(
                _row(date(2024, 1, 9), 101.25),
                source_record_id="fixture:EXAMPLE.O:2024-01-08",
            ),
        ),
        (replace(_row(date(2024, 1, 9), 101.25), source="other"),),
        (
            replace(
                _row(date(2024, 1, 9), 101.25),
                usage_mode=DataUsageMode.PUBLIC,
            ),
        ),
        (
            replace(
                _row(date(2024, 1, 9), 101.25),
                field_map_version="fixture_daily_price_v2",
            ),
        ),
    ],
)
def test_shared_builder_rejects_inconsistent_row_provenance(
    rows: tuple[NormalizedPriceRow, ...],
) -> None:
    with pytest.raises(ProviderDataError):
        build_price_ingestion_result(
            provider="fixture",
            original_source="fixture",
            dataset="daily_price_bar",
            request=_request(),
            field_map_version="fixture_daily_price_v1",
            usage_mode=DataUsageMode.SYNTHETIC,
            rows=rows,
            failures=(),
            started_at=datetime(2024, 1, 10, 10, 0, tzinfo=UTC),
            completed_at=datetime(2024, 1, 10, 10, 0, 1, tzinfo=UTC),
        )


def test_shared_builder_rejects_invalid_acquisition_and_source_times() -> None:
    started_at = datetime(2024, 1, 10, 10, 0, tzinfo=UTC)
    with pytest.raises(ProviderDataError, match="completed_at cannot precede started_at"):
        build_price_ingestion_result(
            provider="fixture",
            original_source="fixture",
            dataset="daily_price_bar",
            request=_request(),
            field_map_version="fixture_daily_price_v1",
            usage_mode=DataUsageMode.SYNTHETIC,
            rows=(_row(date(2024, 1, 9), 101.25),),
            failures=(),
            started_at=started_at,
            completed_at=started_at - timedelta(seconds=1),
        )

    impossible_source_time = _row(
        date(2024, 1, 9),
        101.25,
        source_available_at=datetime(2024, 1, 10, 10, 0, 2, tzinfo=UTC),
    )
    with pytest.raises(ProviderDataError, match="source availability"):
        build_price_ingestion_result(
            provider="fixture",
            original_source="fixture",
            dataset="daily_price_bar",
            request=_request(),
            field_map_version="fixture_daily_price_v1",
            usage_mode=DataUsageMode.SYNTHETIC,
            rows=(impossible_source_time,),
            failures=(),
            started_at=started_at,
            completed_at=started_at + timedelta(seconds=1),
        )


def test_shared_builder_requires_rows_or_failures() -> None:
    with pytest.raises(ProviderDataError, match="rows or failures"):
        build_price_ingestion_result(
            provider="fixture",
            original_source="fixture",
            dataset="daily_price_bar",
            request=_request(),
            field_map_version="fixture_daily_price_v1",
            usage_mode=DataUsageMode.SYNTHETIC,
            rows=(),
            failures=(),
            started_at=datetime(2024, 1, 10, 10, 0, tzinfo=UTC),
            completed_at=datetime(2024, 1, 10, 10, 0, 1, tzinfo=UTC),
        )


def test_failure_message_is_deterministic_and_capped() -> None:
    failures = tuple(
        PriceItemFailure(
            provider_identifier=f"ITEM-{index:03}",
            category=PriceFailureCategory.NO_DATA,
            message="x" * 500,
        )
        for index in reversed(range(10))
    )
    result = build_price_ingestion_result(
        provider="fixture",
        original_source="fixture",
        dataset="daily_price_bar",
        request=_request(),
        field_map_version="fixture_daily_price_v1",
        usage_mode=DataUsageMode.SYNTHETIC,
        rows=(),
        failures=failures,
        started_at=datetime(2024, 1, 10, 10, 0, tzinfo=UTC),
        completed_at=datetime(2024, 1, 10, 10, 0, 1, tzinfo=UTC),
    )
    assert result.batch.error_message is not None
    assert len(result.batch.error_message) == 4_000
    assert result.batch.error_message.startswith("ITEM-000: no_data:")


def test_future_requested_at_is_rejected_by_acquisition_clock_guard() -> None:
    observed_at = REQUESTED_AT - timedelta(seconds=1)
    with pytest.raises(
        ProviderDataError,
        match="request timestamp cannot be later than the acquisition clock",
    ):
        acquisition_started_at(_request(), observed_at)
