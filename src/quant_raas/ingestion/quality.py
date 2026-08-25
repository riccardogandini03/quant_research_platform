"""Cross-record data-quality invariants for ingestion batches."""

from __future__ import annotations

from quant_raas.domain.enums import BatchStatus
from quant_raas.domain.market import PriceBarRequest, PriceIngestionResult


def validate_price_result(request: PriceBarRequest, result: PriceIngestionResult) -> None:
    """Reject internally inconsistent provider responses before persistence."""

    if result.batch.row_count != len(result.bars):
        raise ValueError("ingestion batch row_count does not match returned bars")
    if result.batch.request_fingerprint == "":
        raise ValueError("ingestion batch requires a request fingerprint")
    requested = {item.security_id for item in request.items}
    unexpected = sorted(
        {str(bar.security_id) for bar in result.bars if bar.security_id not in requested}
    )
    if unexpected:
        raise ValueError(f"provider returned unrequested securities: {', '.join(unexpected)}")
    if any(bar.ingestion_batch_id != result.batch.batch_id for bar in result.bars):
        raise ValueError("all price bars must reference their enclosing ingestion batch")
    if any(bar.usage_mode != result.batch.usage_mode for bar in result.bars):
        raise ValueError("all price bars must share their ingestion batch usage_mode")
    if any(bar.source != result.batch.original_source for bar in result.bars):
        raise ValueError("all price bars must share their ingestion batch original_source")
    if result.batch.status not in {
        BatchStatus.SUCCEEDED,
        BatchStatus.PARTIAL,
        BatchStatus.FAILED,
    }:
        raise ValueError("a provider response requires a terminal batch status")
    if result.batch.status == BatchStatus.SUCCEEDED and result.failures:
        raise ValueError("a succeeded price ingestion cannot contain item failures")
    if result.batch.status == BatchStatus.SUCCEEDED and not result.bars:
        raise ValueError("a succeeded price ingestion requires persisted bars")
    if result.batch.status == BatchStatus.PARTIAL and (not result.bars or not result.failures):
        raise ValueError("a partial price ingestion requires bars and item failures")
    if result.batch.status == BatchStatus.FAILED and (result.bars or not result.failures):
        raise ValueError("a failed price ingestion requires item failures and no persisted bars")

    requested_identifiers = {item.provider_identifier for item in request.items}
    failure_identifiers = [failure.provider_identifier for failure in result.failures]
    if any(identifier not in requested_identifiers for identifier in failure_identifiers):
        raise ValueError("price ingestion contains a failure for an unrequested identifier")
    if len(failure_identifiers) != len(set(failure_identifiers)):
        raise ValueError("price ingestion contains duplicate item failures")

    duplicate_keys: set[tuple[object, object, object, object]] = set()
    for bar in result.bars:
        key = (bar.security_id, bar.source, bar.effective_at, bar.available_at)
        if key in duplicate_keys:
            raise ValueError(f"duplicate price-bar vintage in provider response: {key}")
        duplicate_keys.add(key)
