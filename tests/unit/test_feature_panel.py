from datetime import UTC, datetime, timedelta
from uuid import UUID

import pandas as pd
import pytest

from quant_raas.domain.market import FeatureSnapshot
from quant_raas.feature_store.panel import FEATURE_PANEL_COLUMNS, snapshots_to_frame


def test_empty_feature_panel_has_stable_columns() -> None:
    decision = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    frame = snapshots_to_frame((), decision_at=decision)
    assert tuple(frame.columns) == FEATURE_PANEL_COLUMNS
    assert frame.empty


def test_feature_panel_is_stably_ordered_and_keeps_lineage() -> None:
    decision = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available = decision - timedelta(minutes=1)
    run_id = UUID(int=100)
    snapshots = [
        FeatureSnapshot(
            feature_snapshot_id=UUID(int=2),
            security_id=UUID(int=2),
            feature_name="z",
            feature_version="v1",
            effective_at=available,
            available_at=available,
            calculated_at=decision,
            value=2.0,
            research_run_id=run_id,
            code_version="code-v1",
            config_version="config-v1",
        ),
        FeatureSnapshot(
            feature_snapshot_id=UUID(int=1),
            security_id=UUID(int=1),
            feature_name="a",
            feature_version="v1",
            effective_at=available,
            available_at=available,
            calculated_at=decision,
            value=1.0,
            research_run_id=run_id,
            code_version="code-v1",
            config_version="config-v1",
        ),
    ]
    frame = snapshots_to_frame(snapshots, decision_at=decision)
    assert frame[["security_id", "feature_name", "value"]].to_records(index=False).tolist() == [
        (str(UUID(int=1)), "a", 1.0),
        (str(UUID(int=2)), "z", 2.0),
    ]
    assert frame["decision_at"].tolist() == [pd.Timestamp(decision)] * 2
    assert frame["feature_version"].tolist() == ["v1", "v1"]
    assert frame["config_version"].tolist() == ["config-v1", "config-v1"]


def test_feature_panel_rejects_naive_decision_time() -> None:
    with pytest.raises(ValueError, match="explicit timezone"):
        snapshots_to_frame((), decision_at=datetime(2024, 1, 9, 21, 0))
