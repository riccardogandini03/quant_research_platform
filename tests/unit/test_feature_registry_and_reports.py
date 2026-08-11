"""Feature versioning and deterministic report composition contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from quant_raas.domain.enums import ConfidenceLevel, MaterialityTier
from quant_raas.domain.research import ResearchCard
from quant_raas.feature_store.registry import (
    FeatureDefinition,
    FeatureRegistry,
    mvp_price_features,
)
from quant_raas.research.reports import build_morning_brief


def test_feature_registry_is_idempotent_but_rejects_silent_redefinition() -> None:
    definition = FeatureDefinition(
        name="example_signal",
        version="v1",
        unit="zscore",
        description="A pinned example calculation.",
        required_inputs=("price",),
        minimum_history_sessions=20,
    )
    registry = FeatureRegistry()
    registry.register(definition)
    registry.register(definition)
    assert registry.get("example_signal", "v1") == definition
    assert registry.list() == (definition,)

    changed = FeatureDefinition(
        name="example_signal",
        version="v1",
        unit="decimal_return",
        description="Changed without a version bump.",
        required_inputs=("price",),
    )
    with pytest.raises(ValueError, match="version 'v1' changed"):
        registry.register(changed)
    with pytest.raises(KeyError, match="unknown feature"):
        registry.get("missing", "v1")


def test_mvp_registry_matches_daily_service_versioned_feature_contract() -> None:
    definitions = {item.name: item for item in mvp_price_features().list()}
    assert set(definitions) == {
        "daily_return",
        "residual_return_zscore_1d",
        "dollar_volume_zscore_20d",
        "realized_volatility_20d",
        "beta_126d",
        "relative_return_sector_63d",
    }
    assert definitions["daily_return"].minimum_history_sessions == 2
    assert definitions["dollar_volume_zscore_20d"].minimum_history_sessions == 21
    assert all(item.version == "price-mvp-v0" for item in definitions.values())


def _card(*, identifier: int, tier: MaterialityTier, as_of: datetime) -> ResearchCard:
    cutoff = as_of + timedelta(minutes=5)
    return ResearchCard(
        card_id=UUID(int=identifier),
        card_key=f"test-card:{identifier}",
        research_run_id=UUID(int=100),
        security_id=UUID(int=identifier + 10),
        as_of=as_of,
        created_at=cutoff + timedelta(minutes=1),
        materiality_tier=tier,
        change=f"Change {identifier}",
        confidence=ConfidenceLevel.HIGH,
        renderer_version="test-v1",
        data_cutoff_at=cutoff,
    )


def test_morning_brief_suppresses_routine_and_ranks_materiality() -> None:
    as_of = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    routine = _card(identifier=1, tier=MaterialityTier.ROUTINE, as_of=as_of)
    watch = _card(identifier=2, tier=MaterialityTier.WATCH, as_of=as_of)
    material = _card(identifier=3, tier=MaterialityTier.MATERIAL, as_of=as_of)
    labels = {
        str(routine.security_id): "Routine Co",
        str(watch.security_id): "Watch Co",
        str(material.security_id): "Material Co",
    }
    brief = build_morning_brief([watch, routine, material], security_labels=labels)
    assert brief.startswith("# Morning research brief")
    assert "Routine Co" not in brief
    assert brief.index("Material Co") < brief.index("Watch Co")
    assert build_morning_brief([routine], security_labels=labels).endswith(
        "No material quantitative developments at this cutoff.\n"
    )
