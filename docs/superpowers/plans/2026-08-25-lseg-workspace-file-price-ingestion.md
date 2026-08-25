# LSEG Workspace and File Price Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest completed daily prices from an authenticated local LSEG Workspace session or an explicitly declared CSV/Parquet file through one point-in-time-safe, content-idempotent storage path.

**Architecture:** Keep PriceDataProvider as the stable port. Add a lazy desktop-only LSEG gateway, LSEG and file provider adapters, and a shared canonical-content builder that derives batch identity before constructing domain bars. Resolve every provider identifier through one continuous security-master mapping, preserve original-source and usage restrictions, and persist corrections as later knowledge-time vintages without automatic source fallback.

**Tech Stack:** Python 3.12, lseg-data 2.x, pandas 2.x, PyArrow 25.x, Pydantic 2, SQLAlchemy 2, Alembic, argparse, pytest, Ruff, and strict mypy.

**Spec:** docs/superpowers/specs/2026-08-25-lseg-workspace-file-price-ingestion-design.md

## Global Constraints

- Use only lseg.data with open_session(name="desktop.workspace") against the authenticated local Workspace process. Do not add a platform/cloud session, OAuth, App Key, client ID, or client secret.
- Never hardcode Workspace proxy port 9000; desktop configuration discovery belongs to the LSEG library.
- Source selection is explicit for every run. An LSEG error never causes an implicit file, Yahoo, fixture, or other-provider fallback.
- Fetch RICs sequentially. Each history request uses interval="1D", a non-overlapping inclusive chunk of at most 366 calendar days, and the approved raw or adjusted field map.
- Explicit SDK/status checks plus the 366-day and row-count bounds reduce the Access layer's silent-truncation risk; the live smoke must still verify the observed desktop response because a status-free truncation cannot be ruled out mathematically.
- Reject an end date on or after the acquisition clock's current UTC date.
- Preserve raw OHLCV separately from provider-adjusted close. Leave total_return_factor unset; adjusted close alone is not a dividend-reinvested total-return claim.
- A date-only bar uses midnight UTC only with ESTIMATED_TIMESTAMP. A snapshot without trustworthy source availability uses acquisition completion for available_at and ingested_at and carries SNAPSHOT_ONLY.
- DataUsageMode is required on every ingestion batch and price bar. LSEG is always research_only, fixtures synthetic, Yahoo public, generic files explicit, and migrated legacy rows unverified.
- Every batch persists a required 1-to-80-character original_source independently of its transport provider; every successful bar source must match it, including file batches, while all-failure batches retain it without bars.
- A research_only tag is an application restriction, not evidence that contractual extraction, storage, retention, or use rights have been approved.
- Canonical content excludes generated IDs and wall-clock request/acquisition timestamps. It includes a top-level original_source, deterministic effective time, and any trustworthy source-supplied available_at.
- Identical normalized content must reproduce the same batch identity. Changed content, mapping version, currency, original source, usage mode, authoritative source timestamp, or item-failure outcome must produce a new attempted batch identity. A changed observation persists as a correction only with later generated or authoritative availability; a different value at the same authoritative source/effective/available key is a rollback-safe conflict.
- Repositories flush but never commit. The CLI transaction owns commit/rollback.
- CI remains deterministic and does not install lseg-data or run external tests. Fake gateway tests cover the connector.
- Treat each native command shown on its own line as a separate invocation and stop immediately on an unexpected non-zero exit code; do not let a later PowerShell command mask an earlier failure. The only exceptions are steps explicitly labeled "confirm red" and explicit inverted absence checks: verify their documented failure reason/exit code, and stop if it differs.
- Each implementation task follows red-green-refactor, runs its focused checks, and commits only its listed files.

## File Map

- pyproject.toml: add the tested Parquet extra while retaining the existing optional LSEG extra and Python bound.
- .github/workflows/ci.yml: install Parquet support for deterministic file-provider tests; continue excluding external tests.
- .env.example: document only the Workspace desktop mode and remove cloud-credential placeholders.
- src/quant_raas/domain/enums.py: add usage and item-failure enums.
- src/quant_raas/domain/market.py: add required usage/original-source provenance and typed item failures to ingestion results.
- src/quant_raas/domain/protocols.py: expose identifier-record resolution for continuous mapping checks.
- src/quant_raas/normalization/price_content.py: define canonical pre-domain rows, hashing, batch identity input, and shared result construction.
- src/quant_raas/connectors/base.py: add explicit provider errors and content-addressed batch identity.
- src/quant_raas/connectors/fixture.py: emit synthetic usage and use shared content construction.
- src/quant_raas/connectors/public_fallback/yahoo.py: emit public usage and use shared content construction.
- src/quant_raas/connectors/file.py: load and normalize explicit CSV/Parquet price snapshots.
- src/quant_raas/connectors/lseg/gateway.py: own the only optional SDK import and one desktop session per request.
- src/quant_raas/connectors/lseg/provider.py: validate, join, normalize, and label LSEG daily pricing.
- src/quant_raas/connectors/lseg/__init__.py: export the implemented gateway/provider interfaces.
- src/quant_raas/ingestion/quality.py: validate failure and usage consistency.
- src/quant_raas/ingestion/prices.py: return typed item failures in the ingestion summary.
- src/quant_raas/config.py: accept only the supported desktop session setting.
- src/quant_raas/runtime.py: compose an explicitly selected LSEG or file provider without fallback.
- src/quant_raas/security_master/service.py: resolve one identifier mapping across the requested date range.
- src/quant_raas/storage/models.py: persist usage/original source and enforce batch/source-record uniqueness.
- src/quant_raas/storage/repositories.py: hydrate usage/original source and compare content/provenance on retries.
- migrations/versions/20260825_0005_price_provenance.py: atomically backfill legacy usage/original source with the required domain fields.
- migrations/versions/20260825_0006_price_attempt_identity.py: fail closed on legacy duplicates and add the new attempt constraint.
- src/quant_raas/cli.py: add finite ingest-prices parsing, composition, transaction handling, and safe JSON.
- tests/unit/: cover domain, canonical content, providers, gateway, settings, runtime, and CLI parsing.
- tests/integration/: cover migration, identifier resolution, repository retry/correction behavior, CLI, and provider-neutral ingestion.
- tests/external/test_lseg_workspace_smoke.py: manually gated live Workspace verification with no normal database persistence.
- README.md, PLAN.md, docs/data_contracts.md, docs/vendor_entitlements.md: document operation, lineage, limitations, and entitlement status.

---

### Task 0: Provision the supported local Python 3.12 environment

**Files:**

- None. Preserve .venv and .venv314 unchanged.

**Interfaces:**

- Consumes: the Windows Python launcher and a user-approved Python 3.12 installation route.
- Produces: .venv312 with the repository's deterministic development dependencies.

- [ ] **Step 1: Confirm the prerequisite is still absent**

Run:

~~~powershell
py -0p
Get-Command winget.exe
~~~

Expected before provisioning: no registered Python 3.12 interpreter. If Python 3.12 is already present, skip only the installation command and continue with virtual-environment creation.

- [ ] **Step 2: Request approval for the machine-level install**

At execution time, request escalation for this exact command because it writes outside the repository:

~~~powershell
winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
~~~

Do not run the command through another shell, do not remove either Python 3.14 environment, and do not relax requires-python=">=3.12,<3.14".

- [ ] **Step 3: Create and verify the dedicated environment**

Run:

~~~powershell
py -3.12 --version
py -3.12 -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install --upgrade pip
.\.venv312\Scripts\python.exe -m pip install -e ".[dev,api,dashboard]"
.\.venv312\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 12); print(sys.version)"
.\.venv312\Scripts\python.exe -m pip check
~~~

Expected: CPython 3.12, an editable install, and "No broken requirements found."
If either pip command fails because dependency downloads are sandbox- or network-blocked, rerun only that exact pip command with the required approval; do not redirect installation into a system interpreter.

- [ ] **Step 4: Record a clean baseline without changing files**

Run:

~~~powershell
git status --short --branch
.\.venv312\Scripts\python.exe -m pytest -m "not external" -q
~~~

Expected: the existing deterministic suite passes. Keep any pre-existing unrelated worktree changes untouched. This task has no commit.

---

### Task 1: Add explicit source/usage provenance and typed item failures

**Files:**

- Modify: src/quant_raas/domain/enums.py
- Modify: src/quant_raas/domain/market.py
- Modify: src/quant_raas/ingestion/quality.py
- Modify: src/quant_raas/ingestion/prices.py
- Modify: src/quant_raas/connectors/fixture.py
- Modify: src/quant_raas/connectors/public_fallback/yahoo.py
- Modify: src/quant_raas/storage/models.py
- Modify: src/quant_raas/storage/repositories.py
- Create: migrations/versions/20260825_0005_price_provenance.py
- Modify: tests/unit/test_domain_contracts.py
- Create: tests/unit/test_price_ingestion_quality.py
- Create: tests/integration/test_price_provenance_migration.py
- Modify: tests/integration/test_feature_value_encoding_migration.py
- Modify: tests/integration/test_storage_roundtrip.py

**Interfaces:**

- DataUsageMode has exactly research_only, public, synthetic, user_supplied, and unverified.
- PriceFailureCategory has exactly no_data, invalid_identifier, and invalid_currency.
- PriceItemFailure carries provider_identifier, category, and a sanitized message.
- IngestionBatch carries a required original_source independently of its transport provider.
- Domain, ORM, repository hydration, and migration support for required provenance land in the same commit.
- PriceIngestionResult and PriceIngestionSummary expose failures as immutable tuples.

- [ ] **Step 1: Write failing domain and ingestion-quality tests**

Create these fixed local helpers in tests/unit/test_price_ingestion_quality.py:

~~~python
NOW = datetime(2024, 1, 10, 10, 0, tzinfo=UTC)
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
BATCH_ID = UUID("22222222-2222-4222-8222-222222222222")


def _request() -> PriceBarRequest:
    return PriceBarRequest(
        items=(
            PriceRequestItem(
                security_id=SECURITY_ID,
                provider_identifier="EXAMPLE.O",
            ),
        ),
        start_date=date(2024, 1, 9),
        end_date=date(2024, 1, 9),
        requested_at=NOW - timedelta(minutes=2),
    )


def _batch(
    *,
    status: BatchStatus = BatchStatus.SUCCEEDED,
    usage_mode: DataUsageMode = DataUsageMode.SYNTHETIC,
    row_count: int = 1,
    error_message: str | None = None,
) -> IngestionBatch:
    return IngestionBatch(
        batch_id=BATCH_ID,
        batch_key="fixture:1234567890abcdef",
        provider="fixture",
        original_source="fixture",
        dataset="daily_price_bar",
        requested_at=NOW - timedelta(minutes=2),
        started_at=NOW - timedelta(minutes=1),
        completed_at=NOW,
        status=status,
        request_fingerprint="12345678fixture",
        content_hash="abcdef12fixture",
        row_count=row_count,
        error_message=error_message,
        usage_mode=usage_mode,
    )


def _bar(
    *,
    usage_mode: DataUsageMode = DataUsageMode.SYNTHETIC,
) -> PriceBar:
    return PriceBar(
        security_id=SECURITY_ID,
        session_date=date(2024, 1, 9),
        effective_at=datetime(2024, 1, 9, tzinfo=UTC),
        available_at=NOW,
        ingested_at=NOW,
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        adjusted_close=100.5,
        volume=1_000.0,
        currency="USD",
        adjustment_factor=100.5 / 101.0,
        source="fixture",
        source_record_id="EXAMPLE.O:2024-01-09",
        provider_identifier="EXAMPLE.O",
        ingestion_batch_id=BATCH_ID,
        quality_flags=(DataQualityFlag.ESTIMATED_TIMESTAMP,),
        usage_mode=usage_mode,
    )


def test_price_usage_and_failure_enums_are_stable() -> None:
    assert tuple(mode.value for mode in DataUsageMode) == (
        "research_only",
        "public",
        "synthetic",
        "user_supplied",
        "unverified",
    )
    assert tuple(category.value for category in PriceFailureCategory) == (
        "no_data",
        "invalid_identifier",
        "invalid_currency",
    )


def test_price_result_preserves_typed_item_failure() -> None:
    failure = PriceItemFailure(
        provider_identifier="MISSING.O",
        category=PriceFailureCategory.NO_DATA,
        message="MISSING.O: no completed daily rows",
    )
    result = PriceIngestionResult(
        batch=_batch(
            status=BatchStatus.FAILED,
            row_count=0,
            error_message=failure.message,
        ),
        bars=(),
        failures=(failure,),
    )
    assert result.failures == (failure,)


def test_price_result_rejects_usage_mismatch() -> None:
    result = PriceIngestionResult(
        batch=_batch(),
        bars=(_bar(usage_mode=DataUsageMode.PUBLIC),),
    )
    with pytest.raises(ValueError, match="share their ingestion batch usage_mode"):
        validate_price_result(_request(), result)
~~~

Also add tests that omitting usage_mode from IngestionBatch or PriceBar, or omitting original_source from IngestionBatch, raises Pydantic ValidationError; original_source must contain 1 to 80 characters; a provider result must be terminal; SUCCEEDED requires bars and no failures; PARTIAL requires both; FAILED requires failures and no bars; every returned bar source must equal batch.original_source; failure identifiers must belong to the request; and duplicate failure identifiers are rejected. Add test_price_ingestion_service_sanitizes_provider_result_invariant_error: a fake provider returns a typed but cross-record-inconsistent result containing a sentinel identifier, the repository is a fail-if-called spy, and the service raises exactly ProviderDataError("provider result failed price-ingestion validation") with the sentinel absent from its formatted exception chain.

