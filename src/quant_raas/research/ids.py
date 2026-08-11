"""Stable identifiers for idempotent research outputs."""

from __future__ import annotations

from uuid import UUID, uuid5

# A repository-specific namespace keeps deterministic IDs out of the global URL
# or DNS namespaces while making repeated runs with identical keys idempotent.
RESEARCH_NAMESPACE = UUID("656fba2e-f396-4efd-a529-a2b63d810576")


def stable_research_id(kind: str, key: str) -> UUID:
    if not kind.strip() or not key.strip():
        raise ValueError("stable ID kind and key must be non-empty")
    return uuid5(RESEARCH_NAMESPACE, f"{kind.strip().lower()}:{key.strip()}")
