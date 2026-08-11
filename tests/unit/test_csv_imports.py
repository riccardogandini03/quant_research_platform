"""CSV parsing stays side-effect-free so users can review every issue first."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

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
    assert result.rows[0].peer_group == "enterprise_software"
    assert not hasattr(result.rows[0], "weight")


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
