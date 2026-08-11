"""Guarded AI integration points.

No model provider is required for the MVP.  These helpers keep future model
calls behind typed inputs and deterministic validation.
"""

from quant_raas.ai.guardrails import NumericFact, validate_numeric_claims

__all__ = ["NumericFact", "validate_numeric_claims"]
