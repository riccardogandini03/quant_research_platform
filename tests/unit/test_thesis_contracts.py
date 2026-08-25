"""Strict, immutable thesis-domain contract coverage."""

from datetime import UTC, datetime, timedelta
from math import inf
from uuid import UUID

import pytest
from pydantic import ValidationError

from quant_raas.domain.enums import (
    InvalidationComparator,
    ThesisDirection,
    ThesisImpact,
    ThesisRiskSeverity,
    ThesisSelectionStatus,
    ThesisStatus,
)
from quant_raas.domain.research import (
    Thesis,
    ThesisContent,
    ThesisDriver,
    ThesisInvalidationRule,
    ThesisNodeContribution,
    ThesisRelevanceAssessment,
    ThesisRisk,
    ThesisSignal,
    ThesisVersion,
    ThesisVersionSelection,
)

THESIS_ID = UUID("71717171-7171-4717-8717-717171717171")
VERSION_ID = UUID("72727272-7272-4727-8727-727272727272")
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
RELATIVE_FEATURE_ID = UUID("81818181-8181-4818-8818-818181818181")
VOLUME_FEATURE_ID = UUID("82828282-8282-4828-8828-828282828282")
NOW = datetime(2024, 1, 10, 22, 0, tzinfo=UTC)


def thesis_content() -> ThesisContent:
    return ThesisContent(
        summary="Demand durability supports the long-term case.",
        drivers=(
            ThesisDriver(
                node_id="relative_strength",
                statement="Relative strength remains positive.",
                supporting_features=("relative_return_sector_63d",),
                direction=ThesisDirection.POSITIVE,
            ),
        ),
        risks=(
            ThesisRisk(
                node_id="volume_risk",
                statement="Distribution volume may signal weakening sponsorship.",
                watch_features=("dollar_volume_zscore_20d",),
                severity=ThesisRiskSeverity.MEDIUM,
            ),
        ),
        invalidation_rules=(
            ThesisInvalidationRule(
                node_id="relative_break",
                statement="Relative performance falls through the warning range.",
                feature_name="relative_return_sector_63d",
                comparator=InvalidationComparator.LESS_THAN_OR_EQUAL,
                warning_threshold=-0.05,
                breach_threshold=-0.20,
                unit="decimal_return",
            ),
        ),
    )


def test_content_normalizes_features_and_rejects_duplicate_node_ids() -> None:
    content = thesis_content()
    assert content.drivers[0].supporting_features == ("relative_return_sector_63d",)
    with pytest.raises(ValidationError, match="schema_version"):
        ThesisContent.model_validate({**content.model_dump(mode="python"), "schema_version": 2})
    payload = content.model_dump(mode="python")
    payload["risks"][0]["node_id"] = "relative_strength"
    with pytest.raises(ValidationError, match="node IDs must be unique"):
        ThesisContent.model_validate(payload)


@pytest.mark.parametrize("schema_version", [True, 1.0])
def test_content_rejects_non_integer_schema_version_one(schema_version: object) -> None:
    payload = thesis_content().model_dump(mode="python")
    payload["schema_version"] = schema_version
    with pytest.raises(ValidationError, match="schema_version"):
        ThesisContent.model_validate(payload)


def test_invalidation_threshold_order_depends_on_comparator() -> None:
    with pytest.raises(ValidationError, match="breach threshold must be below warning"):
        ThesisInvalidationRule(
            node_id="bad_rule",
            statement="Bad order.",
            feature_name="beta_126d",
            comparator=InvalidationComparator.LESS_THAN_OR_EQUAL,
            warning_threshold=0.8,
            breach_threshold=1.0,
        )


def test_feature_names_are_canonical_stably_deduplicated_and_finite() -> None:
    driver = ThesisDriver(
        node_id="momentum",
        statement="Momentum remains positive.",
        supporting_features=(" Beta_126D ", "beta_126d", "relative_return_63d"),
        direction=ThesisDirection.POSITIVE,
    )
    assert driver.supporting_features == ("beta_126d", "relative_return_63d")
    with pytest.raises(ValidationError, match="canonical feature names"):
        ThesisDriver(
            node_id="bad_feature",
            statement="An invalid feature should be rejected.",
            supporting_features=("Not Valid",),
            direction=ThesisDirection.POSITIVE,
        )
    with pytest.raises(ValidationError, match="thresholds must be finite"):
        ThesisInvalidationRule(
            node_id="infinite_threshold",
            statement="An invalid threshold should be rejected.",
            feature_name="beta_126d",
            comparator=InvalidationComparator.GREATER_THAN_OR_EQUAL,
            warning_threshold=0.5,
            breach_threshold=inf,
        )
    with pytest.raises(ValidationError, match="raw values must be finite"):
        ThesisSignal(
            feature_name="beta_126d",
            raw_value=inf,
            normalized_strength=0.5,
            feature_snapshot_id=VERSION_ID,
        )


def test_thesis_archive_fields_and_version_approval_are_consistent() -> None:
    with pytest.raises(ValidationError, match="archived theses require"):
        Thesis(
            thesis_id=THESIS_ID,
            thesis_key="example_core",
            security_id=SECURITY_ID,
            title="Example core thesis",
            status=ThesisStatus.ARCHIVED,
            created_by="pm@example.com",
            created_at=NOW,
        )
    version = ThesisVersion(
        thesis_version_id=VERSION_ID,
        thesis_id=THESIS_ID,
        version=1,
        valid_from=NOW,
        content=thesis_content(),
        authored_by="analyst@example.com",
        approved_by="pm@example.com",
        created_at=NOW,
        approved_at=NOW + timedelta(minutes=1),
    )
    assert version.approved_at > version.created_at
    with pytest.raises(ValidationError, match="approved_at cannot precede created_at"):
        ThesisVersion.model_validate(
            {
                **version.model_dump(mode="python"),
                "approved_at": NOW - timedelta(seconds=1),
            }
        )


