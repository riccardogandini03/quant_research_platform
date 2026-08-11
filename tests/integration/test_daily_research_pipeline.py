"""Network-free integration of ingestion, daily research, and persistence."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from quant_raas.connectors.fixture import FixturePriceProvider
from quant_raas.domain.enums import BatchStatus
from quant_raas.domain.market import PriceBarRequest, PriceRequestItem
from quant_raas.domain.portfolio import CoverageList, CoverageMember
from quant_raas.domain.security import Security
from quant_raas.ingestion.prices import PriceIngestionService
from quant_raas.research.materiality import MaterialityScorer
from quant_raas.services.daily_research import DailyResearchRequest, DailyResearchService
from quant_raas.storage.repositories import (
    SqlAlchemyFeatureRepository,
    SqlAlchemyMarketDataRepository,
    SqlAlchemyPortfolioRepository,
    SqlAlchemyResearchRepository,
    SqlAlchemySecurityRepository,
)

pytestmark = pytest.mark.integration


@pytest.mark.point_in_time
def test_daily_pipeline_is_cutoff_safe_and_idempotent(
    sqlite_session: Session,
    sample_security: Security,
    fixed_now: datetime,
    materiality_scorer: MaterialityScorer,
) -> None:
    securities = SqlAlchemySecurityRepository(sqlite_session)
    portfolios = SqlAlchemyPortfolioRepository(sqlite_session)
    market_data = SqlAlchemyMarketDataRepository(sqlite_session)
    features = SqlAlchemyFeatureRepository(sqlite_session)
    research = SqlAlchemyResearchRepository(sqlite_session)
    securities.add_security(sample_security)

    coverage = CoverageList(
        coverage_list_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        name="Deterministic integration coverage",
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    portfolios.add_coverage_list(coverage)
    portfolios.add_coverage_members(
        [
            CoverageMember(
                membership_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
                coverage_list_id=coverage.coverage_list_id,
                security_id=sample_security.security_id,
                added_at=datetime(2020, 1, 1, tzinfo=UTC),
                source_identifier="EXAMPLE",
            )
        ]
    )

    sessions = pd.bdate_range(end="2024-01-09", periods=30)
    closes = [100.0 + index for index in range(len(sessions))]
    frame = pd.DataFrame(
        {
            "session_date": sessions,
            "open": [value - 0.25 for value in closes],
            "high": [value + 0.50 for value in closes],
            "low": [value - 0.50 for value in closes],
            "close": closes,
            "adjusted_close": closes,
            # A repeating volume pattern prevents a degenerate zero-variance
            # trailing window while remaining fully deterministic.
            "volume": [1_000.0 + 50.0 * (index % 7) for index in range(len(sessions))],
        }
    )
    provider = FixturePriceProvider({"EXAMPLE": frame}, clock=lambda: fixed_now)
    ingestion = PriceIngestionService(provider=provider, repository=market_data)
    ingestion_summary = ingestion.ingest(
        PriceBarRequest(
            items=(
                PriceRequestItem(
                    security_id=sample_security.security_id,
                    provider_identifier="EXAMPLE",
                ),
            ),
            start_date=date(2023, 11, 1),
            end_date=date(2024, 1, 9),
            requested_at=fixed_now - timedelta(minutes=1),
        )
    )
    assert ingestion_summary.bars_inserted == 30

    service = DailyResearchService(
        securities=securities,
        portfolios=portfolios,
        market_data=market_data,
        features=features,
        research=research,
        materiality=materiality_scorer,
        clock=lambda: fixed_now,
    )
    request = DailyResearchRequest(
        coverage_list_id=coverage.coverage_list_id,
        as_of=datetime(2024, 1, 9, tzinfo=UTC),
        data_cutoff_at=fixed_now,
        lookback_calendar_days=370,
        source="fixture",
        code_version="integration-test-v1",
        feature_config_version="equity-mvp-test-v1",
    )
    first = service.run(request, position_weights={sample_security.security_id: 0.04})
    second = service.run(request, position_weights={sample_security.security_id: 0.04})

    assert first.run.status == BatchStatus.SUCCEEDED
    assert first.failures == ()
    assert len(first.findings) == len(first.cards) == 1
    assert {
        "daily_return",
        "dollar_volume_zscore_20d",
        "realized_volatility_20d",
    }.issubset({feature.feature_name for feature in first.features})

    # Returns use adjusted close and the first observation is intentionally NaN.
    expected_daily_return = closes[-1] / closes[-2] - 1.0
    daily_feature = next(
        feature for feature in first.features if feature.feature_name == "daily_return"
    )
    assert daily_feature.value == pytest.approx(expected_daily_return)
    assert first.cards[0].context.contribution_bps == pytest.approx(
        0.04 * expected_daily_return * 10_000.0
    )
    assert all(feature.available_at <= request.data_cutoff_at for feature in first.features)
    assert all(finding.available_at <= request.data_cutoff_at for finding in first.findings)
    assert first.cards[0].evidence_ids

    # Stable natural keys make retries safe: the same request creates no new
    # logical run, finding, or card even though all calculations are repeated.
    assert second.run.research_run_id == first.run.research_run_id
    assert second.findings[0].finding_id == first.findings[0].finding_id
    assert second.cards[0].card_id == first.cards[0].card_id
    assert [card.card_id for card in research.cards_as_of(knowledge_time=fixed_now)] == [
        first.cards[0].card_id
    ]
