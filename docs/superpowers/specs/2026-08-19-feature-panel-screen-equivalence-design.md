# Point-in-Time Feature Panel and Screen Equivalence Design

## Context

The Phase 1 research pipeline persists versioned `FeatureSnapshot` records, but
the repository can retrieve them only one security at a time. Screen execution
therefore receives caller-built DataFrames, while historical backtests receive
separately assembled panels. That split leaves no enforced guarantee that a
screen evaluated today and the same screen replayed historically select the
same securities at the same cutoff.

This milestone introduces a set-based, version-pinned, point-in-time feature
panel and one shared screen execution path. It closes two related Phase 1 gaps
without requiring licensed vendor access or a database migration.

## Goals

- Retrieve one cross-sectional feature panel for a requested security universe
  with a single repository operation.
- Pin every requested feature to a semantic feature version and one feature
  configuration version.
- Enforce `effective_at <= as_of` and `available_at <= as_of` before a value can
  enter a screen.
- Use the same retrieval, conversion, filtering, and ranking path for one-off
  and historical screen evaluation.
- Prove with an integration test that the one-off and historical paths return
  identical selected securities and ranks at the same cutoff.

## Non-goals

- Building Bloomberg, LSEG, SEC, or FRED connectors.
- Persisting backtest specifications or results.
- Adding neutralization, liquidity filters, or factor-model functionality.
- Exposing new HTTP endpoints or changing the database schema.
- Optimizing a multi-year backtest into one database query. The first contract
  retrieves one cross-section per cutoff; range-query optimization can follow
  when Phase 5 performance is measured.
- Editing `PLAN.md` as part of this implementation.

## Considered approaches

### 1. Batched repository query plus shared execution service — selected

Add a set-based query to the feature repository, convert its typed snapshots to
the existing screen DataFrame contract, and make both one-off and historical
evaluation call the same service method. This preserves module boundaries,
avoids N+1 queries, and makes version and point-in-time policy explicit.

### 2. Loop over the existing per-security query

This would require less repository code, but it produces one query per security
and inherits the current ambiguity when multiple feature versions coexist. It
does not meet the intended cross-sectional performance or reproducibility
contract.

### 3. Return a pandas DataFrame directly from SQLAlchemy

This could be compact and fast, but it would couple the repository protocol to
pandas and bypass the typed `FeatureSnapshot` boundary. It would also make the
storage adapter responsible for application-level screen formatting.

## Repository contract

`FeatureRepository` gains a `panel_as_of` operation with these inputs:

- a sequence of internal security UUIDs;
- a mapping from feature name to semantic feature version;
- an explicit feature configuration version; and
- one timezone-aware `as_of` cutoff.

The operation returns typed `FeatureSnapshot` values. Empty security or feature
collections return an empty tuple without querying. Naive timestamps and empty
version identifiers fail with actionable `ValueError` messages.

The SQLAlchemy adapter executes one batched query constrained by security,
feature name/version pairs, configuration version, `effective_at <= as_of`, and
`available_at <= as_of`. It orders candidates deterministically and retains the
latest row per `(security_id, feature_name)` using this precedence:

1. latest `effective_at`;
2. latest `available_at`;
3. latest `calculated_at`.

Results are returned in stable `(security_id, feature_name)` order. Competing
rows tied through `calculated_at` for the same requested key fail closed instead
of allowing a storage-engine-dependent choice; callers must correct the data or
request a newly versioned feature.

The existing single-security `latest_as_of` method remains available for
current callers. The new screen path uses only the version-pinned panel method.

## Feature panel adapter

A focused module under `feature_store/` converts snapshots into the tabular
contract already consumed by screens and backtests. Its output includes:

- `decision_at`;
- `security_id`;
- `feature_name` and `feature_version`;
- `value`;
- `effective_at`, `available_at`, and `calculated_at`;
- `config_version` and `code_version`.

The adapter always returns these columns, including for an empty panel, so
downstream behavior is deterministic. It does not select vintages; that remains
the repository's responsibility.

## Screen definition and validation

`ScreenDefinition` gains two backward-compatible fields:

- `feature_config_version`, optional for pure in-memory evaluation; and
- `feature_versions`, a mapping from referenced feature names to semantic
  versions.

Repository-backed execution requires a non-empty configuration version and a
version entry for every condition, declared dependency, and ranking feature.
Entries are checked against `FeatureRegistry`. Unknown, missing, or unused
version entries fail before any repository query. Repository screen YAML files
will be updated to state the Phase 1 feature and configuration versions
explicitly.

The ranking feature is included in the required feature set even when it is not
also a condition. This avoids silently skipping a declared ranking input.

## Shared screen execution

A small screen execution service receives a `FeatureRepository` and
`FeatureRegistry`.

Its one-off method:

1. validates the definition's feature pins;
2. retrieves the point-in-time panel at `as_of`;
3. converts snapshots to the canonical DataFrame; and
4. calls the existing pure `run_screen` engine.

Its historical method accepts ordered cutoffs and calls the same one-off method
for each cutoff. There is no alternate filtering or ranking implementation in
the historical path. The result is an ordered tuple of normal `ScreenResult`
objects, making each historical decision independently auditable.

## Missing data and errors

- A missing feature row is handled by the existing screen `missing_policy`.
- An invalid or disabled screen continues to fail explicitly.
- A future vintage is excluded by the repository and remains independently
  rejected by the screen engine's cutoff filter.
- Invalid feature pins fail before data access.
- Ambiguous top vintages fail closed with a repository conflict error.
- The service does not silently substitute another feature or configuration
  version.

## Testing strategy

Implementation follows test-first development:

1. Add integration tests for batched retrieval across multiple securities,
   explicit feature/configuration version filtering, future revisions, stable
   ordering, empty inputs, and ambiguous top vintages.
2. Add unit tests for canonical panel conversion and repository-backed screen
   definition validation.
3. Add the required equivalence integration test. Seed past and future feature
   vintages, run a screen once at cutoff `D`, replay `D` through the historical
   method, and assert identical selected IDs, ordering/ranks, evaluated values,
   and missing-data exclusions.
4. Run the full deterministic test suite, branch-coverage gate, Ruff formatting
   and linting, and strict mypy checks.

Local verification currently uses the available Python 3.14 environment. The
repository's supported Python 3.12 CI remains authoritative because no complete
3.12 or 3.13 environment is installed locally.

## Documentation scope

`README.md` will be corrected to link to `PLAN.md` after the recent file rename.
`PLAN.md` itself will not be modified.
