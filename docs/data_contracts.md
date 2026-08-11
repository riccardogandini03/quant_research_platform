# Data contracts

These are logical contracts for Phase 0/1. Pydantic models and SQLAlchemy rows may
use additional internal fields, but they must preserve these semantics. Schema
changes require a version and migration; silently changing the meaning of an
existing field is not permitted.

## Shared conventions

- Identifiers are trimmed, normalized by identifier type, and resolved through
  time-bounded mappings. Display tickers are not permanent primary keys.
- Timestamps are timezone-aware ISO 8601 instants and are persisted in UTC.
- Dates without times represent calendar or reporting periods, never assumed
  publication times.
- Weights and rates are decimal fractions: `0.042` means 4.2%.
- Persisted numeric values must be finite. Missing is `null`, not `NaN`, `inf`,
  zero, or an empty string.
- Enumerations use stable lowercase machine values; labels may be localized in
  the UI without changing stored values.
- Input rows retain source, source record ID, and ingestion lineage.

## Time and vintage fields

| Field | Meaning |
|---|---|
| `effective_at` | Event time or first instant at which the value applies economically. |
| `available_at` | First instant the value was knowable from the named source. |
| `ingested_at` | Instant this platform received/persisted the record. |
| `as_of` | Cutoff requested by a feature, snapshot, or research query. |
| `period_end` | Reporting/reference period; it does not imply availability. |

For any calculated feature:

```text
max(input.available_at) <= feature.as_of
```

If no eligible vintage exists, the result is insufficient data. Code must not
fall back to the latest present-day record.

## Security and identifiers

### Security

| Field | Type | Rule |
|---|---|---|
| `security_id` | UUID | Stable internal identity. |
| `name` | string | Non-empty display name. |
| `security_type` | enum | Common stock, ADR, ETF, index, or other. |
| `primary_currency` | ISO 4217 string | Trading/reporting usage must be explicit. |
| `exchange_mic` | ISO 10383 MIC | Determines the primary exchange calendar. |
| `exchange_timezone` | IANA timezone | Used to map events to market sessions. |
| `first_trade_date`, `last_trade_date` | date | Optional observed trading lifecycle. |

### SecurityIdentifier

| Field | Type | Rule |
|---|---|---|
| `security_id` | UUID | References `Security`. |
| `scheme` | enum | For example ISIN, RIC, FIGI, or vendor identifier. |
| `value` | string | Canonicalized according to type. |
| `provider` | string/null | Required for provider-specific symbology. |
| `valid_from`, `valid_to` | timestamp/date | Half-open interval `[from, to)`. |

The same provider/scheme/value may not map to two securities over an overlapping
validity interval. Ambiguity is an import error requiring an explicit decision.

`configs/universes/demo.csv` is a combined seed representation: `security_id`
and the security metadata populate `Security`, while `identifier`,
`identifier_scheme`, `provider`, `valid_from`, and `valid_to` populate its
primary `SecurityIdentifier`. Region and benchmark are configuration metadata,
not immutable security identity.

## Holdings and coverage CSVs

`examples/holdings.csv` is the minimum holdings contract:

| Column | Required | Rule |
|---|---|---|
| `identifier` | yes | Resolves uniquely at the snapshot as-of time. |
| `weight` | yes | Finite decimal with `abs(weight) <= 10`; negatives support short books. |
| `thesis_id` | no | Existing thesis reference or blank. |
| `benchmark` | no | Resolvable benchmark alias. |

Holdings may additionally specify `identifier_scheme`, `provider`, and
`exchange_mic` to disambiguate a reference. A weight of `4.2` means 420%, not
4.2%; import validation deliberately permits leverage but does not guess units.

`examples/coverage.csv` has no weight. It accepts `identifier`, optional
`thesis_id`, optional `benchmark`, and optional `peer_group`. Duplicate resolved
security IDs in one file are rejected. Unknown extra columns are rejected by
default so spelling errors cannot silently disappear.

