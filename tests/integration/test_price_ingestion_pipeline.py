"""Network-free provider → validation → repository ingestion integration."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from quant_raas.connectors.fixture import FixturePriceProvider
from quant_raas.domain.market import PriceBarRequest, PriceRequestItem
from quant_raas.domain.security import Security
from quant_raas.ingestion.prices import PriceIngestionService
from quant_raas.storage.repositories import (
    SqlAlchemyMarketDataRepository,
    SqlAlchemySecurityRepository,
)

pytestmark = pytest.mark.integration


def test_fixture_price_ingestion_is_atomic_and_idempotent(
    sqlite_session: Session,
    sample_security: Security,
    fixed_now: datetime,
    ohlcv_frame: pd.DataFrame,
) -> None:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    market = SqlAlchemyMarketDataRepository(sqlite_session)
    provider = FixturePriceProvider({"EXAMPLE": ohlcv_frame}, clock=lambda: fixed_now)
    service = PriceIngestionService(provider=provider, repository=market)
    request = PriceBarRequest(
        items=(
            PriceRequestItem(
                security_id=sample_security.security_id,
                provider_identifier="EXAMPLE",
            ),
        ),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 9),
        requested_at=fixed_now - timedelta(minutes=1),
    )

    first = service.ingest(request)
    second = service.ingest(request)
    assert first.bars_received == 6
    assert first.bars_inserted == 6
    assert second.bars_received == 6
    assert second.bars_inserted == 0
    assert first.batch.batch_id == second.batch.batch_id

    history = market.price_history_as_of(
        [sample_security.security_id],
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 10, tzinfo=UTC),
        knowledge_time=fixed_now,
        source="fixture",
    )
    assert len(history) == 6
    assert [bar.close for bar in history] == [100.0, 101.0, 99.0, 102.0, 103.0, 104.0]
    assert all(bar.ingested_at <= fixed_now for bar in history)
