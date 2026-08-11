"""Dependency routing for future event-driven recalculation."""

from __future__ import annotations

from quant_raas.domain.enums import EventType

_AFFECTED_MODULES = {
    EventType.EARNINGS: ("earnings", "estimates", "price_anomaly", "valuation"),
    EventType.GUIDANCE: ("estimates", "price_anomaly", "valuation"),
    EventType.FILING: ("filing_diff", "fundamental_change"),
    EventType.FOMC: ("macro_sensitivity", "price_anomaly"),
    EventType.CPI: ("macro_sensitivity", "price_anomaly"),
    EventType.MACRO_RELEASE: ("macro_sensitivity", "price_anomaly"),
}


def affected_modules(event_type: EventType) -> tuple[str, ...]:
    """Return only the calculators invalidated by an incoming event."""

    return _AFFECTED_MODULES.get(event_type, ("price_anomaly",))
