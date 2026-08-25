"""Shared connector errors and deterministic request lineage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from quant_raas.domain.enums import DataUsageMode
from quant_raas.domain.market import PriceBarRequest

CONNECTOR_NAMESPACE = UUID("54192fef-f838-4d89-bbaa-785e8b700499")


class ProviderError(RuntimeError):
    """Base error for failures at a data-provider boundary."""


class ProviderNotConfigured(ProviderError):
    """Raised when a licensed or opt-in provider has not been configured."""


class ProviderDataError(ProviderError):
    """Raised when a provider response violates the expected data contract."""


@dataclass(frozen=True, slots=True)
class BatchIdentity:
    batch_id: UUID
    batch_key: str


def request_payload(request: PriceBarRequest) -> dict[str, Any]:
    """Return the stable subset used to identify an ingestion request."""

    return {
        "items": sorted(
            (str(item.security_id), item.provider_identifier) for item in request.items
        ),
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "frequency": request.frequency.value,
    }


def fingerprint_request(request: PriceBarRequest) -> str:
    encoded = json.dumps(request_payload(request), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def content_addressed_batch_identity(
    *,
    provider: str,
    dataset: str,
    request_fingerprint: str,
    field_map_version: str,
    usage_mode: DataUsageMode,
    content_hash: str,
) -> BatchIdentity:
    """Derive deterministic batch lineage from every stable attempt dimension."""

    payload = json.dumps(
        {
            "provider": provider,
            "dataset": dataset,
            "request_fingerprint": request_fingerprint,
            "field_map_version": field_map_version,
            "usage_mode": usage_mode.value,
            "content_hash": content_hash,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return BatchIdentity(
        batch_id=uuid5(CONNECTOR_NAMESPACE, digest),
        batch_key=f"{provider}:{digest[:40]}",
    )


def require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def acquisition_started_at(
    request: PriceBarRequest,
    observed_at: datetime,
) -> datetime:
    """Validate the provider clock without copying a future request timestamp."""

    acquired_at = require_utc(observed_at, field_name="acquisition clock")
    if request.requested_at > acquired_at:
        raise ProviderDataError("request timestamp cannot be later than the acquisition clock")
    return acquired_at
