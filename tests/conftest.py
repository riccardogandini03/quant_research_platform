"""Deterministic fixtures shared by unit and integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from quant_raas.config import Settings
from quant_raas.domain.enums import (
    BatchStatus,
    IdentifierScheme,
    InvalidationComparator,
    SourceType,
    ThesisDirection,
    ThesisRiskSeverity,
)
from quant_raas.domain.research import (
    EvidenceReference,
    ResearchRun,
    Thesis,
    ThesisContent,
    ThesisDriver,
    ThesisInvalidationRule,
    ThesisRisk,
    ThesisVersion,
)
from quant_raas.domain.security import Security, SecurityIdentifier
from quant_raas.research.materiality import MaterialityConfig, MaterialityScorer
from quant_raas.research.thesis import ThesisRelevanceConfig, ThesisRelevanceEvaluator
from quant_raas.storage.session import create_schema, create_session_factory, create_sql_engine

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixed_now() -> datetime:
    """A fixed instant later than every source timestamp in the basic fixtures."""

    return datetime(2024, 1, 10, 22, 0, tzinfo=UTC)


@pytest.fixture
def security_id() -> UUID:
    return UUID("11111111-1111-4111-8111-111111111111")


@pytest.fixture
def benchmark_id() -> UUID:
    return UUID("99999999-9999-4999-8999-999999999999")


@pytest.fixture
def research_run_id() -> UUID:
    return UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


@pytest.fixture
def ingestion_batch_id() -> UUID:
    return UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


@pytest.fixture
def sample_security(security_id: UUID) -> Security:
    created = datetime(2020, 1, 1, tzinfo=UTC)
    return Security(
        security_id=security_id,
        name="Example Corp",
        primary_currency="usd",
        exchange_mic="xnas",
        exchange_timezone="America/New_York",
        country_code="us",
        sector="Information Technology",
        created_at=created,
        updated_at=created,
    )


@pytest.fixture
def sample_identifier(security_id: UUID) -> SecurityIdentifier:
    return SecurityIdentifier(
        identifier_id=UUID("12121212-1212-4212-8212-121212121212"),
        security_id=security_id,
        scheme=IdentifierScheme.VENDOR,
        value="example us",
        provider="demo",
        exchange_mic="xnas",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        is_primary=True,
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def ohlcv_frame() -> pd.DataFrame:
    sessions = pd.bdate_range("2024-01-02", periods=6)
    effective = [
        datetime.combine(label.date(), datetime.min.time(), tzinfo=UTC) + timedelta(hours=21)
        for label in sessions
    ]
    return pd.DataFrame(
        {
            "session_date": sessions,
            "open": [99.0, 100.0, 101.0, 100.0, 102.0, 103.0],
            "high": [101.0, 102.0, 102.0, 103.0, 104.0, 105.0],
            "low": [98.0, 99.0, 98.0, 99.0, 101.0, 102.0],
            "close": [100.0, 101.0, 99.0, 102.0, 103.0, 104.0],
            "adjusted_close": [100.0, 101.0, 99.0, 102.0, 103.0, 104.0],
            "volume": [1_000.0, 1_100.0, 900.0, 1_300.0, 1_200.0, 1_400.0],
            "effective_at": effective,
            "available_at": [value + timedelta(minutes=5) for value in effective],
            "currency": ["USD"] * len(sessions),
        }
    )


@pytest.fixture
def sqlite_session() -> Iterator[Session]:
    """A fresh relational database with real foreign-key enforcement."""

    settings = Settings(
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        database_echo=False,
    )
    engine = create_sql_engine(settings)
    create_schema(engine)
    factory = create_session_factory(engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def materiality_config() -> MaterialityConfig:
    return MaterialityConfig.from_yaml(REPOSITORY_ROOT / "configs" / "materiality" / "default.yaml")


@pytest.fixture
def materiality_scorer(materiality_config: MaterialityConfig) -> MaterialityScorer:
    return MaterialityScorer(materiality_config)


@pytest.fixture
def thesis_content() -> ThesisContent:
    return ThesisContent(
        summary="Demand durability supports the long-term case.",
        drivers=(
            ThesisDriver(
                node_id="relative_strength",
                statement="Relative strength remains positive.",
                supporting_features=("relative_return_sector_63d",),
                direction=ThesisDirection.POSITIVE,
            ),
        ),
        risks=(
            ThesisRisk(
                node_id="volume_risk",
                statement="Distribution volume may signal weakening sponsorship.",
                watch_features=("dollar_volume_zscore_20d",),
                severity=ThesisRiskSeverity.MEDIUM,
            ),
        ),
        invalidation_rules=(
            ThesisInvalidationRule(
                node_id="relative_break",
                statement="Relative performance falls through the warning range.",
                feature_name="relative_return_sector_63d",
                comparator=InvalidationComparator.LESS_THAN_OR_EQUAL,
                warning_threshold=-0.05,
                breach_threshold=-0.20,
                unit="decimal_return",
            ),
        ),
    )


@pytest.fixture
def thesis(security_id: UUID) -> Thesis:
    return Thesis(
        thesis_id=UUID("71717171-7171-4717-8717-717171717171"),
        thesis_key="example_core",
        security_id=security_id,
        title="Example core thesis",
        created_by="pm@example.com",
        created_at=datetime(2024, 1, 5, tzinfo=UTC),
    )


@pytest.fixture
def thesis_version(thesis: Thesis, thesis_content: ThesisContent) -> ThesisVersion:
    return ThesisVersion(
        thesis_version_id=UUID("72727272-7272-4727-8727-727272727272"),
        thesis_id=thesis.thesis_id,
        version=1,
        valid_from=datetime(2024, 1, 5, tzinfo=UTC),
        content=thesis_content,
        authored_by="analyst@example.com",
        approved_by="pm@example.com",
        created_at=datetime(2024, 1, 5, tzinfo=UTC),
        approved_at=datetime(2024, 1, 5, tzinfo=UTC),
    )


@pytest.fixture
def thesis_relevance_config() -> ThesisRelevanceConfig:
    return ThesisRelevanceConfig.from_yaml(
        REPOSITORY_ROOT / "configs" / "thesis" / "relevance.yaml"
    )


@pytest.fixture
def thesis_relevance_evaluator(
    thesis_relevance_config: ThesisRelevanceConfig,
) -> ThesisRelevanceEvaluator:
    return ThesisRelevanceEvaluator(thesis_relevance_config)


@pytest.fixture
def research_run(research_run_id: UUID) -> ResearchRun:
    as_of = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    return ResearchRun(
        research_run_id=research_run_id,
        run_key="daily:2024-01-09",
        as_of=as_of,
        data_cutoff_at=as_of + timedelta(minutes=10),
        started_at=as_of + timedelta(minutes=11),
        completed_at=as_of + timedelta(minutes=12),
        status=BatchStatus.SUCCEEDED,
        code_version="test-code-v1",
        config_version="test-config-v1",
    )


@pytest.fixture
def evidence_reference() -> EvidenceReference:
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    return EvidenceReference(
        evidence_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        source_type=SourceType.MARKET_DATA,
        provider="fixture",
        source_record_id="EXAMPLE:2024-01-09",
        effective_at=effective,
        available_at=effective + timedelta(minutes=5),
        ingested_at=effective + timedelta(minutes=6),
    )