In tests/integration/test_price_provenance_migration.py, create a SQLite database at revision 20260821_0004 with one legacy batch and bar. Add test_price_provenance_migration_backfills_and_round_trips, test_price_provenance_migration_rejects_invalid_legacy_provider_before_ddl, and test_price_provenance_metadata_matches_head_schema. Assert legacy batch/bar usage becomes "unverified", batch original_source is copied from its provider, all three new columns are non-null with no remaining server defaults, a blank or over-80-character legacy provider fails with an actionable RuntimeError before schema mutation, downgrade restores the exact prior column sets without deleting rows, and re-upgrade succeeds. Pin revision-specific backfill/downgrade assertions to a PROVENANCE_REVISION constant; only the ORM/head-metadata assertion upgrades to head. In test_storage_roundtrip.py, assert explicit original_source and usage_mode round-trip on both successful and failed-without-bars batches.

The existing tests/integration/test_feature_value_encoding_migration.py is revision-specific but currently upgrades to "head" and then asserts ENCODING_REVISION. Replace every `command.upgrade(config, "head")` in that file with `command.upgrade(config, ENCODING_REVISION)`, rename `test_head_writes_round_trip_and_downgrade_unwraps_exactly_once` to `test_encoding_revision_writes_round_trip_and_downgrade_unwraps_exactly_once`, and rename only local `head_values`-style variables for clarity. Do not change its migration semantics. This keeps the older migration contract pinned when 0005 and 0006 become later heads.

- [ ] **Step 2: Run the tests and confirm red**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_domain_contracts.py tests\unit\test_price_ingestion_quality.py tests\integration\test_price_provenance_migration.py tests\integration\test_storage_roundtrip.py -v
~~~

Expected: imports or validation assertions fail because the new enums, fields, failure tuple, ORM columns, and migration do not exist.

- [ ] **Step 3: Add the minimal domain contracts**

Add:

~~~python
class DataUsageMode(StrEnum):
    RESEARCH_ONLY = "research_only"
    PUBLIC = "public"
    SYNTHETIC = "synthetic"
    USER_SUPPLIED = "user_supplied"
    UNVERIFIED = "unverified"


class PriceFailureCategory(StrEnum):
    NO_DATA = "no_data"
    INVALID_IDENTIFIER = "invalid_identifier"
    INVALID_CURRENCY = "invalid_currency"
~~~

Add a required, default-free `original_source: str = Field(min_length=1, max_length=80)` to IngestionBatch and required, default-free usage_mode fields to IngestionBatch and PriceBar, then add:

~~~python
class PriceItemFailure(DomainModel):
    provider_identifier: str = Field(min_length=1, max_length=128)
    category: PriceFailureCategory
    message: str = Field(min_length=1, max_length=500)


class PriceIngestionResult(DomainModel):
    batch: IngestionBatch
    bars: tuple[PriceBar, ...]
    failures: tuple[PriceItemFailure, ...] = ()
~~~

Extend PriceIngestionSummary:

~~~python
@dataclass(frozen=True, slots=True)
class PriceIngestionSummary:
    batch: IngestionBatch
    bars_received: int
    bars_inserted: int
    failures: tuple[PriceItemFailure, ...]
~~~

Return result.failures from PriceIngestionService.ingest. In validate_price_result, enforce:

~~~python
if any(bar.usage_mode != result.batch.usage_mode for bar in result.bars):
    raise ValueError("all price bars must share their ingestion batch usage_mode")
if any(bar.source != result.batch.original_source for bar in result.bars):
    raise ValueError("all price bars must share their ingestion batch original_source")
if result.batch.status not in {
    BatchStatus.SUCCEEDED,
    BatchStatus.PARTIAL,
    BatchStatus.FAILED,
}:
    raise ValueError("a provider response requires a terminal batch status")
if result.batch.status == BatchStatus.SUCCEEDED and result.failures:
    raise ValueError("a succeeded price ingestion cannot contain item failures")
if result.batch.status == BatchStatus.SUCCEEDED and not result.bars:
    raise ValueError("a succeeded price ingestion requires persisted bars")
if result.batch.status == BatchStatus.PARTIAL and (
    not result.bars or not result.failures
):
    raise ValueError("a partial price ingestion requires bars and item failures")
if result.batch.status == BatchStatus.FAILED and (
    result.bars or not result.failures
):
    raise ValueError(
        "a failed price ingestion requires item failures and no persisted bars"
    )

requested_identifiers = {item.provider_identifier for item in request.items}
failure_identifiers = [failure.provider_identifier for failure in result.failures]
if any(identifier not in requested_identifiers for identifier in failure_identifiers):
    raise ValueError("price ingestion contains a failure for an unrequested identifier")
if len(failure_identifiers) != len(set(failure_identifiers)):
    raise ValueError("price ingestion contains duplicate item failures")
~~~

Keep the validator's detailed ValueError messages for focused internal tests, but make the application service a sanitized provider boundary before any repository call:

~~~python
try:
    validate_price_result(request, result)
except ValueError:
    raise ProviderDataError(
        "provider result failed price-ingestion validation"
    ) from None
~~~

Do not catch ValueError broadly in the CLI; only this service boundary knows that the ValueError represents an invalid provider result rather than a programming defect.

Update the PriceBar docstring to allow a midnight-UTC date key only when ESTIMATED_TIMESTAMP is present and to state that usage_mode is a handling restriction, not entitlement approval.

- [ ] **Step 4: Land ORM, repository, and migration support atomically**

Add these mapped fields:

~~~python
class IngestionBatchRecord(Base):
    original_source: Mapped[str] = mapped_column(String(80), nullable=False)
    usage_mode: Mapped[str] = mapped_column(String(40), nullable=False)


class PriceBarRecord(Base):
    usage_mode: Mapped[str] = mapped_column(String(40), nullable=False)
~~~

Create revision="20260825_0005" with down_revision="20260821_0004". Before schema mutation, query for the first ingestion_batch whose provider is null, blank after trimming, or longer than 80 characters and raise RuntimeError("cannot backfill ingestion batch original_source: legacy provider must contain 1 to 80 characters") if one exists. Add each usage_mode with temporary server_default=sa.text("'unverified'") and explicitly update all rows to "unverified". Add ingestion_batch.original_source as nullable String(80), populate it from each validated existing ingestion_batch.provider, then use batch_alter_table to make all three columns non-null and remove defaults. Downgrade drops exactly the three new columns. Do not add the attempt unique constraint in this migration and never infer usage rights from legacy source text.

In add_ingestion_batch, serialize usage_mode.value, persist original_source, and hydrate both fields from an existing record. In upsert_price_bars, serialize usage_mode.value; in _price_bar_from_record, hydrate DataUsageMode(record.usage_mode). This compatibility work must be in the same commit as the required Pydantic fields so no intermediate commit passes unknown model_dump keys into older ORM records.

- [ ] **Step 5: Update existing constructors explicitly**

Set FixturePriceProvider batches/bars to original_source="fixture" and DataUsageMode.SYNTHETIC; set YahooFinancePriceProvider batches/bars to original_source="yahoo" and DataUsageMode.PUBLIC. Set hand-built legacy-oriented test objects to an explicit original_source matching their bar source and DataUsageMode.UNVERIFIED unless a test is specifically asserting another source policy. Do not add a domain default that could silently label new data.

- [ ] **Step 6: Run focused verification**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_domain_contracts.py tests\unit\test_price_ingestion_quality.py tests\unit\test_fixture_provider.py tests\integration\test_price_provenance_migration.py tests\integration\test_feature_value_encoding_migration.py tests\integration\test_storage_roundtrip.py -v
.\.venv312\Scripts\python.exe -m ruff check src\quant_raas\domain src\quant_raas\ingestion src\quant_raas\storage migrations tests\unit\test_domain_contracts.py tests\unit\test_price_ingestion_quality.py tests\integration\test_price_provenance_migration.py tests\integration\test_feature_value_encoding_migration.py
.\.venv312\Scripts\python.exe -m mypy src\quant_raas\domain src\quant_raas\ingestion src\quant_raas\storage
~~~

Expected: all focused tests and static checks pass.

- [ ] **Step 7: Commit**

~~~powershell
git add src/quant_raas/domain/enums.py src/quant_raas/domain/market.py src/quant_raas/ingestion/quality.py src/quant_raas/ingestion/prices.py src/quant_raas/connectors/fixture.py src/quant_raas/connectors/public_fallback/yahoo.py src/quant_raas/storage/models.py src/quant_raas/storage/repositories.py migrations/versions/20260825_0005_price_provenance.py tests/unit/test_domain_contracts.py tests/unit/test_price_ingestion_quality.py tests/integration/test_price_provenance_migration.py tests/integration/test_feature_value_encoding_migration.py tests/integration/test_storage_roundtrip.py
git commit -m "feat: add explicit price provenance"
~~~

---

### Task 2: Add canonical price content and content-addressed result construction

**Files:**

- Create: src/quant_raas/normalization/price_content.py
- Modify: src/quant_raas/connectors/base.py
- Modify: src/quant_raas/connectors/fixture.py
- Modify: src/quant_raas/connectors/public_fallback/yahoo.py
- Create: tests/unit/test_price_content.py
- Modify: tests/unit/test_fixture_provider.py
- Create: tests/unit/test_yahoo_provider.py

**Interfaces:**

- NormalizedPriceRow is the acquisition-independent row used before domain IDs exist.
- NormalizedPriceContent contains a required original source, sorted rows, and typed failures.
- build_price_ingestion_result is the only connector helper that hashes content, derives a batch identity, and constructs PriceBar objects.

- [ ] **Step 1: Write failing canonicalization tests**

Create these fixed helpers in tests/unit/test_price_content.py:

~~~python
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
REQUESTED_AT = datetime(2024, 1, 10, 9, 0, tzinfo=UTC)


def _request() -> PriceBarRequest:
    return PriceBarRequest(
        items=(
            PriceRequestItem(
                security_id=SECURITY_ID,
                provider_identifier="EXAMPLE.O",
            ),
        ),
        start_date=date(2024, 1, 8),
        end_date=date(2024, 1, 9),
        requested_at=REQUESTED_AT,
    )


def _row(
    session_date: date,
    close: float,
    *,
    source_available_at: datetime | None = None,
) -> NormalizedPriceRow:
    adjusted_close = close - 0.25
    return NormalizedPriceRow(
        security_id=SECURITY_ID,
        provider_identifier="EXAMPLE.O",
        source_record_id=f"fixture:EXAMPLE.O:{session_date.isoformat()}",
        session_date=session_date,
        effective_at=date_key_effective_at(session_date),
        source_available_at=source_available_at,
        open=close - 0.5,
        high=close + 0.5,
        low=close - 1.0,
        close=close,
        adjusted_close=adjusted_close,
        volume=1_000.5,
        currency="USD",
        adjustment_factor=adjusted_close / close,
        total_return_factor=None,
        source="fixture",
        usage_mode=DataUsageMode.SYNTHETIC,
        quality_flags=(
            (DataQualityFlag.SNAPSHOT_ONLY, DataQualityFlag.ESTIMATED_TIMESTAMP)
            if source_available_at is None
            else (DataQualityFlag.ESTIMATED_TIMESTAMP,)
        ),
        field_map_version="fixture_daily_price_v1",
    )


def _failure(
    provider_identifier: str,
    category: PriceFailureCategory,
) -> PriceItemFailure:
    return PriceItemFailure(
        provider_identifier=provider_identifier,
        category=category,
        message=f"{provider_identifier}: {category.value}",
    )


def _build_result(completed_at: datetime) -> PriceIngestionResult:
    return build_price_ingestion_result(
        provider="fixture",
        original_source="fixture",
        dataset="daily_price_bar",
        request=_request(),
        field_map_version="fixture_daily_price_v1",
        usage_mode=DataUsageMode.SYNTHETIC,
        rows=(_row(date(2024, 1, 9), 101.25),),
        failures=(),
        started_at=completed_at - timedelta(seconds=1),
        completed_at=completed_at,
    )


def test_canonical_content_is_order_invariant_and_uses_float_hex() -> None:
    first = NormalizedPriceContent(
        original_source="fixture",
        rows=(
            _row(date(2024, 1, 9), 101.25),
            _row(date(2024, 1, 8), 100.5),
        ),
        failures=(
            _failure("Z.O", PriceFailureCategory.NO_DATA),
            _failure("A.O", PriceFailureCategory.INVALID_IDENTIFIER),
        ),
    )
    reordered = NormalizedPriceContent(
        original_source=first.original_source,
        rows=tuple(reversed(first.rows)),
        failures=tuple(reversed(first.failures)),
    )
    payload = canonical_price_content(first)
    assert payload == canonical_price_content(reordered)
    assert float(101.25).hex().encode() in payload
    assert b'"requested_at"' not in payload
    assert b'"ingested_at"' not in payload


def test_generated_acquisition_time_does_not_change_identity() -> None:
    first = _build_result(datetime(2024, 1, 10, 10, 0, tzinfo=UTC))
    second = _build_result(datetime(2024, 1, 11, 10, 0, tzinfo=UTC))
    assert first.batch.content_hash == second.batch.content_hash
    assert first.batch.batch_id == second.batch.batch_id
    assert first.bars[0].available_at != second.bars[0].available_at


