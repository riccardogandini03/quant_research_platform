"""Shared connector errors and deterministic request lineage."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from quant_raas.domain.market import PriceBarRequest

CONNECTOR_NAMESPACE = UUID("54192fef-f838-4d89-bbaa-785e8b700499")


class ProviderError(RuntimeError):
    """Base error for failures at a data-provider boundary."""


class ProviderNotConfigured(ProviderError):
    """Raised when a licensed or opt-in provider has not been configured."""


class ProviderDataError(ProviderError):
    """Raised when a provider response violates the expected data contract."""


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


def stable_batch_id(provider: str, request: PriceBarRequest) -> UUID:
    """Make provider retries of the same logical request idempotent."""

    return uuid5(CONNECTOR_NAMESPACE, f"{provider}:{fingerprint_request(request)}")


def batch_key(provider: str, request: PriceBarRequest) -> str:
    return f"{provider}:daily:{fingerprint_request(request)[:24]}"


def require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value
