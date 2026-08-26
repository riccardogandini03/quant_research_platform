"""Repository coverage for content-addressed price ingestion retries."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_raas.common.errors import RepositoryConflictError
from quant_raas.domain.enums import (
    BatchStatus,
    DataQualityFlag,
    DataUsageMode,
)
from quant_raas.domain.market import IngestionBatch, PriceBar
from quant_raas.domain.security import Security
from quant_raas.storage.models import PriceBarRecord
from quant_raas.storage.repositories import (
    SqlAlchemyMarketDataRepository,
    SqlAlchemySecurityRepository,
)

pytestmark = pytest.mark.integration
REQUESTED_AT = datetime(2024, 1, 10, 10, 0, tzinfo=UTC)
EFFECTIVE_AT = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
AVAILABLE_AT = datetime(2024, 1, 9, 21, 5, tzinfo=UTC)
BATCH_ID = UUID("22222222-2222-4222-8222-222222222222")
BATCH_KEY = "lseg:daily_price_bar:attempt-one"
BAR_ID = UUID("33333333-3333-4333-8333-333333333333")
SOURCE_RECORD_ID = "EXAMPLE.O:2024-01-09"
ALTERNATE_SECURITY_ID = UUID("12121212-1212-4212-8212-121212121212")


def _batch(
    *,
    batch_id: UUID = BATCH_ID,
    batch_key: str = BATCH_KEY,
    requested_at: datetime = REQUESTED_AT,
    provider: str = "lseg",
    original_source: str = "lseg",
    usage_mode: DataUsageMode = DataUsageMode.RESEARCH_ONLY,
    dataset: str = "daily_price_bar",
    status: BatchStatus = BatchStatus.SUCCEEDED,
    request_fingerprint: str = "request-fingerprint-one",
    content_hash: str = "content-hash-one",
    row_count: int = 1,
    error_message: str | None = None,
) -> IngestionBatch:
    return IngestionBatch(
        batch_id=batch_id,
        batch_key=batch_key,
        provider=provider,
        original_source=original_source,
        usage_mode=usage_mode,
        dataset=dataset,
        requested_at=requested_at,
        started_at=requested_at + timedelta(seconds=1),
        completed_at=requested_at + timedelta(seconds=2),
        status=status,
        request_fingerprint=request_fingerprint,
        content_hash=content_hash,
        row_count=row_count,
        error_message=error_message,
    )


def _bar(
    *,
    security_id: UUID,
    batch_id: UUID = BATCH_ID,
    price_bar_id: UUID = BAR_ID,
    available_at: datetime = AVAILABLE_AT,
    ingested_at: datetime | None = None,
    close: float = 100.0,
    currency: str = "USD",
    provider_identifier: str | None = "EXAMPLE.O",
    quality_flags: tuple[DataQualityFlag, ...] = (),
    source: str = "lseg",
    usage_mode: DataUsageMode = DataUsageMode.RESEARCH_ONLY,
) -> PriceBar:
    return PriceBar(
        price_bar_id=price_bar_id,
        security_id=security_id,
        session_date=date(2024, 1, 9),
        effective_at=EFFECTIVE_AT,
        available_at=available_at,
        ingested_at=ingested_at or available_at + timedelta(minutes=1),
        open=99.0,
        high=102.0,
        low=98.0,
        close=close,
        adjusted_close=close,
        volume=1_000.0,
        currency=currency,
        adjustment_factor=1.0,
        total_return_factor=None,
        source=source,
        source_record_id=SOURCE_RECORD_ID,
        provider_identifier=provider_identifier,
        ingestion_batch_id=batch_id,
        quality_flags=quality_flags,
        usage_mode=usage_mode,
    )


def _repository_with_security(
    sqlite_session: Session,
    sample_security: Security,
) -> SqlAlchemyMarketDataRepository:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    return SqlAlchemyMarketDataRepository(sqlite_session)


def _validated_bar_copy(bar: PriceBar, changed: dict[str, Any]) -> PriceBar:
    payload = bar.model_dump(mode="python")
    payload.update(changed)
    return PriceBar.model_validate(payload)


def test_identical_batch_identity_ignores_retry_clocks_and_error_formatting(
    sqlite_session: Session,
) -> None:
    repository = SqlAlchemyMarketDataRepository(sqlite_session)
    first = _batch(error_message="first formatting")
    retry = _batch(
        requested_at=REQUESTED_AT + timedelta(hours=1),
        error_message="retry formatting",
    )

    assert repository.add_ingestion_batch(first) == first
    assert repository.add_ingestion_batch(retry) == first


@pytest.mark.parametrize(
    "changed",
    (
        {"batch_id": UUID("44444444-4444-4444-8444-444444444444")},
        {"batch_key": "lseg:daily_price_bar:attempt-two"},
        {"provider": "file"},
        {"original_source": "other_vendor"},
        {"dataset": "other_dataset"},
        {"status": BatchStatus.PARTIAL},
        {"request_fingerprint": "request-fingerprint-two"},
        {"content_hash": "content-hash-two"},
        {"row_count": 2},
        {"usage_mode": DataUsageMode.USER_SUPPLIED},
    ),
    ids=(
        "batch-id",
        "batch-key",
        "provider",
        "original-source",
        "dataset",
        "status",
        "request-fingerprint",
        "content-hash",
        "row-count",
        "usage-mode",
    ),
)
def test_reused_batch_key_or_id_rejects_changed_stable_identity(
    sqlite_session: Session,
    changed: dict[str, Any],
) -> None:
    repository = SqlAlchemyMarketDataRepository(sqlite_session)
    first = _batch()
    repository.add_ingestion_batch(first)

    with pytest.raises(
        RepositoryConflictError,
        match=r"^ingestion batch identity contains different content or provenance$",
    ):
        repository.add_ingestion_batch(first.model_copy(update=changed))


def test_batch_id_and_key_cannot_resolve_to_different_rows(
    sqlite_session: Session,
) -> None:
    repository = SqlAlchemyMarketDataRepository(sqlite_session)
    first = _batch(row_count=0)
    second = _batch(
        batch_id=UUID("55555555-5555-4555-8555-555555555555"),
        batch_key="lseg:daily_price_bar:attempt-two",
        content_hash="content-hash-two",
        row_count=0,
    )
    repository.add_ingestion_batch(first)
    repository.add_ingestion_batch(second)

    split_identity = first.model_copy(update={"batch_key": second.batch_key})
    with pytest.raises(
        RepositoryConflictError,
        match=r"^ingestion batch identity contains different content or provenance$",
    ):
        repository.add_ingestion_batch(split_identity)


def test_matching_attempt_skips_regenerated_bar_identity_and_acquisition_times(
    sqlite_session: Session,
    sample_security: Security,
) -> None:
    repository = _repository_with_security(sqlite_session, sample_security)
    repository.add_ingestion_batch(_batch())
    first = _bar(security_id=sample_security.security_id)
    retry = _bar(
        security_id=sample_security.security_id,
        price_bar_id=UUID("66666666-6666-4666-8666-666666666666"),
        available_at=AVAILABLE_AT + timedelta(hours=1),
        ingested_at=AVAILABLE_AT + timedelta(hours=1, minutes=1),
    )

    assert repository.upsert_price_bars([first]) == 1
    assert repository.upsert_price_bars([retry]) == 0
    assert sqlite_session.scalar(select(func.count()).select_from(PriceBarRecord)) == 1
    stored = repository.price_history_as_of(
        [sample_security.security_id],
        start=EFFECTIVE_AT,
        end=EFFECTIVE_AT,
        knowledge_time=retry.ingested_at,
    )
    assert stored == (first,)


@pytest.mark.parametrize(
    "changed",
    (
        {"security_id": ALTERNATE_SECURITY_ID},
        {"session_date": date(2024, 1, 8)},
        {"effective_at": EFFECTIVE_AT + timedelta(minutes=1)},
        {"open": 100.0},
        {"high": 103.0},
        {"low": 97.0},
        {"close": 101.0},
        {"adjusted_close": 101.0},
        {"volume": 1_100.0},
        {"currency": "EUR"},
        {"adjustment_factor": 1.01},
        {"total_return_factor": 1.01},
        {"provider_identifier": "OTHER.O"},
        {"quality_flags": (DataQualityFlag.SNAPSHOT_ONLY,)},
        {"source": "other_vendor"},
        {"usage_mode": DataUsageMode.USER_SUPPLIED},
    ),
    ids=(
        "security-id",
        "session-date",
        "effective-at",
        "open",
        "high",
        "low",
        "close",
        "adjusted-close",
        "volume",
        "currency",
        "adjustment-factor",
        "total-return-factor",
        "provider-identifier",
        "flags",
        "source",
        "usage",
    ),
)
def test_matching_attempt_rejects_changed_numerical_or_provenance_values(
    sqlite_session: Session,
    sample_security: Security,
    changed: dict[str, Any],
) -> None:
    repository = _repository_with_security(sqlite_session, sample_security)
    if changed.get("security_id") == ALTERNATE_SECURITY_ID:
        SqlAlchemySecurityRepository(sqlite_session).add_security(
            sample_security.model_copy(update={"security_id": ALTERNATE_SECURITY_ID})
        )
    repository.add_ingestion_batch(_batch())
    first = _bar(security_id=sample_security.security_id)
    repository.upsert_price_bars([first])
    retry = _validated_bar_copy(
        first,
        {
            "price_bar_id": UUID("77777777-7777-4777-8777-777777777777"),
            "available_at": AVAILABLE_AT + timedelta(hours=1),
            "ingested_at": AVAILABLE_AT + timedelta(hours=1, minutes=1),
            **changed,
        },
    )

    with pytest.raises(
        RepositoryConflictError,
        match=(
            r"^price bar attempt identity contains different numerical "
            "or provenance values$"
        ),
    ):
        repository.upsert_price_bars([retry])


@pytest.mark.parametrize(
    "changed",
    (
        {"session_date": date(2024, 1, 8)},
        {"open": 100.0},
        {"high": 103.0},
        {"low": 97.0},
        {"close": 101.0},
        {"adjusted_close": 101.0},
        {"volume": 1_100.0},
        {"currency": "EUR"},
        {"adjustment_factor": 1.01},
        {"total_return_factor": 1.01},
        {"source_record_id": "EXAMPLE.O:2024-01-09:revised"},
        {"provider_identifier": "OTHER.O"},
        {"quality_flags": (DataQualityFlag.SNAPSHOT_ONLY,)},
        {"usage_mode": DataUsageMode.USER_SUPPLIED},
    ),
    ids=(
        "session-date",
        "open",
        "high",
        "low",
        "close",
        "adjusted-close",
        "volume",
        "currency",
        "adjustment-factor",
        "total-return-factor",
        "source-record-id",
        "provider-identifier",
        "flags",
        "usage",
    ),
)
def test_same_natural_vintage_rejects_changed_content_from_distinct_attempt(
    sqlite_session: Session,
    sample_security: Security,
    changed: dict[str, Any],
) -> None:
    repository = _repository_with_security(sqlite_session, sample_security)
    first_batch = _batch()
    second_batch = _batch(
        batch_id=UUID("88888888-8888-4888-8888-888888888888"),
        batch_key="lseg:daily_price_bar:attempt-two",
        content_hash="content-hash-two",
    )
    repository.add_ingestion_batch(first_batch)
    repository.add_ingestion_batch(second_batch)
    first = _bar(security_id=sample_security.security_id)
    repository.upsert_price_bars([first])
    contradictory = _validated_bar_copy(
        first,
        {
            "ingestion_batch_id": second_batch.batch_id,
            "price_bar_id": UUID("99999999-9999-4999-8999-999999999999"),
            **changed,
        },
    )

    with pytest.raises(
        RepositoryConflictError,
        match=(r"^price bar vintage contains different numerical or provenance values$"),
    ):
        repository.upsert_price_bars([contradictory])


def test_same_natural_vintage_skips_equal_payload_from_distinct_attempt(
    sqlite_session: Session,
    sample_security: Security,
) -> None:
    repository = _repository_with_security(sqlite_session, sample_security)
    first_batch = _batch()
    second_batch = _batch(
        batch_id=UUID("89898989-8989-4989-8989-898989898989"),
        batch_key="lseg:daily_price_bar:attempt-equal-vintage",
        content_hash="content-hash-equal-vintage",
    )
    repository.add_ingestion_batch(first_batch)
    repository.add_ingestion_batch(second_batch)
    first = _bar(security_id=sample_security.security_id)
    equal_retry = _validated_bar_copy(
        first,
        {
            "ingestion_batch_id": second_batch.batch_id,
            "price_bar_id": UUID("90909090-9090-4090-8090-909090909090"),
        },
    )

    assert repository.upsert_price_bars([first]) == 1
    assert repository.upsert_price_bars([equal_retry]) == 0
    assert sqlite_session.scalar(select(func.count()).select_from(PriceBarRecord)) == 1


def test_later_availability_persists_correction_and_as_of_selects_each_vintage(
    sqlite_session: Session,
    sample_security: Security,
) -> None:
    repository = _repository_with_security(sqlite_session, sample_security)
    first_batch = _batch()
    correction_batch = _batch(
        batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        batch_key="lseg:daily_price_bar:attempt-correction",
        content_hash="content-hash-correction",
    )
    repository.add_ingestion_batch(first_batch)
    repository.add_ingestion_batch(correction_batch)
    first = _bar(security_id=sample_security.security_id)
    correction_available = AVAILABLE_AT + timedelta(days=1)
    correction = _bar(
        security_id=sample_security.security_id,
        batch_id=correction_batch.batch_id,
        price_bar_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        available_at=correction_available,
        ingested_at=correction_available + timedelta(minutes=1),
        close=101.0,
    )

    assert repository.upsert_price_bars([first]) == 1
    assert repository.upsert_price_bars([correction]) == 1
    before = repository.price_history_as_of(
        [sample_security.security_id],
        start=EFFECTIVE_AT,
        end=EFFECTIVE_AT,
        knowledge_time=correction_available - timedelta(microseconds=1),
    )
    after = repository.price_history_as_of(
        [sample_security.security_id],
        start=EFFECTIVE_AT,
        end=EFFECTIVE_AT,
        knowledge_time=correction_available,
    )
    assert before == (first,)
    assert after == (correction,)
    assert after[0].usage_mode == DataUsageMode.RESEARCH_ONLY
