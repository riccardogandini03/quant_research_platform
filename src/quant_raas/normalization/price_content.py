"""Canonical, acquisition-independent daily-price content construction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from uuid import UUID, uuid5

from quant_raas.common.clock import ensure_utc
from quant_raas.connectors.base import (
    ProviderDataError,
    content_addressed_batch_identity,
    fingerprint_request,
    require_utc,
)
from quant_raas.domain.enums import (
    BatchStatus,
    DataQualityFlag,
    DataUsageMode,
)
from quant_raas.domain.market import (
    IngestionBatch,
    PriceBar,
    PriceBarRequest,
    PriceIngestionResult,
    PriceItemFailure,
)


@dataclass(frozen=True, slots=True)
class NormalizedPriceRow:
    security_id: UUID
    provider_identifier: str
    source_record_id: str
    session_date: date
    effective_at: datetime
    source_available_at: datetime | None
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: float
    currency: str
    adjustment_factor: float | None
    total_return_factor: float | None
    source: str
    usage_mode: DataUsageMode
    quality_flags: tuple[DataQualityFlag, ...]
    field_map_version: str


@dataclass(frozen=True, slots=True)
class NormalizedPriceContent:
    original_source: str
    rows: tuple[NormalizedPriceRow, ...]
    failures: tuple[PriceItemFailure, ...] = ()


def canonical_price_content(content: NormalizedPriceContent) -> bytes:
    """Serialize normalized values without generated acquisition metadata."""

    original_source = normalize_original_source(content.original_source)
    rows = [_canonical_row(row) for row in content.rows]
    failures = [
        {
            "provider_identifier": failure.provider_identifier,
            "category": failure.category.value,
        }
        for failure in content.failures
    ]
    rows.sort(key=_canonical_json)
    failures.sort(key=_canonical_json)
    payload = {
        "schema": "normalized_price_content_v1",
        "original_source": original_source,
        "rows": rows,
        "failures": failures,
    }
    return _canonical_json(payload).encode("utf-8")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def hash_price_content(content: NormalizedPriceContent) -> str:
    return hashlib.sha256(canonical_price_content(content)).hexdigest()


def date_key_effective_at(session_date: date) -> datetime:
    return datetime.combine(session_date, time.min, tzinfo=UTC)


def _optional_hex(value: float | None) -> str | None:
    return None if value is None else float(value).hex()


def _canonical_row(row: NormalizedPriceRow) -> dict[str, object]:
    return {
        "security_id": str(row.security_id),
        "provider_identifier": row.provider_identifier,
        "source_record_id": row.source_record_id,
        "session_date": row.session_date.isoformat(),
        "effective_at": ensure_utc(row.effective_at).isoformat(),
        "source_available_at": (
            ensure_utc(row.source_available_at).isoformat()
            if row.source_available_at is not None
            else None
        ),
        "open": float(row.open).hex(),
        "high": float(row.high).hex(),
        "low": float(row.low).hex(),
        "close": float(row.close).hex(),
        "adjusted_close": float(row.adjusted_close).hex(),
        "volume": float(row.volume).hex(),
        "currency": row.currency,
        "adjustment_factor": _optional_hex(row.adjustment_factor),
        "total_return_factor": _optional_hex(row.total_return_factor),
        "source": row.source,
        "usage_mode": row.usage_mode.value,
        "quality_flags": sorted(flag.value for flag in row.quality_flags),
        "field_map_version": row.field_map_version,
    }


def normalize_original_source(original_source: str) -> str:
    normalized = original_source.strip().lower()
    if not 1 <= len(normalized) <= 80:
        raise ProviderDataError("original source must contain 1 to 80 characters")
    return normalized


def build_price_ingestion_result(
    *,
    provider: str,
    original_source: str,
    dataset: str,
    request: PriceBarRequest,
    field_map_version: str,
    usage_mode: DataUsageMode,
    rows: tuple[NormalizedPriceRow, ...],
    failures: tuple[PriceItemFailure, ...],
    started_at: datetime,
    completed_at: datetime,
) -> PriceIngestionResult:
    """Hash stable content before constructing its batch and domain bars."""

    normalized_original_source = normalize_original_source(original_source)
    normalized_started = require_utc(started_at, field_name="started_at")
    normalized_completed = require_utc(completed_at, field_name="completed_at")
    if normalized_completed < normalized_started:
        raise ProviderDataError("completed_at cannot precede started_at")
    prepared_rows = _prepare_rows(
        rows,
        original_source=normalized_original_source,
        usage_mode=usage_mode,
        field_map_version=field_map_version,
        completed_at=normalized_completed,
    )
    content = NormalizedPriceContent(
        original_source=normalized_original_source,
        rows=prepared_rows,
        failures=failures,
    )
    content_hash = hash_price_content(content)
    request_fingerprint = fingerprint_request(request)
    identity = content_addressed_batch_identity(
        provider=provider,
        dataset=dataset,
        request_fingerprint=request_fingerprint,
        field_map_version=field_map_version,
        usage_mode=usage_mode,
        content_hash=content_hash,
    )
    bars = tuple(
        _price_bar_from_normalized(
            row,
            batch_id=identity.batch_id,
            completed_at=normalized_completed,
        )
        for row in prepared_rows
    )
    status = _batch_status(bars=bars, failures=failures)
    batch = IngestionBatch(
        batch_id=identity.batch_id,
        batch_key=identity.batch_key,
        provider=provider,
        original_source=normalized_original_source,
        dataset=dataset,
        requested_at=request.requested_at,
        started_at=normalized_started,
        completed_at=normalized_completed,
        status=status,
        request_fingerprint=request_fingerprint,
        content_hash=content_hash,
        row_count=len(bars),
        error_message=_failure_message(failures),
        usage_mode=usage_mode,
    )
    return PriceIngestionResult(batch=batch, bars=bars, failures=failures)


def _prepare_rows(
    rows: tuple[NormalizedPriceRow, ...],
    *,
    original_source: str,
    usage_mode: DataUsageMode,
    field_map_version: str,
    completed_at: datetime,
) -> tuple[NormalizedPriceRow, ...]:
    seen_source_records: set[str] = set()
    prepared: list[NormalizedPriceRow] = []
    for row in rows:
        if row.source_record_id in seen_source_records:
            raise ProviderDataError("duplicate source_record_id in normalized price rows")
        seen_source_records.add(row.source_record_id)
        if row.source != original_source:
            raise ProviderDataError("normalized row source does not match original source")
        if row.usage_mode != usage_mode:
            raise ProviderDataError("normalized row usage mode does not match batch usage mode")
        if row.field_map_version != field_map_version:
            raise ProviderDataError(
                "normalized row field-map version does not match batch field-map version"
            )
        try:
            effective_at = ensure_utc(row.effective_at)
            source_available_at = (
                ensure_utc(row.source_available_at) if row.source_available_at is not None else None
            )
        except ValueError as error:
            raise ProviderDataError("normalized row timestamps must be timezone-aware") from error
        if source_available_at is not None and not (
            effective_at <= source_available_at <= completed_at
        ):
            raise ProviderDataError(
                "source availability must be between effective_at and completed_at"
            )
        flags = set(row.quality_flags)
        if source_available_at is None:
            flags.add(DataQualityFlag.SNAPSHOT_ONLY)
        prepared.append(
            replace(
                row,
                effective_at=effective_at,
                source_available_at=source_available_at,
                quality_flags=tuple(sorted(flags, key=lambda flag: flag.value)),
            )
        )
    prepared.sort(
        key=lambda row: (
            str(row.security_id),
            row.provider_identifier,
            row.session_date,
            row.source_record_id,
        )
    )
    return tuple(prepared)


def _price_bar_from_normalized(
    row: NormalizedPriceRow,
    *,
    batch_id: UUID,
    completed_at: datetime,
) -> PriceBar:
    return PriceBar(
        price_bar_id=uuid5(batch_id, row.source_record_id),
        security_id=row.security_id,
        session_date=row.session_date,
        effective_at=row.effective_at,
        available_at=row.source_available_at or completed_at,
        ingested_at=completed_at,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        adjusted_close=row.adjusted_close,
        volume=row.volume,
        currency=row.currency,
        adjustment_factor=row.adjustment_factor,
        total_return_factor=row.total_return_factor,
        source=row.source,
        usage_mode=row.usage_mode,
        source_record_id=row.source_record_id,
        provider_identifier=row.provider_identifier,
        ingestion_batch_id=batch_id,
        quality_flags=row.quality_flags,
    )


def _batch_status(
    *,
    bars: tuple[PriceBar, ...],
    failures: tuple[PriceItemFailure, ...],
) -> BatchStatus:
    if bars and failures:
        return BatchStatus.PARTIAL
    if bars:
        return BatchStatus.SUCCEEDED
    if failures:
        return BatchStatus.FAILED
    raise ProviderDataError("price result must contain rows or failures")


def _failure_message(failures: tuple[PriceItemFailure, ...]) -> str | None:
    if not failures:
        return None
    ordered = sorted(
        failures,
        key=lambda failure: (
            failure.provider_identifier,
            failure.category.value,
            failure.message,
        ),
    )
    return "; ".join(
        f"{failure.provider_identifier}: {failure.category.value}: {failure.message}"
        for failure in ordered
    )[:4000]
