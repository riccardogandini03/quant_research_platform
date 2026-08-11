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
    if result.batch.status == BatchStatus.FAILED and result.bars:
        raise ValueError("a failed price ingestion cannot contain persisted bars")

    duplicate_keys: set[tuple[object, object, object, object]] = set()
    for bar in result.bars:
        key = (bar.security_id, bar.source, bar.effective_at, bar.available_at)
        if key in duplicate_keys:
            raise ValueError(f"duplicate price-bar vintage in provider response: {key}")
        duplicate_keys.add(key)
