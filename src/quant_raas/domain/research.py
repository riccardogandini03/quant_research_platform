"""Research findings, cards, thesis, and reproducibility contracts."""

from __future__ import annotations

import re
from collections.abc import Iterable
from math import isfinite
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from quant_raas.common.clock import UtcDatetime, utc_now
from quant_raas.domain.base import DomainModel
from quant_raas.domain.enums import (
    BatchStatus,
    ConfidenceLevel,
    FeedbackKind,
    FindingCategory,
    InvalidationComparator,
    MaterialityTier,
    SourceType,
    ThesisDirection,
    ThesisImpact,
    ThesisRiskSeverity,
    ThesisSelectionStatus,
    ThesisStatus,
)


class ResearchRun(DomainModel):
    """One pinned execution of the daily research pipeline."""

    research_run_id: UUID = Field(default_factory=uuid4)
    run_key: str = Field(min_length=8, max_length=160)
    run_type: str = Field(default="daily", min_length=1, max_length=80)
    as_of: UtcDatetime
    data_cutoff_at: UtcDatetime
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    status: BatchStatus = BatchStatus.PENDING
    code_version: str = Field(min_length=1, max_length=80)
    config_version: str = Field(min_length=1, max_length=80)
    ingestion_batch_ids: tuple[UUID, ...] = ()
    error_message: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_run_timing(self) -> ResearchRun:
        if self.as_of > self.data_cutoff_at:
            raise ValueError("as_of cannot be later than data_cutoff_at")
        if self.data_cutoff_at > self.started_at:
            raise ValueError("data_cutoff_at cannot be later than started_at")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if (
            self.status in {BatchStatus.SUCCEEDED, BatchStatus.PARTIAL, BatchStatus.FAILED}
            and self.completed_at is None
        ):
            raise ValueError("terminal research runs require completed_at")
        return self


