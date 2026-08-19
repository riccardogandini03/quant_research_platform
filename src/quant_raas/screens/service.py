"""Repository-backed execution shared by current and historical screens."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from uuid import UUID

from quant_raas.common.clock import ensure_utc
from quant_raas.domain.protocols import FeatureRepository
from quant_raas.feature_store.panel import snapshots_to_frame
from quant_raas.feature_store.registry import FeatureRegistry
from quant_raas.screens.engine import ScreenResult, run_screen
from quant_raas.screens.models import ScreenDefinition


class ScreenExecutionService:
    """Retrieve a point-in-time panel and evaluate its screen definition."""

    def __init__(self, features: FeatureRepository, registry: FeatureRegistry) -> None:
        self.features = features
        self.registry = registry

    def evaluate(
        self,
        definition: ScreenDefinition,
        security_ids: Sequence[UUID],
        *,
        as_of: datetime,
    ) -> ScreenResult:
        """Evaluate a screen from the feature versions knowable at ``as_of``."""

        cutoff = ensure_utc(as_of)
        if not definition.enabled:
            raise ValueError(f"screen {definition.screen_id!r} is disabled")
        versions = self._validated_versions(definition)
        assert definition.feature_config_version is not None
        snapshots = self.features.panel_as_of(
            security_ids,
            versions,
            config_version=definition.feature_config_version,
            as_of=cutoff,
        )
        return run_screen(
            snapshots_to_frame(snapshots, decision_at=cutoff),
            definition,
            as_of=cutoff,
        )

    def evaluate_history(
        self,
        definition: ScreenDefinition,
        security_ids: Sequence[UUID],
        *,
        cutoffs: Sequence[datetime],
    ) -> tuple[ScreenResult, ...]:
        """Evaluate the same screen at each strictly increasing cutoff."""

        normalized = tuple(ensure_utc(cutoff) for cutoff in cutoffs)
        if any(current >= following for current, following in pairwise(normalized)):
            raise ValueError("historical screen cutoffs must be strictly increasing")
        return tuple(self.evaluate(definition, security_ids, as_of=cutoff) for cutoff in normalized)

    def _validated_versions(self, definition: ScreenDefinition) -> dict[str, str]:
        if definition.feature_config_version is None:
            raise ValueError("feature_config_version is required for repository-backed screens")
        required = set(definition.referenced_features)
        provided = set(definition.feature_versions)
        missing = sorted(required - provided)
        unused = sorted(provided - required)
        if missing:
            raise ValueError(f"missing feature version pins: {', '.join(missing)}")
        if unused:
            raise ValueError(f"unused feature version pins: {', '.join(unused)}")
        for name in sorted(required):
            try:
                self.registry.get(name, definition.feature_versions[name])
            except KeyError as error:
                raise ValueError(str(error)) from error
        return {name: definition.feature_versions[name] for name in sorted(required)}
