# Versioned Thesis Authoring and Deterministic Relevance Design

## Context

The platform already has `Thesis` and `ThesisVersion` domain models and SQL
tables, but they are only a boundary. There is no repository port, service,
HTTP API, dashboard authoring flow, or research-pipeline integration. Thesis
versions are stored as untyped JSON, the optional `thesis_id` in coverage and
holdings imports is an unrelated free-text string, and every generated card
therefore defaults to no thesis impact.

The materiality configuration reserves 0.15 of the score for
`thesis_relevance`, making this the highest-value product capability that can
be built without licensed vendor data or an LLM. The milestone turns the
existing boundary into an auditable, point-in-time subsystem while preserving
the core guardrail: the system never creates or silently changes a PM's
investment thesis.

## Goals

- Let a PM create, read, version, and archive a structured thesis through the
  API and the company page.
- Preserve immutable thesis content versions and explicit approval
  attribution.
- Resolve the exact version that was effective and known at a research cutoff.
- Map numeric findings to thesis nodes using deterministic feature overlap and
  invalidation proximity.
- Feed the bounded relevance score into the existing materiality calculation.
- Persist the exact thesis version and node-level assessment used by each
  finding and card.
- Keep the current no-thesis workflow valid and distinguish it from an
  evaluated thesis with no matching feature.
- Validate coverage and holdings thesis references instead of retaining an
  unenforced free-text relationship.

## Non-goals

- AI or semantic mapping of filing, news, or other prose to thesis nodes.
- System-generated thesis proposals, drafts, or approval queues.
- Authentication, role enforcement, tenant isolation, or authorization. Until
  those exist, author and approver fields are audit attribution supplied by the
  caller, not proof of identity.
- Calibrating materiality weights or lowering the current materiality-tier
  thresholds. Thesis relevance raises the current theoretical score ceiling
  from 0.45 to 0.60; it does not by itself make `material` cards possible.
- Deriving new fundamental, estimate, policy, or filing features.
- Fuzzy feature aliases. Thesis links use exact canonical feature identifiers.
- Hard deletion of theses or their historical versions.
- Closing the separate Phase 1 data-quality milestone.

## Considered approaches

### 1. Typed, append-only thesis aggregate with deterministic relevance - selected

Introduce typed content within the existing JSON storage boundary, a dedicated
repository and service, explicit version lineage, deterministic scoring, and a
small API/dashboard workflow. This delivers the user-visible capability and
the materiality input together while remaining offline, reproducible, and
vendor-independent.

### 2. CRUD and version history first, relevance later

This is a smaller persistence change, but it leaves the chosen product outcome
unmet: materiality and cards still cannot use a thesis. It would also make the
first API schema harder to validate against the eventual scoring contract.

### 3. Untyped text plus semantic or LLM matching

Free-form text is easy to author, but it cannot support auditable invalidation
thresholds and would depend on the unresolved model-provider and data-terms
decision. It would also violate the deterministic-first roadmap sequence.

## Domain contracts

### Thesis identity

`Thesis` remains the stable aggregate identity and gains:

- `thesis_key`: a lowercase, human-readable identifier such as `asml_core`,
  globally unique until tenant scoping exists;
- `created_by`: required caller attribution for the identity's author;
- `archived_at`: the server timestamp at which it stopped being available for
  new research; and
- `archived_by`: optional caller attribution for that action.

The internal `thesis_id` remains a UUID and is used for relational keys. The
public `thesis_key` is used by HTTP routes and by the existing CSV column named
`thesis_id`. Keeping that external column name avoids a breaking import-format
change; the documentation will clarify that its value is the public thesis
key, not the internal UUID.

Keys and node IDs match `^[a-z][a-z0-9_]{0,127}$`. Canonical feature names
match `^[a-z][a-z0-9_]{0,159}$`. Driver direction is one of `positive`,
`negative`, or `mixed`; risk severity is one of `low`, `medium`, or `high`.

`security_id`, `thesis_key`, and the short display `title` are immutable in
this milestone. Changing the PM-authored content appends a version. Replacing a
mistaken identity requires archiving it and creating a corrected key. Multiple
active theses may exist for one security because different coverage contexts
can express different investment cases. The research service never guesses
among them: it uses only the key explicitly attached to the coverage member.

### Typed thesis content

The existing `thesis_version.nodes` JSON column stores a typed
`ThesisContent` object with `schema_version = 1`:

- `summary`: the PM's compact investment case;
- `drivers`: thesis nodes with a unique node ID, statement, direction, and
  zero or more exact `supporting_features`;
