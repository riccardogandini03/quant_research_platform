# LSEG Workspace and File Price Ingestion Design

**Status:** Approved in chat on 2026-08-25  
**Scope:** Research-only daily historical prices  
**Access point:** An already-authenticated LSEG Workspace desktop session on the same machine

## Context

The repository has a complete provider-neutral daily-price path:
`PriceDataProvider` returns a `PriceIngestionResult`, `PriceIngestionService`
validates it, and `MarketDataRepository` persists point-in-time `PriceBar`
vintages. The LSEG connector is currently a placeholder that raises
`ProviderNotConfigured`. CSV and Parquet are not yet first-class price
providers.

The development machine has LSEG Workspace running, and its local Data API
Proxy reports `ST_PROXY_READY` at the time of design. The selected integration
uses the LSEG Data Library for Python (`lseg.data`) through that local desktop
proxy. It does not use an LSEG platform/cloud session, OAuth, a client secret,
or a customer-facing HTTP API.

An open Workspace process is necessary but is not itself a Python data
interface. Python accesses the authenticated desktop session by calling
`ld.open_session(name="desktop.workspace")`. Workspace supplies the desktop
configuration to the library. The application will not collect separate LSEG
cloud credentials.

## Goals

1. Retrieve one or more explicitly supplied RICs' completed daily price history
   through the open Workspace desktop session.
2. Preserve raw OHLCV separately from corporate-action-adjusted close.
3. Normalize and persist LSEG data through the existing price-ingestion path.
4. Restrict all Workspace-derived observations to research-only handling
   without treating technical access as proof of contractual rights.
5. Support CSV and Parquet as explicit alternative inputs through the same
   provider contract and downstream pipeline.
6. Preserve point-in-time honesty when the source does not expose the original
   publication or correction timestamp.
7. Make retries idempotent while treating changed source content with a later
   knowledge timestamp as a new observable vintage and rejecting contradictory
   values claimed for the same authoritative timestamp.
8. Provide a finite local CLI command and a manually gated live smoke test.

## Non-goals

- LSEG platform/cloud sessions, OAuth, service IDs, client secrets, or hosted
  vendor access.
- Automatic fallback from LSEG to CSV, Parquet, Yahoo, or another provider.
- Fundamentals, estimates, news, ownership, intraday, streaming, or real-time
  prices.
- FastAPI routes, dashboard controls, scheduled or unattended extraction.
- Customer delivery or redistribution of Workspace-derived data.
- Proving that a historical Workspace download was available on its original
  market date.
- Generalizing a universal LSEG client for future datasets before they are
  designed.

## Approaches considered

### Selected: injected desktop gateway plus provider adapters

Keep the existing `PriceDataProvider` boundary. Put `lseg.data` lifecycle and
raw calls behind a small injected gateway, implement LSEG normalization in
`LsegPriceProvider`, and implement file loading in `FilePriceProvider`. Both
return the same domain result and use the same ingestion service.

This is the smallest design that is live, testable without Workspace, explicit
about licensing, and reusable by later LSEG dataset adapters.

### Rejected: direct SDK calls inside `LsegPriceProvider`

This is faster to type but couples session state, optional imports, raw schema
handling, and domain normalization in one class. It makes deterministic tests
and error classification materially harder.

### Rejected: universal LSEG data client now

A broad abstraction for prices, estimates, fundamentals, and news would invent
contracts that do not yet exist in the repository. It would increase scope
without improving the first live price slice.

## Architecture

```text
Open Workspace -> LsegDesktopGateway -> LsegPriceProvider --+
                                                           |
CSV / Parquet ---------------------> FilePriceProvider -----+-> normalize
                                                               -> validate
                                                               -> persist
                                                               -> research
```

The stable domain boundary remains:

```python
class PriceDataProvider(Protocol):
    @property
    def name(self) -> str: ...

    def fetch_daily_bars(self, request: PriceBarRequest) -> PriceIngestionResult: ...
```

One source is selected explicitly for each ingestion run. A provider failure is
returned or raised as that provider's failure; the application never changes
sources implicitly.

### `LsegDesktopGateway`

