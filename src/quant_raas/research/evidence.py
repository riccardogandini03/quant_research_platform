"""Helpers for immutable evidence lineage."""

from __future__ import annotations

from datetime import datetime

from quant_raas.domain.enums import SourceType
from quant_raas.domain.research import EvidenceReference
from quant_raas.research.ids import stable_research_id


def price_bar_evidence(
    *,
    provider: str,
    source_record_id: str,
    effective_at: datetime,
    available_at: datetime,
    ingested_at: datetime,
    uri: str | None = None,
) -> EvidenceReference:
    """Create a repeatable evidence pointer for one normalized provider record."""

    # A corrected vintage may reuse the vendor record ID; availability is part
    # of the evidence identity so the original and correction can coexist.
    key = f"{provider}:{source_record_id}:{available_at.isoformat()}"
    return EvidenceReference(
        evidence_id=stable_research_id("evidence", key),
        source_type=SourceType.MARKET_DATA,
        provider=provider,
        source_record_id=source_record_id,
        effective_at=effective_at,
        available_at=available_at,
        ingested_at=ingested_at,
        uri=uri,
    )


def validate_evidence_cutoff(
    references: tuple[EvidenceReference, ...] | list[EvidenceReference],
    *,
    data_cutoff_at: datetime,
) -> None:
    """Assert that every referenced record was available by the run cutoff."""

    leaked = [
        str(reference.evidence_id)
        for reference in references
        if reference.available_at > data_cutoff_at
    ]
    if leaked:
        raise ValueError(f"evidence unavailable at cutoff: {', '.join(leaked[:5])}")
