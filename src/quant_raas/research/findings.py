"""Translate quantitative snapshots into typed candidate findings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from quant_raas.domain.enums import ConfidenceLevel, FindingCategory
from quant_raas.domain.research import QuantMetric, ResearchFinding
from quant_raas.research.ids import stable_research_id
from quant_raas.research.materiality import MaterialityScorer


@dataclass(frozen=True, slots=True)
class PriceResearchSnapshot:
    """Validated numerical inputs produced by the daily price pipeline."""

    security_id: UUID
    as_of: datetime
    available_at: datetime
    created_at: datetime
    daily_return: float | None
    residual_return: float | None
    residual_zscore: float | None
    volume_zscore: float | None
    realized_volatility_20d: float | None
    beta_126d: float | None
    relative_return_sector_63d: float | None
    observations: int
    evidence_ids: tuple[UUID, ...]
    feature_snapshot_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if not self.evidence_ids:
            raise ValueError("a price snapshot requires evidence lineage")
        for name in (
            "daily_return",
            "residual_return",
            "residual_zscore",
            "volume_zscore",
            "realized_volatility_20d",
            "beta_126d",
            "relative_return_sector_63d",
        ):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite when available")


def _bounded_anomaly(value: float | None, *, full_score_at: float = 4.0) -> float | None:
    return None if value is None else min(abs(value) / full_score_at, 1.0)


def _metric(
    name: str, value: float | None, unit: str, as_of: datetime, horizon: str
) -> QuantMetric | None:
    if value is None:
        return None
    return QuantMetric(name=name, value=value, unit=unit, horizon=horizon, as_of=as_of)


def build_price_finding(
    snapshot: PriceResearchSnapshot,
    *,
    research_run_id: UUID,
    scorer: MaterialityScorer,
    position_weight: float | None = None,
) -> ResearchFinding:
    """Emit one daily finding, including a routine snapshot when no alert fires."""

    residual_score = _bounded_anomaly(snapshot.residual_zscore)
    volume_score = _bounded_anomaly(snapshot.volume_zscore)
    factor_change = (
        min(abs(snapshot.relative_return_sector_63d) / 0.20, 1.0)
        if snapshot.relative_return_sector_63d is not None
        else None
    )
    available_anomaly_scores = [
        value for value in (residual_score, volume_score) if value is not None
    ]
    event_novelty = max(available_anomaly_scores) if available_anomaly_scores else None
    score, tier = scorer.score(
        {
            "abnormal_price": residual_score,
            "abnormal_volume": volume_score,
            "factor_change": factor_change,
            # Statistical rarity is an objective Phase-1 novelty proxy. It is
            # not a substitute for later news/filing catalyst novelty.
            "event_novelty": event_novelty,
        },
        position_weight=position_weight,
    )

    if snapshot.residual_zscore is not None and abs(snapshot.residual_zscore) >= 2.0:
        category = FindingCategory.PRICE_ANOMALY
        direction = "negative" if snapshot.residual_zscore < 0 else "positive"
        title = "Abnormal residual price move"
        change = (
            f"The latest return was a {direction} residual outlier after market and "
            "sector controls."
        )
    elif snapshot.volume_zscore is not None and abs(snapshot.volume_zscore) >= 2.0:
        category = FindingCategory.VOLUME_ANOMALY
        direction = "high" if snapshot.volume_zscore > 0 else "low"
        title = "Unusual trading volume"
        change = "Latest volume was unusual relative to its trailing history."
    else:
        category = FindingCategory.OTHER
        direction = None
        title = "Daily quantitative snapshot"
        change = "Daily price, relative-return, and risk diagnostics were refreshed."

    metric_candidates = (
        _metric("daily_return", snapshot.daily_return, "decimal_return", snapshot.as_of, "1d"),
        _metric(
            "residual_return", snapshot.residual_return, "decimal_return", snapshot.as_of, "1d"
        ),
        _metric("residual_return_zscore", snapshot.residual_zscore, "zscore", snapshot.as_of, "1d"),
        _metric("volume_zscore", snapshot.volume_zscore, "zscore", snapshot.as_of, "1d"),
        _metric(
            "realized_volatility",
            snapshot.realized_volatility_20d,
            "annualized_decimal",
            snapshot.as_of,
            "20d",
        ),
        _metric("beta", snapshot.beta_126d, "coefficient", snapshot.as_of, "126d"),
        _metric(
            "relative_return_sector",
            snapshot.relative_return_sector_63d,
            "decimal_return",
            snapshot.as_of,
            "63d",
        ),
    )
    metrics = tuple(metric for metric in metric_candidates if metric is not None)
    confidence = (
        ConfidenceLevel.HIGH
        if snapshot.observations >= 252 and score.completeness >= 0.35
        else ConfidenceLevel.MEDIUM
        if snapshot.observations >= 126
        else ConfidenceLevel.LOW
    )
    finding_key = (
        f"daily-price:{research_run_id}:{snapshot.security_id}:{snapshot.as_of.isoformat()}"
    )
    return ResearchFinding(
        finding_id=stable_research_id("finding", finding_key),
        finding_key=finding_key,
        research_run_id=research_run_id,
        security_id=snapshot.security_id,
        category=category,
        title=title,
        change=change,
        direction=direction,
        effective_at=snapshot.as_of,
        available_at=snapshot.available_at,
        created_at=snapshot.created_at,
        metrics=metrics,
        feature_snapshot_ids=snapshot.feature_snapshot_ids,
        evidence_ids=snapshot.evidence_ids,
        score=score,
        materiality_tier=tier,
        confidence=confidence,
        portfolio_weight=position_weight,
        metadata={"observations": snapshot.observations, "generator": "price-mvp-v0"},
    )
