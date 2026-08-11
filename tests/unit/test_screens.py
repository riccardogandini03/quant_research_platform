"""Declarative screens use strict schemas and latest knowable feature vintages."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from quant_raas.screens.engine import run_screen
from quant_raas.screens.models import ScreenDefinition

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_all_repository_screen_definitions_validate() -> None:
    definitions = {
        path.name: ScreenDefinition.from_yaml(path)
        for path in sorted((REPOSITORY_ROOT / "configs" / "screens").glob("*.yaml"))
    }
    assert set(definitions) == {
        "abnormal_residual_decline.yaml",
        "cheap_positive_revisions.yaml",
        "relative_strength_breakout.yaml",
    }
    assert definitions["abnormal_residual_decline.yaml"].enabled
    assert not definitions["cheap_positive_revisions.yaml"].enabled
    # Enabled Phase-1 screens consume the horizon-versioned names persisted by
    # DailyResearchService; generic aliases would silently produce no matches.
    assert tuple(
        criterion.feature for criterion in definitions["abnormal_residual_decline.yaml"].criteria
    ) == ("residual_return_zscore_1d", "dollar_volume_zscore_20d")
    assert tuple(
        criterion.feature for criterion in definitions["relative_strength_breakout.yaml"].criteria
    ) == ("relative_return_sector_63d", "realized_volatility_20d")


def _feature_panel() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("A", "residual_return_zscore_1d", -2.5, "2024-01-05T20:00:00Z"),
            # This correction exists in storage but is unknowable at the cutoff.
            ("A", "residual_return_zscore_1d", 0.0, "2024-01-06T20:00:00Z"),
            ("A", "dollar_volume_zscore_20d", 1.2, "2024-01-05T20:00:00Z"),
            ("B", "residual_return_zscore_1d", -1.0, "2024-01-05T20:00:00Z"),
            ("B", "dollar_volume_zscore_20d", 2.0, "2024-01-05T20:00:00Z"),
        ],
        columns=["security_id", "feature_name", "value", "available_at"],
    )


@pytest.mark.point_in_time
def test_screen_selects_latest_vintage_available_at_cutoff() -> None:
    definition = ScreenDefinition.from_yaml(
        REPOSITORY_ROOT / "configs" / "screens" / "abnormal_residual_decline.yaml"
    )
    as_of = datetime(2024, 1, 5, 21, 0, tzinfo=UTC)
    result = run_screen(_feature_panel(), definition, as_of=as_of)
    assert result.matches == ("A",)
    assert result.evaluated.loc["A", "residual_return_zscore_1d"] == pytest.approx(-2.5)

    # Adding another future revision must not change an earlier screen result.
    future = pd.DataFrame(
        [("A", "dollar_volume_zscore_20d", -10.0, "2024-01-07T20:00:00Z")],
        columns=["security_id", "feature_name", "value", "available_at"],
    )
    repeated = run_screen(
        pd.concat([_feature_panel(), future], ignore_index=True),
        definition,
        as_of=as_of,
    )
    assert repeated.matches == result.matches
    pd.testing.assert_frame_equal(repeated.evaluated, result.evaluated)


def test_disabled_screen_fails_closed() -> None:
    definition = ScreenDefinition.from_yaml(
        REPOSITORY_ROOT / "configs" / "screens" / "cheap_positive_revisions.yaml"
    )
    with pytest.raises(ValueError, match="is disabled"):
        run_screen(
            _feature_panel(),
            definition,
            as_of=datetime(2024, 1, 5, 21, 0, tzinfo=UTC),
        )
