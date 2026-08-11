"""Constrained parsing for research-query filters."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ResearchQuery(BaseModel):
    """Allowed retrieval fields; this object never executes arbitrary SQL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    security_ids: tuple[str, ...] = ()
    finding_categories: tuple[str, ...] = ()
    minimum_materiality: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=20, ge=1, le=200)


def parse_structured_query(payload: str) -> ResearchQuery:
    """Validate provider-produced JSON against the retrieval allowlist."""

    return ResearchQuery.model_validate_json(payload)
