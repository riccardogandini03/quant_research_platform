"""Point-in-time event-window extraction on exchange session data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from quant_raas.quant.statistics import StatisticalTestResult, mean_test_hac

EventTiming = Literal["BMO", "AMC", "INTRADAY", "DATE_ONLY"]
OverlapPolicy = Literal["flag", "exclude", "allow"]
ReturnKind = Literal["simple", "log"]
_TimestampInput = int | float | str | date | datetime | np.datetime64
_MissingScalarInput = str | float | pd.Timestamp | np.datetime64


@dataclass(frozen=True, slots=True)
class EventWindow:
    """Inclusive session offsets relative to the response session at offset zero."""

    name: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError("window name must be a non-empty identifier-like string")
        if self.start > self.end:
            raise ValueError("window start cannot be after window end")


@dataclass(frozen=True, slots=True)
class EventStudySpec:
    """Event-study conventions, including mutually exclusive return windows."""

    windows: tuple[EventWindow, ...]
    exchange_timezone: str = "America/New_York"
    market_open: time = time(9, 30)
    market_close: time = time(16, 0)
    return_kind: ReturnKind = "simple"
    overlap_policy: OverlapPolicy = "flag"

    def __post_init__(self) -> None:
        if not self.windows:
            raise ValueError("at least one event window is required")
        if len({window.name for window in self.windows}) != len(self.windows):
            raise ValueError("event window names must be unique")
        occupied: set[int] = set()
        for window in self.windows:
            offsets = set(range(window.start, window.end + 1))
            if occupied.intersection(offsets):
                raise ValueError("event windows cannot overlap")
            occupied.update(offsets)
        if self.market_open >= self.market_close:
            raise ValueError("market_open must be before market_close")
        if self.return_kind not in {"simple", "log"}:
            raise ValueError("return_kind must be 'simple' or 'log'")
        if self.overlap_policy not in {"flag", "exclude", "allow"}:
            raise ValueError("unsupported overlap_policy")
        ZoneInfo(self.exchange_timezone)


@dataclass(frozen=True, slots=True)
class SessionAlignment:
    """Response session chosen for one timestamped event."""

    response_session: pd.Timestamp | None
    timing: EventTiming
    rule: str


@dataclass(frozen=True, slots=True)
class EventStudyResult:
    """Per-event returns and audit flags produced by an event-study specification."""

    observations: pd.DataFrame
    spec: EventStudySpec


def standard_event_spec(
    *,
    pre_sessions: int = 5,
    post_sessions: int = 5,
    exchange_timezone: str = "America/New_York",
    overlap_policy: OverlapPolicy = "flag",
) -> EventStudySpec:
    """Build non-overlapping pre/event/post windows with dynamic labels."""

    if pre_sessions < 1 or post_sessions < 1:
        raise ValueError("pre_sessions and post_sessions must be positive")
    return EventStudySpec(
        windows=(
            EventWindow(f"pre_{pre_sessions}d", -pre_sessions, -1),
            EventWindow("event_day", 0, 0),
            EventWindow(f"post_{post_sessions}d", 1, post_sessions),
        ),
        exchange_timezone=exchange_timezone,
        overlap_policy=overlap_policy,
    )


def _aware_timestamp(value: object, *, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(cast(_TimestampInput, value))
    if pd.isna(timestamp):
        raise ValueError(f"{name} contains a missing timestamp")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return timestamp


def _session_lookup(sessions: pd.Index) -> tuple[list[pd.Timestamp], dict[date, int]]:
    labels = [pd.Timestamp(cast(_TimestampInput, label)) for label in sessions]
    if len(set(labels)) != len(labels):
        raise ValueError("session labels must be unique")
    session_dates = [label.date() for label in labels]
    if len(set(session_dates)) != len(session_dates):
        raise ValueError("session labels must map one-to-one to calendar dates")
    if session_dates != sorted(session_dates):
        raise ValueError("session labels must be sorted in increasing order")
    return labels, {session_date: position for position, session_date in enumerate(session_dates)}


def _normalize_timing(value: object | None) -> EventTiming | None:
    if value is None or pd.isna(cast(_MissingScalarInput, value)):
        return None
    normalized = str(value).strip().upper().replace("-", "_")
    aliases: dict[str, EventTiming] = {
        "BMO": "BMO",
        "BEFORE_MARKET_OPEN": "BMO",
        "AMC": "AMC",
        "AFTER_MARKET_CLOSE": "AMC",
        "INTRADAY": "INTRADAY",
        "DATE_ONLY": "DATE_ONLY",
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported event timing: {value}")
    return aliases[normalized]


def align_event_to_session(
    event_at: object,
    sessions: pd.Index,
    *,
    timing: object | None = None,
    exchange_timezone: str = "America/New_York",
    market_open: time = time(9, 30),
    market_close: time = time(16, 0),
) -> SessionAlignment:
    """Align an event to the first daily bar able to reflect the information.

    ``BMO`` maps to the same exchange date when it is a session, ``AMC`` maps
    strictly to the next session, and weekends/holidays roll forward.  Without
    an explicit timing flag, the event's exchange-local timestamp determines
    BMO, intraday, or AMC behavior.
    """

    if market_open >= market_close:
        raise ValueError("market_open must be before market_close")
    labels, positions = _session_lookup(sessions)
    timestamp = _aware_timestamp(event_at, name="event_at")
    local_timestamp = timestamp.tz_convert(ZoneInfo(exchange_timezone))
    normalized_timing = _normalize_timing(timing)
    if normalized_timing is None:
        local_time = local_timestamp.time().replace(tzinfo=None)
        if local_time < market_open:
            normalized_timing = "BMO"
        elif local_time >= market_close:
            normalized_timing = "AMC"
        else:
            normalized_timing = "INTRADAY"

    local_date = local_timestamp.date()
    available_dates = sorted(positions)
    if normalized_timing == "AMC":
        candidates = [session_date for session_date in available_dates if session_date > local_date]
        rule = "strict_next_session_after_close"
    else:
        candidates = [
            session_date for session_date in available_dates if session_date >= local_date
        ]
        rule = "same_or_next_open_session"
    if not candidates:
        return SessionAlignment(None, normalized_timing, "no_future_session")
    selected = candidates[0]
    rolled_for_closed_date = (normalized_timing == "AMC" and (selected - local_date).days > 1) or (
        normalized_timing != "AMC" and selected != local_date
    )
    if rolled_for_closed_date:
        rule += "_holiday_or_weekend_roll"
    return SessionAlignment(labels[positions[selected]], normalized_timing, rule)


def _filter_events_as_of(
    events: pd.DataFrame,
    *,
    as_of: object | None,
    event_time_col: str,
    available_col: str | None,
) -> pd.DataFrame:
    work = events.copy()
    if event_time_col not in work:
        raise ValueError(f"missing required event column: {event_time_col}")
    event_times = work[event_time_col].map(
        lambda value: _aware_timestamp(value, name=event_time_col)
    )
    work[event_time_col] = event_times
    if as_of is None:
        return work
    cutoff = _aware_timestamp(as_of, name="as_of").tz_convert("UTC")
    knowledge_col = event_time_col if available_col is None else available_col
    if knowledge_col not in work:
        raise ValueError(f"missing required availability column: {knowledge_col}")
    available = work[knowledge_col].map(
        lambda value: _aware_timestamp(value, name=knowledge_col).tz_convert("UTC")
    )
    return work.loc[available <= cutoff].copy()


def extract_event_windows(
    session_returns: pd.Series,
    events: pd.DataFrame,
    spec: EventStudySpec,
    *,
    event_time_col: str = "event_at",
    event_id_col: str = "event_id",
    timing_col: str | None = "timing",
    available_col: str | None = "available_at",
    as_of: object | None = None,
) -> EventStudyResult:
    """Extract complete, non-overlapping return windows for timestamped events.

    Missing returns or an out-of-range boundary make that window incomplete and
    leave its return missing.  ``as_of`` filters by ``available_col``; callers
    must also supply a return series whose bars were available at that cutoff.
    """

    if session_returns.index.has_duplicates or not session_returns.index.is_monotonic_increasing:
        raise ValueError("session_returns index must be sorted and unique")
    returns = cast(
        "pd.Series[float]",
        pd.to_numeric(session_returns, errors="coerce").replace([np.inf, -np.inf], np.nan),
    )
    _, date_positions = _session_lookup(returns.index)
    work = _filter_events_as_of(
        events,
        as_of=as_of,
        event_time_col=event_time_col,
        available_col=available_col,
    )
    if event_id_col not in work:
        work[event_id_col] = work.index.map(str)
    work[event_id_col] = work[event_id_col].astype(str)
    if work[event_id_col].duplicated().any():
        raise ValueError("event IDs must be unique")

    rows: list[dict[str, object]] = []
    occupied_ranges: list[tuple[int, int] | None] = []
    minimum_offset = min(window.start for window in spec.windows)
    maximum_offset = max(window.end for window in spec.windows)
    for _, event in work.iterrows():
        timing = event[timing_col] if timing_col is not None and timing_col in work else None
        alignment = align_event_to_session(
            event[event_time_col],
            returns.index,
            timing=timing,
            exchange_timezone=spec.exchange_timezone,
            market_open=spec.market_open,
            market_close=spec.market_close,
        )
        row: dict[str, object] = {
            "event_id": str(event[event_id_col]),
            "event_at": event[event_time_col],
            "response_session": alignment.response_session,
            "event_timing": alignment.timing,
            "alignment_rule": alignment.rule,
        }
        response_position: int | None = None
        if alignment.response_session is not None:
            response_position = date_positions[alignment.response_session.date()]
        occupied_ranges.append(
            None
            if response_position is None
            else (response_position + minimum_offset, response_position + maximum_offset)
        )
        complete_flags: list[bool] = []
        for window in spec.windows:
            complete = False
            value = float("nan")
            if response_position is not None:
                start = response_position + window.start
                end = response_position + window.end
                if start >= 0 and end < len(returns):
                    sample = returns.iloc[start : end + 1]
                    complete = len(sample) == window.end - window.start + 1 and bool(
                        sample.notna().all()
                    )
                    if complete:
                        if spec.return_kind == "simple":
                            value = float(np.prod(1.0 + sample.to_numpy(dtype=float)) - 1.0)
                        else:
                            value = float(sample.sum())
            row[window.name] = value
            row[f"{window.name}_complete"] = complete
            complete_flags.append(complete)
        row["is_complete"] = all(complete_flags)
        rows.append(row)

    overlaps = [False] * len(rows)
    for left in range(len(occupied_ranges)):
        left_range = occupied_ranges[left]
        if left_range is None:
            continue
        for right in range(left + 1, len(occupied_ranges)):
            right_range = occupied_ranges[right]
            if right_range is None:
                continue
            if max(left_range[0], right_range[0]) <= min(left_range[1], right_range[1]):
                overlaps[left] = True
                overlaps[right] = True
    for index, row in enumerate(rows):
        row["overlaps_another_event"] = overlaps[index]
        row["is_eligible"] = bool(row["is_complete"]) and not (
            spec.overlap_policy == "exclude" and overlaps[index]
        )
    observations = pd.DataFrame(rows)
    if observations.empty:
        columns = [
            "event_id",
            "event_at",
            "response_session",
            "event_timing",
            "alignment_rule",
            *[item for window in spec.windows for item in (window.name, f"{window.name}_complete")],
            "is_complete",
            "overlaps_another_event",
            "is_eligible",
        ]
        observations = pd.DataFrame(columns=columns)
    return EventStudyResult(observations=observations, spec=spec)


def summarize_event_windows(
    result: EventStudyResult,
    *,
    minimum_observations: int = 20,
    max_hac_lags: int | None = None,
    eligible_only: bool = True,
) -> dict[str, StatisticalTestResult]:
    """Estimate each event-window mean with HAC standard errors."""

    frame = result.observations
    if eligible_only and "is_eligible" in frame:
        frame = frame.loc[frame["is_eligible"].fillna(False)]
    return {
        window.name: mean_test_hac(
            frame[window.name] if window.name in frame else pd.Series(dtype="float64"),
            max_lags=max_hac_lags,
            minimum_observations=minimum_observations,
        )
        for window in result.spec.windows
    }
