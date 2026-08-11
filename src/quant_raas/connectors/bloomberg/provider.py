"""Explicit Bloomberg placeholder that never reports false success."""

from __future__ import annotations

from quant_raas.connectors.base import ProviderNotConfigured
from quant_raas.domain.market import PriceBarRequest, PriceIngestionResult


class BloombergPriceProvider:
    name = "bloomberg"

    def __init__(self, *, host: str | None = None, port: int = 8194) -> None:
        self.host = host
        self.port = port

    def fetch_daily_bars(self, request: PriceBarRequest) -> PriceIngestionResult:
        del request
        raise ProviderNotConfigured(
            "Bloomberg field mappings and an entitled session must be configured before use"
        )
