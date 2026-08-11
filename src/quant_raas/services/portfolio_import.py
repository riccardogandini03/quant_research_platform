"""Parse-first helpers used by API and dashboard upload adapters."""

from __future__ import annotations

from datetime import datetime

from quant_raas.security_master.importer import parse_coverage_csv, parse_holdings_csv
from quant_raas.security_master.service import (
    CoverageImportResult,
    HoldingsImportResult,
    SecurityMasterService,
)


def import_holdings_csv(
    content: str | bytes,
    *,
    service: SecurityMasterService,
    portfolio_name: str,
    as_of: datetime,
    source_name: str | None = None,
) -> HoldingsImportResult:
    parsed = parse_holdings_csv(content)
    if not parsed.is_valid:
        messages = "; ".join(f"row {issue.row_number}: {issue.message}" for issue in parsed.issues)
        raise ValueError(messages)
    return service.import_holdings(
        parsed.rows,
        portfolio_name=portfolio_name,
        as_of=as_of,
        source_name=source_name,
        source_hash=parsed.source_hash,
    )


def import_coverage_csv(
    content: str | bytes,
    *,
    service: SecurityMasterService,
    name: str,
    as_of: datetime,
    description: str | None = None,
) -> CoverageImportResult:
    parsed = parse_coverage_csv(content)
    if not parsed.is_valid:
        messages = "; ".join(f"row {issue.row_number}: {issue.message}" for issue in parsed.issues)
        raise ValueError(messages)
    return service.import_coverage(parsed.rows, name=name, as_of=as_of, description=description)
