"""Reproducible end-of-day quantitative research pipeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from uuid import UUID

import pandas as pd

from quant_raas.common.clock import ensure_utc, utc_now
from quant_raas.common.errors import QuantRaasError, RepositoryConflictError
from quant_raas.domain.enums import BatchStatus, BenchmarkKind
from quant_raas.domain.market import FeatureSnapshot, PriceBar
from quant_raas.domain.portfolio import CoverageMember
from quant_raas.domain.protocols import (
    FeatureRepository,
    MarketDataRepository,
    PortfolioRepository,
    ResearchRepository,
    SecurityRepository,
    ThesisRepository,
)
from quant_raas.domain.research import (
    EvidenceReference,
    ResearchCard,
    ResearchFinding,
    ResearchRun,
    ThesisRelevanceAssessment,
    ThesisSignal,
)
from quant_raas.quant.anomalies import fit_abnormal_return_model, volume_zscore
from quant_raas.quant.factors import rolling_beta
from quant_raas.quant.returns import relative_return, rolling_total_return, simple_returns
from quant_raas.quant.risk import rolling_volatility
from quant_raas.research.cards import build_research_card
from quant_raas.research.evidence import price_bar_evidence
from quant_raas.research.findings import (
    PriceResearchSnapshot,
    build_price_finding,
    price_signal_strengths,
)
from quant_raas.research.ids import stable_research_id
from quant_raas.research.materiality import MaterialityScorer
from quant_raas.research.thesis import ThesisRelevanceEvaluator


@dataclass(frozen=True, slots=True)
class DailyResearchRequest:
    coverage_list_id: UUID
    as_of: datetime
    data_cutoff_at: datetime
    lookback_calendar_days: int = 550
    source: str = "fixture"
    code_version: str = "working-tree"
    feature_config_version: str = "equity-mvp-v0"

    def __post_init__(self) -> None:
        as_of = ensure_utc(self.as_of)
        cutoff = ensure_utc(self.data_cutoff_at)
        if cutoff < as_of:
            raise ValueError("data_cutoff_at cannot precede as_of")
        if self.lookback_calendar_days < 370:
            raise ValueError("daily research requires at least 370 calendar days of lookback")
        if not self.source.strip():
            raise ValueError("source cannot be empty")


@dataclass(frozen=True, slots=True)
class SecurityResearchFailure:
    security_id: UUID
    message: str


@dataclass(frozen=True, slots=True)
class DailyResearchResult:
    run: ResearchRun
    findings: tuple[ResearchFinding, ...]
    cards: tuple[ResearchCard, ...]
    features: tuple[FeatureSnapshot, ...]
    failures: tuple[SecurityResearchFailure, ...]


@dataclass(frozen=True, slots=True)
class _SecurityCalculation:
    snapshot: PriceResearchSnapshot
    features: tuple[FeatureSnapshot, ...]
    evidence: tuple[EvidenceReference, ...]
    daily_return: float | None
    benchmark_return: float | None
    sector_return: float | None


class DailyResearchService:
    """Calculate one price/risk card per covered security with usable data."""

    def __init__(
        self,
        *,
        securities: SecurityRepository,
        portfolios: PortfolioRepository,
        market_data: MarketDataRepository,
        features: FeatureRepository,
        theses: ThesisRepository,
        research: ResearchRepository,
        materiality: MaterialityScorer,
        thesis_relevance: ThesisRelevanceEvaluator,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.securities = securities
        self.portfolios = portfolios
        self.market_data = market_data
        self.feature_repository = features
        self.thesis_repository = theses
        self.research_repository = research
        self.materiality = materiality
        self.thesis_relevance = thesis_relevance
        self.clock = clock

    def run(
        self,
        request: DailyResearchRequest,
        *,
        position_weights: Mapping[UUID, float] | None = None,
    ) -> DailyResearchResult:
        as_of = ensure_utc(request.as_of)
        cutoff = ensure_utc(request.data_cutoff_at)
        members = tuple(
            self.portfolios.active_coverage_members(request.coverage_list_id, as_of=as_of)
        )
        if not members:
            raise ValueError("coverage list has no active members at as_of")

        benchmark_map = self._resolve_benchmarks(members, as_of=as_of)
        requested_ids = {member.security_id for member in members}
        requested_ids.update(
            benchmark_id
            for mappings in benchmark_map.values()
            for benchmark_id in mappings.values()
            if benchmark_id is not None
        )
        bars = self.market_data.price_history_as_of(
            sorted(requested_ids, key=str),
            start=as_of - timedelta(days=request.lookback_calendar_days),
            end=as_of,
            knowledge_time=cutoff,
            source=request.source,
        )
        by_security = _group_bars(bars)
        batch_ids = tuple(sorted({bar.ingestion_batch_id for bar in bars}, key=str))
        thesis_method_version = self.thesis_relevance.config.method_version
        materiality_score_version = self.materiality.config.score_version
        weights = dict(position_weights or {})
        run_key = _run_key(
            request,
            batch_ids,
            thesis_method_version=thesis_method_version,
            materiality_score_version=materiality_score_version,
            position_weights=position_weights,
            covered_security_ids=tuple(member.security_id for member in members),
        )
        run_id = stable_research_id("run", run_key)
        run_config_version = _run_config_version(
            request.feature_config_version,
            thesis_method_version,
            materiality_score_version,
        )
        existing_run = self.research_repository.run_by_key(run_key)
        if existing_run is None:
            started_at = max(ensure_utc(self.clock()), cutoff)
        else:
            _validate_reusable_run(
                existing_run,
                research_run_id=run_id,
                run_key=run_key,
                as_of=as_of,
                data_cutoff_at=cutoff,
                code_version=request.code_version,
                config_version=run_config_version,
                ingestion_batch_ids=batch_ids,
            )
            started_at = existing_run.started_at

        calculations: list[
            tuple[CoverageMember, _SecurityCalculation, ThesisRelevanceAssessment | None]
        ] = []
        failures: list[SecurityResearchFailure] = []
        for member in members:
            try:
                calculation = self._calculate_security(
                    member,
                    bars_by_security=by_security,
                    benchmarks=benchmark_map[member.security_id],
                    research_run_id=run_id,
                    calculated_at=started_at,
                    code_version=request.code_version,
                    config_version=request.feature_config_version,
                )
                assessment = self._assess_thesis(
                    member,
                    calculation,
                    effective_at=as_of,
                    knowledge_time=cutoff,
                )
                calculations.append((member, calculation, assessment))
            except (QuantRaasError, ValueError, ArithmeticError) as error:
                failures.append(SecurityResearchFailure(member.security_id, str(error)))

        findings: list[ResearchFinding] = []
        cards: list[ResearchCard] = []
        feature_snapshots: list[FeatureSnapshot] = []
        evidence_by_id: dict[UUID, EvidenceReference] = {}
        for member, calculation, assessment in calculations:
            finding = build_price_finding(
                calculation.snapshot,
                research_run_id=run_id,
                scorer=self.materiality,
                position_weight=weights.get(member.security_id),
                thesis_assessment=assessment,
            )
            card = build_research_card(
                [finding],
                research_run_id=run_id,
                security_id=member.security_id,
                as_of=calculation.snapshot.as_of,
                data_cutoff_at=cutoff,
                created_at=started_at,
                position_weight=weights.get(member.security_id),
                daily_return=calculation.daily_return,
                benchmark_return=calculation.benchmark_return,
                sector_return=calculation.sector_return,
            )
            findings.append(finding)
            cards.append(card)
            feature_snapshots.extend(calculation.features)
            evidence_by_id.update({item.evidence_id: item for item in calculation.evidence})

        completed_at = (
            max(ensure_utc(self.clock()), started_at)
            if existing_run is None
            else existing_run.completed_at
        )
        status = (
            BatchStatus.FAILED
            if not cards
            else BatchStatus.PARTIAL
            if failures
            else BatchStatus.SUCCEEDED
        )
        run = ResearchRun(
            research_run_id=run_id,
            run_key=run_key,
            as_of=as_of,
            data_cutoff_at=cutoff,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            code_version=request.code_version,
            config_version=run_config_version,
            ingestion_batch_ids=batch_ids,
            error_message=(
                "; ".join(f"{failure.security_id}: {failure.message}" for failure in failures)[
                    :4000
                ]
                if failures
                else None
            ),
        )

        # Repositories flush but do not commit; the caller's session scope makes
        # the run, features, findings, and cards one atomic transaction.
        persisted_run = self.research_repository.add_run(run)
        for evidence in sorted(evidence_by_id.values(), key=lambda item: str(item.evidence_id)):
            self.research_repository.add_evidence(evidence)
        self.feature_repository.upsert_many(feature_snapshots)
        persisted_findings = tuple(self.research_repository.add_finding(item) for item in findings)
        persisted_cards = tuple(self.research_repository.add_card(item) for item in cards)
        return DailyResearchResult(
            run=persisted_run,
            findings=persisted_findings,
            cards=persisted_cards,
            features=tuple(feature_snapshots),
            failures=tuple(failures),
        )

    def _resolve_benchmarks(
        self,
        members: Sequence[CoverageMember],
        *,
        as_of: datetime,
    ) -> dict[UUID, dict[str, UUID | None]]:
        result: dict[UUID, dict[str, UUID | None]] = {}
        for member in members:
            market = self.securities.benchmark_as_of(
                member.security_id, BenchmarkKind.MARKET, as_of=as_of
            )
            sector = self.securities.benchmark_as_of(
                member.security_id, BenchmarkKind.SECTOR, as_of=as_of
            )
            result[member.security_id] = {
                "market": market.benchmark_security_id if market else None,
                "sector": (
                    sector.benchmark_security_id if sector else member.benchmark_security_id
                ),
            }
        return result

    def _assess_thesis(
        self,
        member: CoverageMember,
        calculation: _SecurityCalculation,
        *,
        effective_at: datetime,
        knowledge_time: datetime,
    ) -> ThesisRelevanceAssessment | None:
        if member.thesis_id is None:
            return None
        thesis = self.thesis_repository.get_by_key(member.thesis_id)
        if thesis is None or thesis.security_id != member.security_id:
            raise ValueError(f"invalid thesis reference {member.thesis_id!r}")
        selection = self.thesis_repository.version_as_of(
            thesis,
            effective_at=effective_at,
            knowledge_time=knowledge_time,
        )
        if selection.version is None:
            raise ValueError(f"thesis {member.thesis_id!r} is {selection.status.value} at cutoff")
        strengths = price_signal_strengths(calculation.snapshot)
        by_name = {feature.feature_name: feature for feature in calculation.features}
        signals = tuple(
            ThesisSignal(
                feature_name=name,
                raw_value=float(by_name[name].value),
                normalized_strength=strength,
                feature_snapshot_id=by_name[name].feature_snapshot_id,
                unit=by_name[name].unit,
            )
            for name, strength in sorted(strengths.items())
            if name in by_name
            and isinstance(by_name[name].value, (int, float))
            and not isinstance(by_name[name].value, bool)
            and isfinite(float(by_name[name].value))
        )
        return self.thesis_relevance.assess(
            selection.version,
            signals=signals,
            features=calculation.features,
        )

    def _calculate_security(
        self,
        member: CoverageMember,
        *,
        bars_by_security: Mapping[UUID, tuple[PriceBar, ...]],
        benchmarks: Mapping[str, UUID | None],
        research_run_id: UUID,
        calculated_at: datetime,
        code_version: str,
        config_version: str,
    ) -> _SecurityCalculation:
        asset_bars = bars_by_security.get(member.security_id, ())
        if len(asset_bars) < 21:
            raise ValueError(
                f"insufficient price history: {len(asset_bars)} bars; need at least 21"
            )
        asset = _bars_frame(asset_bars)
        asset_returns = simple_returns(asset["adjusted_close"])

        factor_returns: dict[str, pd.Series] = {}
        benchmark_frames: dict[str, pd.DataFrame] = {}
        seen_benchmark_ids: set[UUID] = set()
        for kind in ("market", "sector"):
            benchmark_id = benchmarks.get(kind)
            if (
                benchmark_id is None
                or benchmark_id == member.security_id
                or benchmark_id in seen_benchmark_ids
            ):
                continue
            frame = _bars_frame(bars_by_security.get(benchmark_id, ()))
            if frame.empty:
                continue
            benchmark_frames[kind] = frame
            factor_returns[kind] = simple_returns(frame["adjusted_close"]).reindex(asset.index)
            seen_benchmark_ids.add(benchmark_id)

        residual_return: float | None = None
        residual_zscore: float | None = None
        if factor_returns and len(asset_returns.dropna()) >= 63:
            factors = pd.DataFrame(factor_returns, index=asset.index)
            abnormal = fit_abnormal_return_model(
                asset_returns,
                factors,
                window=126,
                minimum_observations=63,
            )
            residual_return = _last_finite(abnormal.residual_return)
            residual_zscore = _last_finite(abnormal.abnormal_score)

        dollar_volume = asset["close"] * asset["volume"]
        dollar_volume_zscore = _last_finite(
            volume_zscore(dollar_volume, window=20, min_periods=20, lag=1)
        )
        volatility = _last_finite(rolling_volatility(asset_returns, window=20, min_periods=20))

        market_returns = factor_returns.get("market")
        if market_returns is None:
            market_returns = factor_returns.get("sector")
        beta = (
            _last_finite(
                rolling_beta(
                    asset_returns,
                    market_returns,
                    window=126,
                    minimum_observations=63,
                    lag=1,
                )
            )
            if market_returns is not None and len(asset_returns.dropna()) >= 63
            else None
        )
        sector_returns = factor_returns.get("sector")
        relative_63d = (
            _last_finite(
                rolling_total_return(
                    relative_return(asset_returns, sector_returns),
                    window=63,
                    min_periods=63,
                )
            )
            if sector_returns is not None
            else None
        )
        daily_return = _last_finite(asset_returns)
        market_daily = (
            _last_at(market_returns, asset.index[-1]) if market_returns is not None else None
        )
        sector_daily = (
            _last_at(sector_returns, asset.index[-1]) if sector_returns is not None else None
        )

        all_input_bars = list(asset_bars)
        for frame_kind, benchmark_id in benchmarks.items():
            if frame_kind in benchmark_frames and benchmark_id is not None:
                all_input_bars.extend(bars_by_security.get(benchmark_id, ()))
        all_input_bars = list(
            {
                (bar.security_id, bar.source_record_id, bar.available_at): bar
                for bar in all_input_bars
            }.values()
        )
        evidence = tuple(_evidence_from_bar(bar) for bar in all_input_bars)
        evidence_ids = tuple(item.evidence_id for item in evidence)
        latest_evidence_ids = [_evidence_from_bar(asset_bars[-1]).evidence_id]
        for kind, _frame in benchmark_frames.items():
            benchmark_id = benchmarks[kind]
            if benchmark_id is not None:
                benchmark_bars = bars_by_security.get(benchmark_id, ())
                if benchmark_bars:
                    latest_evidence_ids.append(_evidence_from_bar(benchmark_bars[-1]).evidence_id)

        available_at = max(bar.available_at for bar in all_input_bars)
        effective_at = asset_bars[-1].effective_at
        values = {
            "daily_return": (daily_return, "decimal_return", "1d"),
            "residual_return": (residual_return, "decimal_return", "1d"),
            "residual_return_zscore_1d": (residual_zscore, "zscore", "1d"),
            "dollar_volume_zscore_20d": (dollar_volume_zscore, "zscore", "20d"),
            "realized_volatility_20d": (volatility, "annualized_decimal", "20d"),
            "beta_126d": (beta, "coefficient", "126d"),
            "relative_return_sector_63d": (relative_63d, "decimal_return", "63d"),
        }
        feature_snapshots = tuple(
            FeatureSnapshot(
                feature_snapshot_id=stable_research_id(
                    "feature",
                    f"{research_run_id}:{member.security_id}:{name}",
                ),
                security_id=member.security_id,
                feature_name=name,
                feature_version="price-mvp-v0",
                effective_at=effective_at,
                available_at=available_at,
                calculated_at=calculated_at,
                value=value,
                unit=unit,
                window=window,
                input_evidence_ids=evidence_ids,
                research_run_id=research_run_id,
                code_version=code_version,
                config_version=config_version,
            )
            for name, (value, unit, window) in values.items()
            if value is not None
        )
        snapshot = PriceResearchSnapshot(
            security_id=member.security_id,
            as_of=effective_at,
            available_at=available_at,
            created_at=calculated_at,
            daily_return=daily_return,
            residual_return=residual_return,
            residual_zscore=residual_zscore,
            volume_zscore=dollar_volume_zscore,
            realized_volatility_20d=volatility,
            beta_126d=beta,
            relative_return_sector_63d=relative_63d,
            observations=int(asset_returns.notna().sum()),
            evidence_ids=tuple(dict.fromkeys(latest_evidence_ids)),
            feature_snapshot_ids=tuple(item.feature_snapshot_id for item in feature_snapshots),
        )
        return _SecurityCalculation(
            snapshot=snapshot,
            features=feature_snapshots,
            evidence=evidence,
            daily_return=daily_return,
            benchmark_return=market_daily,
            sector_return=sector_daily,
        )


def _validate_reusable_run(
    existing: ResearchRun,
    *,
    research_run_id: UUID,
    run_key: str,
    as_of: datetime,
    data_cutoff_at: datetime,
    code_version: str,
    config_version: str,
    ingestion_batch_ids: tuple[UUID, ...],
) -> None:
    expected_fields: tuple[tuple[str, object], ...] = (
        ("research_run_id", research_run_id),
        ("run_key", run_key),
        ("run_type", "daily"),
        ("as_of", as_of),
        ("data_cutoff_at", data_cutoff_at),
        ("code_version", code_version),
        ("config_version", config_version),
        ("ingestion_batch_ids", ingestion_batch_ids),
    )
    for field, expected in expected_fields:
        if getattr(existing, field) != expected:
            raise RepositoryConflictError(f"research run key contains a different {field}")
    if existing.completed_at is None:
        raise RepositoryConflictError("research run key identifies an incomplete persisted run")


def _run_key(
    request: DailyResearchRequest,
    batch_ids: tuple[UUID, ...],
    *,
    thesis_method_version: str,
    materiality_score_version: str,
    position_weights: Mapping[UUID, float] | None,
    covered_security_ids: Sequence[UUID],
) -> str:
    effective_position_weights = _canonical_position_weights(
        position_weights,
        covered_security_ids,
    )
    payload = _canonical_json(
        [
            str(request.coverage_list_id),
            ensure_utc(request.as_of).isoformat(),
            ensure_utc(request.data_cutoff_at).isoformat(),
            request.lookback_calendar_days,
            request.source,
            request.code_version,
            request.feature_config_version,
            thesis_method_version,
            materiality_score_version,
            effective_position_weights,
            [str(value) for value in batch_ids],
        ]
    )
    return f"daily:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _run_config_version(
    feature_config_version: str,
    thesis_method_version: str,
    materiality_score_version: str,
) -> str:
    payload = _canonical_json(
        [feature_config_version, thesis_method_version, materiality_score_version]
    )
    return f"bundle:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _canonical_position_weights(
    position_weights: Mapping[UUID, float] | None,
    covered_security_ids: Sequence[UUID],
) -> dict[str, float]:
    if position_weights is None:
        return {}
    return {
        str(security_id): (
            0.0 if position_weights[security_id] == 0.0 else float(position_weights[security_id])
        )
        for security_id in sorted(set(covered_security_ids), key=str)
        if security_id in position_weights
    }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _group_bars(bars: Sequence[PriceBar]) -> dict[UUID, tuple[PriceBar, ...]]:
    grouped: dict[UUID, list[PriceBar]] = {}
    for bar in bars:
        grouped.setdefault(bar.security_id, []).append(bar)
    return {
        security_id: tuple(sorted(items, key=lambda item: (item.session_date, item.available_at)))
        for security_id, items in grouped.items()
    }


def _bars_frame(bars: Sequence[PriceBar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "adjusted_close", "volume"])
    rows = [
        {
            "session_date": bar.session_date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "adjusted_close": bar.adjusted_close if bar.adjusted_close is not None else bar.close,
            "volume": bar.volume,
        }
        for bar in bars
    ]
    frame = pd.DataFrame(rows).drop_duplicates("session_date", keep="last")
    frame = frame.sort_values("session_date", kind="mergesort").set_index("session_date")
    frame.index = pd.DatetimeIndex(frame.index)
    return frame


def _last_finite(values: pd.Series) -> float | None:
    if values.empty:
        return None
    value = values.iloc[-1]
    return float(value) if pd.notna(value) and isfinite(float(value)) else None


def _last_at(values: pd.Series, index: object) -> float | None:
    value = values.get(index)
    return (
        float(value) if value is not None and pd.notna(value) and isfinite(float(value)) else None
    )


def _evidence_from_bar(bar: PriceBar) -> EvidenceReference:
    return price_bar_evidence(
        provider=bar.source,
        source_record_id=bar.source_record_id,
        effective_at=bar.effective_at,
        available_at=bar.available_at,
        ingested_at=bar.ingested_at,
    )
