"""Price-ingestion provenance and cross-record invariant contracts."""

from __future__ import annotations

import traceback
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from quant_raas.connectors.base import ProviderDataError
from quant_raas.domain.enums import (
    BatchStatus,
    DataQualityFlag,
    DataUsageMode,
    PriceFailureCategory,
)
from quant_raas.domain.market import (
    IngestionBatch,
    PriceBar,
    PriceBarRequest,
    PriceIngestionResult,
    PriceItemFailure,
    PriceRequestItem,
)
from quant_raas.ingestion.prices import PriceIngestionService
from quant_raas.ingestion.quality import validate_price_result

NOW = datetime(2024, 1, 10, 10, 0, tzinfo=UTC)
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
BATCH_ID = UUID("22222222-2222-4222-8222-222222222222")


def _request() -> PriceBarRequest:
    return PriceBarRequest(
        items=(
            PriceRequestItem(
                security_id=SECURITY_ID,
                provider_identifier="EXAMPLE.O",
            ),
        ),
        start_date=date(2024, 1, 9),
        end_date=date(2024, 1, 9),
        requested_at=NOW - timedelta(minutes=2),
    )


def _batch(
    *,
    status: BatchStatus = BatchStatus.SUCCEEDED,
    usage_mode: DataUsageMode = DataUsageMode.SYNTHETIC,
    row_count: int = 1,
    error_message: str | None = None,
) -> IngestionBatch:
    return IngestionBatch(
        batch_id=BATCH_ID,
        batch_key="fixture:1234567890abcdef",
        provider="fixture",
        original_source="fixture",
        dataset="daily_price_bar",
        requested_at=NOW - timedelta(minutes=2),
        started_at=NOW - timedelta(minutes=1),
        completed_at=NOW,
        status=status,
        request_fingerprint="12345678fixture",
        content_hash="abcdef12fixture",
        row_count=row_count,
        error_message=error_message,
        usage_mode=usage_mode,
    )


def _bar(
    *,
    usage_mode: DataUsageMode = DataUsageMode.SYNTHETIC,
    source: str = "fixture",
) -> PriceBar:
    return PriceBar(
        security_id=SECURITY_ID,
        session_date=date(2024, 1, 9),
        effective_at=datetime(2024, 1, 9, tzinfo=UTC),
        available_at=NOW,
        ingested_at=NOW,
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        adjusted_close=100.5,
        volume=1_000.0,
        currency="USD",
        adjustment_factor=100.5 / 101.0,
        source=source,
        source_record_id="EXAMPLE.O:2024-01-09",
        provider_identifier="EXAMPLE.O",
        ingestion_batch_id=BATCH_ID,
        quality_flags=(DataQualityFlag.ESTIMATED_TIMESTAMP,),
        usage_mode=usage_mode,
    )


def _failure(identifier: str = "EXAMPLE.O") -> PriceItemFailure:
    return PriceItemFailure(
        provider_identifier=identifier,
        category=PriceFailureCategory.NO_DATA,
        message=f"{identifier}: no completed daily rows",
    )


def test_price_usage_and_failure_enums_are_stable() -> None:
    assert tuple(mode.value for mode in DataUsageMode) == (
        "research_only",
        "public",
        "synthetic",
        "user_supplied",
        "unverified",
    )
    assert tuple(category.value for category in PriceFailureCategory) == (
        "no_data",
        "invalid_identifier",
        "invalid_currency",
    )


def test_price_result_preserves_typed_item_failure() -> None:
    failure = _failure("MISSING.O")
    result = PriceIngestionResult(
        batch=_batch(
            status=BatchStatus.FAILED,
            row_count=0,
            error_message=failure.message,
        ),
        bars=(),
        failures=(failure,),
    )
    assert result.failures == (failure,)


@pytest.mark.parametrize(
    ("model", "field"),
    (("batch", "original_source"), ("batch", "usage_mode"), ("bar", "usage_mode")),
)
def test_price_provenance_fields_are_required(model: str, field: str) -> None:
    instance = _batch() if model == "batch" else _bar()
    payload = instance.model_dump(mode="python")
    payload.pop(field)
    model_type = IngestionBatch if model == "batch" else PriceBar

    with pytest.raises(ValidationError, match=field):
        model_type.model_validate(payload)


@pytest.mark.parametrize("original_source", ("", "x" * 81))
def test_ingestion_batch_rejects_invalid_original_source(original_source: str) -> None:
    payload = _batch().model_dump(mode="python")
    payload["original_source"] = original_source

    with pytest.raises(ValidationError, match="original_source"):
        IngestionBatch.model_validate(payload)


def test_price_result_rejects_usage_mismatch() -> None:
    result = PriceIngestionResult(
        batch=_batch(),
        bars=(_bar(usage_mode=DataUsageMode.PUBLIC),),
    )
    with pytest.raises(ValueError, match="share their ingestion batch usage_mode"):
        validate_price_result(_request(), result)


def test_price_result_rejects_original_source_mismatch() -> None:
    result = PriceIngestionResult(batch=_batch(), bars=(_bar(source="renamed"),))

    with pytest.raises(ValueError, match="share their ingestion batch original_source"):
        validate_price_result(_request(), result)


