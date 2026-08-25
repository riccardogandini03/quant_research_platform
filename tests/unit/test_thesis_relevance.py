"""Deterministic relevance scoring for PM-authored thesis nodes."""

from datetime import UTC, datetime
from math import inf, nan
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from quant_raas.domain.enums import InvalidationComparator, ThesisImpact
from quant_raas.domain.market import FeatureSnapshot
from quant_raas.domain.research import (
    ThesisContent,
    ThesisInvalidationRule,
    ThesisSignal,
    ThesisVersion,
)
from quant_raas.research.thesis import (
    ThesisRelevanceConfig,
    ThesisRelevanceEvaluator,
)


def _feature(
    *,
    identifier: int,
    name: str,
    value: object,
    security_id: UUID,
    research_run_id: UUID,
) -> FeatureSnapshot:
    available = datetime(2024, 1, 9, 20, 0, tzinfo=UTC)
    return FeatureSnapshot(
        feature_snapshot_id=UUID(int=identifier),
        security_id=security_id,
        feature_name=name,
        feature_version="price-mvp-v0",
        effective_at=available,
        available_at=available,
        calculated_at=datetime(2024, 1, 9, 21, 0, tzinfo=UTC),
        value=value,
        research_run_id=research_run_id,
        code_version="test-code-v1",
        config_version="test-config-v1",
    )


def test_assesses_exact_signal_overlap_with_maximum_score_and_lineage(
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
    thesis_version: ThesisVersion,
    security_id: UUID,
    research_run_id: UUID,
) -> None:
    relative_feature = _feature(
        identifier=101,
        name="relative_return_sector_63d",
        value=-0.10,
        security_id=security_id,
        research_run_id=research_run_id,
    )
    volume_feature = _feature(
        identifier=102,
        name="dollar_volume_zscore_20d",
        value=3.0,
        security_id=security_id,
        research_run_id=research_run_id,
    )
    assessment = thesis_relevance_evaluator.assess(
        thesis_version,
        signals=(
            ThesisSignal(
                feature_name="relative_return_sector_63d",
                raw_value=-0.10,
                normalized_strength=0.50,
                feature_snapshot_id=relative_feature.feature_snapshot_id,
                unit="decimal_return",
            ),
            ThesisSignal(
                feature_name="dollar_volume_zscore_20d",
                raw_value=3.0,
                normalized_strength=0.75,
                feature_snapshot_id=volume_feature.feature_snapshot_id,
                unit="zscore",
            ),
        ),
        features=(relative_feature, volume_feature),
    )
    assert assessment.score == pytest.approx(0.75)
    assert assessment.impact == ThesisImpact.HIGH
    assert assessment.primary_node_id == "volume_risk"
    assert assessment.method_version == "thesis-relevance-v1"
    assert [(item.node_kind, item.node_id) for item in assessment.contributions] == [
        ("driver", "relative_strength"),
        ("invalidation_rule", "relative_break"),
        ("risk", "volume_risk"),
    ]
    volume = assessment.contributions[2]
    assert volume.matched_feature_names == ("dollar_volume_zscore_20d",)
    assert volume.feature_snapshot_ids == (volume_feature.feature_snapshot_id,)


def test_uses_maximum_not_sum_for_correlated_driver_signals(
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
    thesis_version: ThesisVersion,
    security_id: UUID,
    research_run_id: UUID,
) -> None:
    content = thesis_version.content.model_copy(
        update={
            "drivers": (
                thesis_version.content.drivers[0].model_copy(
                    update={
                        "supporting_features": (
                            "relative_return_sector_63d",
                            "dollar_volume_zscore_20d",
                        )
                    }
                ),
            ),
            "risks": (),
            "invalidation_rules": (),
        }
    )
    version = thesis_version.model_copy(update={"content": content})
    first = _feature(
        identifier=103,
        name="relative_return_sector_63d",
        value=0.1,
        security_id=security_id,
        research_run_id=research_run_id,
    )
    second = _feature(
        identifier=104,
        name="dollar_volume_zscore_20d",
        value=2.0,
        security_id=security_id,
        research_run_id=research_run_id,
    )
    assessment = thesis_relevance_evaluator.assess(
        version,
        signals=(
            ThesisSignal(
                feature_name=first.feature_name,
                raw_value=0.1,
                normalized_strength=0.60,
                feature_snapshot_id=first.feature_snapshot_id,
            ),
            ThesisSignal(
                feature_name=second.feature_name,
                raw_value=2.0,
                normalized_strength=0.70,
                feature_snapshot_id=second.feature_snapshot_id,
            ),
        ),
        features=(first, second),
    )
    assert assessment.score == pytest.approx(0.70)
    assert assessment.contributions[0].matched_feature_names == (
        "relative_return_sector_63d",
        "dollar_volume_zscore_20d",
    )


