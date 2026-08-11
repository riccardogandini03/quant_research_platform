"""Explicit LSEG placeholder that never reports false success."""

from __future__ import annotations

from quant_raas.connectors.base import ProviderNotConfigured
from quant_raas.domain.market import PriceBarRequest, PriceIngestionResult


class LsegPriceProvider:
    name = "lseg"

    def __init__(self, *, session_mode: str | None = None) -> None:
        self.session_mode = session_mode

    def fetch_daily_bars(self, request: PriceBarRequest) -> PriceIngestionResult:
        del request
        raise ProviderNotConfigured(
            "LSEG RIC/field mappings and an entitled desktop or platform session are required"
        )
