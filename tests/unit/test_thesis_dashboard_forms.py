"""Behavioral coverage for typed thesis dashboard form conversion."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.dashboard.thesis_panel import (
    content_from_editor_rows,
    editor_rows_from_content,
    parse_utc_timestamp,
)


def test_editor_rows_roundtrip_typed_thesis_content(thesis_content) -> None:
    rows = editor_rows_from_content(thesis_content)

    rebuilt = content_from_editor_rows(
        summary=thesis_content.summary,
        driver_rows=rows.drivers,
        risk_rows=rows.risks,
        invalidation_rows=rows.invalidation_rules,
    )

    assert rebuilt == thesis_content


def test_editor_parser_splits_features_and_rejects_invalid_thresholds() -> None:
    content = content_from_editor_rows(
        summary="A typed summary.",
        driver_rows=[
            {
                "node_id": "relative_strength",
                "statement": "Relative strength persists.",
                "supporting_features": "relative_return_sector_63d, beta_126d",
                "direction": "positive",
            }
        ],
        risk_rows=[],
        invalidation_rows=[],
    )

    assert content.drivers[0].supporting_features == (
        "relative_return_sector_63d",
        "beta_126d",
    )

    with pytest.raises(ValidationError) as raised:
        content_from_editor_rows(
            summary="A typed summary.",
            driver_rows=[],
            risk_rows=[],
            invalidation_rows=[
                {
                    "node_id": "relative_break",
                    "statement": "Relative performance weakens.",
                    "feature_name": "relative_return_sector_63d",
                    "comparator": "less_than_or_equal",
                    "warning_threshold": -0.05,
                    "breach_threshold": 0.0,
                    "unit": "decimal_return",
                }
            ],
        )

    assert (
        raised.value.errors()[0]["msg"]
        == "Value error, breach threshold must be below warning threshold"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024-01-10T22:00:00Z", datetime(2024, 1, 10, 22, 0, tzinfo=UTC)),
        ("2024-01-11T00:00:00+02:00", datetime(2024, 1, 10, 22, 0, tzinfo=UTC)),
    ],
)
def test_parse_utc_timestamp_normalizes_offset_aware_iso8601_values(
    value: str,
    expected: datetime,
) -> None:
    assert parse_utc_timestamp(value) == expected


def test_parse_utc_timestamp_rejects_naive_values() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        parse_utc_timestamp("2024-01-10T22:00:00")
