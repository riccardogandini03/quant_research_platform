"""Small deterministic metrics for research-card evaluation sets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CardEvaluation:
    evidence_precision: float
    evidence_recall: float
    numerical_accuracy: float
    duplicate: bool


def evaluate_evidence(
    predicted_ids: set[str],
    expected_ids: set[str],
    *,
    numeric_claims: int,
    supported_numeric_claims: int,
    duplicate: bool = False,
) -> CardEvaluation:
    """Score lineage coverage without using another model as the judge."""

    true_positive = len(predicted_ids & expected_ids)
    precision = true_positive / len(predicted_ids) if predicted_ids else float(not expected_ids)
    recall = true_positive / len(expected_ids) if expected_ids else 1.0
    numeric_accuracy = supported_numeric_claims / numeric_claims if numeric_claims else 1.0
    return CardEvaluation(precision, recall, numeric_accuracy, duplicate)
