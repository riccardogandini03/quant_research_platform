"""Canonical transformations for macro release vintages."""

from __future__ import annotations

import numpy as np
import pandas as pd


def normalize_economic_releases(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate release timestamps and derive surprise/revision when knowable."""

    required = {"event_id", "period_end", "release_timestamp", "actual", "source"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"economic releases are missing columns: {', '.join(missing)}")

    work = frame.copy()
    work["period_end"] = pd.to_datetime(work["period_end"], errors="coerce").dt.date
    work["release_timestamp"] = pd.to_datetime(work["release_timestamp"], utc=True, errors="coerce")
    if work[["period_end", "release_timestamp"]].isna().any().any():
        raise ValueError("economic release dates must be parseable")
    for column in ("actual", "consensus", "prior", "revised_prior"):
        if column not in work:
            work[column] = np.nan
        work[column] = pd.to_numeric(work[column], errors="coerce")

    # Missing consensus/revision remains missing rather than becoming a false zero.
    work["surprise"] = work["actual"] - work["consensus"]
    work["revision"] = work["revised_prior"] - work["prior"]
    work["available_at"] = work["release_timestamp"]
    return work.sort_values(["event_id", "release_timestamp"], kind="mergesort").reset_index(
        drop=True
    )