An import is atomic after validation: either all unambiguous valid rows persist,
or no snapshot does. A future explicit partial-import mode must report every
excluded row.

## PriceBar

| Field | Type | Rule |
|---|---|---|
| `security_id` | UUID | Resolved internal identity. |
| `session_date` | date | Exchange-local completed session. |
| `open`, `high`, `low`, `close` | decimal/float | Positive finite prices; `high`/`low` bound open and close. |
| `adjusted_close` | decimal/float | Positive finite total-return-compatible close. |
| `volume` | integer/float | Non-negative; units recorded by connector. |
| `currency` | string | ISO currency of the price. |
| `effective_at` | timestamp | Session close or vendor-defined bar endpoint. |
| `available_at`, `ingested_at` | timestamp | Point-in-time lineage. |
| `source`, `source_record_id` | string | Stable source lineage. |

Uniqueness is source-aware. Corrections are new source vintages or an auditable
replacement, never an unexplained overwrite. Raw close is used for overnight and
intraday features; adjusted close is used for multi-session total returns.

## CompanyEvent and EconomicRelease

Events have an immutable event ID, type, affected security IDs, `effective_at`,
`available_at`, source, and evidence reference. Economic observations also keep
`period_end`, actual, consensus, prior, revised prior, units, and revision/vintage
identity. A weekend or after-close event is assigned to a trading session by an
explicit calendar policy stored with the event study.

## FeatureSnapshot

| Field | Type | Rule |
|---|---|---|
| `feature_id` | string | Stable feature name plus semantic version. |
| `entity_id` | UUID/string | Security, universe, or factor identity. |
| `as_of` | timestamp | Information cutoff. |
| `session_date` | date/null | Completed exchange session if applicable. |
| `value` | finite number/null | Null carries an insufficiency reason. |
| `unit` | string | For example decimal return, annualized decimal vol, or z-score. |
| `parameters` | JSON object | Horizon, ddof, annualization, fit window, and model choices. |
| `evidence_ids` | list | Non-empty when a value is present. |
| `max_source_available_at` | timestamp | Must not exceed `as_of`. |

Feature uniqueness includes version and parameters. Two values with different
horizons or annualization conventions are not the same feature.

## ResearchFinding

A finding is structured evidence, not rendered prose. It contains:

- immutable finding ID and schema version;
- security/entity ID and as-of time;
- finding type, direction, title, and concise objective change;
- finite typed metrics with units and feature references;
- materiality component values, base score, score version, and priority;
- confidence label plus machine-readable limitations;
- one or more evidence IDs; and
- created time and producing code/config version.

Numerical statements must be reproducible from the referenced features. An LLM
may not add a number absent from this object.

## EvidenceReference and ResearchCard

Evidence references retain source name, source record ID or URI, source/effective
time, availability time, retrieval time, and an optional content checksum. A
card groups one or more findings and evidence references into the standard
change/evidence/context/thesis/risk/confidence/next-question layout.

Deleting source evidence while retaining a published card is prohibited unless
licensing requires deletion; in that case the card retains auditable tombstone
metadata and the restriction reason.

## Materiality v0

Component inputs are bounded `[0, 1]`. The base score is the weighted sum in
`configs/materiality/default.yaml`; missing inputs contribute zero. Portfolio
context modifies ordering only:

```text
priority = base_score * (1 + k * sqrt(abs(position_weight)))
```

The stored finding keeps the base score, modifier, priority, every component,
and configuration version. Threshold labels use inclusive lower bounds.

## Determinism and validation

- Batch inputs are sorted by stable internal identity before ID generation.
- Stable IDs derive only from normalized business keys, not process time.
- Configuration and evidence collections are serialized in deterministic order.
- Rerunning the same as-of snapshot is idempotent.
- Adding records with `available_at > as_of` cannot change an earlier result.
- Failed records include structured reasons and never become numeric zeroes.