- `risks`: nodes with a unique node ID, statement, severity, and zero or more
  exact `watch_features`; and
- `invalidation_rules`: nodes with a unique node ID, statement, feature name,
  comparator, warning threshold, breach threshold, and optional unit.

Node IDs are unique across all three collections. Feature identifiers must be
non-empty canonical-style names and are deduplicated within a node. They are
not required to exist in today's calculator registry: a PM can author a thesis
for a planned fundamental feature before that data source lands. Unknown
features remain dormant and visible; matching is always exact, never fuzzy.
The summary is required and non-empty; the three node collections may be empty
so a PM can record a narrative thesis before its numeric features exist.

An invalidation comparator is either `greater_than_or_equal` or
`less_than_or_equal`. For a greater-than rule, the breach threshold must exceed
the warning threshold. For a less-than rule, the breach threshold must be below
the warning threshold. Complex conditions such as "two consecutive declining
quarters" must be represented by an upstream derived feature; the thesis
evaluator does not become a second feature engine.

### Version lifecycle

Creation writes a thesis identity and version 1 in one transaction. Each API
mutation is a direct PM-approved version: the server assigns `created_at` and
`approved_at` to the same current UTC timestamp and records the required
`authored_by` and `approved_by` attribution. They may contain the same value,
but remain separate audit fields. Clients may choose `valid_from`, including a
future activation time, but cannot supply or backdate approval timestamps.

An update appends exactly `latest_version + 1`. The request includes
`expected_version`; a stale value returns a conflict instead of overwriting a
concurrent edit. Activation times must be monotonic for the thesis. Existing
version rows and their JSON content are never updated. New versions are
open-ended in this milestone; effective end dates are derived by the next
version during selection rather than written back to the previous row.

Archiving timestamps the identity and prevents new versions or selection for a
later knowledge cutoff. It does not delete rows and does not alter historical
versions or cards. Repeating the same archive request is idempotent.

`Thesis.status` remains a convenient current-state field, but historical
selection never filters on that mutable value alone. It derives archive state
from `archived_at` and the supplied knowledge cutoff.

The current `ThesisVersion` timestamp validator is corrected to express normal
chronology: `created_at <= approved_at`. Direct approval uses equality. The
existing `valid_to` field remains readable for legacy records, but the new API
does not create finite intervals.

## Point-in-time selection

Version selection receives two explicit timestamps:

- `effective_at`: the research observation time; and
- `knowledge_time`: the latest information the run may know.

A thesis identity is eligible only when it was created by `knowledge_time` and
was not archived at or before `knowledge_time`. A version is known only when
`approved_at <= knowledge_time` and is effective only when
`valid_from <= effective_at`. Among eligible versions, selection uses the
latest `valid_from`, then the highest version number, then `approved_at` as a
deterministic tie-breaker. If the selected legacy record has a `valid_to` at or
before `effective_at`, no older version is resurrected.

The daily research pipeline passes the run's `as_of` as `effective_at` and
`data_cutoff_at` as `knowledge_time`. This prevents a version approved later
from leaking into a historical replay. The existing pure
`active_thesis_version` helper is expanded to the same two-time contract and is
covered by the deterministic test suite.

## Deterministic relevance assessment

### Inputs

The evaluator receives one approved thesis version and typed thesis signals
from the finding generator. A signal contains:

- canonical feature name;
- raw finite value;
- normalized strength in `[0, 1]`;
- feature snapshot ID; and
- optional direction and unit.

The Phase 1 price generator emits strengths only for features that actually
drive its finding score:

- absolute `residual_return_zscore_1d`, reaching 1.0 at 4 standard deviations;
- absolute `dollar_volume_zscore_20d`, reaching 1.0 at 4 standard deviations;
  and
- absolute `relative_return_sector_63d`, reaching 1.0 at a 20% relative move.

All persisted numeric feature snapshots remain available to invalidation rules,
including features such as volatility and beta that do not independently drive
the current finding. The signal and feature-snapshot IDs make every
contribution traceable to stored inputs.

### Feature overlap

For each driver or risk node, exact overlap between the node's configured
features and the finding signals creates a contribution. The node's overlap
score is the maximum normalized strength among its matched signals. Taking the
maximum avoids inflating a score merely because the same development is
represented by several correlated features.

### Invalidation proximity

If an invalidation rule's feature is available and numeric, proximity is
calculated linearly between its warning and breach thresholds:

- a value on the safe side of the warning threshold scores 0;
- a value between warning and breach is scaled into `(0, 1)`; and
- a value at or beyond the breach threshold scores exactly 1.

