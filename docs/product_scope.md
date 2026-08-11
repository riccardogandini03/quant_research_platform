# Product scope

## Product intent

Quant RaaS is an equity-research system that turns point-in-time market and
fundamental observations into a short, ranked set of reproducible research
findings. Portfolio holdings provide relevance and ordering context; they do not
turn the product into a portfolio accounting or execution system.

The primary user is a portfolio manager or research analyst covering roughly
30–100 held securities and a larger watch list. A useful output explains what
changed, quantifies whether the change is unusual, links the evidence, and makes
the next research question explicit.

## Phase 0 and Phase 1 scope

The first implementation slice establishes:

- canonical securities and time-bounded external identifiers;
- holdings and coverage-list imports;
- typed point-in-time domain contracts;
- daily adjusted OHLCV ingestion through replaceable provider interfaces;
- reusable return, risk, calendar, event-study, factor, and anomaly calculations;
- deterministic materiality scoring and evidence-linked research findings;
- local persistence and reproducible daily snapshots;
- a research-oriented dashboard/API shell where implemented; and
- synthetic, network-free tests for numerical and temporal integrity.

The MVP is successful when the same inputs, configuration, and as-of timestamp
produce the same ordered snapshot for every security in a 30–100-name input.
The output may state that evidence is insufficient. Completeness is less
important than not inventing or leaking information.

## Explicit non-goals

The initial product is not:

- an order, execution, or portfolio-management system;
- an accounting-grade performance or tax-lot engine;
- a compliance book of record;
- a guarantee that public fallback data is complete or timely;
- an autonomous trading recommendation engine;
- a general-purpose news reader; or
- a substitute for licensed data entitlements or human investment judgment.

The system does not mutate a PM's stored thesis without explicit approval. It
does not calculate authoritative valuation, P&L, or risk numbers from prose.

## Planned later phases

Estimate vintages, valuation histories, regulatory filing diffs, licensed news,
options histories, AI synthesis, full factor-return estimation, and historical
screen backtesting require additional data contracts and entitlements. Configs
that depend on those features remain disabled until point-in-time inputs exist.

## Product guardrails

1. Every displayed number comes from a typed feature or source observation.
2. Every finding retains evidence identifiers and availability timestamps.
3. Missing, stale, or conflicting evidence remains visible.
4. Portfolio weight modifies priority, not underlying research materiality.
5. Live and historical evaluation share the same feature definition.
6. Network/vendor tests never run as part of the deterministic default suite.

