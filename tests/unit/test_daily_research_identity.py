"""Deterministic identity regressions for daily research inputs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from quant_raas.services import daily_research
from quant_raas.services.daily_research import DailyResearchRequest

COVERED_SECURITY_ID = UUID("22222222-2222-4222-8222-222222222222")
EXTRA_SECURITY_ID = UUID("33333333-3333-4333-8333-333333333333")
SECOND_COVERED_SECURITY_ID = UUID("44444444-4444-4444-8444-444444444444")


def _request(
    feature_config_version: str,
    *,
    lookback_calendar_days: int = 550,
) -> DailyResearchRequest:
    return DailyResearchRequest(
        coverage_list_id=UUID("11111111-1111-4111-8111-111111111111"),
        as_of=datetime(2024, 1, 9, 21, 0, tzinfo=UTC),
        data_cutoff_at=datetime(2024, 1, 9, 22, 0, tzinfo=UTC),
        feature_config_version=feature_config_version,
        lookback_calendar_days=lookback_calendar_days,
    )


def _run_key(
    request: DailyResearchRequest,
    *,
    thesis_method_version: str = "thesis-v1",
    materiality_score_version: str = "materiality-v1",
    position_weights: dict[UUID, float] | None = None,
) -> str:
    return daily_research._run_key(
        request,
        (UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),),
        thesis_method_version=thesis_method_version,
        materiality_score_version=materiality_score_version,
        position_weights=position_weights,
        covered_security_ids=(SECOND_COVERED_SECURITY_ID, COVERED_SECURITY_ID),
    )


def test_run_key_canonicalization_is_not_ambiguous_at_delimiters() -> None:
    left = _run_key(_request("x|y"), thesis_method_version="z")
    right = _run_key(_request("x"), thesis_method_version="y|z")

    assert left != right


def test_run_config_identity_canonicalization_is_not_ambiguous_at_delimiters() -> None:
    left = daily_research._run_config_version("x|y", "z", "materiality-v1")
    right = daily_research._run_config_version("x", "y|z", "materiality-v1")

    assert left != right
    assert left.startswith("bundle:")
    assert right.startswith("bundle:")
    assert len(left) == len(right) == 71
    assert daily_research._run_config_version(
        "feature-v1", "thesis-v1", "materiality-v1"
    ) != daily_research._run_config_version("feature-v1", "thesis-v1", "materiality-v2")


def test_run_key_includes_every_bounded_scoring_and_window_version() -> None:
    baseline = _run_key(_request("feature-v1"))

    changed = {
        _run_key(_request("feature-v2")),
        _run_key(_request("feature-v1", lookback_calendar_days=551)),
        _run_key(_request("feature-v1"), thesis_method_version="thesis-v2"),
        _run_key(_request("feature-v1"), materiality_score_version="materiality-v2"),
    }

    assert baseline not in changed
    assert len(changed) == 4
    assert _run_key(_request("feature-v1")) == baseline


def test_run_key_canonicalizes_only_supplied_covered_position_weights() -> None:
    weighted = _run_key(
        _request("feature-v1"),
        position_weights={
            COVERED_SECURITY_ID: 0.04,
            SECOND_COVERED_SECURITY_ID: -0.02,
        },
    )
    reordered_with_irrelevant_extra = _run_key(
        _request("feature-v1"),
        position_weights={
            EXTRA_SECURITY_ID: 0.99,
            SECOND_COVERED_SECURITY_ID: -0.02,
            COVERED_SECURITY_ID: 0.04,
        },
    )

    assert reordered_with_irrelevant_extra == weighted
    assert (
        _run_key(
            _request("feature-v1"),
            position_weights={
                COVERED_SECURITY_ID: 0.05,
                SECOND_COVERED_SECURITY_ID: -0.02,
            },
        )
        != weighted
    )
    assert _run_key(_request("feature-v1")) != _run_key(
        _request("feature-v1"),
        position_weights={COVERED_SECURITY_ID: 0.0},
    )
