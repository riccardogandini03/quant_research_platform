"""Versioned metadata for deterministic feature calculators."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    name: str
    version: str
    unit: str
    description: str
    required_inputs: tuple[str, ...]
    minimum_history_sessions: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ValueError("feature name and version cannot be empty")
        if self.minimum_history_sessions < 1:
            raise ValueError("minimum_history_sessions must be positive")


class FeatureRegistry:
    """Reject silent redefinition of a versioned financial calculation."""

    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], FeatureDefinition] = {}

    def register(self, definition: FeatureDefinition) -> None:
        key = (definition.name, definition.version)
        existing = self._definitions.get(key)
        if existing is not None and existing != definition:
            raise ValueError(f"feature {definition.name!r} version {definition.version!r} changed")
        self._definitions[key] = definition

    def get(self, name: str, version: str) -> FeatureDefinition:
        try:
            return self._definitions[(name, version)]
        except KeyError as error:
            raise KeyError(f"unknown feature {name!r} version {version!r}") from error

    def list(self) -> tuple[FeatureDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


def mvp_price_features() -> FeatureRegistry:
    """Return definitions matching the Phase-1 daily research service."""

    registry = FeatureRegistry()
    for definition in (
        FeatureDefinition(
            "daily_return",
            "price-mvp-v0",
            "decimal_return",
            "One-session adjusted-close return.",
            ("adjusted_close",),
            2,
        ),
        FeatureDefinition(
            "residual_return_zscore_1d",
            "price-mvp-v0",
            "zscore",
            "Return residual standardized using a factor model fitted through t-1.",
            ("adjusted_close", "benchmark_returns"),
            64,
        ),
        FeatureDefinition(
            "dollar_volume_zscore_20d",
            "price-mvp-v0",
            "zscore",
            "Log dollar volume versus the prior 20 completed sessions.",
            ("close", "volume"),
            21,
        ),
        FeatureDefinition(
            "realized_volatility_20d",
            "price-mvp-v0",
            "annualized_decimal",
            "Sample standard deviation of 20 daily returns, annualized by sqrt(252).",
            ("adjusted_close",),
            21,
        ),
        FeatureDefinition(
            "beta_126d",
            "price-mvp-v0",
            "coefficient",
            "Rolling market beta estimated through t-1.",
            ("adjusted_close", "market_returns"),
            64,
        ),
        FeatureDefinition(
            "relative_return_sector_63d",
            "price-mvp-v0",
            "decimal_return",
            "Compounded exact relative return versus the configured sector benchmark.",
            ("adjusted_close", "sector_returns"),
            64,
        ),
    ):
        registry.register(definition)
    return registry