`src/quant_raas/connectors/lseg/gateway.py` will be the only module that imports
`lseg.data`. It will:

- delay the optional import until a desktop-enabled call is made;
- reject every session mode except `workspace_desktop`;
- call `ld.open_session(name="desktop.workspace")` once per ingestion request;
- issue sequential, bounded history calls for each RIC;
- close the library session in `finally` if this gateway opened it;
- return pandas frames or gateway-owned typed results without leaking SDK
  objects into domain or service code; and
- translate structured SDK/status information into connector errors without
  logging raw licensed payloads or credentials.

The application will not hardcode port 9000. Workspace may select another local
proxy port, and the library owns desktop configuration discovery.

### `LsegPriceProvider`

`src/quant_raas/connectors/lseg/provider.py` will replace the current stub while
continuing to implement `PriceDataProvider`. The gateway and clock are injected,
so all deterministic tests run without `lseg-data`, a network, or Workspace.

The provider consumes only explicit request items. It never guesses a ticker,
converts an ISIN into a RIC, or silently substitutes another instrument.

`PriceRequestItem` continues to carry the canonical `security_id` and explicit
`provider_identifier`. Quote currency is listing-specific, so the connector
must not assume that `Security.primary_currency` applies to every RIC. The
gateway retrieves each RIC's quote currency through the same desktop session
with `ld.get_data(..., fields=["TR.PriceClose.currency"])`. A missing,
non-textual, or non-ISO three-letter result is an item-level failure. Currency
is part of normalized content and therefore of content-addressed lineage.

### `FilePriceProvider`

`src/quant_raas/connectors/file.py` will implement the same protocol. It reads a
single explicitly supplied `.csv` or `.parquet` file, filters it to the request
items and dates, and feeds its rows through the same normalization and batch
construction code as LSEG.

CSV support uses the base pandas dependency. Parquet support is exposed through
an optional `parquet` package extra backed by a tested Parquet engine. Requesting
Parquet without that extra raises `ProviderNotConfigured` with an installation
message; it never falls back to CSV parsing.

One file represents one declared original provider and one usage mode.
These values are command/configuration metadata, not inferred from the filename.
An export from Workspace remains `source="lseg"` and
`usage_mode="research_only"`; changing the transport to a file does not change
the underlying license provenance.

Transport and original source remain distinct. A file ingestion batch has
`provider="file"` and `original_source` equal to the declared provider, while
each resulting bar's `source` is that same original provider, such as `lseg`.
A live desktop batch has both `provider="lseg"` and
`original_source="lseg"`, and its bars use `source="lseg"`. Keeping the
original source on the batch preserves provenance when every requested item
fails and no bars exist.

### Local command composition

The CLI will add a finite `ingest-prices` command. It is a local application
adapter, not an HTTP API. The command accepts:

- `--source lseg|file`;
- one or more explicit provider identifiers;
- start and end dates;
- for files, a path, identifier scheme, original provider, and usage
  mode; and
- normal database settings from `Settings`.

For LSEG, identifiers are RICs and the original provider is always `lseg`. Each
identifier must resolve through the security master as a RIC for provider
`lseg`. Unknown or ambiguous identifiers fail before the vendor call. The first
milestone rejects a request whose identifier mapping is not valid at both ends
of the requested date interval; ranges crossing a mapping boundary must be
split explicitly.

The command prints a JSON summary containing status, batch ID, transport
source, original source, row counts, and sanitized failures. It does not print
price values or raw payloads.
`PriceIngestionResult` and `PriceIngestionSummary` carry typed item failures so
the command never has to parse a formatted batch error string to produce this
envelope. After argparse succeeds, expected Pydantic request-validation and
SQLAlchemy operational/integrity failures also map to fixed validation or
storage envelopes; exception text, SQL, driver details, and database paths are
never echoed. Unexpected programming errors are not swallowed.

Operational documentation requires a verified backup followed by
`alembic upgrade head` for an existing database before this command is used. A
fresh database should also be initialized through Alembic. Development
`create_schema()` may create missing tables but is not a substitute for
migrating an existing pre-provenance schema.

