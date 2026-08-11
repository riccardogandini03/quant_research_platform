"""Point-in-time evaluation of declarative screen definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from quant_raas.screens.models import (
    ComparisonOperator,
    MissingPolicy,
    ScreenCriterion,
    ScreenDefinition,
)


@dataclass(frozen=True, slots=True)
class ScreenResult:
    as_of: datetime
    matches: tuple[str, ...]
    evaluated: pd.DataFrame
    excluded_for_missing_data: tuple[str, ...]


def _evaluate(values: pd.Series, criterion: ScreenCriterion) -> pd.Series:
    if criterion.operator == ComparisonOperator.IS_FINITE:
        return pd.Series(np.isfinite(values), index=values.index)
    assert criterion.value is not None  # Guaranteed by the validated schema.
    if criterion.operator == ComparisonOperator.GREATER_THAN:
        return values > criterion.value
    if criterion.operator == ComparisonOperator.GREATER_THAN_OR_EQUAL:
        return values >= criterion.value
    if criterion.operator == ComparisonOperator.LESS_THAN:
        return values < criterion.value
    if criterion.operator == ComparisonOperator.LESS_THAN_OR_EQUAL:
        return values <= criterion.value
    if criterion.operator == ComparisonOperator.BETWEEN:
        assert criterion.upper is not None  # Guaranteed by the validated schema.
        return values.between(criterion.value, criterion.upper, inclusive="both")
    raise ValueError(f"unsupported screen operator: {criterion.operator}")


def run_screen(
    features: pd.DataFrame,
    definition: ScreenDefinition,
    *,
    as_of: datetime,
) -> ScreenResult:
    """Evaluate the latest knowable feature vintage for every security."""

    required = {"security_id", "feature_name", "value", "available_at"}
    missing = sorted(required.difference(features.columns))
    if missing:
        raise ValueError(f"feature frame is missing columns: {', '.join(missing)}")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not definition.enabled:
        raise ValueError(f"screen {definition.screen_id!r} is disabled")

    wanted = {criterion.feature for criterion in definition.criteria} | set(
        definition.requires_features
    )
    work = features.loc[features["feature_name"].isin(wanted)].copy()
    work["available_at"] = pd.to_datetime(work["available_at"], utc=True, errors="coerce")
    if work["available_at"].isna().any():
        raise ValueError("available_at contains invalid timestamps")
    cutoff = pd.Timestamp(as_of).tz_convert("UTC")
    work = work.loc[work["available_at"] <= cutoff]
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work = work.replace([np.inf, -np.inf], np.nan)
    work = work.sort_values(["security_id", "feature_name", "available_at"], kind="mergesort")
    latest = work.groupby(["security_id", "feature_name"], sort=False, as_index=False).tail(1)
    wide = latest.pivot(index="security_id", columns="feature_name", values="value")

    absent_globally = sorted(wanted.difference(wide.columns))
    if absent_globally and definition.missing_policy == MissingPolicy.FAIL:
        raise ValueError(f"features unavailable at cutoff: {', '.join(absent_globally)}")
    for feature in absent_globally:
        wide[feature] = np.nan

    missing_mask = (
        wide[list(wanted)].isna().any(axis=1) if not wide.empty else pd.Series(dtype=bool)
    )
    excluded = tuple(sorted(wide.index[missing_mask].astype(str)))
    if excluded and definition.missing_policy == MissingPolicy.FAIL:
        raise ValueError(f"missing screen inputs for securities: {', '.join(excluded[:10])}")

    matches = pd.Series(True, index=wide.index, dtype=bool)
    for criterion in definition.criteria:
        matches &= _evaluate(wide[criterion.feature], criterion).fillna(False)
    evaluated = wide.assign(matches=matches)
    if definition.rank is not None and definition.rank.feature in evaluated:
        evaluated = evaluated.sort_values(
            definition.rank.feature,
            ascending=definition.rank.direction == "ascending",
            kind="mergesort",
        )
    else:
        evaluated = evaluated.sort_index()
    matched_ids = evaluated.index[evaluated["matches"]].astype(str)[: definition.limit]
    return ScreenResult(
        as_of=as_of,
        matches=tuple(matched_ids),
        evaluated=evaluated,
        excluded_for_missing_data=excluded,
    )
