"""Canonical tabular representation of typed feature snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd

from quant_raas.common.clock import ensure_utc
from quant_raas.domain.market import FeatureSnapshot

FEATURE_PANEL_COLUMNS = (
    "decision_at",
    "security_id",
    "feature_name",
    "feature_version",
    "value",
    "effective_at",
    "available_at",
    "calculated_at",
    "config_version",
    "code_version",
)


def snapshots_to_frame(
    snapshots: Sequence[FeatureSnapshot],
    *,
    decision_at: datetime,
) -> pd.DataFrame:
    cutoff = ensure_utc(decision_at)
    rows = [
        {
            "decision_at": cutoff,
            "security_id": str(item.security_id),
            "feature_name": item.feature_name,
            "feature_version": item.feature_version,
            "value": item.value,
            "effective_at": item.effective_at,
            "available_at": item.available_at,
            "calculated_at": item.calculated_at,
            "config_version": item.config_version,
            "code_version": item.code_version,
        }
        for item in snapshots
    ]
    frame = pd.DataFrame.from_records(rows, columns=FEATURE_PANEL_COLUMNS)
    if frame.empty:
        return frame
    return frame.sort_values(["security_id", "feature_name"], kind="mergesort").reset_index(
        drop=True
    )