class EvidenceReference(DomainModel):
    """Immutable pointer from research output back to an input record."""

    evidence_id: UUID = Field(default_factory=uuid4)
    source_type: SourceType
    provider: str = Field(min_length=1, max_length=80)
    source_record_id: str = Field(min_length=1, max_length=256)
    effective_at: UtcDatetime
    available_at: UtcDatetime
    ingested_at: UtcDatetime
    uri: str | None = Field(default=None, max_length=2000)
    label: str | None = Field(default=None, max_length=300)
    content_hash: str | None = Field(default=None, min_length=8, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence_timing(self) -> EvidenceReference:
        if self.available_at > self.ingested_at:
            raise ValueError("available_at cannot be later than ingested_at")
        return self


class QuantMetric(DomainModel):
    """Typed numerical evidence shown on a finding or card."""

    name: str = Field(min_length=1, max_length=160)
    value: float
    unit: str | None = Field(default=None, max_length=40)
    horizon: str | None = Field(default=None, max_length=80)
    as_of: UtcDatetime
    feature_snapshot_id: UUID | None = None

    @field_validator("value")
    @classmethod
    def validate_metric_value(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("metric values must be finite")
        return value


class MaterialityScore(DomainModel):
    """Auditable deterministic score and its portfolio priority modifier."""

    component_scores: dict[str, float] = Field(default_factory=dict)
    component_weights: dict[str, float] = Field(default_factory=dict)
    raw_score: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    priority_modifier: float = Field(default=1, ge=0)
    priority_score: float = Field(ge=0)
    config_version: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_components(self) -> MaterialityScore:
        if set(self.component_scores) - set(self.component_weights):
            raise ValueError("every scored component must have a configured weight")
        if any(not 0 <= value <= 1 for value in self.component_scores.values()):
            raise ValueError("component scores must be between zero and one")
        if any(value < 0 for value in self.component_weights.values()):
            raise ValueError("component weights cannot be negative")
        return self


class ResearchFinding(DomainModel):
    """Typed candidate finding emitted by a quant module."""

    finding_id: UUID = Field(default_factory=uuid4)
    finding_key: str = Field(min_length=8, max_length=200)
    research_run_id: UUID
    security_id: UUID
    category: FindingCategory
    title: str = Field(min_length=1, max_length=300)
    change: str = Field(min_length=1, max_length=2000)
    direction: str | None = Field(default=None, max_length=40)
    effective_at: UtcDatetime
    available_at: UtcDatetime
    created_at: UtcDatetime = Field(default_factory=utc_now)
    metrics: tuple[QuantMetric, ...] = ()
    feature_snapshot_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    score: MaterialityScore
    materiality_tier: MaterialityTier
    confidence: ConfidenceLevel
    portfolio_weight: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_finding_timing(self) -> ResearchFinding:
        # Upcoming earnings can generate a valid risk finding before event time.
        if self.available_at > self.created_at:
            raise ValueError("available_at cannot be later than created_at")
        return self


class CardContext(DomainModel):
    """Portfolio and benchmark context, never accounting-grade attribution."""

    position_weight: float | None = None
    contribution_bps: float | None = None
    benchmark_return: float | None = None
    sector_return: float | None = None
    peer_return: float | None = None
    macro_event: str | None = Field(default=None, max_length=500)
    notes: tuple[str, ...] = ()


class ResearchCard(DomainModel):
    """Persisted, deterministic Phase-1 rendering of related findings."""

    card_id: UUID = Field(default_factory=uuid4)
    card_key: str = Field(min_length=8, max_length=200)
    research_run_id: UUID
    security_id: UUID
    as_of: UtcDatetime
    created_at: UtcDatetime = Field(default_factory=utc_now)
    materiality_tier: MaterialityTier
    change: str = Field(min_length=1, max_length=3000)
    quant_evidence: tuple[QuantMetric, ...] = ()
    context: CardContext = Field(default_factory=CardContext)
    thesis_impact: ThesisImpact = ThesisImpact.NONE
    thesis_node_id: str | None = Field(default=None, max_length=128)
    key_risk_or_opportunity: str | None = Field(default=None, max_length=1000)
    confidence: ConfidenceLevel
    next_research_question: str | None = Field(default=None, max_length=1000)
    finding_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    renderer_version: str = Field(min_length=1, max_length=80)
    model_version: str | None = Field(default=None, max_length=160)
    data_cutoff_at: UtcDatetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_card_timing(self) -> ResearchCard:
        if self.as_of > self.data_cutoff_at or self.data_cutoff_at > self.created_at:
            raise ValueError("card timing must satisfy as_of <= data_cutoff_at <= created_at")
        return self


_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,127}$"
_FEATURE_PATTERN = r"^[a-z][a-z0-9_]{0,159}$"


def _normalize_feature_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("feature names must be strings")
    normalized = value.strip().lower()
    if not re.fullmatch(_FEATURE_PATTERN, normalized):
        raise ValueError("feature names must be canonical feature names")
    return normalized


def _normalize_feature_names(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = (value,)
    else:
        if not isinstance(value, Iterable):
            raise ValueError("feature names must be a sequence")
        values = tuple(value)
    return tuple(dict.fromkeys(_normalize_feature_name(item) for item in values))


class ThesisDriver(DomainModel):
    """A typed, auditable positive, negative, or mixed thesis driver."""

    node_id: str = Field(pattern=_KEY_PATTERN)
    statement: str = Field(min_length=1, max_length=2000)
    supporting_features: tuple[str, ...] = ()
    direction: ThesisDirection

    _normalize_supporting_features = field_validator("supporting_features", mode="before")(
        _normalize_feature_names
    )


class ThesisRisk(DomainModel):
    """A typed risk node monitored through exact feature names."""

    node_id: str = Field(pattern=_KEY_PATTERN)
    statement: str = Field(min_length=1, max_length=2000)
    watch_features: tuple[str, ...] = ()
    severity: ThesisRiskSeverity

    _normalize_watch_features = field_validator("watch_features", mode="before")(
        _normalize_feature_names
    )


class ThesisInvalidationRule(DomainModel):
    """A threshold-based, deterministic thesis invalidation rule."""

    node_id: str = Field(pattern=_KEY_PATTERN)
    statement: str = Field(min_length=1, max_length=2000)
    feature_name: str = Field(pattern=_FEATURE_PATTERN)
    comparator: InvalidationComparator
    warning_threshold: float
    breach_threshold: float
    unit: str | None = Field(default=None, max_length=40)

    _normalize_feature_name = field_validator("feature_name", mode="before")(
        _normalize_feature_name
    )

    @field_validator("warning_threshold", "breach_threshold")
    @classmethod
    def validate_finite_threshold(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("thresholds must be finite")
        return value

    @model_validator(mode="after")
    def validate_threshold_order(self) -> ThesisInvalidationRule:
        if (
            self.comparator is InvalidationComparator.GREATER_THAN_OR_EQUAL
            and self.breach_threshold <= self.warning_threshold
        ):
            raise ValueError("breach threshold must be above warning threshold")
        if (
            self.comparator is InvalidationComparator.LESS_THAN_OR_EQUAL
            and self.breach_threshold >= self.warning_threshold
        ):
            raise ValueError("breach threshold must be below warning threshold")
        return self


class ThesisContent(DomainModel):
    """Versioned PM-authored content with a strict, stable schema."""

    schema_version: Literal[1] = 1
    summary: str = Field(min_length=1, max_length=5000)
    drivers: tuple[ThesisDriver, ...] = ()
    risks: tuple[ThesisRisk, ...] = ()
    invalidation_rules: tuple[ThesisInvalidationRule, ...] = ()

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value: object) -> int:
        if type(value) is int and value == 1:
            return value
        raise ValueError("schema_version must be the integer 1")

    @model_validator(mode="after")
    def validate_unique_node_ids(self) -> ThesisContent:
        node_ids = (
            *(node.node_id for node in self.drivers),
            *(node.node_id for node in self.risks),
            *(node.node_id for node in self.invalidation_rules),
        )
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node IDs must be unique across thesis content")
        return self


class Thesis(DomainModel):
    """Stable identity for a PM-owned investment thesis."""

    thesis_id: UUID = Field(default_factory=uuid4)
    thesis_key: str = Field(pattern=_KEY_PATTERN)
    security_id: UUID
    title: str = Field(min_length=1, max_length=300)
    status: ThesisStatus = ThesisStatus.ACTIVE
    created_by: str = Field(min_length=1, max_length=160)
    created_at: UtcDatetime = Field(default_factory=utc_now)
    archived_at: UtcDatetime | None = None
    archived_by: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_archive_state(self) -> Thesis:
        if self.status is ThesisStatus.ARCHIVED:
            if self.archived_at is None or self.archived_by is None:
                raise ValueError("archived theses require archived_at and archived_by")
            if self.archived_at < self.created_at:
                raise ValueError("archived_at cannot precede created_at")
        elif self.archived_at is not None or self.archived_by is not None:
            raise ValueError("active theses cannot have archive fields")
        return self


class ThesisVersion(DomainModel):
    """Immutable thesis content; activation requires explicit PM approval."""

    thesis_version_id: UUID = Field(default_factory=uuid4)
    thesis_id: UUID
    version: int = Field(ge=1)
    valid_from: UtcDatetime
    valid_to: UtcDatetime | None = None
    content: ThesisContent
    authored_by: str = Field(min_length=1, max_length=160)
    approved_by: str = Field(min_length=1, max_length=160)
    approved_at: UtcDatetime
    created_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_thesis_version(self) -> ThesisVersion:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if self.created_at > self.approved_at:
            raise ValueError("approved_at cannot precede created_at")
        return self


class ThesisSignal(DomainModel):
    """One finite, point-in-time feature value available to thesis evaluation."""

    feature_name: str = Field(pattern=_FEATURE_PATTERN)
    raw_value: float
    normalized_strength: float = Field(ge=0.0, le=1.0)
    feature_snapshot_id: UUID
    direction: str | None = Field(default=None, max_length=40)
    unit: str | None = Field(default=None, max_length=40)

    _normalize_feature_name = field_validator("feature_name", mode="before")(
        _normalize_feature_name
    )

    @field_validator("raw_value")
    @classmethod
    def validate_raw_value(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("raw values must be finite")
        return value


class ThesisNodeContribution(DomainModel):
    """Traceable relevance result for one typed thesis node."""

    node_id: str = Field(pattern=_KEY_PATTERN)
    node_kind: Literal["driver", "risk", "invalidation_rule"]
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    matched_feature_names: tuple[str, ...] = ()
    feature_snapshot_ids: tuple[UUID, ...] = ()
    unevaluated_reason: str | None = Field(default=None, min_length=1, max_length=80)

    _normalize_matched_feature_names = field_validator("matched_feature_names", mode="before")(
        _normalize_feature_names
    )

    @model_validator(mode="after")
    def validate_contribution_lineage(self) -> ThesisNodeContribution:
        if self.feature_snapshot_ids and len(self.matched_feature_names) != len(
            self.feature_snapshot_ids
        ):
            raise ValueError("matched feature names and feature snapshot ids must be aligned")
        if self.score is None and self.unevaluated_reason is None:
            raise ValueError("unevaluated contributions require unevaluated_reason")
        if self.score is not None and self.unevaluated_reason is not None:
            raise ValueError("scored contributions cannot have unevaluated_reason")
        return self


class ThesisRelevanceAssessment(DomainModel):
    """Immutable output and lineage of deterministic thesis relevance evaluation."""

    thesis_id: UUID
    thesis_version_id: UUID
    score: float = Field(ge=0.0, le=1.0)
    impact: ThesisImpact
    primary_node_id: str | None = Field(default=None, pattern=_KEY_PATTERN)
    contributions: tuple[ThesisNodeContribution, ...] = ()
    method_version: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_assessment_lineage(self) -> ThesisRelevanceAssessment:
        node_ids = tuple(contribution.node_id for contribution in self.contributions)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("contribution node IDs must be unique")

        evaluated_scores = tuple(
            contribution.score
            for contribution in self.contributions
            if contribution.score is not None
        )
        expected_score = max(evaluated_scores, default=0.0)
        if self.score != expected_score:
            raise ValueError("assessment score must equal the maximum evaluable contribution")

        matched = tuple(
            contribution
            for contribution in self.contributions
            if contribution.score is not None and contribution.matched_feature_names
        )
        if not matched:
            if self.primary_node_id is not None:
                raise ValueError(
                    "primary_node_id must be None when no contribution matched a feature"
                )
            return self

        primary = min(
            matched,
            key=lambda contribution: (-(contribution.score or 0.0), contribution.node_id),
        )
        if self.primary_node_id != primary.node_id:
            raise ValueError("primary_node_id must be the deterministic matched contributor")
        return self


class ThesisVersionSelection(DomainModel):
    """Point-in-time thesis version selection with an explicit outcome."""

    thesis_id: UUID
    effective_at: UtcDatetime
    knowledge_time: UtcDatetime
    status: ThesisSelectionStatus
    version: ThesisVersion | None = None

    @model_validator(mode="after")
    def validate_selection_lineage(self) -> ThesisVersionSelection:
        if (self.status is ThesisSelectionStatus.SELECTED) != (self.version is not None):
            raise ValueError("status must be SELECTED if and only if version is present")
        if self.version is not None and self.version.thesis_id != self.thesis_id:
            raise ValueError("selected version belongs to thesis_id only when identities match")
        return self


class MaterialityFeedback(DomainModel):
    """PM feedback retained separately from deterministic calculations."""

    feedback_id: UUID = Field(default_factory=uuid4)
    card_id: UUID
    feedback: FeedbackKind
    user_id: str | None = Field(default=None, max_length=160)
    comment: str | None = Field(default=None, max_length=2000)
    created_at: UtcDatetime = Field(default_factory=utc_now)
