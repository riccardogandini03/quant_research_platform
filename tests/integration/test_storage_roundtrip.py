"""SQLite roundtrips exercise the same temporal repositories used by services."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from quant_raas.config import Settings
from quant_raas.domain.enums import BatchStatus
from quant_raas.domain.market import FeatureSnapshot, IngestionBatch, PriceBar
from quant_raas.domain.research import EvidenceReference, ResearchRun
from quant_raas.domain.security import Security, SecurityIdentifier
from quant_raas.research.cards import build_research_card
from quant_raas.research.findings import PriceResearchSnapshot, build_price_finding
from quant_raas.research.materiality import MaterialityScorer
from quant_raas.storage.repositories import (
    SqlAlchemyFeatureRepository,
    SqlAlchemyMarketDataRepository,
    SqlAlchemyResearchRepository,
    SqlAlchemySecurityRepository,
)
from quant_raas.storage.session import create_schema, create_session_factory, create_sql_engine

pytestmark = pytest.mark.integration


def test_in_memory_sqlite_schema_is_shared_across_api_threads() -> None:
    """An API worker must see schema created in the lifespan/caller thread."""

    engine = create_sql_engine(
        Settings(
            environment="test",
            database_url="sqlite+pysqlite:///:memory:",
            database_echo=False,
        )
    )
    try:
        create_schema(engine)
        factory = create_session_factory(engine)

        def read_from_request_thread() -> tuple[int, int]:
            with factory() as session:
                foreign_keys = session.scalar(text("PRAGMA foreign_keys"))
                security_count = session.scalar(text("SELECT count(*) FROM security"))
                return int(foreign_keys or 0), int(security_count or 0)

        with ThreadPoolExecutor(max_workers=1) as executor:
            foreign_keys, security_count = executor.submit(read_from_request_thread).result()

        assert isinstance(engine.pool, StaticPool)
        assert foreign_keys == 1
        assert security_count == 0
    finally:
        # check_same_thread=False also makes teardown safe outside the thread
        # that last checked out the shared in-memory connection.
        engine.dispose()


def _batch(batch_id: UUID, *, row_count: int, requested_at: datetime) -> IngestionBatch:
    return IngestionBatch(
        batch_id=batch_id,
        batch_key="fixture:roundtrip:2024-01-09",
        provider="fixture",
        dataset="daily_price_bar",
        requested_at=requested_at,
        started_at=requested_at,
        completed_at=requested_at + timedelta(seconds=1),
        status=BatchStatus.SUCCEEDED,
        request_fingerprint="12345678fixture",
        content_hash="abcdef12fixture",
        row_count=row_count,
    )


def _bar(
    *,
    bar_id: UUID,
    security_id: UUID,
    batch_id: UUID,
    available_at: datetime,
    ingested_at: datetime,
    close: float,
) -> PriceBar:
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    return PriceBar(
        price_bar_id=bar_id,
        security_id=security_id,
        session_date=date(2024, 1, 9),
        effective_at=effective,
        available_at=available_at,
        ingested_at=ingested_at,
        open=100.0,
        high=max(106.0, close),
        low=99.0,
        close=close,
        adjusted_close=close,
        volume=1_000.0,
        currency="USD",
        adjustment_factor=1.0,
        source="fixture",
        source_record_id="EXAMPLE:2024-01-09",
        provider_identifier="EXAMPLE",
        ingestion_batch_id=batch_id,
    )


@pytest.mark.point_in_time
def test_price_and_feature_repositories_return_latest_knowable_vintage(
    sqlite_session: Session,
    sample_security: Security,
    sample_identifier: SecurityIdentifier,
    ingestion_batch_id: UUID,
    research_run: ResearchRun,
) -> None:
    security_repository = SqlAlchemySecurityRepository(sqlite_session)
    security_repository.add_security(sample_security)
    security_repository.add_identifier(sample_identifier)
    research_repository = SqlAlchemyResearchRepository(sqlite_session)
    research_repository.add_run(research_run)

    market_repository = SqlAlchemyMarketDataRepository(sqlite_session)
    requested_at = datetime(2024, 1, 10, 10, 0, tzinfo=UTC)
    market_repository.add_ingestion_batch(
        _batch(ingestion_batch_id, row_count=2, requested_at=requested_at)
    )
    old_available = datetime(2024, 1, 9, 21, 5, tzinfo=UTC)
    revised_available = datetime(2024, 1, 10, 9, 0, tzinfo=UTC)
    old_bar = _bar(
        bar_id=UUID("01010101-0101-4101-8101-010101010101"),
        security_id=sample_security.security_id,
        batch_id=ingestion_batch_id,
        available_at=old_available,
        ingested_at=requested_at,
        close=100.0,
    )
    revised_bar = _bar(
        bar_id=UUID("02020202-0202-4202-8202-020202020202"),
        security_id=sample_security.security_id,
        batch_id=ingestion_batch_id,
        available_at=revised_available,
        ingested_at=requested_at,
        close=105.0,
    )
    assert market_repository.upsert_price_bars([old_bar, revised_bar]) == 2
    assert market_repository.upsert_price_bars([old_bar, revised_bar]) == 0

    effective = old_bar.effective_at
    before_revision = market_repository.price_history_as_of(
        [sample_security.security_id],
        start=effective,
        end=effective,
        knowledge_time=old_available,
    )
    after_revision = market_repository.price_history_as_of(
        [sample_security.security_id],
        start=effective,
        end=effective,
        knowledge_time=revised_available,
    )
    assert [bar.close for bar in before_revision] == [100.0]
    assert [bar.close for bar in after_revision] == [105.0]

    feature_repository = SqlAlchemyFeatureRepository(sqlite_session)
    old_feature = FeatureSnapshot(
        feature_snapshot_id=UUID("03030303-0303-4303-8303-030303030303"),
        security_id=sample_security.security_id,
        feature_name="return_1d",
        feature_version="v1",
        effective_at=effective,
        available_at=old_available,
        calculated_at=old_available + timedelta(minutes=1),
        value=0.01,
        unit="decimal_return",
        window="1d",
        research_run_id=research_run.research_run_id,
        code_version="test-code-v1",
        config_version="test-config-v1",
    )
    revised_feature = old_feature.model_copy(
        update={
            "feature_snapshot_id": UUID("04040404-0404-4404-8404-040404040404"),
            "available_at": revised_available,
            "calculated_at": revised_available + timedelta(minutes=1),
            "value": 0.05,
        }
    )
    assert feature_repository.upsert_many([old_feature, revised_feature]) == 2
    assert feature_repository.latest_as_of(
        sample_security.security_id,
        ["return_1d"],
        effective_at=effective,
        knowledge_time=old_available,
    )[0].value == pytest.approx(0.01)
    assert feature_repository.latest_as_of(
        sample_security.security_id,
        ["return_1d"],
        effective_at=effective,
        knowledge_time=revised_available,
    )[0].value == pytest.approx(0.05)


def test_research_repository_roundtrips_evidence_finding_and_card(
    sqlite_session: Session,
    sample_security: Security,
    sample_identifier: SecurityIdentifier,
    research_run: ResearchRun,
    evidence_reference: EvidenceReference,
    materiality_scorer: MaterialityScorer,
) -> None:
    securities = SqlAlchemySecurityRepository(sqlite_session)
    securities.add_security(sample_security)
    securities.add_identifier(sample_identifier)
    repository = SqlAlchemyResearchRepository(sqlite_session)
    repository.add_run(research_run)
    repository.add_evidence(evidence_reference)

    snapshot = PriceResearchSnapshot(
        security_id=sample_security.security_id,
        as_of=research_run.as_of,
        available_at=evidence_reference.available_at,
        created_at=research_run.started_at,
        daily_return=-0.04,
        residual_return=-0.03,
        residual_zscore=-3.0,
        volume_zscore=2.0,
        realized_volatility_20d=0.30,
        beta_126d=1.2,
        relative_return_sector_63d=-0.10,
        observations=252,
        evidence_ids=(evidence_reference.evidence_id,),
    )
    finding = build_price_finding(
        snapshot,
        research_run_id=research_run.research_run_id,
        scorer=materiality_scorer,
        position_weight=0.035,
    )
    repository.add_finding(finding)
    card = build_research_card(
        [finding],
        research_run_id=research_run.research_run_id,
        security_id=sample_security.security_id,
        as_of=research_run.as_of,
        data_cutoff_at=research_run.data_cutoff_at,
        created_at=research_run.started_at,
        position_weight=0.035,
        daily_return=-0.04,
    )
    repository.add_card(card)

    assert repository.cards_as_of(knowledge_time=card.created_at - timedelta(microseconds=1)) == ()
    stored = repository.cards_as_of(
        knowledge_time=card.created_at,
        security_id=sample_security.security_id,
    )
    assert len(stored) == 1
    assert stored[0].card_id == card.card_id
    assert stored[0].finding_ids == (finding.finding_id,)
    assert stored[0].evidence_ids == (evidence_reference.evidence_id,)
    assert stored[0].context.contribution_bps == pytest.approx(-14.0)

    # Natural keys make retries idempotent and avoid duplicate link-table rows.
    assert repository.add_finding(finding).finding_id == finding.finding_id
    assert repository.add_card(card).card_id == card.card_id