Missing, non-numeric, or non-finite inputs do not fabricate a contribution;
the assessment records why the rule could not be evaluated. A breached rule
therefore produces maximum thesis relevance by construction.

### Aggregation and impact

The final `thesis_relevance` component is the maximum node contribution. A
single invalidation risk must not be diluted by unrelated nodes. The primary
node is selected by highest contribution and then lexicographic node ID, making
ties reproducible.

Impact labels are versioned configuration, initially:

- `none`: score exactly 0;
- `low`: score greater than 0 and below 0.50;
- `moderate`: score from 0.50 up to but not including 0.75; and
- `high`: score at least 0.75.

These thresholds and `method_version` live in
`configs/thesis/relevance.yaml`; configuration validation requires descending,
non-overlapping bounds and a zero-score `none` case.

The evaluator emits a `ThesisRelevanceAssessment` containing the score, impact,
thesis and version IDs, primary node, every node contribution, matched feature
names and snapshot IDs, unevaluated-rule reasons, and
`method_version = thesis-relevance-v1`.

A selected thesis with no overlap produces an explicit assessment with score
0.0. The materiality component is present, so completeness includes its 0.15
weight. No selected thesis produces no assessment and passes `None` to the
materiality scorer, so completeness remains lower. This distinction is a
required regression test.

## Persistence and repository boundaries

A dedicated `ThesisRepository` port keeps thesis lifecycle operations out of
the general research-output repository. Its adapter supports:

- create and retrieve identity by UUID or public key;
- list identities by security and archive state;
- list immutable versions in stable version order;
- resolve one version by effective and knowledge timestamps;
- append a version with optimistic conflict detection; and
- archive an identity without committing the caller-owned transaction.

A `ThesisService` owns timestamps, approval attribution, content validation,
version allocation, security/key checks, and conversion of repository
conflicts into typed application errors. SQL uniqueness on
`(thesis_id, version)` remains the final concurrency guard.

`ResearchFinding` gains optional `thesis_version_id` and
`thesis_relevance` fields. `ResearchCard` gains optional
`thesis_version_id` and a `thesis_node_ids` tuple while retaining the singular
`thesis_node_id` as its backward-compatible primary node. Domain validation
requires the assessment and lineage IDs to agree whenever they are present.

One Alembic migration adds:

- unique non-null `thesis.thesis_key`, with deterministic UUID-based backfill
  for any pre-existing rows;
- non-null `thesis.created_by` and `thesis_version.authored_by`, backfilled from
  existing version approval attribution where possible and otherwise marked as
  a legacy import;
- nullable `thesis.archived_at` and `thesis.archived_by`;
- nullable `research_finding.thesis_version_id` plus a restrictive foreign key;
- nullable JSON `research_finding.thesis_relevance`;
- nullable `research_card.thesis_version_id` plus a restrictive foreign key;
  and
- JSON `research_card.thesis_node_ids`, defaulting to an empty list while the
  existing singular `thesis_node_id` remains the deterministic primary node.

Thesis versions cannot be hard-deleted, and the new foreign keys make that
lineage rule enforceable. Legacy findings and cards remain valid with null
thesis lineage.

## Research pipeline and card flow

For each coverage member, the daily service performs the following after
calculating the security's typed features and before building its finding:

1. If the member's optional thesis reference is blank, continue with no thesis
   assessment.
2. Resolve the public key and require it to belong to the same security.
3. Select its version at the run's effective and knowledge cutoffs.
4. Evaluate the generator's normalized signals and all usable numeric feature
   snapshots against that version.
5. Pass the assessment score into `MaterialityScorer` as
   `thesis_relevance` and persist the complete assessment on the finding.
6. Copy the exact thesis-version ID, impact, primary node, and all matched node
   IDs onto the card contract.

An unknown, cross-security, archived, or not-yet-effective explicit thesis key
is a per-security research failure, not a silent no-thesis fallback. Other
securities in the run still succeed under the existing partial-failure policy.
Re-running identical inputs and cutoffs produces identical assessments,
finding IDs, card IDs, scores, and node ordering.

When several finding families are later merged into one card, the card builder
selects the assessment with the highest relevance score and uses the same
node-ID tie-breaker. Findings for one card must not claim different thesis
versions; such input fails closed until a deliberate multi-thesis card contract
is designed.

Card rendering displays the impact, primary node, and short thesis-version
identifier. It does not claim that a relevance score proves or disproves the
investment case.

## API surface

The milestone adds these routes:

