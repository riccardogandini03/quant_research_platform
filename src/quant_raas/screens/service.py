"""Repository-backed execution shared by current and historical screens."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from uuid import UUID

import pandas as pd

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
        requested_ids = tuple(sorted(set(security_ids), key=str))
        snapshots = self.features.panel_as_of(
            requested_ids,
            versions,
            config_version=definition.feature_config_version,
            as_of=cutoff,
        )
        placeholder_feature = next(iter(versions))
        frame = _with_requested_universe(
            snapshots_to_frame(snapshots, decision_at=cutoff),
            requested_ids,
            feature_name=placeholder_feature,
            feature_version=versions[placeholder_feature],
            config_version=definition.feature_config_version,
            cutoff=cutoff,
        )
        return run_screen(
            frame,
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
        if not definition.feature_config_version.strip():
            raise ValueError("feature_config_version cannot be empty")
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


def _with_requested_universe(
    frame: pd.DataFrame,
    security_ids: Sequence[UUID],
    *,
    feature_name: str,
    feature_version: str,
    config_version: str,
    cutoff: datetime,
) -> pd.DataFrame:
    present_ids = set(frame["security_id"].astype(str))
    absent_ids = tuple(
        str(security_id) for security_id in security_ids if str(security_id) not in present_ids
    )
    if not absent_ids:
        return frame
    placeholders = pd.DataFrame.from_records(
        [
            {
                "decision_at": cutoff,
                "security_id": security_id,
                "feature_name": feature_name,
                "feature_version": feature_version,
                "value": float("nan"),
                "effective_at": cutoff,
                "available_at": cutoff,
                "calculated_at": cutoff,
                "config_version": config_version,
                "code_version": "",
            }
            for security_id in absent_ids
        ],
        columns=frame.columns,
    )
    return pd.concat((frame, placeholders), ignore_index=True)
