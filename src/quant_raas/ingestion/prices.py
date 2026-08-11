"""Price-ingestion application service."""

from __future__ import annotations

from dataclasses import dataclass

from quant_raas.domain.market import IngestionBatch, PriceBarRequest
from quant_raas.domain.protocols import MarketDataRepository, PriceDataProvider
from quant_raas.ingestion.quality import validate_price_result


@dataclass(frozen=True, slots=True)
class PriceIngestionSummary:
    batch: IngestionBatch
    bars_received: int
    bars_inserted: int


class PriceIngestionService:
    """Fetch, validate, and persist one auditable price request."""

    def __init__(
        self,
        *,
        provider: PriceDataProvider,
        repository: MarketDataRepository,
    ) -> None:
        self.provider = provider
        self.repository = repository

    def ingest(self, request: PriceBarRequest) -> PriceIngestionSummary:
        result = self.provider.fetch_daily_bars(request)
        validate_price_result(request, result)
        persisted_batch = self.repository.add_ingestion_batch(result.batch)
        inserted = self.repository.upsert_price_bars(result.bars)
        return PriceIngestionSummary(
            batch=persisted_batch,
            bars_received=len(result.bars),
            bars_inserted=inserted,
        )
