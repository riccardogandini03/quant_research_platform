"""Point-in-time thesis version selection."""

from __future__ import annotations

from datetime import datetime

from quant_raas.domain.research import ThesisVersion


def active_thesis_version(
    versions: list[ThesisVersion] | tuple[ThesisVersion, ...],
    *,
    as_of: datetime,
) -> ThesisVersion | None:
    """Return the latest PM-approved version valid at a historical cutoff."""

    eligible = [
        version
        for version in versions
        if version.valid_from <= as_of
        and (version.valid_to is None or version.valid_to > as_of)
        and version.approved_at <= as_of
    ]
    return max(eligible, key=lambda item: (item.version, item.approved_at)) if eligible else None