def test_source_supplied_availability_changes_identity() -> None:
    first = NormalizedPriceContent(
        original_source="fixture",
        rows=(
            _row(
                date(2024, 1, 9),
                101.25,
                source_available_at=datetime(2024, 1, 9, 21, 5, tzinfo=UTC),
            ),
        )
    )
    second = NormalizedPriceContent(
        original_source="fixture",
        rows=(
            _row(
                date(2024, 1, 9),
                101.25,
                source_available_at=datetime(2024, 1, 9, 21, 6, tzinfo=UTC),
            ),
        )
    )
    assert hash_price_content(first) != hash_price_content(second)
~~~

Add `test_all_failure_content_is_bound_to_original_source`: construct two zero-row contents with the same typed failure but original_source values `lseg` and `user_export`; assert different hashes, then build both through provider="file" and assert different batch IDs plus the exact persisted batch.original_source. Also prove that an empty, whitespace-only, or over-80-character original source is rejected; row order, flag order, and failure order do not matter; and changing a numeric value, currency, row source, usage mode, field-map version, failure identifier, or failure category changes the content hash or derived batch identity as applicable.

- [ ] **Step 2: Run the tests and confirm red**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_price_content.py -v
~~~

Expected: import failure for quant_raas.normalization.price_content.

- [ ] **Step 3: Implement the pre-domain projection**

Create these exact immutable data shapes:

~~~python
@dataclass(frozen=True, slots=True)
class NormalizedPriceRow:
    security_id: UUID
    provider_identifier: str
    source_record_id: str
    session_date: date
    effective_at: datetime
    source_available_at: datetime | None
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: float
    currency: str
    adjustment_factor: float | None
    total_return_factor: float | None
    source: str
    usage_mode: DataUsageMode
    quality_flags: tuple[DataQualityFlag, ...]
    field_map_version: str


@dataclass(frozen=True, slots=True)
class NormalizedPriceContent:
    original_source: str
    rows: tuple[NormalizedPriceRow, ...]
    failures: tuple[PriceItemFailure, ...] = ()
~~~

Canonicalize with one schema-tagged JSON object. Convert every numeric field with float(value).hex(), every datetime with ensure_utc(value).isoformat(), every enum with value, and sort the complete serialized row/failure objects rather than relying on caller order:

~~~python
def canonical_price_content(content: NormalizedPriceContent) -> bytes:
    original_source = normalize_original_source(content.original_source)
    rows = [_canonical_row(row) for row in content.rows]
    failures = [
        {
            "provider_identifier": failure.provider_identifier,
            "category": failure.category.value,
        }
        for failure in content.failures
    ]
    rows.sort(key=_canonical_json)
    failures.sort(key=_canonical_json)
    payload = {
        "schema": "normalized_price_content_v1",
        "original_source": original_source,
        "rows": rows,
        "failures": failures,
    }
    return _canonical_json(payload).encode("utf-8")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def hash_price_content(content: NormalizedPriceContent) -> str:
    return hashlib.sha256(canonical_price_content(content)).hexdigest()


def date_key_effective_at(session_date: date) -> datetime:
    return datetime.combine(session_date, time.min, tzinfo=UTC)
~~~

Use this complete row projection:

~~~python
def _optional_hex(value: float | None) -> str | None:
    return None if value is None else float(value).hex()


def _canonical_row(row: NormalizedPriceRow) -> dict[str, object]:
    return {
        "security_id": str(row.security_id),
        "provider_identifier": row.provider_identifier,
        "source_record_id": row.source_record_id,
        "session_date": row.session_date.isoformat(),
        "effective_at": ensure_utc(row.effective_at).isoformat(),
        "source_available_at": (
            ensure_utc(row.source_available_at).isoformat()
            if row.source_available_at is not None
            else None
        ),
        "open": float(row.open).hex(),
        "high": float(row.high).hex(),
        "low": float(row.low).hex(),
        "close": float(row.close).hex(),
        "adjusted_close": float(row.adjusted_close).hex(),
        "volume": float(row.volume).hex(),
        "currency": row.currency,
        "adjustment_factor": _optional_hex(row.adjustment_factor),
        "total_return_factor": _optional_hex(row.total_return_factor),
        "source": row.source,
        "usage_mode": row.usage_mode.value,
        "quality_flags": sorted(flag.value for flag in row.quality_flags),
        "field_map_version": row.field_map_version,
    }
~~~

The content model must not accept requested_at, started_at, completed_at, generated available_at, ingested_at, batch_id, or price_bar_id.

- [ ] **Step 4: Derive batch identity from all stable dimensions**

Replace request-only stable_batch_id and batch_key with:

~~~python
@dataclass(frozen=True, slots=True)
class BatchIdentity:
    batch_id: UUID
    batch_key: str


