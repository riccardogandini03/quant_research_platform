"""Finding generation, materiality scoring, and deterministic card rendering."""

from quant_raas.research.cards import build_research_card, render_card_markdown
from quant_raas.research.findings import PriceResearchSnapshot, build_price_finding
from quant_raas.research.materiality import MaterialityConfig, MaterialityScorer

__all__ = [
    "MaterialityConfig",
    "MaterialityScorer",
    "PriceResearchSnapshot",
    "build_price_finding",
    "build_research_card",
    "render_card_markdown",
]
