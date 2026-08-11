"""Auditable stage-one materiality and portfolio-priority scoring."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_raas.domain.enums import MaterialityTier
from quant_raas.domain.research import MaterialityScore


class ScoreSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    components: dict[str, float] = Field(min_length=1)
    input_min: float = 0.0
    input_max: float = 1.0
    missing_component_policy: str = Field(default="zero", pattern="^zero$")

    @model_validator(mode="after")
    def validate_weights(self) -> ScoreSettings:
        if self.input_max <= self.input_min:
            raise ValueError("input_max must exceed input_min")
        if any(not math.isfinite(weight) or weight < 0.0 for weight in self.components.values()):
            raise ValueError("component weights must be finite and non-negative")
        if not math.isclose(sum(self.components.values()), 1.0, abs_tol=1e-9):
            raise ValueError("materiality component weights must sum to one")
        return self


class PrioritySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    formula: str = Field(default="sqrt_position_modifier", pattern="^sqrt_position_modifier$")
    k: float = Field(default=1.0, ge=0.0)
    unheld_position_weight: float = Field(default=0.0, ge=0.0)
    maximum_position_weight: float = Field(default=1.0, gt=0.0)


class LabelThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    minimum_score: float = Field(ge=0.0, le=1.0)


class EvidenceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_references: int = Field(default=1, ge=1)
    reject_non_finite_numbers: bool = True
    require_source_available_at: bool = True


class MaterialityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    score_version: str = Field(min_length=1)
    score: ScoreSettings
    priority: PrioritySettings
    labels: tuple[LabelThreshold, ...] = Field(min_length=1)
    evidence: EvidenceSettings = Field(default_factory=EvidenceSettings)

    @model_validator(mode="after")
    def validate_labels(self) -> MaterialityConfig:
        thresholds = [label.minimum_score for label in self.labels]
        if thresholds != sorted(thresholds, reverse=True):
            raise ValueError("materiality labels must be ordered from highest to lowest")
        if thresholds[-1] != 0.0:
            raise ValueError("materiality labels must include a zero lower bound")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> MaterialityConfig:
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


_TIER_ALIASES = {
    "high": MaterialityTier.CRITICAL,
    "critical": MaterialityTier.CRITICAL,
    "material": MaterialityTier.MATERIAL,
    "watch": MaterialityTier.WATCH,
    "informational": MaterialityTier.ROUTINE,
    "routine": MaterialityTier.ROUTINE,
}


class MaterialityScorer:
    """Score intrinsic evidence first and apply position size only to priority."""

    def __init__(self, config: MaterialityConfig) -> None:
        self.config = config

    def score(
        self,
        components: Mapping[str, float | None],
        *,
        position_weight: float | None = None,
    ) -> tuple[MaterialityScore, MaterialityTier]:
        unknown = sorted(set(components).difference(self.config.score.components))
        if unknown:
            raise ValueError(f"unknown materiality components: {', '.join(unknown)}")

        present: dict[str, float] = {}
        for name, value in components.items():
            if value is None:
                continue
            if not math.isfinite(value):
                raise ValueError(f"materiality component {name!r} must be finite")
            if not self.config.score.input_min <= value <= self.config.score.input_max:
                raise ValueError(
                    f"materiality component {name!r} must be in "
                    f"[{self.config.score.input_min}, {self.config.score.input_max}]"
                )
            present[name] = float(value)

        weights = self.config.score.components
        raw_score = sum(present.get(name, 0.0) * weight for name, weight in weights.items())
        available_weight = sum(weights[name] for name in present)
        total_weight = sum(weights.values())
        completeness = available_weight / total_weight if total_weight else 0.0

        if position_weight is None:
            relevance_weight = self.config.priority.unheld_position_weight
        else:
            if not math.isfinite(position_weight):
                raise ValueError("position_weight must be finite")
            # Short positions are as relevant as long positions for inbox order;
            # the signed weight is still retained in portfolio context.
            relevance_weight = min(
                abs(position_weight), self.config.priority.maximum_position_weight
            )
        modifier = 1.0 + self.config.priority.k * math.sqrt(relevance_weight)
        priority_score = raw_score * modifier

        tier = MaterialityTier.ROUTINE
        for threshold in self.config.labels:
            if raw_score >= threshold.minimum_score:
                try:
                    tier = _TIER_ALIASES[threshold.name.lower()]
                except KeyError as error:
                    raise ValueError(f"unsupported materiality label {threshold.name!r}") from error
                break

        result = MaterialityScore(
            component_scores=present,
            component_weights=weights,
            raw_score=raw_score,
            completeness=completeness,
            priority_modifier=modifier,
            priority_score=priority_score,
            config_version=self.config.score_version,
        )
        return result, tier