def content_addressed_batch_identity(
    *,
    provider: str,
    dataset: str,
    request_fingerprint: str,
    field_map_version: str,
    usage_mode: DataUsageMode,
    content_hash: str,
) -> BatchIdentity:
    payload = json.dumps(
        {
            "provider": provider,
            "dataset": dataset,
            "request_fingerprint": request_fingerprint,
            "field_map_version": field_map_version,
            "usage_mode": usage_mode.value,
            "content_hash": content_hash,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return BatchIdentity(
        batch_id=uuid5(CONNECTOR_NAMESPACE, digest),
        batch_key=f"{provider}:{digest[:40]}",
    )
~~~

Keep fingerprint_request unchanged because it is the logical request fingerprint.

Add one shared acquisition-clock guard and use it in Fixture, Yahoo, File, and LSEG providers:

~~~python
def acquisition_started_at(
    request: PriceBarRequest,
    observed_at: datetime,
) -> datetime:
    acquired_at = require_utc(observed_at, field_name="acquisition clock")
    if request.requested_at > acquired_at:
        raise ProviderDataError(
            "request timestamp cannot be later than the acquisition clock"
        )
    return acquired_at
~~~

Add a unit test proving a future requested_at is rejected rather than copied into started_at, available_at, or ingested_at.

- [ ] **Step 5: Implement shared batch/bar construction**

Add this public signature to price_content.py:

~~~python
def build_price_ingestion_result(
    *,
    provider: str,
    original_source: str,
    dataset: str,
    request: PriceBarRequest,
    field_map_version: str,
    usage_mode: DataUsageMode,
    rows: tuple[NormalizedPriceRow, ...],
    failures: tuple[PriceItemFailure, ...],
    started_at: datetime,
    completed_at: datetime,
) -> PriceIngestionResult:
    normalized_original_source = normalize_original_source(original_source)
    normalized_started = require_utc(started_at, field_name="started_at")
    normalized_completed = require_utc(completed_at, field_name="completed_at")
    prepared_rows = _prepare_rows(
        rows,
        original_source=normalized_original_source,
        usage_mode=usage_mode,
        field_map_version=field_map_version,
    )
    content = NormalizedPriceContent(
        original_source=normalized_original_source,
        rows=prepared_rows,
        failures=failures,
    )
    content_hash = hash_price_content(content)
    request_fingerprint = fingerprint_request(request)
    identity = content_addressed_batch_identity(
        provider=provider,
        dataset=dataset,
        request_fingerprint=request_fingerprint,
        field_map_version=field_map_version,
        usage_mode=usage_mode,
        content_hash=content_hash,
    )
    bars = tuple(
        _price_bar_from_normalized(
            row,
            batch_id=identity.batch_id,
            completed_at=normalized_completed,
        )
        for row in prepared_rows
    )
    status = _batch_status(bars=bars, failures=failures)
    batch = IngestionBatch(
        batch_id=identity.batch_id,
        batch_key=identity.batch_key,
        provider=provider,
        original_source=normalized_original_source,
        dataset=dataset,
        requested_at=request.requested_at,
        started_at=normalized_started,
        completed_at=normalized_completed,
        status=status,
        request_fingerprint=request_fingerprint,
        content_hash=content_hash,
        row_count=len(bars),
        error_message=_failure_message(failures),
        usage_mode=usage_mode,
    )
    return PriceIngestionResult(batch=batch, bars=bars, failures=failures)
~~~

Implement normalize_original_source by stripping and lower-casing text, then raising ProviderDataError("original source must contain 1 to 80 characters") unless its length is 1 through 80. Implement _prepare_rows with dataclasses.replace: reject any row whose source differs from normalized_original_source or whose usage_mode or field_map_version differs from the function arguments; normalize effective_at and any source_available_at with ensure_utc; add SNAPSHOT_ONLY when source_available_at is absent; de-duplicate and sort flags by value; sort rows by security UUID, provider identifier, session date, and source record ID; and reject duplicate source_record_id values before hashing. Reject completed_at before started_at and explicit source availability outside effective_at <= source_available_at <= completed_at.

_price_bar_from_normalized uses source_available_at or completed_at as available_at, completed_at as ingested_at, uuid5(batch_id, source_record_id) as price_bar_id, and every remaining row field unchanged. _batch_status returns succeeded for rows only, partial for rows plus failures, and failed for failures without rows; it raises ProviderDataError when both collections are empty. _failure_message joins deterministic "identifier: category: message" entries sorted by identifier/category and caps the result at 4,000 characters.

- [ ] **Step 6: Refactor fixture and Yahoo onto the shared builder**

Define FIXTURE_PRICE_FIELD_MAP_VERSION="fixture_daily_price_v1" and YAHOO_PRICE_FIELD_MAP_VERSION="yahoo_daily_price_v1". Have each adapter create NormalizedPriceRow objects plus typed failures, then call build_price_ingestion_result with original_source="fixture" or original_source="yahoo". Remove the duplicated JSON hashing and request-only batch-ID code. Preserve explicit fixture timestamps as source timestamps; generated snapshot times remain excluded from content identity.

For Yahoo, an empty DataFrame is a typed NO_DATA item failure. A malformed non-empty schema raises sanitized ProviderDataError("Yahoo response failed daily-price validation") from None. A download/session/network exception raises ProviderError("Yahoo price request failed") from None and aborts the response; never place an arbitrary exception string in a typed failure, batch message, or rendered exception chain.

Add assertions that fixture usage is synthetic, Yahoo usage is public, identical content is stable across different injected acquisition clocks, and no adapter imports or selects another source.
In tests/unit/test_yahoo_provider.py, inject a fake yfinance module through monkeypatch.setitem(sys.modules, "yfinance", fake_module). Cover a valid public result, an empty NO_DATA result, malformed non-empty data raising the fixed ProviderDataError, and a downloader exception raising the fixed ProviderError. Put a sentinel in each underlying exception and assert it is absent from str(error) and "".join(traceback.format_exception(error)).

- [ ] **Step 7: Run focused verification**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_price_content.py tests\unit\test_fixture_provider.py tests\unit\test_yahoo_provider.py -v
.\.venv312\Scripts\python.exe -m ruff format --check src\quant_raas\normalization\price_content.py src\quant_raas\connectors tests\unit\test_price_content.py tests\unit\test_fixture_provider.py
.\.venv312\Scripts\python.exe -m ruff check src\quant_raas\normalization\price_content.py src\quant_raas\connectors tests\unit\test_price_content.py tests\unit\test_fixture_provider.py
.\.venv312\Scripts\python.exe -m mypy src\quant_raas\normalization\price_content.py src\quant_raas\connectors
~~~

Expected: all focused tests and static checks pass.

- [ ] **Step 8: Commit**

~~~powershell
git add src/quant_raas/normalization/price_content.py src/quant_raas/connectors/base.py src/quant_raas/connectors/fixture.py src/quant_raas/connectors/public_fallback/yahoo.py tests/unit/test_price_content.py tests/unit/test_fixture_provider.py tests/unit/test_yahoo_provider.py
git commit -m "feat: add canonical price content identity"
~~~

---

### Task 3: Enforce content-attempt identity

**Files:**

- Modify: src/quant_raas/storage/models.py
- Modify: src/quant_raas/storage/repositories.py
- Create: migrations/versions/20260825_0006_price_attempt_identity.py
- Create: tests/integration/test_price_attempt_identity_migration.py
- Create: tests/integration/test_price_repository_idempotency.py
- Modify: tests/integration/test_storage_roundtrip.py
- Modify: tests/integration/test_price_ingestion_pipeline.py

**Interfaces:**

- Task 1's source/usage domain and persistence columns are the starting schema, not work deferred into this task.
- PriceBarRecord adds uq_price_bar_ingestion_batch_source_record over ingestion_batch_id and source_record_id.
- Existing retries compare stable content/provenance and ignore regenerated acquisition timestamps.

- [ ] **Step 1: Write the failing migration tests**

Create SQLite databases at revision 20260825_0005 with non-conflicting and duplicate attempt rows. Add tests named:

- test_price_attempt_migration_adds_unique_constraint
- test_price_attempt_migration_rejects_legacy_duplicate_rows_before_ddl
- test_price_attempt_metadata_matches_head_schema

Assert the named constraint rejects a duplicate pair even with another available_at; the duplicate preflight raises the exact actionable RuntimeError before any DDL; downgrade removes only the new constraint and preserves Task 1's three provenance columns and every row; and re-upgrade succeeds.

- [ ] **Step 2: Run the migration test and confirm red**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\integration\test_price_attempt_identity_migration.py -v
~~~

Expected: failure because revision 20260825_0006 and the attempt constraint do not exist.

- [ ] **Step 3: Add the ORM constraint and focused migration**

Add this constraint alongside uq_price_bar_vintage:

~~~python
UniqueConstraint(
    "ingestion_batch_id",
    "source_record_id",
    name="uq_price_bar_ingestion_batch_source_record",
)
~~~

Set revision="20260825_0006" and down_revision="20260825_0005". Before any schema mutation, run:

~~~python
duplicate = op.get_bind().execute(
    sa.text(
        "SELECT ingestion_batch_id, source_record_id "
        "FROM price_bar "
        "GROUP BY ingestion_batch_id, source_record_id "
        "HAVING COUNT(*) > 1 "
        "LIMIT 1"
    )
).first()
if duplicate is not None:
    raise RuntimeError(
        "cannot add price attempt identity: duplicate legacy "
        "(ingestion_batch_id, source_record_id) rows must be remediated first"
    )
~~~

Then create uq_price_bar_ingestion_batch_source_record with batch_alter_table. Downgrade drops only that constraint. Do not touch the required provenance columns introduced by revision 20260825_0005.

- [ ] **Step 4: Write failing repository idempotency tests**

Cover these exact cases:

- An identical batch key and ID with later request/start/completion clocks returns the first batch.
- A matching ingestion_batch_id/source_record_id with a new bar UUID and later generated availability/ingestion inserts zero rows.
- The same attempt pair with changed close, currency, provider_identifier, flags, source, or usage raises RepositoryConflictError.
- A reused batch key or batch ID with changed stable batch identity, including original_source, raises RepositoryConflictError.
- A distinct batch/attempt with changed numerical content at the same source/effective/authoritative-available natural key raises RepositoryConflictError instead of overwriting or inventing a timestamp.
- A changed content hash/batch identity with later available_at inserts a correction vintage.
- price_history_as_of returns the old value before the correction cutoff and the new value after it.

Update test_price_and_feature_repositories_return_latest_knowable_vintage so the old and revised bars belong to distinct batches with row_count=1, distinct IDs/keys/content hashes, and the same source_record_id.

- [ ] **Step 5: Run repository tests and confirm red**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\integration\test_price_repository_idempotency.py tests\integration\test_storage_roundtrip.py tests\integration\test_price_ingestion_pipeline.py -v
~~~

Expected: permissive batch reuse and the old natural-vintage-only retry path fail the new assertions; Task 1's provenance round-trip remains green.

- [ ] **Step 6: Implement stable conflict comparison**

In add_ingestion_batch, look up by both batch_id and batch_key. If they resolve to different rows, or if an existing row differs on any of these fields, raise RepositoryConflictError("ingestion batch identity contains different content or provenance"):

~~~python
(
    "batch_id",
    "batch_key",
    "provider",
    "original_source",
    "dataset",
    "status",
    "request_fingerprint",
    "content_hash",
    "row_count",
    "usage_mode",
)
~~~

Ignore requested_at, started_at, completed_at, and formatted error_message for retry identity. Preserve Task 1's usage_mode/original_source serialization and hydration while adding the stronger identity comparison.

In upsert_price_bars, query the attempt pair before the natural vintage. Compare:

~~~python
def _stable_price_bar_payload(bar: PriceBar) -> tuple[object, ...]:
    return (
        bar.security_id,
        bar.session_date,
        bar.frequency.value,
        bar.effective_at,
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        bar.adjusted_close,
        bar.volume,
        bar.currency,
        bar.adjustment_factor,
        bar.total_return_factor,
        bar.source,
        bar.source_record_id,
        bar.provider_identifier,
        tuple(sorted(flag.value for flag in bar.quality_flags)),
        bar.usage_mode.value,
    )
~~~

Ignore price_bar_id, available_at, and ingested_at only for a matching attempt pair. Equal content skips; unequal content raises RepositoryConflictError("price bar attempt identity contains different numerical or provenance values"). If no attempt pair exists, retain the natural-vintage lookup and compare the full numerical/provenance payload; divergent content raises RepositoryConflictError("price bar vintage contains different numerical or provenance values"). Hydrate usage_mode in _price_bar_from_record.

- [ ] **Step 7: Run focused verification**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\integration\test_price_attempt_identity_migration.py tests\integration\test_price_repository_idempotency.py tests\integration\test_storage_roundtrip.py tests\integration\test_price_ingestion_pipeline.py -v
.\.venv312\Scripts\python.exe -m ruff check src\quant_raas\storage migrations tests\integration\test_price_attempt_identity_migration.py tests\integration\test_price_repository_idempotency.py
.\.venv312\Scripts\python.exe -m mypy src\quant_raas\storage
~~~

Expected: constraint round-trip, retry idempotency, correction vintages, provenance regression coverage, and static checks pass.

- [ ] **Step 8: Commit**

~~~powershell
git add src/quant_raas/storage/models.py src/quant_raas/storage/repositories.py migrations/versions/20260825_0006_price_attempt_identity.py tests/integration/test_price_attempt_identity_migration.py tests/integration/test_price_repository_idempotency.py tests/integration/test_storage_roundtrip.py tests/integration/test_price_ingestion_pipeline.py
git commit -m "feat: enforce price ingestion attempt identity"
~~~

---

### Task 4: Ingest normalized daily prices from CSV and Parquet

**Files:**

- Create: src/quant_raas/connectors/file.py
- Create: tests/unit/test_file_price_provider.py
- Modify: pyproject.toml
- Modify: .github/workflows/ci.yml

**Interfaces:**

- FilePriceProvider(path, source, usage_mode, clock) implements PriceDataProvider.
- FILE_PRICE_FIELD_MAP_VERSION is "file_daily_price_v1".
- The normalized content and persisted batch retain the declared original source even when no bars are produced.
- CSV is in base pandas; Parquet uses the optional parquet extra and never falls back to CSV parsing.

- [ ] **Step 1: Write the failing CSV structure/subset tests**

Create one DataFrame fixture and write it to CSV and Parquet. Add these exact tests:

- test_file_columns_are_case_insensitive_and_default_source_record_id_is_deterministic
- test_file_provider_preserves_original_source_and_usage_mode
- test_lseg_file_requires_research_only_usage
- test_duplicate_selected_identifier_dates_are_rejected_before_normalization
- test_unrequested_and_out_of_range_rows_are_ignored
- test_requested_identifier_without_rows_is_a_no_data_failure
- test_all_missing_items_return_a_persistable_failed_batch_with_original_source
- test_unsupported_suffix_missing_columns_and_malformed_csv_raise_fixed_data_errors
- test_invalid_session_date_raises_fixed_provider_data_error

- [ ] **Step 2: Run the CSV slice and confirm red**

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_file_price_provider.py -k "not parquet and not timestamp and not adjusted_close" -v
~~~

Expected test result: import failure for quant_raas.connectors.file.

- [ ] **Step 3: Implement the minimal strict CSV/subset path**

Create:

~~~python
FILE_PRICE_FIELD_MAP_VERSION = "file_daily_price_v1"
FILE_REQUIRED_COLUMNS = (
    "provider_identifier",
    "session_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "currency",
)
FILE_OPTIONAL_COLUMNS = (
    "adjusted_close",
    "effective_at",
    "available_at",
    "source_record_id",
)


class FilePriceProvider:
    name = "file"

    def __init__(
        self,
        path: Path,
        *,
        source: str,
        usage_mode: DataUsageMode,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._path = path
        self._source = normalize_original_source(source)
        self._usage_mode = usage_mode
        self._clock = clock
        if self._source == "lseg" and usage_mode != DataUsageMode.RESEARCH_ONLY:
            raise ProviderNotConfigured(
                "an LSEG-derived file must use research_only handling"
            )
~~~

At this red-green checkpoint, _read_frame calls pandas.read_csv only for .csv and rejects every other suffix with ProviderDataError("price file must use .csv or .parquet"). Catch pandas parser, decoding, I/O, and other Exception subclasses raised by the isolated read_csv call and use `raise ProviderDataError("CSV price file could not be read") from None`; do not embed raw parser output or catch BaseException.

Normalize stripped lower-case column names and reject case-folded collisions. Require all eight required columns. Parse provider_identifier and every session_date before filtering to explicit request identifiers and inclusive dates, using this fixed boundary:

~~~python
try:
    parsed_session_dates = pd.to_datetime(
        frame["session_date"],
        format="%Y-%m-%d",
        exact=True,
        errors="raise",
    )
except (TypeError, ValueError):
    raise ProviderDataError(
        "price file session_date failed validation"
    ) from None
if parsed_session_dates.isna().any():
    raise ProviderDataError("price file session_date failed validation")
frame = frame.assign(session_date=parsed_session_dates.dt.date)
~~~

The invalid-session-date test uses a requested row and asserts that exact fixed message without parser text in either str(error) or "".join(traceback.format_exception(error)). Reject duplicate selected provider_identifier/session_date pairs before normalize_price_frame can drop them.

Run the CSV subset again and require green:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_file_price_provider.py -k "not parquet and not timestamp and not adjusted_close" -v
~~~

- [ ] **Step 4: Add failing timestamp/adjustment tests, then build canonical rows**

Add:

- test_missing_adjusted_close_column_copies_close_and_marks_all_rows_unadjusted
- test_missing_timestamps_use_completion_and_conservative_flags
- test_aware_source_timestamps_are_preserved_and_affect_content_identity
- test_naive_effective_or_available_timestamp_is_rejected
- test_invalid_timestamp_text_raises_fixed_provider_data_error
- test_invalid_numeric_or_normalized_schema_raises_fixed_provider_data_error

Run those six tests first and confirm red because the CSV structure path does not yet construct timestamp-safe NormalizedPriceRow values:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_file_price_provider.py -k "adjusted_close or timestamp or normalized_schema" -v
~~~

For each requested item, record adjusted_column_present = "adjusted_close" in selected.columns before normalize_price_frame fills an absent column, then normalize its selected frame and create NormalizedPriceRow values. Validate currency as exactly three alphabetic characters and upper-case it. Use:

~~~python
def _optional_text(value: object) -> str | None:
    if value is None or (
        not isinstance(value, str) and bool(pd.isna(cast(Any, value)))
    ):
        return None
    text_value = str(value).strip()
    return text_value or None


def _optional_utc_timestamp(value: object, *, column: str) -> datetime | None:
    text_value = _optional_text(value)
    if text_value is None:
        return None
    try:
        parsed = pd.Timestamp(text_value)
    except (TypeError, ValueError):
        raise ProviderDataError("price file timestamps failed validation") from None
    if parsed.tzinfo is None:
        raise ProviderDataError(f"{column} must include an explicit timezone")
    return parsed.tz_convert("UTC").to_pydatetime()


supplied_source_record_id = _optional_text(row.get("source_record_id"))
supplied_effective_at = _optional_utc_timestamp(
    row.get("effective_at"),
    column="effective_at",
)
supplied_available_at = _optional_utc_timestamp(
    row.get("available_at"),
    column="available_at",
)
source_record_id = supplied_source_record_id or (
    f"{self._source}:{item.provider_identifier}:"
    f"{session_date.isoformat()}:{FILE_PRICE_FIELD_MAP_VERSION}"
)
effective_at = supplied_effective_at or date_key_effective_at(session_date)
source_available_at = supplied_available_at
quality_flags = tuple(
    flag
    for flag, required in (
        (DataQualityFlag.ESTIMATED_TIMESTAMP, supplied_effective_at is None),
        (DataQualityFlag.UNADJUSTED, not adjusted_column_present),
    )
    if required
)
~~~

The shared builder adds SNAPSHOT_ONLY when source_available_at is absent. Reject naive supplied timestamps and enforce effective_at <= source_available_at <= completed_at. Around each selected-frame normalize_price_frame call and canonical-row construction, catch TypeError, ValueError (including Pydantic ValidationError), pandas timestamp conversion defects, and schema/numeric conversion defects, then raise ProviderDataError("price file failed daily-price validation") from None. Preserve an already-sanitized ProviderDataError unchanged. In every malformed CSV, optional-timestamp, and normalization test, put a sentinel in the underlying exception and assert it is absent from both str(error) and "".join(traceback.format_exception(error)). A requested identifier with no selected rows contributes PriceFailureCategory.NO_DATA. Extra identifiers and dates are ignored. Call build_price_ingestion_result with provider="file", original_source=self._source, dataset="daily_price_bar", and the explicit usage mode. Assert the returned batch.original_source equals self._source even when every requested identifier becomes a NO_DATA failure and bars is empty.

Run the same timestamp/adjustment command again and require green.

- [ ] **Step 5: Add Parquet in its own red-green slice**

Add:

- test_csv_and_parquet_equivalent_values_have_identical_content_hash_and_batch_id
- test_missing_parquet_engine_raises_not_configured_without_csv_fallback
- test_malformed_parquet_raises_fixed_provider_data_error_without_csv_fallback

For the missing-engine test, monkeypatch pandas.read_parquet to raise ImportError and pandas.read_csv to fail the test if invoked. Run the three tests and confirm red while .parquet is still rejected:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_file_price_provider.py -k "parquet" -v
~~~

Add:

~~~toml
parquet = ["pyarrow>=25,<26"]
~~~

The major-series bound matches the current package line, which publishes CPython 3.12 Windows wheels in the [PyArrow package metadata](https://pypi.org/project/pyarrow/).

Change both CI editable-install commands to install .[dev,api,dashboard,parquet]. Do not install the lseg extra in CI and retain pytest -m "not external". Install locally:

~~~powershell
.\.venv312\Scripts\python.exe -m pip install -e ".[dev,api,dashboard,parquet]"
.\.venv312\Scripts\python.exe -m pip check
~~~

Extend _read_frame so .parquet calls only pandas.read_parquet. Translate ImportError with `raise ProviderNotConfigured("Install the 'parquet' extra to read Parquet price files") from None`. Catch every other Exception raised by the isolated read_parquet call, including pyarrow.lib.ArrowInvalid, and use `raise ProviderDataError("Parquet price file could not be read") from None`; never fall back to CSV. The malformed-Parquet test writes arbitrary bytes, monkeypatches read_csv to fail if called, and asserts the exact fixed error plus absence of a sentinel from its formatted exception chain. Run the same Parquet command again and require green.

- [ ] **Step 6: Run focused verification**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_file_price_provider.py -v
.\.venv312\Scripts\python.exe -m ruff format --check src\quant_raas\connectors\file.py tests\unit\test_file_price_provider.py
.\.venv312\Scripts\python.exe -m ruff check src\quant_raas\connectors\file.py tests\unit\test_file_price_provider.py
.\.venv312\Scripts\python.exe -m mypy src\quant_raas\connectors\file.py
~~~

Expected: CSV/Parquet equivalence, strict failure behavior, and static checks pass.

- [ ] **Step 7: Commit**

~~~powershell
git add pyproject.toml .github/workflows/ci.yml src/quant_raas/connectors/file.py tests/unit/test_file_price_provider.py
git commit -m "feat: ingest prices from CSV and Parquet"
~~~

---

### Task 5: Add the bounded Workspace desktop gateway and explicit provider errors

**Files:**

- Modify: src/quant_raas/connectors/base.py
- Create: src/quant_raas/connectors/lseg/gateway.py
- Modify: src/quant_raas/connectors/lseg/__init__.py
- Create: tests/unit/test_lseg_gateway.py

**Interfaces:**

- gateway.py is the only module permitted to import lseg.data.
- LsegDesktopGateway.fetch_daily_prices owns one open/close lifecycle and returns SDK-free typed frames.
- ProviderSessionError, ProviderEntitlementError, and ProviderQuotaError distinguish operational failures.

- [ ] **Step 1: Write failing gateway lifecycle and mapping tests**

Build a fake LsegDataModule that records every call and can return frames or raise exceptions with structured code, status_code, and http_status attributes. Add these exact tests:

- test_gateway_rejects_non_desktop_mode_before_loading_sdk
- test_gateway_import_is_lazy_and_missing_sdk_is_not_configured
- test_gateway_opens_and_closes_once_per_request
- test_gateway_closes_after_currency_or_history_exception
- test_gateway_rejects_a_returned_closed_session
- test_gateway_uses_exact_fields_adjustments_header_type_and_sequential_ric_order
- test_daily_chunks_are_consecutive_non_overlapping_and_at_most_366_days
- test_structured_entitlement_status_beats_a_conflicting_exception_message
- test_http_429_maps_to_quota_without_exposing_exception_text
- test_connection_failure_maps_to_sanitized_session_error
- test_invalid_identifier_becomes_an_item_failure_and_the_next_ric_continues
- test_unknown_sdk_exception_becomes_a_sanitized_provider_error
- test_frame_limit_or_truncation_metadata_is_rejected
- test_gateway_never_passes_a_proxy_port_or_cloud_credentials

The expected call order for two RICs and two chunks is:

~~~text
open desktop.workspace
RIC-1 currency
RIC-1 chunk-1 raw
RIC-1 chunk-1 adjusted
RIC-1 chunk-2 raw
RIC-1 chunk-2 adjusted
RIC-2 currency
RIC-2 chunk-1 raw
RIC-2 chunk-1 adjusted
RIC-2 chunk-2 raw
RIC-2 chunk-2 adjusted
close
~~~

- [ ] **Step 2: Run the tests and confirm red**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_lseg_gateway.py -v
~~~

Expected: import failure for quant_raas.connectors.lseg.gateway and missing error classes.

- [ ] **Step 3: Add explicit connector errors**

Add classes with these public meanings:

~~~python
class ProviderSessionError(ProviderError):
    """The selected local provider session could not be opened or used."""


class ProviderEntitlementError(ProviderError):
    """The active provider session lacks permission for the request."""


class ProviderQuotaError(ProviderError):
    """The provider reported a request, rate, or response-size limit."""
~~~

ProviderNotConfigured remains the error for disabled desktop mode or a missing optional package. ProviderDataError remains the error for an unsafe schema or response inconsistency.

- [ ] **Step 4: Add exact LSEG constants and SDK-free result types**

Create:

~~~python
LSEG_PRICE_FIELD_MAP_VERSION = "lseg_interday_price_v1"
LSEG_RAW_FIELD_MAP = {
    "OPEN_PRC": "open",
    "HIGH_1": "high",
    "LOW_1": "low",
    "TRDPRC_1": "close",
    "ACVOL_UNS": "volume",
}
LSEG_RAW_ADJUSTMENTS = ("unadjusted",)
LSEG_ADJUSTED_FIELDS = ("TRDPRC_1",)
LSEG_ADJUSTED_ADJUSTMENTS = (
    "exchangeCorrection",
    "manualCorrection",
    "CCH",
    "CRE",
    "RPO",
    "RTS",
)
LSEG_CURRENCY_FIELDS = ("TR.PriceClose.currency",)
LSEG_CURRENCY_COLUMN_ALIASES = (
    "TR.PriceClose.currency",
    "Currency",
)
LSEG_INTERVAL = "1D"
LSEG_MAX_CHUNK_DAYS = 366


@dataclass(frozen=True, slots=True)
class LsegDailyChunk:
    start_date: date
    end_date: date
    raw_frame: pd.DataFrame
    adjusted_frame: pd.DataFrame


@dataclass(frozen=True, slots=True)
class LsegItemResult:
    provider_identifier: str
    currency_frame: pd.DataFrame
    chunks: tuple[LsegDailyChunk, ...]


@dataclass(frozen=True, slots=True)
class LsegGatewayResult:
    items: tuple[LsegItemResult, ...]
    failures: tuple[PriceItemFailure, ...] = ()
~~~

Define the LsegPriceGateway protocol with fetch_daily_prices(provider_identifiers, start_date, end_date) returning LsegGatewayResult. Define the SDK protocol around open_session, close_session, get_data, get_history, and HeaderType.NAME so tests never install lseg-data.

- [ ] **Step 5: Implement lazy loading, chunking, and one session lifecycle**

Use:

~~~python
def load_lseg_data() -> LsegDataModule:
    try:
        module = importlib.import_module("lseg.data")
    except ImportError:
        raise ProviderNotConfigured(
            "Install the 'lseg' extra to use the Workspace desktop connector"
        ) from None
    return cast(LsegDataModule, module)


def daily_chunks(start_date: date, end_date: date) -> tuple[tuple[date, date], ...]:
    chunks: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=365), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return tuple(chunks)
~~~

LsegDesktopGateway.fetch_daily_prices must reject session_mode other than "workspace_desktop" before module_loader runs, call module.open_session(name="desktop.workspace"), validate a returned open_state when present, iterate RICs and chunks sequentially, and call module.close_session() in finally whenever open_session returned. Expose an is_open read-only property for lifecycle tests.

For currency, call:

~~~python
module.get_data(
    universe=[provider_identifier],
    fields=list(LSEG_CURRENCY_FIELDS),
)
~~~

For each chunk, call raw then adjusted:

~~~python
module.get_history(
    universe=[provider_identifier],
    fields=list(LSEG_RAW_FIELD_MAP),
    interval=LSEG_INTERVAL,
    start=chunk_start.isoformat(),
    end=chunk_end.isoformat(),
    adjustments=list(LSEG_RAW_ADJUSTMENTS),
    header_type=module.HeaderType.NAME,
)

module.get_history(
    universe=[provider_identifier],
    fields=list(LSEG_ADJUSTED_FIELDS),
    interval=LSEG_INTERVAL,
    start=chunk_start.isoformat(),
    end=chunk_end.isoformat(),
    adjustments=list(LSEG_ADJUSTED_ADJUSTMENTS),
    header_type=module.HeaderType.NAME,
)
~~~

Do not pass port, app_key, client_id, client_secret, grant, token, or a platform session name.

Run the lifecycle/mapping slice before adding error classification:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_lseg_gateway.py -k "mode or lazy or opens or closes or closed_session or fields or chunks or proxy" -v
~~~

Expected: this slice is green while the explicit error/status tests remain red.

- [ ] **Step 6: Implement fail-closed SDK/status classification**

Inspect structured http_status, status_code, and code attributes before considering the exception class/message. Map 403 or entitlement/permission structured tokens to ProviderEntitlementError; 429 or quota/rate-limit tokens to ProviderQuotaError; connection/session/proxy/closed tokens to ProviderSessionError; invalid-instrument tokens to a typed INVALID_IDENTIFIER item failure; and unknown exceptions to ProviderError("LSEG desktop request failed"). Every raised sanitized provider exception uses `from None`. Public messages may include the affected RIC and sanitized category but must never reproduce the exception body or rendered cause chain. Put a sentinel in each fake SDK exception and assert it is absent from str(error) and "".join(traceback.format_exception(error)).

Inspect DataFrame.attrs for documented or returned limit/truncation/status indicators. Any positive truncated/limit indicator raises ProviderDataError("LSEG history response reported a limit or truncation"). Empty raw or adjusted frames for an individual weekend/holiday-only chunk are valid. Only a structured invalid-identifier outcome, or a RIC whose combined raw history is empty across all chunks, becomes an item failure. Add no retries.

Run the error/status slice and require green:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_lseg_gateway.py -k "entitlement or quota or connection or invalid_identifier or unknown or truncation" -v
~~~

- [ ] **Step 7: Run focused verification**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_lseg_gateway.py -v
.\.venv312\Scripts\python.exe -m ruff format --check src\quant_raas\connectors\base.py src\quant_raas\connectors\lseg tests\unit\test_lseg_gateway.py
.\.venv312\Scripts\python.exe -m ruff check src\quant_raas\connectors\base.py src\quant_raas\connectors\lseg tests\unit\test_lseg_gateway.py
.\.venv312\Scripts\python.exe -m mypy src\quant_raas\connectors\base.py src\quant_raas\connectors\lseg
~~~

Expected: exact call mapping, lifecycle, chunking, lazy import, and sanitized errors pass without lseg-data installed.

- [ ] **Step 8: Commit**

~~~powershell
git add src/quant_raas/connectors/base.py src/quant_raas/connectors/lseg/gateway.py src/quant_raas/connectors/lseg/__init__.py tests/unit/test_lseg_gateway.py
git commit -m "feat: add bounded LSEG Workspace gateway"
~~~

---

### Task 6: Normalize LSEG daily pricing through the shared provider path

**Files:**

- Replace: src/quant_raas/connectors/lseg/provider.py
- Modify: src/quant_raas/connectors/lseg/__init__.py
- Modify: pyproject.toml
- Create: tests/unit/test_lseg_provider.py

**Interfaces:**

- LsegPriceProvider(gateway, clock) implements PriceDataProvider.
- Gateway frames remain outside the domain; the provider returns only PriceIngestionResult.
- LSEG rows and batches are always research_only and source="lseg".

- [ ] **Step 1: Write failing provider mapping and point-in-time tests**

Create fake gateway results whose raw frames use OPEN_PRC, HIGH_1, LOW_1, TRDPRC_1, and ACVOL_UNS, whose adjusted frame uses TRDPRC_1, and whose currency frame covers both field-name output TR.PriceClose.currency and display-title output Currency. Add:

- test_lseg_provider_maps_raw_and_adjusted_fields_without_mixing_ohlc
- test_missing_adjusted_date_falls_back_per_row_and_marks_only_that_row_unadjusted
- test_vendor_currency_is_used_instead_of_security_master_currency
- test_currency_parser_accepts_field_name_and_display_title_headers
- test_empty_weekend_chunk_does_not_fail_a_ric_with_rows_in_another_chunk
- test_missing_non_textual_ambiguous_or_non_iso_currency_is_an_item_failure
- test_effective_available_and_ingested_times_follow_snapshot_policy
- test_identical_content_with_different_acquisition_clocks_has_the_same_identity
- test_changed_price_currency_or_item_failure_has_a_new_identity
- test_one_success_and_one_failure_is_partial
- test_all_healthy_item_failures_return_a_persistable_failed_lseg_source_batch
- test_current_or_future_end_date_is_rejected_before_gateway_access
- test_duplicate_out_of_range_oversized_or_malformed_chunk_raises_data_error
- test_non_finite_or_non_positive_adjusted_close_raises_data_error
- test_adjusted_dates_outside_raw_dates_raise_data_error
- test_session_entitlement_and_quota_errors_propagate_without_fallback
- test_gateway_receives_request_rics_once_in_caller_order

Assert adjustment_factor equals adjusted_close / close, total_return_factor is None, effective_at is midnight UTC, available_at equals ingested_at at completion, and every bar carries ESTIMATED_TIMESTAMP plus SNAPSHOT_ONLY.

- [ ] **Step 2: Run the tests and confirm red**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_lseg_provider.py -v
~~~

Expected: the placeholder provider either rejects configuration or lacks the injected-gateway interface.

- [ ] **Step 3: Replace the placeholder with the injected provider**

Use:

~~~python
class LsegPriceProvider:
    name = "lseg"

    def __init__(
        self,
        gateway: LsegPriceGateway,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._gateway = gateway
        self._clock = clock

    def fetch_daily_bars(self, request: PriceBarRequest) -> PriceIngestionResult:
        acquired_at = acquisition_started_at(request, self._clock())
        started_at = acquired_at
        if request.end_date >= acquired_at.date():
            raise ProviderDataError(
                "LSEG daily history requires an end date before the current UTC date"
            )
        gateway_result = self._gateway.fetch_daily_prices(
            tuple(item.provider_identifier for item in request.items),
            start_date=request.start_date,
            end_date=request.end_date,
        )
        rows, failures = self._normalize_gateway_result(request, gateway_result)
        completed_at = max(
            require_utc(self._clock(), field_name="clock"),
            started_at,
        )
        return build_price_ingestion_result(
            provider=self.name,
            original_source="lseg",
            dataset="daily_price_bar",
            request=request,
            field_map_version=LSEG_PRICE_FIELD_MAP_VERSION,
            usage_mode=DataUsageMode.RESEARCH_ONLY,
            rows=rows,
            failures=failures,
            started_at=started_at,
            completed_at=completed_at,
        )
~~~

Reject duplicate request RICs and require each requested RIC to have exactly one gateway item or one typed failure, never both.

Run the request-guard/delegation tests now and require green:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_lseg_provider.py -k "current_or_future" -v
~~~

- [ ] **Step 4: Validate every chunk before joining**

Flatten a one-RIC MultiIndex by selecting the component equal to an exact requested field name. Use HeaderType.NAME output names as the canonical path and reject missing or ambiguous requested fields. Reset the date index, parse dates, and for each chunk enforce:

~~~python
if len(frame) > LSEG_MAX_CHUNK_DAYS:
    raise ProviderDataError("LSEG daily chunk returned more than 366 rows")
if session_dates.duplicated().any():
    raise ProviderDataError("LSEG daily chunk contains duplicate session dates")
if (
    (session_dates.dt.date < chunk.start_date)
    | (session_dates.dt.date > chunk.end_date)
).any():
    raise ProviderDataError("LSEG daily chunk contains an out-of-bounds date")
~~~

Catch ValueError from normalize_price_frame and raise ProviderDataError("LSEG raw history failed daily-price validation") from None. Validate adjusted close as finite and strictly positive; invalid adjusted values raise ProviderDataError("LSEG adjusted history failed daily-price validation") from None. Raw frames may not overlap across chunks. Adjusted dates may be a subset of raw dates; an adjusted date outside the raw set is malformed. Do not let pandas, ValueError, Pydantic ValidationError, or their formatted exception chains escape the provider boundary for vendor-response defects; cover a sentinel cause in the malformed-frame tests.

Run the malformed/chunk-validation slice now and require green:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_lseg_provider.py -k "duplicate or out_of_range or oversized or malformed or non_finite or adjusted_dates" -v
~~~

- [ ] **Step 5: Build conservative LSEG rows**

Flatten a one-RIC currency MultiIndex and accept exactly one column matching LSEG_CURRENCY_COLUMN_ALIASES. Parse exactly one distinct, non-null, three-letter alphabetic quote currency per RIC. Missing, non-textual, ambiguous, conflicting, or invalid currency creates INVALID_CURRENCY for that item and no bars for it. An entirely empty combined raw result creates NO_DATA; an empty individual chunk does not.

For every complete raw row:

~~~python
adjusted_close = adjusted_by_date.get(session_date, close)
quality_flags = [
    DataQualityFlag.ESTIMATED_TIMESTAMP,
    DataQualityFlag.SNAPSHOT_ONLY,
]
if session_date not in adjusted_by_date:
    quality_flags.append(DataQualityFlag.UNADJUSTED)

row = NormalizedPriceRow(
    security_id=item.security_id,
    provider_identifier=item.provider_identifier,
    source_record_id=(
        f"lseg:{item.provider_identifier}:{session_date.isoformat()}:"
        f"{LSEG_PRICE_FIELD_MAP_VERSION}"
    ),
    session_date=session_date,
    effective_at=date_key_effective_at(session_date),
    source_available_at=None,
    open=open_price,
    high=high_price,
    low=low_price,
    close=close,
    adjusted_close=adjusted_close,
    volume=volume,
    currency=currency,
    adjustment_factor=adjusted_close / close,
    total_return_factor=None,
    source="lseg",
    usage_mode=DataUsageMode.RESEARCH_ONLY,
    quality_flags=tuple(quality_flags),
    field_map_version=LSEG_PRICE_FIELD_MAP_VERSION,
)
~~~

Post-filter the combined rows to the request's inclusive date bounds even though each chunk was already bounded.

Remove src/quant_raas/connectors/lseg/* from tool.coverage.run.omit in pyproject.toml now that deterministic fake-gateway/provider tests exercise the implementation. Do not add the external test or lseg-data itself to CI.

- [ ] **Step 6: Run focused verification**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_lseg_gateway.py tests\unit\test_lseg_provider.py -v
.\.venv312\Scripts\python.exe -m ruff format --check src\quant_raas\connectors\lseg tests\unit\test_lseg_gateway.py tests\unit\test_lseg_provider.py
.\.venv312\Scripts\python.exe -m ruff check src\quant_raas\connectors\lseg tests\unit\test_lseg_gateway.py tests\unit\test_lseg_provider.py
.\.venv312\Scripts\python.exe -m mypy src\quant_raas\connectors\lseg
~~~

Expected: all deterministic gateway/provider tests pass without Workspace or the optional SDK.

- [ ] **Step 7: Commit**

~~~powershell
git add pyproject.toml src/quant_raas/connectors/lseg/provider.py src/quant_raas/connectors/lseg/__init__.py tests/unit/test_lseg_provider.py
git commit -m "feat: normalize LSEG desktop daily prices"
~~~

---

### Task 7: Resolve continuous identifier mappings and compose explicit providers

**Files:**

- Modify: src/quant_raas/domain/protocols.py
- Modify: src/quant_raas/storage/repositories.py
- Modify: src/quant_raas/security_master/service.py
- Modify: src/quant_raas/config.py
- Modify: src/quant_raas/runtime.py
- Modify: tests/integration/test_security_master.py
- Create: tests/unit/test_config.py
- Create: tests/unit/test_runtime.py

**Interfaces:**

- SecurityRepository.resolve_identifier returns the unique SecurityIdentifier record at an instant.
- SecurityMasterService.resolve_price_request_items proves one identifier record covers the whole requested range.
- price_provider_for composes exactly one explicit LSEG or file adapter.

- [ ] **Step 1: Write failing temporal-resolution tests**

Add:

- test_price_request_resolution_requires_one_mapping_for_the_whole_range
- test_price_request_resolution_rejects_unknown_start_or_end
- test_price_request_resolution_preserves_ambiguous_identifier_failure
- test_price_request_resolution_rejects_a_boundary_even_for_the_same_security
- test_price_request_resolution_rejects_duplicate_normalized_identifiers
- test_price_request_resolution_preserves_caller_order

Create two non-overlapping SecurityIdentifier records with the same RIC and security ID on opposite sides of a boundary; the range crossing that boundary must fail because identifier_id differs.

- [ ] **Step 2: Run the resolution tests and confirm red**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\integration\test_security_master.py -v
~~~

Expected: SecurityRepository and SecurityMasterService lack the new methods.

- [ ] **Step 3: Add identifier-record resolution**

Add this protocol method:

~~~python
def resolve_identifier(
    self,
    reference: SecurityReference,
    *,
    as_of: datetime,
) -> SecurityIdentifier:
    raise NotImplementedError
~~~

Move the existing scheme/provider/MIC and half-open interval query into SqlAlchemySecurityRepository.resolve_identifier. Return _identifier_from_record for exactly one record; raise IdentifierNotFoundError for zero and AmbiguousIdentifierError for more than one. Implement resolve by calling resolve_identifier and then get_security, raising DomainValidationError only if referential integrity is unexpectedly broken.

Add:

~~~python
def resolve_price_request_items(
    self,
    provider_identifiers: Iterable[str],
    *,
    scheme: IdentifierScheme,
    provider: str | None,
    start_date: date,
    end_date: date,
) -> tuple[PriceRequestItem, ...]:
    if end_date < start_date:
        raise DomainValidationError("end date cannot precede start date")
    start_at = datetime.combine(start_date, time.min, tzinfo=UTC)
    end_at = (
        datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
        - timedelta(microseconds=1)
    )
    output: list[PriceRequestItem] = []
    seen: set[str] = set()
    for value in provider_identifiers:
        reference = SecurityReference(
            identifier=value,
            scheme=scheme,
            provider=provider,
        )
        if reference.identifier in seen:
            raise DomainValidationError("duplicate provider identifier")
        seen.add(reference.identifier)
        first = self.securities.resolve_identifier(reference, as_of=start_at)
        last = self.securities.resolve_identifier(reference, as_of=end_at)
        if first.identifier_id != last.identifier_id:
            raise DomainValidationError(
                f"{reference.identifier} crosses an identifier mapping boundary; "
                "split the requested date range"
            )
        output.append(
            PriceRequestItem(
                security_id=first.security_id,
                provider_identifier=reference.identifier,
            )
        )
    return tuple(output)
~~~

- [ ] **Step 4: Write failing configuration/composition tests**

Add:

- test_settings_accept_only_workspace_desktop_for_lseg
- test_lseg_composition_requires_desktop_mode_before_sdk_loading
- test_lseg_composition_passes_exact_workspace_mode
- test_file_composition_preserves_path_original_source_and_usage
- test_incomplete_file_metadata_is_not_configured
- test_provider_composition_never_falls_back

- [ ] **Step 5: Add settings and lazy runtime composition**

Change:

~~~python
market_data_provider: Literal["fixture", "yahoo", "lseg", "file"] = "fixture"
lseg_session_mode: Literal["workspace_desktop"] | None = None
~~~

Add this exact runtime signature:

~~~python
def price_provider_for(
    settings: Settings,
    *,
    source: Literal["lseg", "file"],
    file_path: Path | None = None,
    original_provider: str | None = None,
    usage_mode: DataUsageMode | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> PriceDataProvider:
    if source == "lseg":
        if settings.lseg_session_mode != "workspace_desktop":
            raise ProviderNotConfigured(
                "set QUANT_RAAS_LSEG_SESSION_MODE=workspace_desktop"
            )
        return LsegPriceProvider(
            LsegDesktopGateway(session_mode=settings.lseg_session_mode),
            clock=clock,
        )
    if file_path is None or not original_provider or usage_mode is None:
        raise ProviderNotConfigured(
            "file ingestion requires path, original provider, and usage mode"
        )
    return FilePriceProvider(
        file_path,
        source=original_provider,
        usage_mode=usage_mode,
        clock=clock,
    )
~~~

Keep connector imports inside price_provider_for so init-db and file-only paths do not import lseg.data. The explicit source argument is authoritative for this finite command; market_data_provider remains the configured default for other composition paths. Do not catch one provider's error and instantiate another.

- [ ] **Step 6: Run focused verification**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\integration\test_security_master.py tests\unit\test_config.py tests\unit\test_runtime.py -v
.\.venv312\Scripts\python.exe -m ruff check src\quant_raas\domain\protocols.py src\quant_raas\storage\repositories.py src\quant_raas\security_master\service.py src\quant_raas\config.py src\quant_raas\runtime.py tests\unit\test_config.py tests\unit\test_runtime.py
.\.venv312\Scripts\python.exe -m mypy src\quant_raas
~~~

Expected: temporal mapping, settings validation, lazy imports, and explicit composition pass.

- [ ] **Step 7: Commit**

~~~powershell
git add src/quant_raas/domain/protocols.py src/quant_raas/storage/repositories.py src/quant_raas/security_master/service.py src/quant_raas/config.py src/quant_raas/runtime.py tests/integration/test_security_master.py tests/unit/test_config.py tests/unit/test_runtime.py
git commit -m "feat: resolve and compose price data sources"
~~~

---

### Task 8: Add the finite ingest-prices command

**Files:**

- Modify: src/quant_raas/cli.py
- Create: tests/unit/test_cli.py
- Create: tests/integration/test_price_ingestion_cli.py

**Interfaces:**

- quant-raas ingest-prices accepts an explicit source, identifiers, completed date range, and source-specific file provenance.
- Once command arguments parse, every expected provider, domain-validation, Pydantic-validation, and SQLAlchemy operational/integrity outcome produces one safe JSON object with separate transport source and original source; no raw frames, price values, secrets, SQL text, proxy details, or database URL are printed. Unexpected programming errors still propagate.

- [ ] **Step 1: Write failing parser tests**

Add this parser contract:

~~~text
quant-raas ingest-prices
  --source {lseg,file}
  --provider-identifier IDENTIFIER [IDENTIFIER ...]
  --start-date YYYY-MM-DD
  --end-date YYYY-MM-DD
  [--file PATH]
  [--identifier-scheme SCHEME]
  [--original-provider NAME]
  [--usage-mode MODE]
~~~

Test required arguments, invalid ISO dates, invalid enum values, LSEG rejection of file-only arguments, and file requirements for all four provenance arguments.

- [ ] **Step 2: Run parser tests and confirm red**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_cli.py -v
~~~

Expected: argparse reports that ingest-prices is not a known command.

- [ ] **Step 3: Add parsing and source-specific validation**

Add:

~~~python
def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from None
~~~

Use type=Path for --file, type=IdentifierScheme with choices=tuple(IdentifierScheme) for --identifier-scheme, and type=DataUsageMode with choices=tuple(DataUsageMode) for --usage-mode. --source, --provider-identifier, --start-date, and --end-date are required. --provider-identifier uses nargs="+". For source=lseg, fix scheme=RIC and mapping provider="lseg", and reject file path, identifier scheme, original provider, or usage override. For source=file:

- Require --file, --identifier-scheme, --original-provider, and --usage-mode.
- Use original_provider as the identifier-provider qualifier only for RIC and VENDOR schemes; use no provider qualifier for provider-neutral schemes such as ISIN and FIGI.
- Preserve original_provider independently as PriceBar.source.
- Rely on FilePriceProvider to enforce source=lseg with research_only usage.

- [ ] **Step 4: Add exact CLI helper contracts**

Add:

~~~python
def _identifier_scheme(args: argparse.Namespace) -> IdentifierScheme:
    if args.source == "lseg":
        return IdentifierScheme.RIC
    if not isinstance(args.identifier_scheme, IdentifierScheme):
        raise DomainValidationError("file ingestion requires an identifier scheme")
    return args.identifier_scheme


def _identifier_provider(args: argparse.Namespace) -> str | None:
    if args.source == "lseg":
        return "lseg"
    scheme = _identifier_scheme(args)
    if scheme not in {IdentifierScheme.RIC, IdentifierScheme.VENDOR}:
        return None
    if not args.original_provider:
        raise DomainValidationError(
            "RIC and vendor identifiers require an original provider"
        )
    return str(args.original_provider).strip().lower()


def _summary_payload(summary: PriceIngestionSummary) -> dict[str, object]:
    return {
        "status": summary.batch.status.value,
        "batch_id": str(summary.batch.batch_id),
        "source": summary.batch.provider,
        "original_source": summary.batch.original_source,
        "usage_mode": summary.batch.usage_mode.value,
        "bars_received": summary.bars_received,
        "bars_inserted": summary.bars_inserted,
        "failures": [
            {
                "provider_identifier": failure.provider_identifier,
                "category": failure.category.value,
                "message": failure.message,
            }
            for failure in summary.failures
        ],
    }


SafeCliError: TypeAlias = (
    QuantRaasError | ProviderError | ValidationError | SQLAlchemyError
)


def _safe_error_category(error: SafeCliError) -> str:
    if isinstance(error, SQLAlchemyError):
        return "storage"
    if isinstance(error, ValidationError):
        return "validation"
    if isinstance(error, ProviderSessionError):
        return "session"
    if isinstance(error, ProviderEntitlementError):
        return "entitlement"
    if isinstance(error, ProviderQuotaError):
        return "quota"
    if isinstance(error, ProviderNotConfigured):
        return "not_configured"
    if isinstance(error, ProviderDataError):
        return "data"
    if isinstance(error, ProviderError):
        return "provider"
    return "validation"


def _safe_error_message(error: SafeCliError) -> str:
    if isinstance(error, SQLAlchemyError):
        return "The local database operation failed"
    if isinstance(error, ValidationError):
        return "The price ingestion request failed validation"
    if isinstance(error, ProviderSessionError):
        return "The local provider session is unavailable"
    if isinstance(error, ProviderEntitlementError):
        return "The provider session is not entitled for this request"
    if isinstance(error, ProviderQuotaError):
        return "The provider reported a request or response limit"
    if isinstance(error, ProviderNotConfigured):
        return "The selected price provider is not configured"
    if isinstance(error, ProviderDataError):
        return "The provider response failed price-data validation"
    if isinstance(error, ProviderError):
        return "The price provider request failed"
    return str(error)[:500]


def _error_payload(
    args: argparse.Namespace,
    error: SafeCliError,
) -> dict[str, object]:
    usage_mode = (
        DataUsageMode.RESEARCH_ONLY.value
        if args.source == "lseg"
        else (
            args.usage_mode.value
            if isinstance(args.usage_mode, DataUsageMode)
            else None
        )
    )
    original_source_candidate = (
        str(args.original_provider).strip().lower()
        if args.source == "file" and args.original_provider
        else "lseg" if args.source == "lseg" else ""
    )
    original_source = (
        original_source_candidate
        if 1 <= len(original_source_candidate) <= 80
        else None
    )
    return {
        "status": "error",
        "batch_id": None,
        "source": args.source,
        "original_source": original_source,
        "usage_mode": usage_mode,
        "bars_received": 0,
        "bars_inserted": 0,
        "failures": [
            {
                "provider_identifier": None,
                "category": _safe_error_category(error),
                "message": _safe_error_message(error),
            }
        ],
    }
~~~

Import TypeAlias from typing, ValidationError from pydantic, and SQLAlchemyError from sqlalchemy.exc. All ProviderError subclasses created in earlier tasks expose fixed sanitized messages, and _safe_error_message deliberately does not echo them. QuantRaasError messages contain only caller-supplied identifiers and validation context. Pydantic and SQLAlchemy branches always use the fixed messages above; never pass an arbitrary SDK, validation, database, SQL, or connection exception string into _error_payload.

- [ ] **Step 5: Re-run the parser/helper slice and require green**

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_cli.py -v
~~~

- [ ] **Step 6: Write failing command integration tests**

Add:

- test_file_cli_resolves_and_ingests_through_the_normal_repository_path
- test_current_or_future_end_date_never_resolves_or_builds_a_provider
- test_unknown_ambiguous_or_boundary_crossing_identifier_never_builds_a_provider
- test_lseg_session_failure_persists_no_batch_or_bars
- test_lseg_failure_never_invokes_file_provider
- test_partial_and_all_item_failed_results_have_defined_exit_codes
- test_all_failed_file_result_persists_and_reports_original_source
- test_cli_json_contains_only_safe_summary_fields
- test_malformed_provider_result_returns_fixed_data_json_without_persistence
- test_pydantic_validation_error_returns_fixed_safe_json
- test_sqlalchemy_error_rolls_back_and_returns_fixed_safe_json

Register temporal identifiers in SQLite. Use a temporary CSV for the file path and an injected fake provider factory for LSEG paths. Put a sentinel close value 987654.321 and sentinel secret "DO-NOT-PRINT" in fake internals; assert neither occurs in stdout. Return one typed but cross-record-inconsistent fake-provider result with a sentinel bar key and assert category=data, the generic provider-data message, and no batch/bar persistence or sentinel leakage. Force one overlong/invalid Pydantic identifier/provider input after argparse and assert category=validation with the fixed message. Force a SQLAlchemyError containing sentinel SQL, database path, and driver text during the transaction; assert rollback leaves no batch/bars and stdout contains only category=storage plus "The local database operation failed".

- [ ] **Step 7: Implement one transaction and safe JSON**

Add a testable handler:

~~~python
def _run_ingest_prices(
    args: argparse.Namespace,
    settings: Settings,
    *,
    clock: Callable[[], datetime] = utc_now,
    provider_factory: Callable[..., PriceDataProvider] = price_provider_for,
) -> int:
    acquired_at = ensure_utc(clock())
    if args.end_date >= acquired_at.date():
        raise DomainValidationError(
            "end date must precede the current UTC date"
        )
    engine = create_sql_engine(settings)
    if settings.environment in {"development", "test"}:
        create_schema(engine)
    factory = create_session_factory(engine)
    with session_scope(factory) as session:
        repos = repositories_for(session)
        security_master = SecurityMasterService(
            repos.securities,
            repos.portfolios,
            repos.theses,
        )
        items = security_master.resolve_price_request_items(
            args.provider_identifier,
            scheme=_identifier_scheme(args),
            provider=_identifier_provider(args),
            start_date=args.start_date,
            end_date=args.end_date,
        )
        provider = provider_factory(
            settings,
            source=args.source,
            file_path=args.file,
            original_provider=args.original_provider,
            usage_mode=args.usage_mode,
            clock=clock,
        )
        summary = PriceIngestionService(
            provider=provider,
            repository=repos.market_data,
        ).ingest(
            PriceBarRequest(
                items=items,
                start_date=args.start_date,
                end_date=args.end_date,
                requested_at=acquired_at,
            )
        )
    print(json.dumps(_summary_payload(summary), sort_keys=True))
    return 1 if summary.batch.status == BatchStatus.FAILED else 0
~~~

The success/partial/failed payload has exactly:

~~~json
{
  "status": "succeeded",
  "batch_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "source": "lseg",
  "original_source": "lseg",
  "usage_mode": "research_only",
  "bars_received": 5,
  "bars_inserted": 5,
  "failures": []
}
~~~

Each typed failure object contains only provider_identifier, category, and sanitized message. PARTIAL returns 0 because valid rows committed; FAILED returns 1. In main, dispatch `ingest-prices` before the existing unconditional `settings = get_settings()` line, and put both `get_settings()` and the complete `_run_ingest_prices` call (including transaction exit) inside this command-specific boundary:

~~~python
if args.command == "ingest-prices":
    try:
        return _run_ingest_prices(args, get_settings())
    except (
        ProviderError,
        QuantRaasError,
        ValidationError,
        SQLAlchemyError,
    ) as error:
        print(json.dumps(_error_payload(args, error), sort_keys=True))
        return 1

settings = get_settings()
~~~

This preserves existing command behavior, includes settings validation in the safe ingestion envelope, and ensures SQLAlchemy rollback completes before the fixed storage envelope is printed. Do not catch unexpected programming errors.

- [ ] **Step 8: Run focused verification**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_cli.py tests\integration\test_price_ingestion_cli.py -v
.\.venv312\Scripts\python.exe -m ruff format --check src\quant_raas\cli.py tests\unit\test_cli.py tests\integration\test_price_ingestion_cli.py
.\.venv312\Scripts\python.exe -m ruff check src\quant_raas\cli.py tests\unit\test_cli.py tests\integration\test_price_ingestion_cli.py
.\.venv312\Scripts\python.exe -m mypy src\quant_raas\cli.py
~~~

Expected: parser, resolution-before-provider, transactional persistence, no fallback, exit codes, and safe JSON pass.

- [ ] **Step 9: Commit**

~~~powershell
git add src/quant_raas/cli.py tests/unit/test_cli.py tests/integration/test_price_ingestion_cli.py
git commit -m "feat: add finite price ingestion command"
~~~

---

### Task 9: Prove provider-neutral idempotency and correction vintages end to end

**Files:**

- Modify: tests/integration/test_price_ingestion_pipeline.py
- Modify: tests/integration/test_price_ingestion_cli.py

**Interfaces:**

- Both new providers enter through PriceIngestionService and SqlAlchemyMarketDataRepository.
- A content retry is a no-op; a changed content snapshot with later availability is a later point-in-time vintage, while contradictory content at the same authoritative availability is rejected atomically.

- [ ] **Step 1: Add end-to-end verification tests**

Add:

- test_file_and_fake_lseg_use_price_ingestion_service_and_repository
- test_identical_file_retry_inserts_no_batch_or_bars
- test_identical_lseg_retry_with_a_later_clock_inserts_no_batch_or_bars
- test_changed_content_creates_a_later_knowledge_time_vintage
- test_file_change_at_same_authoritative_availability_rolls_back_as_conflict
- test_file_change_at_later_authoritative_availability_creates_vintage
- test_failed_item_only_result_persists_original_source_without_observations
- test_usage_mode_round_trips_for_file_and_lseg

For the generated-availability correction test, ingest one close value at clock T1, change one close value, ingest at T2, and assert:

~~~python
assert before_t2[0].close == pytest.approx(first_close)
assert at_t2[0].close == pytest.approx(corrected_close)
assert before_t2[0].ingestion_batch_id != at_t2[0].ingestion_batch_id
assert first_summary.bars_inserted == 1
assert retry_summary.bars_inserted == 0
assert correction_summary.bars_inserted == 1
~~~

For the authoritative-file tests, first ingest a row with an explicit aware available_at. Re-ingest a different close with the same available_at and assert RepositoryConflictError, transaction rollback, no second batch/bar, and the original as-of value unchanged. Then advance only the file's authoritative available_at together with the corrected close; assert a distinct batch/bar, the old value before the new cutoff, and the corrected value at/after it. This is provenance consistency, not an instruction to synthesize or silently rewrite a supplied timestamp.

- [ ] **Step 2: Run the tests; they should already be green**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\integration\test_price_ingestion_pipeline.py tests\integration\test_price_ingestion_cli.py -v
~~~

Expected: all tests pass because Tasks 2 through 8 already implemented each boundary. Any failure is evidence that its owning task is incomplete, not a request for new behavior here.

- [ ] **Step 3: Route any failure back to its owning task**

No new production behavior is planned in this integration task. If the red run exposes a defect, stop here, return to the task that owns that boundary, add the regression assertion to that task's focused test file, make its already-specified minimal implementation correction, and rerun that task before returning. Never duplicate normalization in the service/CLI or weaken the database constraint.

- [ ] **Step 4: Run the complete price-ingestion slice**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_price_content.py tests\unit\test_file_price_provider.py tests\unit\test_lseg_gateway.py tests\unit\test_lseg_provider.py tests\unit\test_cli.py tests\integration\test_price_provenance_migration.py tests\integration\test_price_attempt_identity_migration.py tests\integration\test_price_repository_idempotency.py tests\integration\test_price_ingestion_pipeline.py tests\integration\test_price_ingestion_cli.py -v
.\.venv312\Scripts\python.exe -m ruff check src\quant_raas tests\unit tests\integration migrations
.\.venv312\Scripts\python.exe -m mypy src\quant_raas
~~~

Expected: the entire deterministic ingestion slice passes.

- [ ] **Step 5: Commit**

~~~powershell
git add tests/integration/test_price_ingestion_pipeline.py tests/integration/test_price_ingestion_cli.py
git commit -m "test: verify price ingestion correction vintages"
~~~

Before committing, inspect git diff --cached --name-only and remove any unrelated staged path. Any production correction must already have been committed at its owning task boundary.

---

### Task 10: Add the manually gated live Workspace smoke test

**Files:**

- Create: tests/external/test_lseg_workspace_smoke.py

**Interfaces:**

- QUANT_RAAS_RUN_LSEG_EXTERNAL must equal "1".
- QUANT_RAAS_LSEG_SMOKE_RIC, QUANT_RAAS_LSEG_SMOKE_START_DATE, and QUANT_RAAS_LSEG_SMOKE_END_DATE define one entitled, completed range of at most 31 calendar days.
- The test calls the provider directly and never opens the normal development database.

- [ ] **Step 1: Write the gated external test**

Mark the module external. Skip unless the enable flag is exactly "1". When enabled, fail before session access if a RIC/date variable is absent, the range is reversed, the range exceeds 31 calendar days, or end_date is current/future UTC.

Construct one deterministic PriceRequestItem, LsegDesktopGateway(session_mode="workspace_desktop"), and LsegPriceProvider. Assert:

~~~python
assert result.bars
assert {bar.provider_identifier for bar in result.bars} == {ric}
assert all(len(bar.currency) == 3 and bar.currency.isalpha() for bar in result.bars)
assert all(bar.effective_at.utcoffset() == timedelta(0) for bar in result.bars)
assert all(bar.available_at.utcoffset() == timedelta(0) for bar in result.bars)
assert all(bar.ingested_at.utcoffset() == timedelta(0) for bar in result.bars)
assert result.batch.provider == "lseg"
assert result.batch.original_source == "lseg"
assert result.batch.usage_mode == DataUsageMode.RESEARCH_ONLY
assert all(bar.source == "lseg" for bar in result.bars)
assert all(bar.usage_mode == DataUsageMode.RESEARCH_ONLY for bar in result.bars)
assert all(DataQualityFlag.ESTIMATED_TIMESTAMP in bar.quality_flags for bar in result.bars)
assert all(DataQualityFlag.SNAPSHOT_ONLY in bar.quality_flags for bar in result.bars)
assert all(bar.adjusted_close is not None for bar in result.bars)
assert all(
    bar.adjustment_factor == pytest.approx(bar.adjusted_close / bar.close)
    for bar in result.bars
    if bar.adjusted_close is not None
)
assert all(bar.total_return_factor is None for bar in result.bars)
assert gateway.is_open is False
~~~

Do not assert numeric golden values and do not print bar values or raw frames. Deterministic fake-module tests remain responsible for close-on-failure behavior.

- [ ] **Step 2: Verify the test remains excluded by default**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pytest tests\unit\test_lseg_gateway.py tests\external\test_lseg_workspace_smoke.py -m "not external" -v
~~~

Expected: deterministic fake-gateway tests pass, the one external smoke is deselected, pytest exits 0, and no real SDK/session access occurs.

- [ ] **Step 3: Install the optional SDK in Python 3.12**

Run:

~~~powershell
.\.venv312\Scripts\python.exe -m pip install -e ".[lseg,parquet]"
.\.venv312\Scripts\python.exe -m pip check
.\.venv312\Scripts\python.exe -c "import lseg.data; print('lseg.data import ok')"
~~~

If dependency download is blocked by the sandbox or network policy, request approval for this exact pip install. Do not install into .venv or .venv314.

- [ ] **Step 4: Run the live smoke against the already-authenticated Workspace session**

Use an entitled RIC; this explicit example uses AAPL.O and completed dates:

~~~powershell
$env:QUANT_RAAS_RUN_LSEG_EXTERNAL="1"
$env:QUANT_RAAS_LSEG_SMOKE_RIC="AAPL.O"
$env:QUANT_RAAS_LSEG_SMOKE_START_DATE="2026-08-17"
$env:QUANT_RAAS_LSEG_SMOKE_END_DATE="2026-08-21"
.\.venv312\Scripts\python.exe -m pytest tests\external\test_lseg_workspace_smoke.py -m external -vv
~~~

If AAPL.O is not entitled, select another explicitly entitled RIC and record only the identifier and sanitized failure category, never returned data. A closed Workspace, entitlement denial, quota response, or schema mismatch is a real acceptance blocker to diagnose; do not substitute another provider.

- [ ] **Step 5: Commit**

~~~powershell
git add tests/external/test_lseg_workspace_smoke.py
git commit -m "test: add gated LSEG Workspace smoke"
~~~

---

### Task 11: Document operation, lineage, and legal boundaries

**Files:**

- Modify: .env.example
- Modify: README.md
- Modify: PLAN.md
- Modify: docs/data_contracts.md
- Modify: docs/vendor_entitlements.md

**Interfaces:**

- Documentation must let a local operator install, map a RIC, ingest from either source, interpret timestamps/adjustments, and run the smoke test without implying cloud support or contractual approval.

- [ ] **Step 1: Update the environment example**

Replace the current LSEG credential placeholders with:

~~~dotenv
# LSEG desktop access uses the authenticated Workspace application on this
# machine. Platform/cloud sessions, OAuth credentials, client secrets, and App
# Keys are not supported by this milestone.
# QUANT_RAAS_MARKET_DATA_PROVIDER=lseg
# QUANT_RAAS_LSEG_SESSION_MODE=workspace_desktop
~~~

Delete LSEG_APP_KEY, LSEG_CLIENT_ID, and LSEG_CLIENT_SECRET from .env.example.

- [ ] **Step 2: Add exact README operation examples**

Document Python 3.12 and:

~~~powershell
.\.venv312\Scripts\python.exe -m pip install -e ".[dev,lseg,parquet]"

# For the default existing SQLite database, stop writers and make a recoverable
# backup first. Refuse to overwrite a prior backup. For any configured external
# database, use its native verified backup procedure instead of Copy-Item.
$priceDatabase = (Resolve-Path -LiteralPath ".\quant_raas.db").Path
$priceDatabaseBackup = "$priceDatabase.pre-price-ingestion.bak"
if (Test-Path -LiteralPath $priceDatabaseBackup) {
    throw "backup already exists: $priceDatabaseBackup"
}
Copy-Item -LiteralPath $priceDatabase -Destination $priceDatabaseBackup
.\.venv312\Scripts\python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "database migration failed" }

$env:QUANT_RAAS_LSEG_SESSION_MODE="workspace_desktop"
.\.venv312\Scripts\python.exe -m quant_raas.cli ingest-prices --source lseg --provider-identifier AAPL.O --start-date 2026-08-17 --end-date 2026-08-21

.\.venv312\Scripts\python.exe -m quant_raas.cli ingest-prices --source file --provider-identifier AAPL.O --start-date 2026-08-17 --end-date 2026-08-21 --file data\aapl_prices.csv --identifier-scheme ric --original-provider lseg --usage-mode research_only
~~~

Put the backup block under an "existing default SQLite database" label and separately show `python -m alembic upgrade head` as the preferred initializer for a fresh database (no copy step when the file does not exist). State that `create_schema()` creates missing tables but does not migrate an existing pre-0005 database. Operators using a configured non-default database must take and verify a database-native backup before upgrade. State that a temporal scheme=ric, provider=lseg security-master mapping must already exist through the existing API/application service because this milestone adds no security-universe CLI. Document all required/optional file columns, case-insensitive matching, duplicate rejection, timezone requirements, and requested-subset behavior.

State explicitly:

- Workspace must already be open and authenticated on the same machine.
- The application calls desktop.workspace and no proxy port is configured in code.
- LSEG exports retain source=lseg and research_only even through file transport.
- There is no cloud auth, source fallback, scheduler, raw-payload logging, customer delivery route, or total-return guarantee.
- Safe JSON summaries contain separate transport-source and original-source fields but no prices.
- The live smoke does not persist to the normal database.

- [ ] **Step 3: Correct data-contract and entitlement documentation**

In docs/data_contracts.md:

- Add required usage_mode to IngestionBatch and PriceBar with all five values.
- Add required original_source to IngestionBatch, require successful bar sources to match it, and explain why all-failure file batches retain it.
- Define adjusted_close as provider-declared adjusted close with a versioned method, not necessarily dividend-reinvested total return.
- Reserve total-return claims for an explicit total_return_factor.
- Permit midnight-UTC effective_at only with ESTIMATED_TIMESTAMP.
- Explain acquisition completion, SNAPSHOT_ONLY, trustworthy source availability, canonical content identity, later-timestamp correction vintages, and rollback on changed values that claim the same authoritative availability timestamp.
- Add the exact file schema and transport-provider/original-source distinction.

In docs/vendor_entitlements.md, keep LSEG status Unverified, narrow the current intended mode to research-only completed daily price history through authenticated Workspace desktop access, mark production/cloud support out of scope, and state that technical success does not prove extraction, storage, retention, intended-use, or redistribution rights.

In PLAN.md, change only the daily-price portion of the LSEG connector status from placeholder/boundary to implemented desktop research ingestion; leave fundamentals, estimates, news, macro, platform, and production claims unbuilt.

- [ ] **Step 4: Run documentation assertions**

Run:

~~~powershell
rg -n "workspace_desktop|desktop.workspace|research_only|Parquet|adjusted_close|total_return_factor|Unverified|alembic upgrade head|backup" README.md PLAN.md docs\data_contracts.md docs\vendor_entitlements.md .env.example
if ($LASTEXITCODE -ne 0) { throw "required documentation concepts are missing" }
$priceForbiddenLsegEnv = rg -n "LSEG_APP_KEY|LSEG_CLIENT_ID|LSEG_CLIENT_SECRET" .env.example
if ($LASTEXITCODE -eq 0) { throw "legacy LSEG credential placeholders remain: $priceForbiddenLsegEnv" }
if ($LASTEXITCODE -ne 1) { throw "credential placeholder scan failed" }
git diff --check
if ($LASTEXITCODE -ne 0) { throw "documentation diff check failed" }
~~~

Expected: the first search exits 0 and shows each required concept, the inverted credential scan observes ripgrep's documented no-match exit 1, and git diff --check exits 0.

- [ ] **Step 5: Commit**

~~~powershell
git add .env.example README.md PLAN.md docs/data_contracts.md docs/vendor_entitlements.md
git commit -m "docs: explain desktop and file price ingestion"
~~~

---

### Task 12: Run the full quality gate and publish the branch

**Files:**

- No planned source changes. If verification exposes a defect, return to the owning task, add a regression test, make the smallest fix, and commit it separately.

**Interfaces:**

- Deterministic CI gate passes without Workspace.
- Manual external acceptance passes with the user's open, entitled Workspace session.
- The feature branch is pushed without touching unrelated user changes.

- [ ] **Step 1: Run formatting, lint, typing, migration, and deterministic tests**

Run:

~~~powershell
$pricePython = (Resolve-Path -LiteralPath ".\.venv312\Scripts\python.exe").Path
& $pricePython -m ruff format --check .
if ($LASTEXITCODE -ne 0) { throw "Ruff format check failed" }
& $pricePython -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "Ruff lint failed" }
& $pricePython -m mypy src\quant_raas
if ($LASTEXITCODE -ne 0) { throw "mypy failed" }
& $pricePython -m pytest -m "not external" --cov=quant_raas --cov-branch --cov-report=term-missing --cov-report=xml --cov-fail-under=80
if ($LASTEXITCODE -ne 0) { throw "deterministic pytest gate failed" }
$priceMigrationDb = Join-Path ([System.IO.Path]::GetTempPath()) ("quant-raas-price-" + [guid]::NewGuid().ToString() + ".db")
try {
    $env:QUANT_RAAS_DATABASE_URL = "sqlite+pysqlite:///" + $priceMigrationDb.Replace("\", "/")
    & $pricePython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed" }
    & $pricePython -m alembic downgrade 20260821_0004
    if ($LASTEXITCODE -ne 0) { throw "Alembic downgrade failed" }
    & $pricePython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic re-upgrade failed" }
}
finally {
    if (Test-Path -LiteralPath $priceMigrationDb) {
        Remove-Item -LiteralPath $priceMigrationDb
    }
    Remove-Item Env:QUANT_RAAS_DATABASE_URL -ErrorAction SilentlyContinue
}
git diff --check
if ($LASTEXITCODE -ne 0) { throw "git diff check failed" }
~~~

Expected: every command exits 0. The Alembic round-trip uses only the explicit unique temporary SQLite path and never an unreviewed shared database.

- [ ] **Step 2: Re-run the manually gated Workspace acceptance**

With Workspace open and authenticated, run the Task 10 external command again. Confirm a nonempty normalized result, research-only/source lineage, UTC timestamps, conservative flags, and a closed gateway without printing numeric values.

- [ ] **Step 3: Inspect the exact branch delta**

Run:

~~~powershell
git status --short --branch
git log --oneline --decorate -12
git diff --stat origin/main...HEAD
git diff --name-status origin/main...HEAD
~~~

Expected: only this milestone's spec, plan, implementation, tests, migration, and documentation appear. Preserve the known stale .git/worktrees/pit-feature-panel warning; do not delete worktree metadata without separate authorization.

- [ ] **Step 4: Push the feature branch**

Run:

~~~powershell
git push origin feature/lseg-workspace-price-ingestion
~~~

Expected: origin/feature/lseg-workspace-price-ingestion advances to the verified implementation commits.

- [ ] **Step 5: Report evidence**

Report the pushed commit, deterministic test count and coverage, Ruff/mypy/migration results, external smoke result and RIC/date range, and any entitlement/schema limitation. Do not report or paste licensed numeric market data.