def test_price_result_requires_terminal_batch_status() -> None:
    result = PriceIngestionResult(
        batch=_batch(status=BatchStatus.RUNNING),
        bars=(_bar(),),
    )

    with pytest.raises(ValueError, match="requires a terminal batch status"):
        validate_price_result(_request(), result)


@pytest.mark.parametrize(
    ("bars", "failures", "row_count", "message"),
    (
        ((), (), 0, "requires persisted bars"),
        ((_bar(),), (_failure(),), 1, "cannot contain item failures"),
    ),
)
def test_succeeded_price_result_requires_bars_without_failures(
    bars: tuple[PriceBar, ...],
    failures: tuple[PriceItemFailure, ...],
    row_count: int,
    message: str,
) -> None:
    result = PriceIngestionResult(
        batch=_batch(status=BatchStatus.SUCCEEDED, row_count=row_count),
        bars=bars,
        failures=failures,
    )

    with pytest.raises(ValueError, match=message):
        validate_price_result(_request(), result)


@pytest.mark.parametrize(
    ("bars", "failures", "row_count"),
    (((_bar(),), (), 1), ((), (_failure(),), 0)),
)
def test_partial_price_result_requires_bars_and_failures(
    bars: tuple[PriceBar, ...],
    failures: tuple[PriceItemFailure, ...],
    row_count: int,
) -> None:
    result = PriceIngestionResult(
        batch=_batch(status=BatchStatus.PARTIAL, row_count=row_count),
        bars=bars,
        failures=failures,
    )

    with pytest.raises(ValueError, match="requires bars and item failures"):
        validate_price_result(_request(), result)


@pytest.mark.parametrize(
    ("bars", "failures", "row_count"),
    (((_bar(),), (_failure(),), 1), ((), (), 0)),
)
def test_failed_price_result_requires_failures_without_bars(
    bars: tuple[PriceBar, ...],
    failures: tuple[PriceItemFailure, ...],
    row_count: int,
) -> None:
    result = PriceIngestionResult(
        batch=_batch(status=BatchStatus.FAILED, row_count=row_count),
        bars=bars,
        failures=failures,
    )

    with pytest.raises(ValueError, match="requires item failures and no persisted bars"):
        validate_price_result(_request(), result)


def test_price_result_rejects_failure_for_unrequested_identifier() -> None:
    result = PriceIngestionResult(
        batch=_batch(status=BatchStatus.FAILED, row_count=0),
        bars=(),
        failures=(_failure("SENTINEL-NOT-REQUESTED"),),
    )

    with pytest.raises(ValueError, match="failure for an unrequested identifier"):
        validate_price_result(_request(), result)


def test_price_result_rejects_duplicate_failure_identifiers() -> None:
    result = PriceIngestionResult(
        batch=_batch(status=BatchStatus.FAILED, row_count=0),
        bars=(),
        failures=(_failure(), _failure()),
    )

    with pytest.raises(ValueError, match="duplicate item failures"):
        validate_price_result(_request(), result)


class _StaticProvider:
    name = "fixture"

    def __init__(self, result: PriceIngestionResult) -> None:
        self.result = result

    def fetch_daily_bars(self, request: PriceBarRequest) -> PriceIngestionResult:
        return self.result


class _RecordingRepository:
    def __init__(self) -> None:
        self.batch_calls = 0
        self.bar_calls = 0

    def add_ingestion_batch(self, batch: IngestionBatch) -> IngestionBatch:
        self.batch_calls += 1
        return batch

    def upsert_price_bars(self, bars: Iterable[PriceBar]) -> int:
        self.bar_calls += 1
        return len(tuple(bars))


class _FailIfCalledRepository:
    def add_ingestion_batch(self, batch: IngestionBatch) -> IngestionBatch:
        raise AssertionError("repository must not be called")

    def upsert_price_bars(self, bars: Iterable[PriceBar]) -> int:
        raise AssertionError("repository must not be called")


def test_price_ingestion_service_returns_typed_failures() -> None:
    failure = _failure()
    result = PriceIngestionResult(
        batch=_batch(status=BatchStatus.FAILED, row_count=0, error_message=failure.message),
        bars=(),
        failures=(failure,),
    )
    repository = _RecordingRepository()

    summary = PriceIngestionService(
        provider=_StaticProvider(result),
        repository=repository,
    ).ingest(_request())

    assert summary.failures == (failure,)
    assert summary.bars_received == 0
    assert summary.bars_inserted == 0
    assert repository.batch_calls == 1
    assert repository.bar_calls == 1


def test_price_ingestion_service_sanitizes_provider_result_invariant_error() -> None:
    sentinel = "SENTINEL-NOT-REQUESTED"
    failure = _failure(sentinel)
    result = PriceIngestionResult(
        batch=_batch(status=BatchStatus.FAILED, row_count=0, error_message=failure.message),
        bars=(),
        failures=(failure,),
    )

    with pytest.raises(
        ProviderDataError,
        match=r"^provider result failed price-ingestion validation$",
    ) as caught:
        PriceIngestionService(
            provider=_StaticProvider(result),
            repository=_FailIfCalledRepository(),
        ).ingest(_request())

    rendered_chain = "".join(
        traceback.format_exception(type(caught.value), caught.value, caught.value.__traceback__)
    )
    assert sentinel not in rendered_chain