## LSEG historical-price mapping

The versioned initial field map is:

| Canonical field | LSEG interday field |
|---|---|
| `open` | `OPEN_PRC` |
| `high` | `HIGH_1` |
| `low` | `LOW_1` |
| `close` | `TRDPRC_1` |
| `volume` | `ACVOL_UNS` |

Raw OHLCV and adjusted close must not be mixed in one series. For each RIC the
gateway first retrieves listing currency, then makes two sequential pricing
requests over each daily interval chunk:

1. the five interday fields with `adjustments=["unadjusted"]`; and
2. `TRDPRC_1` with
   `adjustments=["exchangeCorrection", "manualCorrection", "CCH", "CRE", "RPO", "RTS"]`.

Every pricing request sets `interval="1D"`. A request is split into consecutive,
non-overlapping chunks of at most 366 calendar days, and the normalized result
is post-filtered to the caller's inclusive start/end dates. The command rejects
an end date on or after the acquisition clock's current UTC date, so the first
milestone cannot request an incomplete current or future session.

Each chunk rejects duplicate dates, dates outside its bounds, an SDK truncation
or limit status, and more than 366 returned daily rows. Raw data must exist for
the item; adjusted dates may be a subset and receive the conservative fallback
defined below. Small deterministic chunks and explicit status checks minimize
the risk of an oversized response being silently truncated without inventing a
vendor-wide quota constant.

The raw response supplies OHLCV and `close`. The second response supplies
`adjusted_close`. The provider joins them by session date and calculates
`adjustment_factor = adjusted_close / close` when close is non-zero. A missing
adjusted value becomes `adjusted_close = close` and carries `UNADJUSTED`; a row
without complete raw OHLC cannot become a `PriceBar`.

This LSEG series is corporate-action-adjusted pricing, not a guaranteed
dividend-reinvested total-return index. The connector therefore leaves
`total_return_factor` unset and the documentation will not describe these
returns as total returns. `docs/data_contracts.md` will be corrected so
`adjusted_close` means a provider-declared adjusted close whose adjustment
method is preserved in lineage; a separate total-return factor remains the
only basis for claiming total-return treatment.

The mapping and adjustment lists are named, versioned constants. Their version
participates in request/batch lineage so a later mapping change cannot masquerade
as the same ingestion definition.

The first implementation fetches RICs sequentially. It deliberately does not
introduce concurrency or request batching before the desktop entitlement and
quota behavior have been measured.

## File contract

Each CSV or Parquet row represents one daily bar snapshot. Required columns are:

