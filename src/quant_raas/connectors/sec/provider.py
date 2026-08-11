"""Configuration gate for future SEC submissions and Company Facts ingestion."""

from __future__ import annotations

from quant_raas.connectors.base import ProviderNotConfigured


class SecFilingProvider:
    """Retain fair-access identity configuration before enabling requests."""

    name = "sec"

    def __init__(self, *, user_agent: str | None = None) -> None:
        self.user_agent = user_agent

    def require_configured(self) -> None:
        if not self.user_agent or "@" not in self.user_agent:
            raise ProviderNotConfigured(
                "SEC_USER_AGENT must identify the research organization and a contact email"
            )
