"""Point-in-time thesis selection and deterministic relevance evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import Literal, TypedDict
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from quant_raas.common.clock import ensure_utc
from quant_raas.domain.enums import InvalidationComparator, ThesisImpact, ThesisSelectionStatus
from quant_raas.domain.market import FeatureSnapshot
from quant_raas.domain.research import (
    Thesis,
    ThesisInvalidationRule,
    ThesisNodeContribution,
    ThesisRelevanceAssessment,
    ThesisSignal,
    ThesisVersion,
    ThesisVersionSelection,
)


class ImpactThreshold(BaseModel):
    """One descending, inclusive minimum score for a relevance impact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ThesisImpact
    minimum_score: float = Field(ge=0.0, le=1.0)

    @field_validator("minimum_score")
    @classmethod
    def validate_finite_minimum_score(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("minimum_score must be finite")
        return value


class _SelectionBase(TypedDict):
    thesis_id: UUID
    effective_at: datetime
    knowledge_time: datetime


class ThesisRelevanceConfig(BaseModel):
    """Frozen, versioned settings for deterministic thesis relevance labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    method_version: str = Field(min_length=1, max_length=80)
    zero_impact: ThesisImpact
    impact_thresholds: tuple[ImpactThreshold, ...] = Field(min_length=1)

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value: object) -> int:
        if type(value) is int and value == 1:
            return value
        raise ValueError("schema_version must be the integer 1")

    @model_validator(mode="after")
    def validate_thresholds(self) -> ThesisRelevanceConfig:
        if self.zero_impact is not ThesisImpact.NONE:
            raise ValueError("zero_impact must be none")
        names = tuple(threshold.name for threshold in self.impact_thresholds)
        if len(names) != len(set(names)):
            raise ValueError("impact threshold labels must be unique")
        minimums = tuple(threshold.minimum_score for threshold in self.impact_thresholds)
        if minimums != tuple(sorted(minimums, reverse=True)):
            raise ValueError("impact thresholds must be ordered from highest to lowest")
        if minimums[-1] != 0.0:
            raise ValueError("impact thresholds must include a zero lower bound")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> ThesisRelevanceConfig:
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def impact_for(self, score: float) -> ThesisImpact:
        if not isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("relevance score must be finite and in [0, 1]")
        if score == 0.0:
            return self.zero_impact
        for threshold in self.impact_thresholds:
            if score >= threshold.minimum_score:
                return threshold.name
        raise ValueError("impact thresholds must include a positive-score lower bound")


def select_thesis_version(
    thesis: Thesis,
    versions: Sequence[ThesisVersion],
    *,
    effective_at: datetime,
    knowledge_time: datetime,
) -> ThesisVersionSelection:
    """Select one immutable thesis version without leaking future knowledge."""

    effective = ensure_utc(effective_at)
    known = ensure_utc(knowledge_time)
    base: _SelectionBase = {
        "thesis_id": thesis.thesis_id,
        "effective_at": effective,
        "knowledge_time": known,
    }
    if thesis.created_at > known:
        return ThesisVersionSelection(**base, status=ThesisSelectionStatus.NOT_KNOWN_AT_CUTOFF)
    if thesis.archived_at is not None and thesis.archived_at <= known:
        return ThesisVersionSelection(**base, status=ThesisSelectionStatus.ARCHIVED_AT_CUTOFF)
    approved = [item for item in versions if item.approved_at <= known]
    if not approved:
        return ThesisVersionSelection(**base, status=ThesisSelectionStatus.NOT_YET_APPROVED)
    effective_versions = [item for item in approved if item.valid_from <= effective]
    if not effective_versions:
        return ThesisVersionSelection(**base, status=ThesisSelectionStatus.NOT_YET_EFFECTIVE)
    selected = max(
        effective_versions,
        key=lambda item: (item.valid_from, item.version, item.approved_at),
    )
    if selected.valid_to is not None and selected.valid_to <= effective:
        return ThesisVersionSelection(**base, status=ThesisSelectionStatus.EXPIRED_AT_CUTOFF)
    return ThesisVersionSelection(
        **base,
        status=ThesisSelectionStatus.SELECTED,
        version=selected,
    )


def active_thesis_version(
    thesis: Thesis,
    versions: Sequence[ThesisVersion],
    *,
    effective_at: datetime,
    knowledge_time: datetime,
) -> ThesisVersion | None:
    """Return only the selected version from the explicit two-time result."""

    return select_thesis_version(
        thesis,
        versions,
        effective_at=effective_at,
        knowledge_time=knowledge_time,
    ).version


class ThesisRelevanceEvaluator:
    """Evaluate one thesis version against point-in-time features and signals."""

    def __init__(self, config: ThesisRelevanceConfig) -> None:
        self.config = config

    def assess(
        self,
        version: ThesisVersion,
        *,
        signals: Sequence[ThesisSignal],
        features: Sequence[FeatureSnapshot],
    ) -> ThesisRelevanceAssessment:
        signal_by_name = _unique_by_name(signals, description="signal feature names")
        feature_by_name = _unique_by_name(features, description="feature snapshot names")
        contributions = [
            *(
                self._signal_contribution(
                    node_id=node.node_id,
                    node_kind="driver",
                    feature_names=node.supporting_features,
                    signals=signal_by_name,
                )
                for node in version.content.drivers
            ),
            *(
                self._signal_contribution(
                    node_id=node.node_id,
                    node_kind="risk",
                    feature_names=node.watch_features,
                    signals=signal_by_name,
                )
                for node in version.content.risks
            ),
            *(
                self._invalidation_contribution(node, feature_by_name)
                for node in version.content.invalidation_rules
            ),
        ]
        ordered = tuple(sorted(contributions, key=lambda item: (item.node_kind, item.node_id)))
        score = max((item.score for item in ordered if item.score is not None), default=0.0)
        matched = tuple(item for item in ordered if item.matched_feature_names)
        primary = (
            min(matched, key=lambda item: (-(item.score or 0.0), item.node_id)) if matched else None
        )
        return ThesisRelevanceAssessment(
            thesis_id=version.thesis_id,
            thesis_version_id=version.thesis_version_id,
            score=score,
            impact=self.config.impact_for(score),
            primary_node_id=primary.node_id if primary is not None else None,
            contributions=ordered,
            method_version=self.config.method_version,
        )

    @staticmethod
    def _signal_contribution(
        *,
        node_id: str,
        node_kind: Literal["driver", "risk"],
        feature_names: Sequence[str],
        signals: dict[str, ThesisSignal],
    ) -> ThesisNodeContribution:
        matched = tuple(signals[name] for name in feature_names if name in signals)
        return ThesisNodeContribution(
            node_id=node_id,
            node_kind=node_kind,
            score=max((signal.normalized_strength for signal in matched), default=0.0),
            matched_feature_names=tuple(signal.feature_name for signal in matched),
            feature_snapshot_ids=tuple(signal.feature_snapshot_id for signal in matched),
        )

    @staticmethod
    def _invalidation_contribution(
        rule: ThesisInvalidationRule,
        features: dict[str, FeatureSnapshot],
    ) -> ThesisNodeContribution:
        feature = features.get(rule.feature_name)
        if feature is None:
            return ThesisNodeContribution(
                node_id=rule.node_id,
                node_kind="invalidation_rule",
                unevaluated_reason="feature_missing",
            )
        if isinstance(feature.value, bool) or not isinstance(feature.value, Real):
            return ThesisNodeContribution(
                node_id=rule.node_id,
                node_kind="invalidation_rule",
                unevaluated_reason="feature_non_numeric",
            )
        value = float(feature.value)
        if not isfinite(value):
            return ThesisNodeContribution(
                node_id=rule.node_id,
                node_kind="invalidation_rule",
                unevaluated_reason="feature_non_finite",
            )
        if rule.comparator is InvalidationComparator.GREATER_THAN_OR_EQUAL:
            proximity = (value - rule.warning_threshold) / (
                rule.breach_threshold - rule.warning_threshold
            )
        else:
            proximity = (rule.warning_threshold - value) / (
                rule.warning_threshold - rule.breach_threshold
            )
        return ThesisNodeContribution(
            node_id=rule.node_id,
            node_kind="invalidation_rule",
            score=min(max(proximity, 0.0), 1.0),
            matched_feature_names=(feature.feature_name,),
            feature_snapshot_ids=(feature.feature_snapshot_id,),
        )


def _unique_by_name[T: ThesisSignal | FeatureSnapshot](
    values: Sequence[T],
    *,
    description: str,
) -> dict[str, T]:
    by_name = {item.feature_name: item for item in values}
    if len(by_name) != len(values):
        raise ValueError(f"duplicate {description}")
    return by_name
