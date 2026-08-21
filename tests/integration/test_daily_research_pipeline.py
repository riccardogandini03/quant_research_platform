"""Network-free integration of ingestion, daily research, and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid5

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_raas.connectors.fixture import FixturePriceProvider
from quant_raas.domain.enums import BatchStatus, ThesisRiskSeverity
from quant_raas.domain.market import FeatureSnapshot, PriceBarRequest, PriceRequestItem
from quant_raas.domain.portfolio import CoverageList, CoverageMember
from quant_raas.domain.research import Thesis, ThesisContent, ThesisRisk, ThesisVersion
from quant_raas.domain.security import Security
from quant_raas.ingestion.prices import PriceIngestionService
from quant_raas.research.materiality import MaterialityScorer
from quant_raas.research.thesis import ThesisRelevanceEvaluator
from quant_raas.services.daily_research import DailyResearchRequest, DailyResearchService
from quant_raas.storage.models import (
    FeatureSnapshotRecord,
    ResearchCardRecord,
    ResearchFindingRecord,
    ResearchRunRecord,
)
from quant_raas.storage.repositories import (
    SqlAlchemyFeatureRepository,
    SqlAlchemyMarketDataRepository,
    SqlAlchemyPortfolioRepository,
    SqlAlchemyResearchRepository,
    SqlAlchemySecurityRepository,
    SqlAlchemyThesisRepository,
)

pytestmark = pytest.mark.integration

AS_OF = datetime(2024, 1, 9, tzinfo=UTC)
ADDED_AT = datetime(2020, 1, 1, tzinfo=UTC)
OTHER_SECURITY_ID = UUID("22222222-2222-4222-8222-222222222222")
TEST_NAMESPACE = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


@dataclass(frozen=True, slots=True)
class _PipelineHarness:
    securities: SqlAlchemySecurityRepository
    portfolios: SqlAlchemyPortfolioRepository
    market_data: SqlAlchemyMarketDataRepository
    features: SqlAlchemyFeatureRepository
    theses: SqlAlchemyThesisRepository
    research: SqlAlchemyResearchRepository
    materiality: MaterialityScorer
    thesis_relevance: ThesisRelevanceEvaluator
    fixed_now: datetime

    def service(
        self,
        *,
        evaluator: ThesisRelevanceEvaluator | None = None,
        clock_at: datetime | None = None,
    ) -> DailyResearchService:
        return DailyResearchService(
            securities=self.securities,
            portfolios=self.portfolios,
            market_data=self.market_data,
            features=self.features,
            theses=self.theses,
            research=self.research,
            materiality=self.materiality,
            thesis_relevance=evaluator or self.thesis_relevance,
            clock=lambda: clock_at or self.fixed_now,
        )


def _pipeline_harness(
    session: Session,
    *,
    fixed_now: datetime,
    materiality: MaterialityScorer,
    thesis_relevance: ThesisRelevanceEvaluator,
) -> _PipelineHarness:
    return _PipelineHarness(
        securities=SqlAlchemySecurityRepository(session),
        portfolios=SqlAlchemyPortfolioRepository(session),
        market_data=SqlAlchemyMarketDataRepository(session),
        features=SqlAlchemyFeatureRepository(session),
        theses=SqlAlchemyThesisRepository(session),
        research=SqlAlchemyResearchRepository(session),
        materiality=materiality,
        thesis_relevance=thesis_relevance,
        fixed_now=fixed_now,
    )


def _price_frame() -> pd.DataFrame:
    sessions = pd.bdate_range(end="2024-01-09", periods=30)
    closes = [100.0 + index for index in range(len(sessions))]
    return pd.DataFrame(
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


def _ingest_prices(
    harness: _PipelineHarness,
    securities: tuple[Security, ...],
) -> None:
    frames = {security.name: _price_frame() for security in securities}
    provider = FixturePriceProvider(frames, clock=lambda: harness.fixed_now)
    summary = PriceIngestionService(provider=provider, repository=harness.market_data).ingest(
        PriceBarRequest(
            items=tuple(
                PriceRequestItem(
                    security_id=security.security_id,
                    provider_identifier=security.name,
                )
                for security in securities
            ),
            start_date=date(2023, 11, 1),
            end_date=date(2024, 1, 9),
            requested_at=harness.fixed_now - timedelta(minutes=1),
        )
    )
    assert summary.bars_inserted == 30 * len(securities)


def _persist_thesis(
    harness: _PipelineHarness,
    *,
    thesis_key: str,
    security_id: UUID,
    created_at: datetime,
    valid_from: datetime,
    approved_at: datetime,
    watch_features: tuple[str, ...] = ("dollar_volume_zscore_20d",),
) -> tuple[Thesis, ThesisVersion]:
    thesis = Thesis(
        thesis_id=uuid5(TEST_NAMESPACE, f"thesis:{thesis_key}"),
        thesis_key=thesis_key,
        security_id=security_id,
        title=f"{thesis_key} thesis",
        created_by="pm@example.com",
        created_at=created_at,
    )
    version = ThesisVersion(
        thesis_version_id=uuid5(TEST_NAMESPACE, f"version:{thesis_key}:1"),
        thesis_id=thesis.thesis_id,
        version=1,
        valid_from=valid_from,
        content=ThesisContent(
            summary=f"Explicit authored content for {thesis_key}.",
            risks=(
                ThesisRisk(
                    node_id="volume_risk",
                    statement="Distribution volume may weaken sponsorship.",
                    watch_features=watch_features,
                    severity=ThesisRiskSeverity.MEDIUM,
                ),
            ),
        ),
        authored_by="analyst@example.com",
        approved_by="pm@example.com",
        created_at=approved_at,
        approved_at=approved_at,
    )
    return harness.theses.add_thesis(thesis), harness.theses.add_version(
        version,
        expected_version=0,
    )


def _add_coverage(
    harness: _PipelineHarness,
    *,
    name: str,
    members: tuple[tuple[Security, str | None], ...],
) -> CoverageList:
    coverage = harness.portfolios.add_coverage_list(
        CoverageList(
            coverage_list_id=uuid5(TEST_NAMESPACE, f"coverage:{name}"),
            name=name,
            created_at=ADDED_AT,
        )
    )
    harness.portfolios.add_coverage_members(
        CoverageMember(
            membership_id=uuid5(
                TEST_NAMESPACE,
                f"member:{name}:{security.security_id}:{thesis_key}",
            ),
            coverage_list_id=coverage.coverage_list_id,
            security_id=security.security_id,
            added_at=ADDED_AT,
            thesis_id=thesis_key,
            source_identifier=security.name,
        )
        for security, thesis_key in members
    )
    return coverage


def _request(
    coverage: CoverageList,
    *,
    cutoff: datetime,
    feature_config_version: str = "equity-mvp-test-v1",
) -> DailyResearchRequest:
    return DailyResearchRequest(
        coverage_list_id=coverage.coverage_list_id,
        as_of=AS_OF,
        data_cutoff_at=cutoff,
        lookback_calendar_days=370,
        source="fixture",
        code_version="integration-test-v1",
        feature_config_version=feature_config_version,
    )


def _assert_stored_feature_matches(
    record: FeatureSnapshotRecord,
    snapshot: FeatureSnapshot,
) -> None:
    payload = snapshot.model_dump(mode="json")
    assert record.feature_snapshot_id == snapshot.feature_snapshot_id
    assert record.security_id == snapshot.security_id
    assert record.feature_name == snapshot.feature_name
    assert record.feature_version == snapshot.feature_version
    assert record.effective_at == snapshot.effective_at
    assert record.available_at == snapshot.available_at
    assert record.calculated_at == snapshot.calculated_at
    assert type(record.value) is type(payload["value"])
    assert record.value == payload["value"]
    assert record.unit == snapshot.unit
    assert record.window == snapshot.window
    assert record.quality_flags == payload["quality_flags"]
    assert record.input_evidence_ids == payload["input_evidence_ids"]
    assert record.research_run_id == snapshot.research_run_id
    assert record.code_version == snapshot.code_version
    assert record.config_version == snapshot.config_version
    assert record.metadata_json == payload["metadata"]


@pytest.mark.point_in_time
def test_daily_pipeline_without_thesis_is_cutoff_safe_and_idempotent(
    sqlite_session: Session,
    sample_security: Security,
    fixed_now: datetime,
    materiality_scorer: MaterialityScorer,
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
) -> None:
    harness = _pipeline_harness(
        sqlite_session,
        fixed_now=fixed_now,
        materiality=materiality_scorer,
        thesis_relevance=thesis_relevance_evaluator,
    )
    harness.securities.add_security(sample_security)
    coverage = _add_coverage(
        harness,
        name="Deterministic integration coverage",
        members=((sample_security, None),),
    )
    _ingest_prices(harness, (sample_security,))

    request = _request(coverage, cutoff=fixed_now)
    first = harness.service().run(
        request,
        position_weights={sample_security.security_id: 0.04},
    )
    second = harness.service().run(
        request,
        position_weights={sample_security.security_id: 0.04},
    )

    assert first.run.status == BatchStatus.SUCCEEDED
    assert first.failures == ()
    assert len(first.findings) == len(first.cards) == 1
    assert {
        "daily_return",
        "dollar_volume_zscore_20d",
        "realized_volatility_20d",
    }.issubset({feature.feature_name for feature in first.features})

    closes = [100.0 + index for index in range(30)]
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
    assert first.findings[0].thesis_relevance is None
    assert "thesis_relevance" not in first.findings[0].score.component_scores
    assert first.findings[0].score.completeness == pytest.approx(0.20)
    assert first.cards[0].thesis_version_id is None

    assert second.run.research_run_id == first.run.research_run_id
    assert second.findings[0].finding_id == first.findings[0].finding_id
    assert second.cards[0].card_id == first.cards[0].card_id
    assert [card.card_id for card in harness.research.cards_as_of(knowledge_time=fixed_now)] == [
        first.cards[0].card_id
    ]


@pytest.mark.point_in_time
def test_daily_pipeline_assesses_selected_thesis_with_stored_feature_lineage(
    sqlite_session: Session,
    sample_security: Security,
    fixed_now: datetime,
    materiality_scorer: MaterialityScorer,
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
) -> None:
    harness = _pipeline_harness(
        sqlite_session,
        fixed_now=fixed_now,
        materiality=materiality_scorer,
        thesis_relevance=thesis_relevance_evaluator,
    )
    harness.securities.add_security(sample_security)
    _, thesis_version = _persist_thesis(
        harness,
        thesis_key="example_core",
        security_id=sample_security.security_id,
        created_at=AS_OF - timedelta(days=5),
        valid_from=AS_OF - timedelta(days=5),
        approved_at=AS_OF - timedelta(days=5),
    )
    coverage = _add_coverage(
        harness,
        name="Thesis-aware coverage",
        members=((sample_security, "example_core"),),
    )
    _ingest_prices(harness, (sample_security,))
    request = _request(coverage, cutoff=fixed_now)

    first = harness.service().run(request)
    second = harness.service().run(request)

    assessment = first.findings[0].thesis_relevance
    assert assessment is not None
    assert assessment.thesis_version_id == thesis_version.thesis_version_id
    assert assessment.method_version == thesis_relevance_evaluator.config.method_version
    assert first.findings[0].score.component_scores["thesis_relevance"] == pytest.approx(
        assessment.score
    )
    assert first.cards[0].thesis_version_id == thesis_version.thesis_version_id
    assert first.cards[0].thesis_impact == assessment.impact
    assert first.cards[0].thesis_node_id == assessment.primary_node_id

    stored_volume = harness.features.latest_as_of(
        sample_security.security_id,
        ["dollar_volume_zscore_20d"],
        effective_at=AS_OF,
        knowledge_time=fixed_now,
    )[0]
    volume_contribution = next(
        contribution
        for contribution in assessment.contributions
        if contribution.node_id == "volume_risk"
    )
    assert volume_contribution.feature_snapshot_ids == (stored_volume.feature_snapshot_id,)
    assert assessment.score == pytest.approx(min(abs(float(stored_volume.value)) / 4.0, 1.0))

    assert second.run.research_run_id == first.run.research_run_id
    assert second.features == first.features
    assert second.findings[0].finding_id == first.findings[0].finding_id
    assert second.cards[0].card_id == first.cards[0].card_id
    assert second.findings[0].thesis_relevance is not None
    assert second.findings[0].thesis_relevance.model_dump(mode="json") == assessment.model_dump(
        mode="json"
    )


@pytest.mark.point_in_time
def test_daily_pipeline_retry_reuses_persisted_operational_timestamps(
    sqlite_session: Session,
    sample_security: Security,
    fixed_now: datetime,
    materiality_scorer: MaterialityScorer,
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
) -> None:
    harness = _pipeline_harness(
        sqlite_session,
        fixed_now=fixed_now,
        materiality=materiality_scorer,
        thesis_relevance=thesis_relevance_evaluator,
    )
    harness.securities.add_security(sample_security)
    _persist_thesis(
        harness,
        thesis_key="clock_retry_core",
        security_id=sample_security.security_id,
        created_at=AS_OF - timedelta(days=5),
        valid_from=AS_OF - timedelta(days=5),
        approved_at=AS_OF - timedelta(days=5),
    )
    coverage = _add_coverage(
        harness,
        name="Clock-advanced retry coverage",
        members=((sample_security, "clock_retry_core"),),
    )
    _ingest_prices(harness, (sample_security,))
    request = _request(coverage, cutoff=fixed_now)

    first = harness.service(clock_at=fixed_now).run(request)
    later = harness.service(clock_at=fixed_now + timedelta(seconds=1)).run(request)

    assert later == first
    assert later.run.started_at == first.run.started_at == fixed_now
    assert later.run.completed_at == first.run.completed_at == fixed_now
    assert later.findings[0].thesis_relevance is not None
    assert later.findings[0].thesis_relevance == first.findings[0].thesis_relevance
    assert sqlite_session.scalar(select(func.count()).select_from(ResearchRunRecord)) == 1
    assert sqlite_session.scalar(select(func.count()).select_from(FeatureSnapshotRecord)) == len(
        first.features
    )
    assert sqlite_session.scalar(select(func.count()).select_from(ResearchFindingRecord)) == 1
    assert sqlite_session.scalar(select(func.count()).select_from(ResearchCardRecord)) == 1
    assert harness.research.run_by_key(first.run.run_key) == first.run

    stored = sqlite_session.scalars(
        select(FeatureSnapshotRecord).where(
            FeatureSnapshotRecord.research_run_id == first.run.research_run_id
        )
    ).all()
    assert {row.feature_snapshot_id for row in stored} == {
        feature.feature_snapshot_id for feature in first.features
    }
    returned = {feature.feature_snapshot_id: feature for feature in later.features}
    for row in stored:
        _assert_stored_feature_matches(row, returned[row.feature_snapshot_id])


def test_selected_thesis_without_overlap_adds_explicit_zero_component(
    sqlite_session: Session,
    sample_security: Security,
    fixed_now: datetime,
    materiality_scorer: MaterialityScorer,
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
) -> None:
    harness = _pipeline_harness(
        sqlite_session,
        fixed_now=fixed_now,
        materiality=materiality_scorer,
        thesis_relevance=thesis_relevance_evaluator,
    )
    harness.securities.add_security(sample_security)
    _, thesis_version = _persist_thesis(
        harness,
        thesis_key="planned_fundamental",
        security_id=sample_security.security_id,
        created_at=AS_OF - timedelta(days=5),
        valid_from=AS_OF - timedelta(days=5),
        approved_at=AS_OF - timedelta(days=5),
        watch_features=("planned_fundamental_feature",),
    )
    coverage = _add_coverage(
        harness,
        name="No-overlap thesis coverage",
        members=((sample_security, "planned_fundamental"),),
    )
    _ingest_prices(harness, (sample_security,))

    result = harness.service().run(_request(coverage, cutoff=fixed_now))

    assessment = result.findings[0].thesis_relevance
    assert assessment is not None
    assert assessment.thesis_version_id == thesis_version.thesis_version_id
    assert assessment.score == 0.0
    assert result.findings[0].score.component_scores["thesis_relevance"] == 0.0
    assert result.findings[0].score.completeness == pytest.approx(0.20 + 0.15)
    assert result.cards[0].thesis_version_id == thesis_version.thesis_version_id
    assert result.cards[0].thesis_node_ids == ()


@pytest.mark.point_in_time
def test_version_approved_after_knowledge_cutoff_is_excluded(
    sqlite_session: Session,
    sample_security: Security,
    fixed_now: datetime,
    materiality_scorer: MaterialityScorer,
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
) -> None:
    harness = _pipeline_harness(
        sqlite_session,
        fixed_now=fixed_now,
        materiality=materiality_scorer,
        thesis_relevance=thesis_relevance_evaluator,
    )
    harness.securities.add_security(sample_security)
    thesis, selected_version = _persist_thesis(
        harness,
        thesis_key="cutoff_core",
        security_id=sample_security.security_id,
        created_at=AS_OF - timedelta(days=5),
        valid_from=AS_OF - timedelta(days=5),
        approved_at=AS_OF - timedelta(days=5),
    )
    future_version = ThesisVersion(
        thesis_version_id=uuid5(TEST_NAMESPACE, "version:cutoff_core:2"),
        thesis_id=thesis.thesis_id,
        version=2,
        valid_from=AS_OF - timedelta(days=1),
        content=ThesisContent(
            summary="This version was not yet known.",
            risks=(
                ThesisRisk(
                    node_id="future_risk",
                    statement="Future-only content must not leak.",
                    watch_features=("planned_future_feature",),
                    severity=ThesisRiskSeverity.HIGH,
                ),
            ),
        ),
        authored_by="analyst@example.com",
        approved_by="pm@example.com",
        created_at=fixed_now + timedelta(minutes=1),
        approved_at=fixed_now + timedelta(minutes=1),
    )
    harness.theses.add_version(future_version, expected_version=1)
    coverage = _add_coverage(
        harness,
        name="Knowledge-cutoff coverage",
        members=((sample_security, "cutoff_core"),),
    )
    _ingest_prices(harness, (sample_security,))

    result = harness.service().run(_request(coverage, cutoff=fixed_now))

    assessment = result.findings[0].thesis_relevance
    assert assessment is not None
    assert assessment.thesis_version_id == selected_version.thesis_version_id
    assert assessment.thesis_version_id != future_version.thesis_version_id
    assert {item.node_id for item in assessment.contributions} == {"volume_risk"}


@pytest.mark.point_in_time
@pytest.mark.parametrize(
    ("invalid_kind", "expected_message"),
    [
        ("unknown", "invalid thesis reference 'unknown_core'"),
        ("cross_security", "invalid thesis reference 'cross_security_core'"),
        ("archived", "archived_at_cutoff"),
        ("not_approved", "not_yet_approved"),
        ("not_effective", "not_yet_effective"),
    ],
)
def test_invalid_explicit_thesis_reference_is_isolated_per_security(
    invalid_kind: str,
    expected_message: str,
    sqlite_session: Session,
    sample_security: Security,
    fixed_now: datetime,
    materiality_scorer: MaterialityScorer,
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
) -> None:
    harness = _pipeline_harness(
        sqlite_session,
        fixed_now=fixed_now,
        materiality=materiality_scorer,
        thesis_relevance=thesis_relevance_evaluator,
    )
    invalid_security = sample_security.model_copy(
        update={"security_id": OTHER_SECURITY_ID, "name": "INVALID"}
    )
    harness.securities.add_security(sample_security)
    harness.securities.add_security(invalid_security)
    _persist_thesis(
        harness,
        thesis_key="valid_core",
        security_id=sample_security.security_id,
        created_at=AS_OF - timedelta(days=5),
        valid_from=AS_OF - timedelta(days=5),
        approved_at=AS_OF - timedelta(days=5),
    )

    invalid_key = f"{invalid_kind}_core"
    if invalid_kind == "cross_security":
        _persist_thesis(
            harness,
            thesis_key=invalid_key,
            security_id=sample_security.security_id,
            created_at=AS_OF - timedelta(days=5),
            valid_from=AS_OF - timedelta(days=5),
            approved_at=AS_OF - timedelta(days=5),
        )
    elif invalid_kind != "unknown":
        invalid_approval = (
            fixed_now + timedelta(minutes=1)
            if invalid_kind == "not_approved"
            else AS_OF - timedelta(days=5)
        )
        invalid_activation = (
            AS_OF + timedelta(days=1)
            if invalid_kind == "not_effective"
            else AS_OF - timedelta(days=5)
        )
        invalid_thesis, _ = _persist_thesis(
            harness,
            thesis_key=invalid_key,
            security_id=invalid_security.security_id,
            created_at=AS_OF - timedelta(days=5),
            valid_from=invalid_activation,
            approved_at=invalid_approval,
        )
        if invalid_kind == "archived":
            harness.theses.archive(
                invalid_thesis.thesis_id,
                archived_at=fixed_now - timedelta(minutes=1),
                archived_by="pm@example.com",
            )

    coverage = _add_coverage(
        harness,
        name=f"Partial {invalid_kind} coverage",
        members=(
            (sample_security, "valid_core"),
            (invalid_security, invalid_key),
        ),
    )
    _ingest_prices(harness, (sample_security, invalid_security))

    result = harness.service().run(_request(coverage, cutoff=fixed_now))

    assert result.run.status == BatchStatus.PARTIAL
    assert {finding.security_id for finding in result.findings} == {sample_security.security_id}
    assert {card.security_id for card in result.cards} == {sample_security.security_id}
    assert len(result.failures) == 1
    assert result.failures[0].security_id == invalid_security.security_id
    assert expected_message in result.failures[0].message
    assert result.findings[0].thesis_relevance is not None


def test_thesis_method_version_changes_immutable_run_lineage(
    sqlite_session: Session,
    sample_security: Security,
    fixed_now: datetime,
    materiality_scorer: MaterialityScorer,
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
) -> None:
    harness = _pipeline_harness(
        sqlite_session,
        fixed_now=fixed_now,
        materiality=materiality_scorer,
        thesis_relevance=thesis_relevance_evaluator,
    )
    harness.securities.add_security(sample_security)
    _persist_thesis(
        harness,
        thesis_key="method_core",
        security_id=sample_security.security_id,
        created_at=AS_OF - timedelta(days=5),
        valid_from=AS_OF - timedelta(days=5),
        approved_at=AS_OF - timedelta(days=5),
    )
    coverage = _add_coverage(
        harness,
        name="Method-lineage coverage",
        members=((sample_security, "method_core"),),
    )
    _ingest_prices(harness, (sample_security,))
    feature_config_version = "f" * 80
    request = _request(
        coverage,
        cutoff=fixed_now,
        feature_config_version=feature_config_version,
    )
    first = harness.service().run(request)
    changed_evaluator = ThesisRelevanceEvaluator(
        thesis_relevance_evaluator.config.model_copy(update={"method_version": "m" * 80})
    )

    changed = harness.service(evaluator=changed_evaluator).run(request)

    assert first.run.research_run_id != changed.run.research_run_id
    assert first.findings[0].finding_id != changed.findings[0].finding_id
    assert first.cards[0].card_id != changed.cards[0].card_id
    assert {feature.feature_snapshot_id for feature in first.features}.isdisjoint(
        feature.feature_snapshot_id for feature in changed.features
    )
    assert first.run.config_version.startswith("bundle:")
    assert changed.run.config_version.startswith("bundle:")
    assert len(first.run.config_version) == len(changed.run.config_version) == 71
    assert first.run.config_version != changed.run.config_version
    assert {feature.config_version for feature in first.features} == {feature_config_version}
    assert {feature.config_version for feature in changed.features} == {feature_config_version}
    assert changed.findings[0].thesis_relevance is not None
    assert changed.findings[0].thesis_relevance.method_version == "m" * 80
    assert {card.card_id for card in harness.research.cards_as_of(knowledge_time=fixed_now)} == {
        first.cards[0].card_id,
        changed.cards[0].card_id,
    }
    for result in (first, changed):
        assessment = result.findings[0].thesis_relevance
        assert assessment is not None
        returned_ids = {feature.feature_snapshot_id for feature in result.features}
        assessment_ids = {
            feature_snapshot_id
            for contribution in assessment.contributions
            for feature_snapshot_id in contribution.feature_snapshot_ids
        }
        referenced_ids = returned_ids | assessment_ids
        stored = sqlite_session.scalars(
            select(FeatureSnapshotRecord).where(
                FeatureSnapshotRecord.feature_snapshot_id.in_(referenced_ids)
            )
        ).all()
        assert {row.feature_snapshot_id: row.research_run_id for row in stored} == dict.fromkeys(
            referenced_ids, result.run.research_run_id
        )
