"""Deterministic scoring and cards must remain auditable and idempotent."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

import quant_raas.research.findings as price_findings
from quant_raas.domain.enums import MaterialityTier, ThesisImpact
from quant_raas.domain.research import (
    EvidenceReference,
    ResearchCard,
    ResearchFinding,
    ResearchRun,
    ThesisNodeContribution,
    ThesisRelevanceAssessment,
)
from quant_raas.research.cards import build_research_card, render_card_markdown
from quant_raas.research.evidence import validate_evidence_cutoff
from quant_raas.research.findings import PriceResearchSnapshot, build_price_finding
from quant_raas.research.materiality import MaterialityConfig, MaterialityScorer

THESIS_ID = UUID("71717171-7171-4717-8717-717171717171")
THESIS_VERSION_ID = UUID("72727272-7272-4727-8727-727272727272")
OTHER_THESIS_VERSION_ID = UUID("73737373-7373-4737-8737-737373737373")
RELATIVE_FEATURE_ID = UUID("81818181-8181-4818-8818-818181818181")
VOLUME_FEATURE_ID = UUID("82828282-8282-4828-8828-828282828282")


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


def _assessment(
    *,
    score: float = 0.75,
    impact: ThesisImpact = ThesisImpact.HIGH,
    primary_node_id: str | None = "relative_strength",
    thesis_version_id: UUID = THESIS_VERSION_ID,
    contributions: tuple[ThesisNodeContribution, ...] | None = None,
) -> ThesisRelevanceAssessment:
    if contributions is None:
        contributions = (
            ThesisNodeContribution(
                node_id="relative_strength",
                node_kind="driver",
                score=score,
                matched_feature_names=("relative_return_sector_63d",),
                feature_snapshot_ids=(RELATIVE_FEATURE_ID,),
            ),
        )
    return ThesisRelevanceAssessment(
        thesis_id=THESIS_ID,
        thesis_version_id=thesis_version_id,
        score=score,
        impact=impact,
        primary_node_id=primary_node_id,
        contributions=contributions,
        method_version="thesis-relevance-v1",
    )


def test_price_signal_strengths_use_exact_bounds_and_omit_missing_inputs(
    security_id: UUID,
    research_run: ResearchRun,
    evidence_reference: EvidenceReference,
) -> None:
    snapshot = _price_snapshot(
        security_id=security_id,
        run=research_run,
        evidence=evidence_reference,
    )
    assert price_findings.price_signal_strengths(snapshot) == {
        "residual_return_zscore_1d": 0.75,
        "dollar_volume_zscore_20d": 0.5,
        "relative_return_sector_63d": 0.5,
    }

    bounded = replace(
        snapshot,
        residual_zscore=-8.0,
        volume_zscore=None,
        relative_return_sector_63d=0.40,
    )
    assert price_findings.price_signal_strengths(bounded) == {
        "residual_return_zscore_1d": 1.0,
        "relative_return_sector_63d": 1.0,
    }


def test_finding_scores_exact_assessment_and_card_derives_complete_lineage(
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
    baseline = build_price_finding(
        snapshot,
        research_run_id=research_run.research_run_id,
        scorer=materiality_scorer,
    )
    assessment = _assessment(
        contributions=(
            ThesisNodeContribution(
                node_id="relative_strength",
                node_kind="driver",
                score=0.75,
                matched_feature_names=("relative_return_sector_63d",),
                feature_snapshot_ids=(RELATIVE_FEATURE_ID,),
            ),
            ThesisNodeContribution(
                node_id="relative_break",
                node_kind="invalidation_rule",
                score=0.0,
                matched_feature_names=("relative_return_sector_63d",),
                feature_snapshot_ids=(RELATIVE_FEATURE_ID,),
            ),
            ThesisNodeContribution(
                node_id="volume_risk",
                node_kind="risk",
                score=0.5,
                matched_feature_names=("dollar_volume_zscore_20d",),
                feature_snapshot_ids=(VOLUME_FEATURE_ID,),
            ),
        )
    )
    finding = build_price_finding(
        snapshot,
        research_run_id=research_run.research_run_id,
        scorer=materiality_scorer,
        thesis_assessment=assessment,
    )

    assert "thesis_relevance" not in baseline.score.component_scores
    assert baseline.thesis_relevance is None
    assert baseline.thesis_version_id is None
    assert finding.score.component_scores["thesis_relevance"] == pytest.approx(0.75)
    assert finding.thesis_version_id == assessment.thesis_version_id
    assert finding.thesis_relevance == assessment
    assert finding.score.raw_score == pytest.approx(
        baseline.score.raw_score + 0.15 * assessment.score
    )
    assert finding.score.completeness == pytest.approx(baseline.score.completeness + 0.15)

    card = build_research_card(
        [finding],
        research_run_id=research_run.research_run_id,
        security_id=security_id,
        as_of=research_run.as_of,
        data_cutoff_at=research_run.data_cutoff_at,
        created_at=research_run.started_at,
    )
    assert card.thesis_version_id == THESIS_VERSION_ID
    assert card.thesis_impact is ThesisImpact.HIGH
    assert card.thesis_node_id == "relative_strength"
    assert card.thesis_node_ids == ("relative_break", "relative_strength", "volume_risk")
    markdown = render_card_markdown(card, security_label="EXAMPLE US")
    assert "High (version 72727272, node relative_strength)" in markdown
    assert "proves" not in markdown.lower()
    assert "disproves" not in markdown.lower()


def test_explicit_zero_assessment_is_complete_and_visibly_distinct_from_no_thesis(
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
    baseline = build_price_finding(
        snapshot,
        research_run_id=research_run.research_run_id,
        scorer=materiality_scorer,
    )
    assessment = _assessment(
        score=0.0,
        impact=ThesisImpact.NONE,
        primary_node_id=None,
        contributions=(),
    )
    finding = build_price_finding(
        snapshot,
        research_run_id=research_run.research_run_id,
        scorer=materiality_scorer,
        thesis_assessment=assessment,
    )
    assert finding.score.component_scores["thesis_relevance"] == 0.0
    assert finding.score.raw_score == pytest.approx(baseline.score.raw_score)
    assert finding.score.completeness == pytest.approx(baseline.score.completeness + 0.15)

    no_thesis_card = build_research_card(
        [baseline],
        research_run_id=research_run.research_run_id,
        security_id=security_id,
        as_of=research_run.as_of,
        data_cutoff_at=research_run.data_cutoff_at,
        created_at=research_run.started_at,
    )
    zero_card = build_research_card(
        [finding],
        research_run_id=research_run.research_run_id,
        security_id=security_id,
        as_of=research_run.as_of,
        data_cutoff_at=research_run.data_cutoff_at,
        created_at=research_run.started_at,
    )
    assert zero_card.thesis_impact is ThesisImpact.NONE
    assert zero_card.thesis_version_id == THESIS_VERSION_ID
    assert zero_card.thesis_node_id is None
    assert zero_card.thesis_node_ids == ()
    zero_markdown = render_card_markdown(zero_card, security_label="EXAMPLE US")
    no_thesis_markdown = render_card_markdown(no_thesis_card, security_label="EXAMPLE US")
    assert "None (version 72727272)" in zero_markdown
    assert "version 72727272" not in no_thesis_markdown
    assert "node " not in no_thesis_markdown


def test_card_fails_closed_on_mixed_versions_and_breaks_primary_ties_by_node_id(
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
    alpha = _assessment(
        primary_node_id="alpha_node",
        contributions=(
            ThesisNodeContribution(
                node_id="alpha_node",
                node_kind="driver",
                score=0.75,
                matched_feature_names=("relative_return_sector_63d",),
                feature_snapshot_ids=(RELATIVE_FEATURE_ID,),
            ),
        ),
    )
    zeta = _assessment(
        primary_node_id="zeta_node",
        contributions=(
            ThesisNodeContribution(
                node_id="zeta_node",
                node_kind="risk",
                score=0.75,
                matched_feature_names=("dollar_volume_zscore_20d",),
                feature_snapshot_ids=(VOLUME_FEATURE_ID,),
            ),
        ),
    )
    alpha_finding = build_price_finding(
        snapshot,
        research_run_id=research_run.research_run_id,
        scorer=materiality_scorer,
        thesis_assessment=alpha,
    )
    zeta_finding = ResearchFinding.model_validate(
        {
            **build_price_finding(
                snapshot,
                research_run_id=research_run.research_run_id,
                scorer=materiality_scorer,
                thesis_assessment=zeta,
            ).model_dump(mode="python"),
            "finding_id": UUID("81818181-8181-4818-8818-818181818181"),
            "finding_key": "daily-price:zeta-node",
        }
    )
    card = build_research_card(
        [zeta_finding, alpha_finding],
        research_run_id=research_run.research_run_id,
        security_id=security_id,
        as_of=research_run.as_of,
        data_cutoff_at=research_run.data_cutoff_at,
        created_at=research_run.started_at,
    )
    assert card.thesis_node_id == "alpha_node"
    assert card.thesis_node_ids == ("alpha_node", "zeta_node")

    other = _assessment(thesis_version_id=OTHER_THESIS_VERSION_ID)
    mixed = ResearchFinding.model_validate(
        {
            **alpha_finding.model_dump(mode="python"),
            "finding_id": UUID("82828282-8282-4828-8828-828282828282"),
            "finding_key": "daily-price:other-version",
            "thesis_version_id": other.thesis_version_id,
            "thesis_relevance": other,
        }
    )
    with pytest.raises(ValueError, match="thesis version"):
        build_research_card(
            [alpha_finding, mixed],
            research_run_id=research_run.research_run_id,
            security_id=security_id,
            as_of=research_run.as_of,
            data_cutoff_at=research_run.data_cutoff_at,
            created_at=research_run.started_at,
        )


def test_finding_and_card_contracts_reject_inconsistent_thesis_lineage(
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
    assessment = _assessment()
    finding = build_price_finding(
        snapshot,
        research_run_id=research_run.research_run_id,
        scorer=materiality_scorer,
        thesis_assessment=assessment,
    )
    finding_payload = finding.model_dump(mode="python")
    for update in (
        {"thesis_relevance": None},
        {"thesis_version_id": None},
        {"thesis_version_id": OTHER_THESIS_VERSION_ID},
    ):
        with pytest.raises(ValidationError, match="thesis"):
            ResearchFinding.model_validate({**finding_payload, **update})

    card = build_research_card(
        [finding],
        research_run_id=research_run.research_run_id,
        security_id=security_id,
        as_of=research_run.as_of,
        data_cutoff_at=research_run.data_cutoff_at,
        created_at=research_run.started_at,
    )
    card_payload = card.model_dump(mode="python")
    invalid_updates = (
        {"thesis_node_id": "missing_node"},
        {"thesis_version_id": None},
        {"thesis_node_ids": ("volume_risk", "relative_strength")},
        {"thesis_node_ids": ("relative_strength", "relative_strength")},
        {"thesis_node_id": None},
        {
            "thesis_version_id": None,
            "thesis_impact": ThesisImpact.NONE,
            "thesis_node_id": None,
        },
    )
    for update in invalid_updates:
        with pytest.raises(ValidationError, match="thesis"):
            ResearchCard.model_validate({**card_payload, **update})


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
