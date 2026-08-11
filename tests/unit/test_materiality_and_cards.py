"""Deterministic scoring and cards must remain auditable and idempotent."""

from __future__ import annotations

import math
from datetime import timedelta
from uuid import UUID

import pytest

from quant_raas.domain.enums import MaterialityTier
from quant_raas.domain.research import EvidenceReference, ResearchRun
from quant_raas.research.cards import build_research_card, render_card_markdown
from quant_raas.research.evidence import validate_evidence_cutoff
from quant_raas.research.findings import PriceResearchSnapshot, build_price_finding
from quant_raas.research.materiality import MaterialityConfig, MaterialityScorer


def test_materiality_weights_reproduce_constant_component_score(
    materiality_scorer: MaterialityScorer,
) -> None:
    components = {name: 0.4 for name in materiality_scorer.config.score.components}
    score, tier = materiality_scorer.score(components, position_weight=-0.04)
    assert score.raw_score == pytest.approx(0.4)
    assert score.completeness == pytest.approx(1.0)
    # Short and long positions receive the same relevance modifier.
    assert score.priority_modifier == pytest.approx(1.0 + math.sqrt(0.04))
    assert score.priority_score == pytest.approx(0.48)
    # The configured watch threshold is 0.30; tiering uses intrinsic raw score,
    # while position size affects inbox priority only.
    assert tier == MaterialityTier.WATCH


def test_missing_materiality_components_contribute_zero_without_renormalization(
    materiality_scorer: MaterialityScorer,
) -> None:
    score, _ = materiality_scorer.score({"abnormal_price": 1.0})
    assert score.raw_score == pytest.approx(0.15)
    assert score.completeness == pytest.approx(0.15)


def test_materiality_configuration_rejects_weights_that_do_not_sum_to_one(
    materiality_config: MaterialityConfig,
) -> None:
    payload = materiality_config.model_dump(mode="python")
    payload["score"]["components"]["abnormal_price"] = 0.16
    with pytest.raises(ValueError, match="sum to one"):
        MaterialityConfig.model_validate(payload)


def _price_snapshot(
    *,
    security_id: UUID,
    run: ResearchRun,
    evidence: EvidenceReference,
) -> PriceResearchSnapshot:
    return PriceResearchSnapshot(
        security_id=security_id,
        as_of=run.as_of,
        available_at=evidence.available_at,
        created_at=run.started_at,
        daily_return=-0.04,
        residual_return=-0.03,
        residual_zscore=-3.0,
        volume_zscore=2.0,
        realized_volatility_20d=0.30,
        beta_126d=1.2,
        relative_return_sector_63d=-0.10,
        observations=252,
        evidence_ids=(evidence.evidence_id,),
    )


def test_finding_and_card_are_stable_evidence_linked_and_numerically_exact(
    security_id: UUID,
    research_run: ResearchRun,
    evidence_reference: EvidenceReference,
    materiality_scorer: MaterialityScorer,
) -> None:
    snapshot = _price_snapshot(
        security_id=security_id,
        run=research_run,
        evidence=evidence_reference,
    )
    finding = build_price_finding(
        snapshot,
        research_run_id=research_run.research_run_id,
        scorer=materiality_scorer,
        position_weight=0.035,
    )
    repeated = build_price_finding(
        snapshot,
        research_run_id=research_run.research_run_id,
        scorer=materiality_scorer,
        position_weight=0.035,
    )
    assert finding.finding_id == repeated.finding_id
    assert finding.evidence_ids == (evidence_reference.evidence_id,)
    assert finding.title == "Abnormal residual price move"

    card = build_research_card(
        [finding],
        research_run_id=research_run.research_run_id,
        security_id=security_id,
        as_of=research_run.as_of,
        data_cutoff_at=research_run.data_cutoff_at,
        created_at=research_run.started_at,
        position_weight=0.035,
        daily_return=-0.04,
    )
    repeated_card = build_research_card(
        [finding],
        research_run_id=research_run.research_run_id,
        security_id=security_id,
        as_of=research_run.as_of,
        data_cutoff_at=research_run.data_cutoff_at,
        created_at=research_run.started_at,
        position_weight=0.035,
        daily_return=-0.04,
    )
    assert card.card_id == repeated_card.card_id
    assert card.context.contribution_bps == pytest.approx(-14.0)
    assert card.evidence_ids == (evidence_reference.evidence_id,)
    markdown = render_card_markdown(card, security_label="EXAMPLE US")
    assert "-3.00 sigma" in markdown
    assert "Position weight: 3.50%" in markdown
    assert "Indicative daily contribution: -14.0 bps" in markdown


def test_cards_refuse_unavailable_or_absent_evidence(
    security_id: UUID,
    research_run: ResearchRun,
    evidence_reference: EvidenceReference,
    materiality_scorer: MaterialityScorer,
) -> None:
    with pytest.raises(ValueError, match="unavailable at cutoff"):
        validate_evidence_cutoff(
            [evidence_reference],
            data_cutoff_at=evidence_reference.available_at - timedelta(seconds=1),
        )

    snapshot = _price_snapshot(
        security_id=security_id,
        run=research_run,
        evidence=evidence_reference,
    )
    finding = build_price_finding(
        snapshot,
        research_run_id=research_run.research_run_id,
        scorer=materiality_scorer,
    )
    empty_lineage = finding.model_copy(update={"evidence_ids": ()})
    with pytest.raises(ValueError, match="require evidence lineage"):
        build_research_card(
            [empty_lineage],
            research_run_id=research_run.research_run_id,
            security_id=security_id,
            as_of=research_run.as_of,
            data_cutoff_at=research_run.data_cutoff_at,
            created_at=research_run.started_at,
        )