```text
POST   /v1/theses
GET    /v1/theses?security_id=&include_archived=
GET    /v1/theses/{thesis_key}?effective_at=&knowledge_time=
GET    /v1/theses/{thesis_key}/versions
POST   /v1/theses/{thesis_key}/versions
DELETE /v1/theses/{thesis_key}
```

Create and append requests contain structured content, `authored_by`,
`approved_by`, and an optional `valid_from`; create also records the identity's
`created_by`, while append requires `expected_version`. Archive requires
`archived_by`. Mutation timestamps are server-owned.

Reads return the identity, selected version or history, requested cutoff, and
maximum approval timestamp represented by the response. Errors are explicit:

- `404` for an unknown thesis key;
- `409` for a duplicate key, stale expected version, or mutation of an archived
  thesis; and
- `422` for invalid structured content, thresholds, timestamps, or a
  cross-security reference.

A known identity with no version at the requested cutoffs returns `200` with a
null selected version and an explicit selection reason such as
`not_yet_effective` or `archived_at_cutoff`; it is not confused with an unknown
key.

Because authentication is not yet implemented, responses and documentation
state that attribution fields are not authenticated identities.

Coverage and holdings import retain the current `thesis_id` header but validate
a supplied value as a public thesis key belonging to the resolved security at
the import cutoff. An invalid reference appears as a row-level validation issue
before persistence. Demo fixtures are updated so their referenced thesis keys
resolve. `SecurityMasterService` receives the `ThesisRepository` as an injected
dependency and performs this validation after security resolution but before
the existing atomic persistence step, keeping CLI, API, and dashboard imports
consistent.

## Dashboard workflow

The company tab gains a thesis panel for the selected security:

- list active and archived thesis keys;
- show the selected current version, summary, drivers, risks, invalidation
  rules, approval attribution, and approval/effective timestamps;
- show immutable version history;
- create a thesis or append a version through a structured Streamlit form; and
- archive through an explicit confirmation action.

The editor uses ordinary fields plus editable driver, risk, and invalidation
tables rather than asking a PM to manipulate raw database JSON. Submission
requires an approver value and a confirmation checkbox stating that the version
is being approved. Validation errors are shown without partial persistence.
There is no autosave or system-authored default content.

## Error handling and integrity

- Domain validation rejects duplicate node IDs, malformed canonical feature
  names, inconsistent invalidation thresholds, non-finite values, and empty
  required statements.
- The service rejects stale versions and non-monotonic activation timestamps.
- Repository uniqueness and foreign keys remain the final race and lineage
  guards.
- API and dashboard mutations use one transaction for the thesis identity and
  its first version or for each appended version.
- An explicit invalid thesis reference fails only the affected security during
  research; absence of a reference remains valid.
- Unknown future feature names are retained and remain unmatched until an
  input signal or feature snapshot with that exact canonical name exists.
- No error path silently substitutes the current version for the requested
  historical cutoff.

## Testing strategy

Implementation follows test-driven development:

1. Domain tests cover typed content, unique node IDs, feature-name validation,
   comparator/threshold rules, UTC timestamps, and approval chronology.
2. Pure evaluator tests cover overlap, correlated-feature maximum aggregation,
   both invalidation directions, boundary values, breaches, missing/non-finite
   inputs, deterministic ties, impact thresholds, and method lineage.
3. Selector tests prove separate effective and knowledge cutoffs, future
   approvals, future activations, archival history, legacy expiry, and no
   resurrection of an older version.
4. SQLite repository tests cover key uniqueness, round trips, stable history,
   optimistic append conflicts, archive idempotency, and restrictive lineage.
5. Service and import tests cover explicit approval, server-owned timestamps,
   security/key validation, and atomic failure.
6. Pipeline integration tests prove no-thesis versus zero-relevance
   completeness, exact score contribution, card version/node lineage,
   deterministic reruns, future-version exclusion, and per-security failure
   isolation.
7. API tests cover every route and typed error. Dashboard tests cover form
   conversion and the create/version/archive workflow at the service boundary.
8. Run the complete deterministic suite with branch coverage, Ruff formatting
   and linting, and strict mypy checks.

Local verification may use the available Python 3.14 environment with
`--ignore-requires-python`, but the repository's supported Python 3.12 CI is
authoritative.

## Documentation scope

Update the thesis section of the data-contract documentation, the company-page
wireframe, API route inventory, and README capability summary. Update the
targeted thesis status and acceptance notes in `PLAN.md` after the feature is
implemented; do not reorder unrelated roadmap phases.
