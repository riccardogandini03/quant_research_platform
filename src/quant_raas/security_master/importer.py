"""Side-effect-free CSV parsing for holdings and research coverage.

Parsing and security resolution are separate steps so a UI can show every row
error before any portfolio state is persisted.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from quant_raas.domain.portfolio import CoverageUploadRow, HoldingUploadRow
from quant_raas.domain.security import SecurityUploadRow


@dataclass(frozen=True, slots=True)
class CsvIssue:
    """One actionable problem or warning tied to a CSV row."""

    row_number: int
    field: str | None
    message: str
    severity: str = "error"
    value: str | None = None


@dataclass(frozen=True, slots=True)
class CsvValidationResult[RowT: (HoldingUploadRow, CoverageUploadRow, SecurityUploadRow)]:
    """Parsed rows plus all issues, suitable for display in an upload UI."""

    rows: tuple[RowT, ...]
    issues: tuple[CsvIssue, ...]
    source_hash: str

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def _read_source(source: str | bytes | Path | TextIO) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8-sig")
    if isinstance(source, bytes):
        return source.decode("utf-8-sig")
    if hasattr(source, "read"):
        value = source.read()
        return value.decode("utf-8-sig") if isinstance(value, bytes) else value
    # Strings are content, not implicit paths. This avoids surprising reads of
    # user-controlled values; callers with a file should pass pathlib.Path.
    return source.lstrip("\ufeff")


def _normalize_headers(row: dict[str | None, str | None]) -> dict[str, str | None]:
    aliases = {
        "identifier_type": "identifier_scheme",
    }
    normalized: dict[str, str | None] = {}
    for raw_key, value in row.items():
        if raw_key is None:
            continue
        key = aliases.get(raw_key.strip().lower(), raw_key.strip().lower())
        normalized[key] = value.strip() if isinstance(value, str) else value
    return normalized


def _parse_csv[RowT: (HoldingUploadRow, CoverageUploadRow, SecurityUploadRow)](
    source: str | bytes | Path | TextIO,
    *,
    model: Callable[..., RowT],
    required_columns: set[str],
    allowed_columns: set[str],
) -> CsvValidationResult[RowT]:
    content = _read_source(source)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    stream = io.StringIO(content)
    reader = csv.DictReader(stream)
    issues: list[CsvIssue] = []
    rows: list[RowT] = []

    if reader.fieldnames is None:
        return CsvValidationResult(
            rows=(),
            issues=(CsvIssue(1, None, "CSV must contain a header row"),),
            source_hash=digest,
        )

    headers = {
        {"identifier_type": "identifier_scheme"}.get(
            name.lstrip("\ufeff").strip().lower(), name.lstrip("\ufeff").strip().lower()
        )
        for name in reader.fieldnames
        if name
    }
    for missing in sorted(required_columns - headers):
        issues.append(CsvIssue(1, missing, f"missing required column {missing!r}"))
    for unexpected in sorted(headers - allowed_columns):
        issues.append(
            CsvIssue(
                1,
                unexpected,
                "column is not used by this import contract",
                severity="warning",
            )
        )
    if required_columns - headers:
        return CsvValidationResult((), tuple(issues), digest)

    seen: set[tuple[str, str, str, str]] = set()
    for row_number, raw_row in enumerate(reader, start=2):
        normalized = _normalize_headers(raw_row)
        if not any(value for value in normalized.values()):
            continue
        payload = {key: normalized.get(key) or None for key in allowed_columns}
        try:
            parsed = model(**payload)
        except ValidationError as exc:
            for error in exc.errors(include_url=False):
                field = ".".join(str(part) for part in error["loc"])
                issues.append(
                    CsvIssue(
                        row_number,
                        field or None,
                        error["msg"],
                        value=normalized.get(field),
                    )
                )
            continue

        duplicate_key = (
            parsed.identifier.strip().upper(),
            str(parsed.identifier_scheme or ""),
            (parsed.provider or "").strip().lower(),
            (parsed.exchange_mic or "").strip().upper(),
        )
        if duplicate_key in seen:
            issues.append(
                CsvIssue(
                    row_number,
                    "identifier",
                    "duplicate security row in the same upload",
                    value=parsed.identifier,
                )
            )
            continue
        seen.add(duplicate_key)
        rows.append(parsed)

    if not rows and not any(issue.severity == "error" for issue in issues):
        issues.append(CsvIssue(2, None, "CSV contains no data rows"))
    return CsvValidationResult(tuple(rows), tuple(issues), digest)


def parse_holdings_csv(
    source: str | bytes | Path | TextIO,
) -> CsvValidationResult[HoldingUploadRow]:
    """Validate the plan's holdings format plus optional resolution columns."""

    columns = {
        "identifier",
        "weight",
        "thesis_id",
        "benchmark",
        "identifier_scheme",
        "provider",
        "exchange_mic",
    }
    return _parse_csv(
        source,
        model=HoldingUploadRow,
        required_columns={"identifier", "weight"},
        allowed_columns=columns,
    )


def parse_coverage_csv(
    source: str | bytes | Path | TextIO,
) -> CsvValidationResult[CoverageUploadRow]:
    """Validate a research coverage list independent of holdings weights."""

    columns = {
        "identifier",
        "thesis_id",
        "benchmark",
        "peer_group",
        "identifier_scheme",
        "provider",
        "exchange_mic",
    }
    return _parse_csv(
        source,
        model=CoverageUploadRow,
        required_columns={"identifier"},
        allowed_columns=columns,
    )


def parse_security_universe_csv(
    source: str | bytes | Path | TextIO,
) -> CsvValidationResult[SecurityUploadRow]:
    """Validate a deterministic security-master seed without resolving it."""

    columns = {
        "security_id",
        "identifier",
        "identifier_scheme",
        "provider",
        "name",
        "security_type",
        "status",
        "exchange_mic",
        "exchange_timezone",
        "primary_currency",
        "country_code",
        "region",
        "sector",
        "industry",
        "benchmark",
        "first_trade_date",
        "last_trade_date",
        "valid_from",
        "valid_to",
    }
    return _parse_csv(
        source,
        model=SecurityUploadRow,
        required_columns={
            "security_id",
            "identifier",
            "identifier_scheme",
            "name",
            "security_type",
            "status",
            "primary_currency",
            "valid_from",
        },
        allowed_columns=columns,
    )