- `provider_identifier`
- `session_date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `currency`

Optional columns are:

- `adjusted_close`
- `effective_at`
- `available_at`
- `source_record_id`

Column matching is case-insensitive and normalizes to the canonical names. CSV
and Parquet inputs with equivalent normalized values must produce the same
content hash. Duplicate provider-identifier/session-date rows are rejected in
this milestone rather than resolved by file order.

Every unique provider identifier in the selected file subset must correspond to
an explicit request item and resolve to one canonical security. Extra file rows
outside the requested identifiers/date interval are ignored; a requested
identifier with no matching rows is an item-level failure.

If `adjusted_close` is absent, the provider copies `close` and adds `UNADJUSTED`.
If `effective_at` or `available_at` is supplied, it must be timezone-aware. A
file with LSEG data must still declare `source="lseg"` and
`usage_mode="research_only"` even if a user has renamed or transformed it.

## Timestamp and point-in-time policy

`session_date` is the vendor's completed daily session date. Interday history
usually returns a date rather than a defensible publication timestamp. The
initial LSEG adapter therefore uses a conservative date-derived
`effective_at`, marks it `ESTIMATED_TIMESTAMP`, and never asserts a precise
exchange close time. The exact initial conversion is midnight UTC at the start
of `session_date`, matching the repository's existing date-only adapter
convention. Because `available_at` remains the later acquisition time, this
estimate cannot make the value visible to an earlier knowledge-time query.

The `PriceBar` docstring and `docs/data_contracts.md` will explicitly permit
this date-key placeholder only when `ESTIMATED_TIMESTAMP` is present. Without
that flag, `effective_at` continues to mean the vendor-provided bar endpoint or
market close.

For a newly observed LSEG or file snapshot without a trustworthy source
publication timestamp:

- `available_at` is the current acquisition completion time;
- `ingested_at` equals that acquisition completion time; and
- `SNAPSHOT_ONLY` is present.

Consequently, a history downloaded today is not visible to a knowledge-time
query before today. This intentionally sacrifices retrospective vintage depth
instead of introducing look-ahead bias.

When a file supplies trustworthy, timezone-aware `effective_at` and
`available_at`, the provider preserves them after validating
`effective_at <= available_at <= ingested_at`. Merely containing a date column
does not establish historical availability.

## Usage restriction and entitlement provenance

Add `DataUsageMode` with these persisted values:

- `research_only`: data that must remain in local research workflows;
- `public`: a public fallback such as Yahoo;
- `synthetic`: deterministic fixture/demo data;
- `user_supplied`: data whose rights and provenance are declared by the user;
- `unverified`: legacy records whose handling restriction was not recorded.

`usage_mode` is non-null on both `IngestionBatch` and `PriceBar`, and on their
SQLAlchemy records. `IngestionBatch.original_source` is also a required,
persisted 1-to-80-character value; every successful bar's `source` must equal
it. LSEG desktop data is always `research_only`; this cannot be overridden by
CLI input. Fixture and Yahoo adapters are updated to emit `synthetic` and
`public` respectively. Generic files require an explicit value.

The first of two ordered Alembic migrations lands atomically with the required
domain fields. It adds both usage columns with a temporary `unverified` server
default and adds the batch `original_source` column with a temporary
`provider`-derived backfill. It makes all three columns non-null and removes the
server defaults where the database supports that operation. This migration
does not infer rights from legacy `source` text; copying the legacy batch
provider to `original_source` records only the best available transport/source
context. A following attempt-identity migration adds the batch/source-record
unique constraint. Before doing so, it fails closed with an actionable error if
a legacy database already contains duplicate
`(ingestion_batch_id, source_record_id)` pairs; it never deletes or merges an
unverifiable vintage automatically.

`usage_mode` is an application handling restriction, not an assertion that a
contract has been reviewed. The LSEG row in `docs/vendor_entitlements.md`
remains `Unverified` until the data owner confirms extraction, storage,
retention, and intended-use rights. A successful Workspace call proves only
technical access. Documentation must keep these two concepts separate.

This milestone stores and tests the tag but does not add customer card routes.
Later delivery work must filter or reject `research` and `unverified` records;
the absence of such a delivery path is a non-goal here.

## Idempotency and correction vintages

The existing request fingerprint identifies the logical universe/date request.
Live and file sources also need content-aware attempt identity:

1. Normalize successful bars and item-level failures into a canonical,
   timestamp-independent representation.
2. Hash that representation to form `content_hash`.
3. Derive the batch key and deterministic batch ID from provider, dataset,
   request fingerprint, field-map version, usage mode, and content hash. The
   content hash already binds the separately declared original source.

The hash input is a pre-domain `NormalizedPriceContent` projection constructed
before `IngestionBatch` and `PriceBar`. It contains a required top-level
`original_source` value, validated to the same 1-to-80-character contract as
the domain fields, so an all-failure result remains source-distinct. For each
sorted row it contains the
canonical security ID, provider identifier, source record ID, session date,
deterministic date-derived effective time, raw and adjusted numeric values
encoded with `float.hex()`, currency, original source, usage mode, sorted quality
flags, and field-map version. It also contains sorted item-failure identifiers
and categories. Generated UUIDs plus requested, acquisition, availability, and
ingestion timestamps are excluded. A trustworthy, explicitly source-supplied
file `available_at` is content provenance rather than a generated acquisition
timestamp, so it is included; changing that source timestamp must create a new
content identity.

After hashing this projection, the connector derives the batch key/ID and only
then constructs domain bars referencing that batch ID. This ordering avoids a
batch-ID/content-hash construction cycle.

An identical retry therefore resolves to the same batch. Changed normalized
content produces a new attempted batch identity. When availability is generated
at acquisition, a later correction naturally receives a later `available_at`
and persists as a new vintage. When a file supplies authoritative
`available_at`, a changed observation is accepted only if that timestamp also
advances. A different value claiming the same
source/effective/authoritative-availability key is contradictory provenance;
the repository raises a conflict and the CLI transaction rolls back the new
batch and bars.

Price persistence additionally recognizes an existing
`ingestion_batch_id`/`source_record_id` pair as the same content-addressed row
and verifies its numerical/provenance fields before skipping it. This prevents
an identical retry's new wall-clock acquisition time from creating a false
correction vintage. The existing natural vintage key remains responsible for
detecting conflicting values at the same source/effective/available time.
The database adds a unique constraint on
`(ingestion_batch_id, source_record_id)` so this idempotency rule is enforced
below the repository layer as well.

## Configuration

The relevant settings are:

```text
QUANT_RAAS_MARKET_DATA_PROVIDER=lseg
QUANT_RAAS_LSEG_SESSION_MODE=workspace_desktop
```

File paths and provenance can be supplied by finite CLI arguments; persistent
file defaults may live under the existing data/config directories. The
application accepts no LSEG platform session value in this milestone.

The `.env.example` desktop section will document only desktop mode. The current
client ID/client secret placeholders will be removed from the active milestone
example so they do not imply cloud authentication is supported. No App Key is
stored in repository configuration; desktop discovery remains owned by
Workspace and the LSEG library.

The repository already exposes `lseg-data>=2,<3` as the `lseg` optional extra.
Implementation and the live smoke test must run under the project's supported
Python 3.12 environment, matching CI. The project will not relax its `<3.14`
bound or install the connector into the existing Python 3.14-only environment.
The implementation plan must begin by provisioning a dedicated Python 3.12
environment through a user-approved installation route because the Windows
Python launcher currently reports no installed interpreter.

## Failure handling

Connector errors are explicit subclasses of `ProviderError`:

- `ProviderNotConfigured`: desktop mode disabled or optional dependency absent;
- `ProviderSessionError`: Workspace unavailable or desktop handshake failed;
- `ProviderEntitlementError`: the user/session lacks permission;
- `ProviderQuotaError`: a documented quota or rate limit was returned; and
- `ProviderDataError`: response-level schema, duplicate-row, or consistency
  failure that makes the provider response unsafe to interpret.

Structured SDK/status attributes take precedence when classifying an error.
Unknown SDK exceptions become a generic provider error with a sanitized message;
the adapter does not rely solely on brittle message matching.

The file adapter translates malformed CSV/Parquet payloads, invalid required
`session_date` values, invalid optional timestamp text, and numeric/schema
normalization defects into fixed `ProviderDataError` messages. Pandas, PyArrow,
Pydantic, and parser exception text never crosses the provider boundary or
bypasses the CLI's safe JSON error envelope; translated errors suppress the
original rendered cause chain.

Cross-record provider-result invariants retain detailed internal validator
messages for unit diagnosis, but `PriceIngestionService` translates their
`ValueError` to one fixed `ProviderDataError` before persistence. The CLI does
not broadly catch `ValueError`, so unrelated programming defects remain visible.

Item-level data failures have these batch semantics:

- a no-data or invalid-identifier result for one RIC is an item failure, not a
  raised response-schema error;
- at least one valid RIC plus one item failure -> `PARTIAL`;
- all RICs producing item failures with a healthy session -> persisted `FAILED`
  batch;
- session, entitlement, or quota failure -> raise immediately and persist no
  observations; and
- any provider failure -> no automatic fallback to a file or another provider.

The first milestone adds no automatic retries. This avoids amplifying desktop
quota problems and keeps finite jobs predictable. A later retry policy can be
designed from measured error and quota behavior.

Error messages include the affected RIC and sanitized category where useful,
are capped by the existing batch error length, and exclude credentials, config
contents, proxy tokens, and raw response bodies.

## Tests

### Deterministic unit tests

An injected fake gateway verifies:

- desktop-only guard and lazy optional import;
- one open and one close per request, including exceptions;
- exact field/adjustment mapping and sequential RIC behavior;
- raw/adjusted joins, adjustment factors, currency, and quality flags;
- stable content hashes and content-addressed batch identity;
- partial and failed item-level batches;
- session, entitlement, quota, and malformed-data errors; and
- absence of implicit source fallback.

File-provider tests cover:

- equivalent CSV and Parquet normalization/content hashes;
- all-failure original-source identity and persistence;
- fixed, sanitized CSV, Parquet, timestamp, schema, and numeric parse errors;
- strict required columns and timezone validation;
- explicit source/usage provenance;
- missing adjusted close;
- duplicate rows and unrequested identifiers; and
- a missing optional Parquet engine.

### Integration tests

Fake gateway/file inputs plus SQLite verify:

- both providers use `PriceIngestionService` and the same repository path;
- identical reruns insert no new batch or bars;
- changed content with later generated or authoritative availability creates a
  later knowledge-time vintage, while changed content at the same authoritative
  timestamp conflicts and rolls back;
- `price_history_as_of` returns the appropriate vintage at each cutoff;
- usage mode round-trips on batches and bars, and original source round-trips
  on batches even without bars;
- ordered Alembic upgrades from the current head backfill legacy usage to
  `unverified`, backfill batch original source from its provider, and add
  attempt identity; downgrades remove the constraint and exactly the three new
  columns;
- RIC resolution is temporal and fails on unknown/ambiguous mappings; and
- CLI JSON summaries contain no raw prices or secrets.

### External Workspace smoke test

`tests/external/test_lseg_workspace_smoke.py` is marked `external` and requires
an explicit enable flag plus a user-configured RIC and a small completed recent
date range. It verifies:

- `desktop.workspace` opens through the running Workspace application;
- raw and adjusted calls return a usable schema;
- normalized bars have the requested RIC, vendor-reported quote currency, UTC
  timestamps, LSEG source, research-only usage, and conservative quality flags;
  and
- the session closes after success or failure.

The smoke test has no numeric golden values and does not persist to the normal
development database. CI continues to run `pytest -m "not external"`; no CI job
depends on Workspace, credentials, entitlements, or changing market data.

## Acceptance criteria

The milestone is complete when:

1. A dedicated supported Python 3.12 environment is provisioned and can install
   `.[lseg]` plus the optional Parquet extra.
2. With Workspace open and authenticated, the manual smoke test retrieves one
   configured RIC's recent completed daily history through `desktop.workspace`.
3. The local command persists normalized LSEG bars as
   `source="lseg"`, `usage_mode="research_only"`, `SNAPSHOT_ONLY` data while the
   contractual entitlement inventory remains `Unverified`.
4. Raw OHLCV and adjusted close remain semantically separate.
5. Repeating an identical request is idempotent; changed source content with a
   later knowledge timestamp becomes a later vintage, while contradictory
   content at the same authoritative timestamp is rejected atomically.
6. Equivalent CSV and Parquet inputs traverse the same provider-neutral
   ingestion path and yield equivalent normalized content.
7. A bad file, closed Workspace, unavailable entitlement, quota response, and
   invalid RIC each fail with the designed explicit behavior.
8. The complete deterministic test suite, branch coverage gate, Ruff format and
   lint checks, mypy, and migration checks pass.
9. Documentation explains local-session prerequisites, file schema, research
   licensing restrictions, smoke-test invocation, and the absence of cloud API
   support or automatic fallback.

## Official LSEG references

- [LSEG Data Library Python quick start](https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python/quick-start)
- [LSEG Data Library configuration process](https://developers.lseg.com/en/article-catalog/article/configuration-process)
- [Official `get_history` example](https://github.com/LSEG-API-Samples/Example.DataLibrary.Python/blob/lseg-data-examples/Examples/1-Access/EX-1.01.02-GetHistory.ipynb)
- [LSEG Workspace corporate-actions and price-adjustment guide](https://developers.lseg.com/en/article-catalog/article/workspace-corporate-actions-content-set-guide)
- [`lseg-data` package metadata](https://pypi.org/project/lseg-data/)