@pytest.mark.parametrize(
    ("comparator", "warning", "breach", "value", "expected"),
    [
        (InvalidationComparator.GREATER_THAN_OR_EQUAL, 1.0, 3.0, 2.0, 0.50),
        (InvalidationComparator.LESS_THAN_OR_EQUAL, -1.0, -3.0, -2.0, 0.50),
        (InvalidationComparator.GREATER_THAN_OR_EQUAL, 1.0, 3.0, 1.0, 0.0),
        (InvalidationComparator.LESS_THAN_OR_EQUAL, -1.0, -3.0, -1.0, 0.0),
        (InvalidationComparator.GREATER_THAN_OR_EQUAL, 1.0, 3.0, 3.0, 1.0),
        (InvalidationComparator.LESS_THAN_OR_EQUAL, -1.0, -3.0, -3.0, 1.0),
    ],
)
def test_invalidation_rules_use_linear_proximity_and_include_boundaries(
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
    thesis_version: ThesisVersion,
    security_id: UUID,
    research_run_id: UUID,
    comparator: InvalidationComparator,
    warning: float,
    breach: float,
    value: float,
    expected: float,
) -> None:
    rule = ThesisInvalidationRule(
        node_id="threshold_rule",
        statement="Threshold determines relevance.",
        feature_name="beta_126d",
        comparator=comparator,
        warning_threshold=warning,
        breach_threshold=breach,
    )
    version = thesis_version.model_copy(
        update={
            "content": ThesisContent(
                summary="Threshold case.",
                invalidation_rules=(rule,),
            )
        }
    )
    feature = _feature(
        identifier=105,
        name="beta_126d",
        value=value,
        security_id=security_id,
        research_run_id=research_run_id,
    )
    assessment = thesis_relevance_evaluator.assess(version, signals=(), features=(feature,))
    assert assessment.score == pytest.approx(expected)
    assert assessment.contributions[0].score == pytest.approx(expected)
    assert assessment.contributions[0].matched_feature_names == ("beta_126d",)
    assert assessment.contributions[0].feature_snapshot_ids == (feature.feature_snapshot_id,)


def test_returns_explicit_zero_for_no_overlap(
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
    thesis_version: ThesisVersion,
    security_id: UUID,
    research_run_id: UUID,
) -> None:
    unrelated = _feature(
        identifier=106,
        name="beta_126d",
        value=0.5,
        security_id=security_id,
        research_run_id=research_run_id,
    )
    assessment = thesis_relevance_evaluator.assess(
        thesis_version, signals=(), features=(unrelated,)
    )
    assert assessment.score == 0.0
    assert assessment.impact == ThesisImpact.NONE
    assert assessment.primary_node_id is None


@pytest.mark.parametrize(
    ("value", "reason"),
    [(None, "feature_non_numeric"), (nan, "feature_non_finite"), (inf, "feature_non_finite")],
)
def test_retains_unevaluated_invalidation_reason_for_unusable_feature_values(
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
    thesis_version: ThesisVersion,
    security_id: UUID,
    research_run_id: UUID,
    value: object,
    reason: str,
) -> None:
    feature = _feature(
        identifier=107,
        name="relative_return_sector_63d",
        value=value,
        security_id=security_id,
        research_run_id=research_run_id,
    )
    assessment = thesis_relevance_evaluator.assess(thesis_version, signals=(), features=(feature,))
    invalidation = next(
        item for item in assessment.contributions if item.node_id == "relative_break"
    )
    assert invalidation.score is None
    assert invalidation.unevaluated_reason == reason


def test_reports_missing_invalidation_feature_and_rejects_duplicate_input_names(
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
    thesis_version: ThesisVersion,
    security_id: UUID,
    research_run_id: UUID,
) -> None:
    assessment = thesis_relevance_evaluator.assess(thesis_version, signals=(), features=())
    invalidation = next(
        item for item in assessment.contributions if item.node_id == "relative_break"
    )
    assert invalidation.score is None
    assert invalidation.unevaluated_reason == "feature_missing"

    feature = _feature(
        identifier=108,
        name="relative_return_sector_63d",
        value=0.1,
        security_id=security_id,
        research_run_id=research_run_id,
    )
    signal = ThesisSignal(
        feature_name=feature.feature_name,
        raw_value=0.1,
        normalized_strength=0.5,
        feature_snapshot_id=feature.feature_snapshot_id,
    )
    with pytest.raises(ValueError, match="duplicate signal feature names"):
        thesis_relevance_evaluator.assess(
            thesis_version,
            signals=(signal, signal),
            features=(feature,),
        )
    with pytest.raises(ValueError, match="duplicate feature snapshot names"):
        thesis_relevance_evaluator.assess(
            thesis_version,
            signals=(signal,),
            features=(feature, feature),
        )


