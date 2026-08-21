"""Deterministic identity regressions for daily research inputs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from quant_raas.services import daily_research
from quant_raas.services.daily_research import DailyResearchRequest


def _request(feature_config_version: str) -> DailyResearchRequest:
    return DailyResearchRequest(
        coverage_list_id=UUID("11111111-1111-4111-8111-111111111111"),
        as_of=datetime(2024, 1, 9, 21, 0, tzinfo=UTC),
        data_cutoff_at=datetime(2024, 1, 9, 22, 0, tzinfo=UTC),
        feature_config_version=feature_config_version,
    )


def test_run_key_canonicalization_is_not_ambiguous_at_delimiters() -> None:
    batch_ids = (UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),)

    left = daily_research._run_key(_request("x|y"), batch_ids, thesis_method_version="z")
    right = daily_research._run_key(_request("x"), batch_ids, thesis_method_version="y|z")

    assert left != right


def test_run_config_identity_canonicalization_is_not_ambiguous_at_delimiters() -> None:
    left = daily_research._run_config_version("x|y", "z")
    right = daily_research._run_config_version("x", "y|z")

    assert left != right
    assert left.startswith("bundle:")
    assert right.startswith("bundle:")
    assert len(left) == len(right) == 71
