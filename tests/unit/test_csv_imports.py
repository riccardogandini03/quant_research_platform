"""CSV parsing stays side-effect-free so users can review every issue first."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from quant_raas.domain import (
    CoverageMember,
    CoverageUploadRow,
    HoldingUploadRow,
    PortfolioPosition,
)
from quant_raas.domain.enums import IdentifierScheme
from quant_raas.security_master.importer import (
    parse_coverage_csv,
    parse_holdings_csv,
    parse_security_universe_csv,
)


def test_holdings_parser_accepts_short_weight_and_identifier_alias() -> None:
    result = parse_holdings_csv(
        "identifier,weight,identifier_type,provider,unused_note\n"
        " example us ,-0.04,vendor,demo,reviewed\n"
    )

    assert result.is_valid
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.weight == Decimal("-0.04")
    assert row.identifier_scheme == IdentifierScheme.VENDOR
    assert row.security_reference().identifier == "EXAMPLE US"
    assert [(issue.field, issue.severity) for issue in result.issues] == [
        ("unused_note", "warning")
    ]


def test_holdings_parser_reports_duplicates_and_percent_unit_errors() -> None:
    duplicate = parse_holdings_csv("identifier,weight\nEXAMPLE US,0.04\nEXAMPLE US,0.04\n")
    assert not duplicate.is_valid
    assert len(duplicate.rows) == 1
    assert any("duplicate security row" in issue.message for issue in duplicate.issues)

    wrong_units = parse_holdings_csv("identifier,weight\nEXAMPLE US,10.1\n")
    assert not wrong_units.is_valid
    assert wrong_units.rows == ()
    assert any(issue.field == "weight" for issue in wrong_units.issues)


def test_coverage_parser_preserves_peer_group_without_creating_weight() -> None:
    result = parse_coverage_csv(
        "identifier,thesis_id,peer_group\nEXAMPLE US,example_core,enterprise_software\n"
    )
    assert result.is_valid
    assert result.rows[0].thesis_id == "example_core"
    assert result.rows[0].peer_group == "enterprise_software"
    assert not hasattr(result.rows[0], "weight")


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (HoldingUploadRow, {"identifier": "EXAMPLE", "weight": "0.01"}),
        (CoverageUploadRow, {"identifier": "EXAMPLE"}),
        (
            PortfolioPosition,
            {
                "snapshot_id": "11111111-1111-4111-8111-111111111111",
                "security_id": "22222222-2222-4222-8222-222222222222",
                "weight": "0.01",
                "source_identifier": "EXAMPLE",
            },
        ),
        (
            CoverageMember,
            {
                "coverage_list_id": "33333333-3333-4333-8333-333333333333",
                "security_id": "22222222-2222-4222-8222-222222222222",
                "added_at": "2024-01-10T00:00:00Z",
                "source_identifier": "EXAMPLE",
            },
        ),
    ],
)
def test_optional_csv_thesis_references_normalize_to_public_keys(
    model: type[object], payload: dict[str, str]
) -> None:
    row = model.model_validate({**payload, "thesis_id": " Example_Core "})
    assert row.thesis_id == "example_core"


def test_repository_examples_follow_the_public_csv_contract() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    holdings = parse_holdings_csv(repository_root / "examples" / "holdings.csv")
    coverage = parse_coverage_csv(repository_root / "examples" / "coverage.csv")
    universe = parse_security_universe_csv(repository_root / "configs" / "universes" / "demo.csv")
    assert holdings.is_valid, holdings.issues
    assert coverage.is_valid, coverage.issues
    assert universe.is_valid, universe.issues
    assert len(holdings.rows) == 3
    assert len(coverage.rows) == 4
    assert len(universe.rows) == 6
    assert all(row.identifier_scheme == IdentifierScheme.VENDOR for row in universe.rows)