def test_breaks_primary_ties_lexicographically(
    thesis_relevance_evaluator: ThesisRelevanceEvaluator,
    thesis_version: ThesisVersion,
    security_id: UUID,
    research_run_id: UUID,
) -> None:
    first = _feature(
        identifier=109,
        name="relative_return_sector_63d",
        value=0.1,
        security_id=security_id,
        research_run_id=research_run_id,
    )
    second = _feature(
        identifier=110,
        name="dollar_volume_zscore_20d",
        value=1.0,
        security_id=security_id,
        research_run_id=research_run_id,
    )
    assessment = thesis_relevance_evaluator.assess(
        thesis_version,
        signals=(
            ThesisSignal(
                feature_name=first.feature_name,
                raw_value=0.1,
                normalized_strength=0.75,
                feature_snapshot_id=first.feature_snapshot_id,
            ),
            ThesisSignal(
                feature_name=second.feature_name,
                raw_value=1.0,
                normalized_strength=0.75,
                feature_snapshot_id=second.feature_snapshot_id,
            ),
        ),
        features=(first, second),
    )
    assert assessment.primary_node_id == "relative_strength"


def test_configuration_is_strict_frozen_and_requires_ordered_unique_labels(tmp_path: Path) -> None:
    valid = {
        "schema_version": 1,
        "method_version": "thesis-relevance-v1",
        "zero_impact": "none",
        "impact_thresholds": [
            {"name": "high", "minimum_score": 0.75},
            {"name": "moderate", "minimum_score": 0.50},
            {"name": "low", "minimum_score": 0.00},
        ],
    }
    config = ThesisRelevanceConfig.model_validate(valid)
    assert config.impact_for(0.0) == ThesisImpact.NONE
    assert config.impact_for(0.49) == ThesisImpact.LOW
    assert config.impact_for(0.50) == ThesisImpact.MODERATE
    assert config.impact_for(0.75) == ThesisImpact.HIGH
    with pytest.raises(ValidationError):
        config.method_version = "mutated"  # type: ignore[misc]

    for invalid in (
        {**valid, "schema_version": True},
        {**valid, "schema_version": 1.0},
        {**valid, "zero_impact": "low"},
        {**valid, "impact_thresholds": list(reversed(valid["impact_thresholds"]))},
        {
            **valid,
            "impact_thresholds": [
                {"name": "high", "minimum_score": 0.75},
                {"name": "high", "minimum_score": 0.50},
                {"name": "low", "minimum_score": 0.00},
            ],
        },
    ):
        with pytest.raises(ValidationError):
            ThesisRelevanceConfig.model_validate(invalid)

    config_path = tmp_path / "relevance.yaml"
    config_path.write_text("schema_version: 1\nunknown: rejected\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        ThesisRelevanceConfig.from_yaml(config_path)


def test_configuration_rejects_none_as_a_positive_score_threshold() -> None:
    with pytest.raises(ValidationError, match="impact threshold labels cannot include none"):
        ThesisRelevanceConfig.model_validate(
            {
                "schema_version": 1,
                "method_version": "thesis-relevance-v1",
                "zero_impact": "none",
                "impact_thresholds": [
                    {"name": "high", "minimum_score": 0.75},
                    {"name": "none", "minimum_score": 0.00},
                ],
            }
        )


@pytest.mark.parametrize("minimum_score", [True, False, "0.5"])
def test_configuration_rejects_coerced_threshold_minimums(minimum_score: object) -> None:
    with pytest.raises(ValidationError, match="minimum_score must be a finite real number"):
        ThesisRelevanceConfig.model_validate(
            {
                "schema_version": 1,
                "method_version": "thesis-relevance-v1",
                "zero_impact": "none",
                "impact_thresholds": [
                    {"name": "high", "minimum_score": 0.75},
                    {"name": "moderate", "minimum_score": minimum_score},
                    {"name": "low", "minimum_score": 0.00},
                ],
            }
        )


def test_configuration_rejects_repeated_minimum_scores() -> None:
    with pytest.raises(ValidationError, match="impact thresholds must be strictly descending"):
        ThesisRelevanceConfig.model_validate(
            {
                "schema_version": 1,
                "method_version": "thesis-relevance-v1",
                "zero_impact": "none",
                "impact_thresholds": [
                    {"name": "high", "minimum_score": 0.75},
                    {"name": "moderate", "minimum_score": 0.75},
                    {"name": "low", "minimum_score": 0.00},
                ],
            }
        )
