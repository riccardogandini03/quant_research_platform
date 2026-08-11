"""Deterministic Phase-1 research-card assembly and presentation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from quant_raas.domain.enums import ConfidenceLevel, FindingCategory, MaterialityTier, ThesisImpact
from quant_raas.domain.research import CardContext, QuantMetric, ResearchCard, ResearchFinding
from quant_raas.research.ids import stable_research_id

_TIER_ORDER = {
    MaterialityTier.ROUTINE: 0,
    MaterialityTier.WATCH: 1,
    MaterialityTier.MATERIAL: 2,
    MaterialityTier.CRITICAL: 3,
}


def _next_question(category: FindingCategory) -> str:
    if category == FindingCategory.PRICE_ANOMALY:
        return (
            "Is the residual move explained by new fundamental evidence or a temporary dislocation?"
        )
    if category == FindingCategory.VOLUME_ANOMALY:
        return "What catalyst or positioning change explains the abnormal volume?"
    return "Which new data would most change the current research thesis?"


def build_research_card(
    findings: Iterable[ResearchFinding],
    *,
    research_run_id: UUID,
    security_id: UUID,
    as_of: datetime,
    data_cutoff_at: datetime,
    created_at: datetime,
    position_weight: float | None = None,
    daily_return: float | None = None,
    benchmark_return: float | None = None,
    sector_return: float | None = None,
    thesis_impact: ThesisImpact = ThesisImpact.NONE,
    thesis_node_id: str | None = None,
) -> ResearchCard:
    """Merge related findings into one ranked, evidence-linked security card."""

    selected = [finding for finding in findings if finding.security_id == security_id]
    if not selected:
        raise ValueError("at least one finding for the security is required")
    if any(finding.research_run_id != research_run_id for finding in selected):
        raise ValueError("all findings must belong to the requested research run")
    selected.sort(key=lambda item: (-item.score.priority_score, item.finding_key))
    lead = selected[0]

    metrics_by_key: dict[tuple[str, str | None], QuantMetric] = {}
    for finding in selected:
        for metric in finding.metrics:
            metrics_by_key.setdefault((metric.name, metric.horizon), metric)
    metrics = tuple(metrics_by_key[key] for key in sorted(metrics_by_key))
    finding_ids = tuple(finding.finding_id for finding in selected)
    evidence_ids = tuple(
        sorted({item for finding in selected for item in finding.evidence_ids}, key=str)
    )
    if not evidence_ids:
        raise ValueError("research cards require evidence lineage")

    tier = max((finding.materiality_tier for finding in selected), key=_TIER_ORDER.__getitem__)
    confidence = min(
        (finding.confidence for finding in selected),
        key={
            ConfidenceLevel.LOW: 0,
            ConfidenceLevel.MEDIUM: 1,
            ConfidenceLevel.HIGH: 2,
        }.__getitem__,
    )
    contribution = (
        position_weight * daily_return * 10_000.0
        if position_weight is not None and daily_return is not None
        else None
    )
    context_notes = (
        ("Contribution is a simple weight x return estimate, not accounting-grade attribution.",)
        if contribution is not None
        else ()
    )
    card_key = f"daily-card:{research_run_id}:{security_id}:{as_of.isoformat()}"
    change = " ".join(dict.fromkeys(finding.change for finding in selected))
    return ResearchCard(
        card_id=stable_research_id("card", card_key),
        card_key=card_key,
        research_run_id=research_run_id,
        security_id=security_id,
        as_of=as_of,
        created_at=created_at,
        materiality_tier=tier,
        change=change,
        quant_evidence=metrics,
        context=CardContext(
            position_weight=position_weight,
            contribution_bps=contribution,
            benchmark_return=benchmark_return,
            sector_return=sector_return,
            notes=context_notes,
        ),
        thesis_impact=thesis_impact,
        thesis_node_id=thesis_node_id,
        key_risk_or_opportunity=(
            "The cause of the residual move is not yet resolved."
            if lead.category == FindingCategory.PRICE_ANOMALY
            else None
        ),
        confidence=confidence,
        next_research_question=_next_question(lead.category),
        finding_ids=finding_ids,
        evidence_ids=evidence_ids,
        renderer_version="deterministic-card-v0",
        model_version=None,
        data_cutoff_at=data_cutoff_at,
        metadata={"lead_finding_id": str(lead.finding_id)},
    )


def _format_metric(metric: QuantMetric) -> str:
    if metric.unit in {"decimal_return", "annualized_decimal"}:
        value = f"{metric.value * 100:.2f}%"
    elif metric.unit == "basis_points":
        value = f"{metric.value * 10_000:.1f} bps"
    elif metric.unit == "zscore":
        value = f"{metric.value:+.2f} sigma"
    else:
        value = f"{metric.value:.3f}"
    horizon = f" ({metric.horizon})" if metric.horizon else ""
    return f"- {metric.name}{horizon}: {value}"


def render_card_markdown(card: ResearchCard, *, security_label: str) -> str:
    """Render the consistent research-card schema without an LLM."""

    evidence = "\n".join(_format_metric(metric) for metric in card.quant_evidence)
    context: list[str] = []
    if card.context.position_weight is not None:
        context.append(f"- Position weight: {card.context.position_weight * 100:.2f}%")
    if card.context.contribution_bps is not None:
        context.append(f"- Indicative daily contribution: {card.context.contribution_bps:+.1f} bps")
    context.extend(f"- {note}" for note in card.context.notes)
    context_text = "\n".join(context) or "- Not held or holdings context unavailable."
    return (
        f"# {security_label} — {card.materiality_tier.value.upper()}\n\n"
        f"## Change\n\n{card.change}\n\n"
        f"## Quant evidence\n\n{evidence or '- No displayable metric.'}\n\n"
        f"## Context\n\n{context_text}\n\n"
        f"## Thesis impact\n\n{card.thesis_impact.value.title()}\n\n"
        f"## Confidence\n\n{card.confidence.value.title()}\n\n"
        f"## Next research question\n\n{card.next_research_question or 'Insufficient evidence.'}\n"
    )
