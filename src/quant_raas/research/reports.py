"""Morning-brief composition from already ranked research cards."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_raas.domain.enums import MaterialityTier
from quant_raas.domain.research import ResearchCard
from quant_raas.research.cards import render_card_markdown

_TIER_RANK = {
    MaterialityTier.CRITICAL: 3,
    MaterialityTier.MATERIAL: 2,
    MaterialityTier.WATCH: 1,
    MaterialityTier.ROUTINE: 0,
}


def build_morning_brief(
    cards: Sequence[ResearchCard],
    *,
    security_labels: Mapping[str, str],
    limit: int = 8,
) -> str:
    """Return a compact brief; routine cards remain queryable but are suppressed."""

    if limit < 1:
        raise ValueError("limit must be positive")
    material = [card for card in cards if card.materiality_tier != MaterialityTier.ROUTINE]
    material.sort(
        key=lambda card: (-_TIER_RANK[card.materiality_tier], card.as_of, str(card.security_id)),
        reverse=False,
    )
    selected = material[:limit]
    if not selected:
        return "# Morning research brief\n\nNo material quantitative developments at this cutoff.\n"
    rendered = [
        render_card_markdown(
            card,
            security_label=security_labels.get(str(card.security_id), str(card.security_id)),
        )
        for card in selected
    ]
    return "# Morning research brief\n\n" + "\n\n---\n\n".join(rendered)
