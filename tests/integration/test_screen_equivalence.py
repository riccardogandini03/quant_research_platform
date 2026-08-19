"""Integration coverage for repository-backed screen execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from quant_raas.domain.market import FeatureSnapshot
from quant_raas.domain.research import ResearchRun
from quant_raas.domain.security import Security
from quant_raas.feature_store.registry import mvp_price_features
from quant_raas.screens.models import ScreenDefinition
from quant_raas.screens.service import ScreenExecutionService
from quant_raas.storage.repositories import (
    SqlAlchemyFeatureRepository,
    SqlAlchemyResearchRepository,
    SqlAlchemySecurityRepository,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _screen_snapshot(
    identifier: int,
    security_id: UUID,
    research_run_id: UUID,
    feature_name: str,
    value: float,
    effective_at: datetime,
    available_at: datetime,
    *,
    feature_version: str = "price-mvp-v0",
) -> FeatureSnapshot:
    return FeatureSnapshot(
        feature_snapshot_id=UUID(int=identifier),
        security_id=security_id,
        feature_name=feature_name,
        feature_version=feature_version,
        effective_at=effective_at,
        available_at=available_at,
        calculated_at=max(available_at, effective_at) + timedelta(minutes=1),
        value=value,
        research_run_id=research_run_id,
        code_version="test-code-v1",
        config_version="equity-mvp-v0",
    )


@pytest.mark.integration
@pytest.mark.point_in_time
def test_one_off_and_historical_screen_paths_are_identical_at_same_cutoff(
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    second_security = sample_security.model_copy(
        update={"security_id": UUID(int=2), "name": "Second Corp"}
    )
    securities = SqlAlchemySecurityRepository(sqlite_session)
    securities.add_security(sample_security)
    securities.add_security(second_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)

    cutoff = datetime(2024, 1, 9, 22, 0, tzinfo=UTC)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available = effective + timedelta(minutes=5)
    future = cutoff + timedelta(hours=1)
    feature_repository = SqlAlchemyFeatureRepository(sqlite_session)
    feature_repository.upsert_many(
        [
            _screen_snapshot(
                301,
                sample_security.security_id,
                research_run.research_run_id,
                "residual_return_zscore_1d",
                -2.5,
                effective,
                available,
            ),
            _screen_snapshot(
                302,
                sample_security.security_id,
                research_run.research_run_id,
                "dollar_volume_zscore_20d",
                1.2,
                effective,
                available,
            ),
            _screen_snapshot(
                303,
                second_security.security_id,
                research_run.research_run_id,
                "residual_return_zscore_1d",
                -1.0,
                effective,
                available,
            ),
            _screen_snapshot(
                306,
                second_security.security_id,
                research_run.research_run_id,
                "dollar_volume_zscore_20d",
                1.2,
                effective,
                available,
            ),
            _screen_snapshot(
                304,
                sample_security.security_id,
                research_run.research_run_id,
                "residual_return_zscore_1d",
                0.0,
                effective,
                future,
            ),
            _screen_snapshot(
                305,
                second_security.security_id,
                research_run.research_run_id,
                "residual_return_zscore_1d",
                -3.0,
                effective,
                available,
                feature_version="price-mvp-v1",
            ),
        ]
    )

    definition = ScreenDefinition.from_yaml(
        REPOSITORY_ROOT / "configs" / "screens" / "abnormal_residual_decline.yaml"
    )
    service = ScreenExecutionService(feature_repository, mvp_price_features())
    one_off = service.evaluate(
        definition,
        [second_security.security_id, sample_security.security_id],
        as_of=cutoff,
    )
    historical = service.evaluate_history(
        definition,
        [second_security.security_id, sample_security.security_id],
        cutoffs=[cutoff],
    )[0]

    assert one_off.matches == (str(sample_security.security_id),)
    assert one_off.excluded_for_missing_data == ()
    assert historical.matches == one_off.matches
    assert historical.excluded_for_missing_data == one_off.excluded_for_missing_data
    pd.testing.assert_frame_equal(historical.evaluated, one_off.evaluated)


class _NeverCalledFeatureRepository:
    def panel_as_of(self, *args: object, **kwargs: object) -> tuple[FeatureSnapshot, ...]:
        raise AssertionError("repository must not be called")


def _versioned_definition(
    *,
    config_version: str | None = "equity-mvp-v0",
    pins: dict[str, str] | None = None,
) -> ScreenDefinition:
    return ScreenDefinition(
        screen_id="validation-v1",
        name="Validation screen",
        feature_config_version=config_version,
        feature_versions=pins
        or {
            "residual_return_zscore_1d": "price-mvp-v0",
            "dollar_volume_zscore_20d": "price-mvp-v0",
        },
        conditions=[
            {
                "feature": "residual_return_zscore_1d",
                "operator": "less_than",
                "value": -2.0,
            },
            {
                "feature": "dollar_volume_zscore_20d",
                "operator": "greater_than",
                "value": 1.0,
            },
        ],
    )


def test_repository_backed_screen_validation_fails_before_data_access() -> None:
    service = ScreenExecutionService(_NeverCalledFeatureRepository(), mvp_price_features())
    security_ids = [UUID(int=1)]
    cutoff = datetime(2024, 1, 9, 22, 0, tzinfo=UTC)
    complete = {
        "residual_return_zscore_1d": "price-mvp-v0",
        "dollar_volume_zscore_20d": "price-mvp-v0",
    }

    with pytest.raises(ValueError, match="feature_config_version is required"):
        service.evaluate(_versioned_definition(config_version=None), security_ids, as_of=cutoff)
    with pytest.raises(ValueError, match="missing feature version pins"):
        service.evaluate(
            _versioned_definition(pins={"residual_return_zscore_1d": "price-mvp-v0"}),
            security_ids,
            as_of=cutoff,
        )
    with pytest.raises(ValueError, match="unused feature version pins"):
        service.evaluate(
            _versioned_definition(pins={**complete, "unused": "v1"}),
            security_ids,
            as_of=cutoff,
        )
    with pytest.raises(ValueError, match="unknown feature"):
        service.evaluate(
            _versioned_definition(pins={**complete, "residual_return_zscore_1d": "missing-v9"}),
            security_ids,
            as_of=cutoff,
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        service.evaluate_history(_versioned_definition(), security_ids, cutoffs=[cutoff, cutoff])
