"""Evidence-bound synthesis interface for Phase 2 integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from quant_raas.ai.guardrails import NumericFact, require_evidence_ids, validate_numeric_claims


class ResearchTextModel(Protocol):
    def synthesize(self, payload: dict[str, object]) -> str: ...


@dataclass(slots=True)
class GuardedSynthesizer:
    """Validate a provider's prose against typed facts before returning it."""

    model: ResearchTextModel

    def synthesize(
        self,
        *,
        payload: dict[str, object],
        numeric_facts: list[NumericFact],
        evidence_ids: list[str],
    ) -> str:
        require_evidence_ids(evidence_ids)
        text = self.model.synthesize(payload)
        validation = validate_numeric_claims(text, numeric_facts)
        if not validation.valid:
            unsupported = ", ".join(claim.raw for claim in validation.unsupported_claims)
            raise ValueError(f"synthesis introduced unsupported numbers: {unsupported}")
        return text
