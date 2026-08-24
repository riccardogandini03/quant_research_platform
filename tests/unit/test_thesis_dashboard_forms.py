"""Behavioral coverage for typed thesis dashboard form conversion."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.dashboard import thesis_panel
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


def test_editor_parser_skips_only_exact_untouched_row_templates() -> None:
    content = content_from_editor_rows(
        summary="A typed summary.",
        driver_rows=[
            {
                "node_id": "",
                "statement": "",
                "supporting_features": "",
                "direction": "positive",
            }
        ],
        risk_rows=[
            {
                "node_id": "",
                "statement": "",
                "watch_features": "",
                "severity": "medium",
            }
        ],
        invalidation_rows=[
            {
                "node_id": "",
                "statement": "",
                "feature_name": "",
                "comparator": "greater_than_or_equal",
                "warning_threshold": 0.0,
                "breach_threshold": 0.0,
                "unit": "",
            }
        ],
    )

    assert content.drivers == ()
    assert content.risks == ()
    assert content.invalidation_rules == ()


@pytest.mark.parametrize(
    ("driver_rows", "risk_rows", "invalidation_rows"),
    [
        (
            [
                {
                    "node_id": "",
                    "statement": "Authored driver text must not disappear.",
                    "supporting_features": "",
                    "direction": "positive",
                }
            ],
            [],
            [],
        ),
        (
            [],
            [
                {
                    "node_id": "",
                    "statement": "",
                    "watch_features": "beta_126d",
                    "severity": "medium",
                }
            ],
            [],
        ),
        (
            [],
            [],
            [
                {
                    "node_id": "",
                    "statement": "",
                    "feature_name": "",
                    "comparator": "less_than_or_equal",
                    "warning_threshold": 0.0,
                    "breach_threshold": 0.0,
                    "unit": "",
                }
            ],
        ),
    ],
    ids=("driver", "risk", "invalidation"),
)
def test_editor_parser_rejects_partially_authored_rows_instead_of_erasing_them(
    driver_rows: list[dict[str, object]],
    risk_rows: list[dict[str, object]],
    invalidation_rows: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        content_from_editor_rows(
            summary="A typed summary.",
            driver_rows=driver_rows,
            risk_rows=risk_rows,
            invalidation_rows=invalidation_rows,
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


class _EditorStreamlit:
    def __init__(self) -> None:
        self.text_area_values: dict[str, str] = {}
        self.text_input_values: dict[str, str] = {}

    def text_area(self, label: str, *, value: str, key: str) -> str:
        self.text_area_values[label] = value
        return value

    def caption(self, value: str) -> None:
        pass

    def data_editor(self, value, **kwargs):
        return value

    def text_input(self, label: str, *, value: str = "", key: str) -> str:
        self.text_input_values[label] = value
        return value

    def checkbox(self, label: str, *, key: str) -> bool:
        return False


class _HistoryStreamlit:
    def __init__(self) -> None:
        self.dataframes: list[list[dict[str, object]]] = []

    def subheader(self, value: str) -> None:
        pass

    def caption(self, value: str) -> None:
        pass

    def selectbox(self, label: str, *, options, index: int, **kwargs):
        return options[index]

    def markdown(self, value: str) -> None:
        pass

    def dataframe(self, value, **kwargs) -> None:
        self.dataframes.append(value)


def test_create_editor_requires_user_authored_summary_and_effective_time(monkeypatch) -> None:
    streamlit = _EditorStreamlit()
    monkeypatch.setattr(thesis_panel, "st", streamlit, raising=False)

    summary, *_ = thesis_panel._render_editor(None, key_prefix="create")
    valid_from, *_ = thesis_panel._authoring_fields(key_prefix="create")

    assert summary == ""
    assert streamlit.text_area_values["Summary"] == ""
    assert valid_from == ""
    assert streamlit.text_input_values["Valid from (ISO-8601 with Z or offset)"] == ""


def test_history_rendering_exposes_complete_typed_content_without_invented_state(
    monkeypatch,
    thesis,
    thesis_version,
) -> None:
    streamlit = _HistoryStreamlit()
    monkeypatch.setattr(thesis_panel, "st", streamlit, raising=False)

    selected = thesis_panel._render_history(thesis, (thesis_version,))

    assert selected == thesis_version
    selected_rows, history_rows = streamlit.dataframes
    by_kind = {row["kind"]: row for row in selected_rows}
    assert by_kind["driver"] == {
        "kind": "driver",
        "node_id": "relative_strength",
        "statement": "Relative strength remains positive.",
        "supporting_features": "relative_return_sector_63d",
        "direction": "positive",
    }
    assert by_kind["risk"] == {
        "kind": "risk",
        "node_id": "volume_risk",
        "statement": "Distribution volume may signal weakening sponsorship.",
        "watch_features": "dollar_volume_zscore_20d",
        "severity": "medium",
    }
    assert by_kind["invalidation"] == {
        "kind": "invalidation",
        "node_id": "relative_break",
        "statement": "Relative performance falls through the warning range.",
        "feature_name": "relative_return_sector_63d",
        "comparator": "less_than_or_equal",
        "warning_threshold": -0.05,
        "breach_threshold": -0.2,
        "unit": "decimal_return",
        "invalidation_state": "not evaluated",
    }
    assert {row["kind"] for row in history_rows} == {"driver", "risk", "invalidation"}
    assert {row["summary"] for row in history_rows} == {thesis_version.content.summary}
    assert {row["version"] for row in history_rows} == {1}
    assert next(row for row in history_rows if row["kind"] == "invalidation") == {
        "version": 1,
        "valid_from": thesis_version.valid_from,
        "approved_at": thesis_version.approved_at,
        "authored_by": thesis_version.authored_by,
        "approved_by": thesis_version.approved_by,
        "summary": thesis_version.content.summary,
        **by_kind["invalidation"],
    }
