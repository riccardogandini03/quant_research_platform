"""Typed boundaries for evidence-grounded document extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel


class TextModel(Protocol):
    """Minimal provider-neutral interface for a structured-output model."""

    def generate_json(self, *, system: str, prompt: str, schema: dict[str, object]) -> str: ...


class EvidenceSpan(BaseModel):
    document_id: str
    start: int
    end: int
    text: str


class ExtractedClaim(BaseModel):
    subject: str
    predicate: str
    object: str
    evidence: list[EvidenceSpan]
    confidence: float


TModel = TypeVar("TModel", bound=BaseModel)


@dataclass(slots=True)
class StructuredExtractor:
    """Ask a model for JSON and validate it before downstream use."""

    client: TextModel

    def extract(self, *, text: str, instructions: str, output_type: type[TModel]) -> TModel:
        if not text.strip():
            raise ValueError("document text cannot be empty")
        raw = self.client.generate_json(
            system=(
                "Extract only facts directly supported by the supplied document. "
                "Return insufficient evidence instead of inferring missing values."
            ),
            prompt=f"{instructions}\n\nDOCUMENT\n{text}",
            schema=output_type.model_json_schema(),
        )
        return output_type.model_validate_json(raw)
