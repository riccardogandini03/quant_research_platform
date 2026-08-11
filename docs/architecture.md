# Architecture

## Design stance

Quant RaaS begins as a modular monolith. API, dashboard, scheduled jobs, and
research calculations share one versioned Python package and one logical data
model. Process boundaries may be introduced for workload isolation later, but
vendor-specific code and numerical code are separated from the start.

The implementation uses a `src` layout so tests import the installed
`quant_raas` package rather than accidentally importing repository files.

## Logical flow

```text
holdings / coverage                                      configuration
        │                                                       │
        ▼                                                       ▼
security resolution ──► provider interface ──► normalization / validation
                                                       │
                                                       ▼
                                        point-in-time observations
                                                       │
                              ┌────────────────────────┴───────────────┐
                              ▼                                        ▼
                     quantitative features                   event studies
                              └────────────────────────┬───────────────┘
                                                       ▼
                                      candidate research findings
                                                       ▼
                                  deterministic materiality + priority
                                                       ▼
                              evidence-linked snapshot / API / dashboard
```

AI components may summarize already-validated structured findings. They do not
replace numerical feature calculation, source reconciliation, or materiality
scoring.

## Package boundaries

```text
src/quant_raas/
├── config/             environment and versioned file configuration
├── domain/             typed contracts and enums; no vendor dependencies
├── security_master/    temporal identifier resolution and imports
├── connectors/         provider adapters implementing domain protocols
├── ingestion/          orchestration, retries, and raw-to-normalized handoff
├── normalization/      deterministic validation and canonicalization
├── storage/            SQLAlchemy models, repositories, and transactions
├── feature_store/      point-in-time feature persistence and retrieval
├── quant/              pure numerical functions
├── research/           evidence, findings, materiality, and reports
├── backtest/           historical consumers of the same feature definitions
├── ai/                 structured extraction/synthesis with guardrails
└── common/             narrowly shared utilities
```

Top-level `apps/` contains composition code only. `workflows/` calls package
services; it does not own financial formulas. `configs/` contains versioned,
reviewable research parameters. Vendor SDKs may be imported only by their
connector modules.

Dependency direction is toward domain contracts and pure functions:

```text
apps/workflows → services → domain/protocols ← connectors/storage
                             ↑
                        quant/research
```

Domain and quant modules must remain importable without network, API, dashboard,
or licensed-vendor extras.

## Point-in-time model

Records distinguish three concepts:

- `effective_at`: when the observed event/value applies economically;
- `available_at`: when it first became knowable to the research process; and
- `ingested_at`: when this system received the record.

All instants are timezone-aware and normalized to UTC. Exchange-local calendars
determine session membership; UTC alone does not define a trading day. An as-of
query may use only records whose `available_at <= as_of`. Later revisions create
new vintages and do not overwrite what was knowable historically.

This convention is a hard boundary shared by live features, snapshots, and
backtests. See [data contracts](data_contracts.md) for field-level rules.

## Numerical conventions

- Price returns use adjusted close unless a feature explicitly requires raw
  open/high/low/close data.
- Multi-session simple returns compound; they are not sums of daily returns.
- Annualized volatility uses `sqrt(252)` by default, with the convention stored
  alongside the feature version.
- Sample standard deviation uses `ddof=1` unless the feature definition says
  otherwise.
- A session-t anomaly is fitted/scaled using information through t-1.
- Holdings relevance uses absolute position weight, so a short position is not
  treated as less relevant merely because its signed weight is negative.
- Insufficient samples and zero denominators produce an explicit missing result,
  never infinity or an invented zero.
- Persisted numbers must be finite. Units and horizons are part of the feature
  identity, not display-only metadata.

## Persistence and deployment

SQLite supports deterministic local development and tests. PostgreSQL is the
deployment target; SQLAlchemy repositories keep persistence behavior portable
where practical. Parquet/object storage is a later raw-data and analytical
storage option, not the initial source of truth for domain relationships.

The Docker image installs only core plus selected extras. Docker Compose supplies
a local PostgreSQL service and application composition for development. It is
not a production topology: production still requires secret management,
identity, TLS, backups, monitoring, entitlement review, and an approved job
scheduler.

## Reproducibility and lineage

Every snapshot should retain:

- the requested as-of time and completed market session;
- source observation and evidence identifiers;
- maximum source `available_at` used;
- feature name, parameters, and code/config version;
- materiality component values and score version; and
- a deterministic ordering and stable identifier.

Re-running unchanged inputs must be idempotent. Partial provider failures are
recorded per security and must not corrupt successful securities in the batch.
