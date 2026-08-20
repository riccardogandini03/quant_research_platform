"""Strict schema for declarative quantitative screens."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ComparisonOperator(StrEnum):
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    BETWEEN = "between"
    IS_FINITE = "is_finite"


class MissingPolicy(StrEnum):
    EXCLUDE = "exclude"
    FAIL = "fail"


class ScreenCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feature: str = Field(min_length=1)
    operator: ComparisonOperator
    value: float | None = None
    upper: float | None = None

    @model_validator(mode="after")
    def validate_between(self) -> ScreenCriterion:
        if self.operator == ComparisonOperator.IS_FINITE:
            if self.value is not None or self.upper is not None:
                raise ValueError("is_finite does not accept value bounds")
            return self
        if self.value is None:
            raise ValueError(f"{self.operator} requires a value")
        if self.operator == ComparisonOperator.BETWEEN:
            if self.upper is None:
                raise ValueError("between criteria require an upper bound")
            if self.upper < self.value:
                raise ValueError("between upper bound must be >= lower bound")
        elif self.upper is not None:
            raise ValueError("upper is only valid for a between criterion")
        return self


class ScreenRanking(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feature: str = Field(min_length=1)
    direction: str = Field(pattern="^(ascending|descending)$")


class ScreenDefinition(BaseModel):
    """A versioned screen that can be evaluated live or at a historical cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    screen_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    enabled: bool = True
    universe: str = "coverage"
    as_of_policy: str = "latest_complete_session"
    minimum_history_sessions: int = Field(default=1, ge=1)
    feature_config_version: str | None = Field(default=None, min_length=1)
    feature_versions: dict[str, str] = Field(default_factory=dict)
    requires_features: tuple[str, ...] = ()
    conditions: tuple[ScreenCriterion, ...] = Field(min_length=1)
    rank: ScreenRanking | None = None
    limit: int = Field(default=25, ge=1, le=10_000)
    missing_policy: MissingPolicy = MissingPolicy.EXCLUDE

    @property
    def criteria(self) -> tuple[ScreenCriterion, ...]:
        """Expose a domain-oriented name while retaining the YAML contract."""

        return self.conditions

    @field_validator("feature_config_version")
    @classmethod
    def validate_feature_config_version(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("feature_config_version cannot be empty")
        return value

    @field_validator("feature_versions")
    @classmethod
    def validate_feature_versions(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not name.strip() or not version.strip() for name, version in value.items()):
            raise ValueError("feature version names and values cannot be empty")
        return value

    @property
    def referenced_features(self) -> tuple[str, ...]:
        names = [criterion.feature for criterion in self.criteria]
        names.extend(self.requires_features)
        if self.rank is not None:
            names.append(self.rank.feature)
        return tuple(dict.fromkeys(names))

    @classmethod
    def from_yaml(cls, path: str | Path) -> ScreenDefinition:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(payload)