def test_lifecycle_validates_archive_time_and_version_interval() -> None:
    with pytest.raises(ValidationError, match="active theses cannot have archive fields"):
        Thesis(
            thesis_id=THESIS_ID,
            thesis_key="example_core",
            security_id=SECURITY_ID,
            title="Example core thesis",
            created_by="pm@example.com",
            created_at=NOW,
            archived_at=NOW,
            archived_by="pm@example.com",
        )
    with pytest.raises(ValidationError, match="archived_at cannot precede created_at"):
        Thesis(
            thesis_id=THESIS_ID,
            thesis_key="example_core",
            security_id=SECURITY_ID,
            title="Example core thesis",
            status=ThesisStatus.ARCHIVED,
            created_by="pm@example.com",
            created_at=NOW,
            archived_at=NOW - timedelta(seconds=1),
            archived_by="pm@example.com",
        )
    with pytest.raises(ValidationError, match="valid_to must be later than valid_from"):
        ThesisVersion(
            thesis_version_id=VERSION_ID,
            thesis_id=THESIS_ID,
            version=1,
            valid_from=NOW,
            valid_to=NOW,
            content=thesis_content(),
            authored_by="analyst@example.com",
            approved_by="pm@example.com",
            approved_at=NOW,
        )


def test_assessment_and_selection_require_consistent_lineage() -> None:
    contribution = ThesisNodeContribution(
        node_id="relative_strength",
        node_kind="driver",
        score=0.5,
        matched_feature_names=("relative_return_sector_63d",),
        feature_snapshot_ids=(RELATIVE_FEATURE_ID,),
    )
    assessment = ThesisRelevanceAssessment(
        thesis_id=THESIS_ID,
        thesis_version_id=VERSION_ID,
        score=0.5,
        impact=ThesisImpact.MODERATE,
        primary_node_id="relative_strength",
        contributions=(contribution,),
        method_version="thesis-relevance-v1",
    )
    assert assessment.primary_node_id == contribution.node_id
    selection = ThesisVersionSelection(
        thesis_id=THESIS_ID,
        effective_at=NOW,
        knowledge_time=NOW,
        status=ThesisSelectionStatus.NOT_YET_EFFECTIVE,
    )
    assert selection.version is None


def test_contribution_assessment_and_selection_validate_lineage() -> None:
    with pytest.raises(ValidationError, match="aligned"):
        ThesisNodeContribution(
            node_id="relative_strength",
            node_kind="driver",
            score=0.5,
            matched_feature_names=("relative_return_sector_63d",),
            feature_snapshot_ids=(VERSION_ID, THESIS_ID),
        )
    with pytest.raises(ValidationError, match="aligned"):
        ThesisNodeContribution(
            node_id="relative_strength",
            node_kind="driver",
            score=0.5,
            matched_feature_names=("relative_return_sector_63d",),
        )
    with pytest.raises(ValidationError, match="aligned"):
        ThesisNodeContribution(
            node_id="relative_strength",
            node_kind="driver",
            score=0.5,
            feature_snapshot_ids=(RELATIVE_FEATURE_ID,),
        )
    with pytest.raises(ValidationError, match="unevaluated_reason"):
        ThesisNodeContribution(
            node_id="relative_strength",
            node_kind="driver",
            matched_feature_names=("relative_return_sector_63d",),
            feature_snapshot_ids=(RELATIVE_FEATURE_ID,),
        )
    low = ThesisNodeContribution(
        node_id="alpha",
        node_kind="driver",
        score=0.5,
        matched_feature_names=("relative_return_sector_63d",),
        feature_snapshot_ids=(RELATIVE_FEATURE_ID,),
    )
    high = ThesisNodeContribution(
        node_id="beta",
        node_kind="risk",
        score=0.8,
        matched_feature_names=("dollar_volume_zscore_20d",),
        feature_snapshot_ids=(VOLUME_FEATURE_ID,),
    )
    with pytest.raises(ValidationError, match="maximum evaluable contribution"):
        ThesisRelevanceAssessment(
            thesis_id=THESIS_ID,
            thesis_version_id=VERSION_ID,
            score=0.5,
            impact=ThesisImpact.MODERATE,
            primary_node_id="alpha",
            contributions=(low, high),
            method_version="thesis-relevance-v1",
        )
    with pytest.raises(ValidationError, match="deterministic matched contributor"):
        ThesisRelevanceAssessment(
            thesis_id=THESIS_ID,
            thesis_version_id=VERSION_ID,
            score=0.8,
            impact=ThesisImpact.HIGH,
            primary_node_id="alpha",
            contributions=(low, high),
            method_version="thesis-relevance-v1",
        )
    version = ThesisVersion(
        thesis_version_id=VERSION_ID,
        thesis_id=THESIS_ID,
        version=1,
        valid_from=NOW,
        content=thesis_content(),
        authored_by="analyst@example.com",
        approved_by="pm@example.com",
        created_at=NOW,
        approved_at=NOW,
    )
    with pytest.raises(ValidationError, match="SELECTED"):
        ThesisVersionSelection(
            thesis_id=THESIS_ID,
            effective_at=NOW,
            knowledge_time=NOW,
            status=ThesisSelectionStatus.SELECTED,
        )
    with pytest.raises(ValidationError, match="belongs to thesis_id"):
        ThesisVersionSelection(
            thesis_id=SECURITY_ID,
            effective_at=NOW,
            knowledge_time=NOW,
            status=ThesisSelectionStatus.SELECTED,
            version=version,
        )
