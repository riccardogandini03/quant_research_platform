# Versioned Thesis Authoring and Deterministic Relevance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build PM-authored, append-only thesis CRUD and deterministic point-in-time thesis relevance that contributes to materiality and remains traceable on findings and cards.

**Architecture:** Add strict thesis content and assessment contracts, a pure selector/evaluator, and a dedicated repository/service boundary. Compose those through SQLite/PostgreSQL-compatible storage, FastAPI, the security-master imports, the daily research pipeline, and a focused Streamlit panel while preserving caller-owned transactions and the current no-thesis path.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2, Alembic, FastAPI, Streamlit, PyYAML, pytest, Ruff, and strict mypy.

**Spec:** `docs/superpowers/specs/2026-08-20-thesis-versioning-relevance-design.md`

## Global Constraints

- Supported runtime remains Python `>=3.12,<3.14`; Python 3.12 CI is authoritative.
- The feature must run without network access, licensed vendors, or an LLM.
- Thesis content is caller-authored and explicitly approved; server code never invents or silently edits it.
- `thesis_id` is an internal UUID; `thesis_key` is the lowercase public key used by API and CSV references.
- Multiple theses may belong to one security, but research uses only the key explicitly stored on its coverage member.
- Versions are immutable. Update appends `latest + 1`; delete archives; no code path hard-deletes thesis history.
- Every selector accepts separate `effective_at` and `knowledge_time` cutoffs and rejects naive datetimes.
- No thesis means an absent materiality component; an evaluated thesis with no match means an explicit `0.0` component.
- Exact canonical feature-name matching is the only deterministic mapping in this milestone.
- Repositories flush but never commit; API, CLI, dashboard, and workflow transaction scopes own commits.
- Local commands use `.venv314` with `--ignore-requires-python` only because no supported 3.12 interpreter is installed locally.
- Each task follows red-green-refactor, runs focused formatting/lint/type checks, and commits only its listed files.

## File map

- `src/quant_raas/domain/enums.py`: thesis direction, severity, comparator, and selection enums.
- `src/quant_raas/domain/research.py`: immutable thesis content, lifecycle, signal, assessment, and output-lineage contracts.
- `src/quant_raas/domain/portfolio.py`: normalize optional CSV thesis references as public keys.
- `src/quant_raas/research/thesis.py`: pure point-in-time selection, relevance configuration, and deterministic evaluator.
- `configs/thesis/relevance.yaml`: versioned impact thresholds and method version.
- `src/quant_raas/domain/protocols.py`: dedicated `ThesisRepository` port.
- `src/quant_raas/storage/models.py`: thesis identity/version fields and finding/card lineage columns.
- `src/quant_raas/storage/repositories.py`: thesis adapter plus finding/card lineage hydration.
- `migrations/versions/20260820_0002_thesis_relevance.py`: additive schema/backfill migration.
- `src/quant_raas/services/theses.py`: authoring, approval, optimistic append, read, and archive orchestration.
- `src/quant_raas/runtime.py`: repository and evaluator composition.
- `apps/api/schemas.py`, `apps/api/routes.py`: typed thesis requests and REST routes.
- `src/quant_raas/security_master/service.py`: validate supplied public thesis keys after security resolution.
- `configs/thesis/demo.yaml`, `src/quant_raas/demo.py`: explicit offline demo theses.
- `src/quant_raas/research/findings.py`, `src/quant_raas/research/cards.py`: score and render thesis-aware outputs.
- `src/quant_raas/services/daily_research.py`, `src/quant_raas/services/close_workflow.py`:
  select and assess the pinned thesis and compose it in the installable close
  workflow.
- `apps/dashboard/thesis_panel.py`, `apps/dashboard/app.py`: focused company-page authoring/history UI.
- `tests/unit/`, `tests/integration/`, and `tests/point_in_time/`: deterministic contract, repository, API, pipeline, and UI-helper coverage.
- `README.md`, `docs/data_contracts.md`, `docs/wireframes.md`, and `PLAN.md`: targeted capability/status documentation.

---

### Task 1: Strict thesis and public-key domain contracts

**Files:**
- Modify: `src/quant_raas/domain/enums.py:107-132`
- Modify: `src/quant_raas/domain/research.py:119-225`
- Modify: `src/quant_raas/domain/portfolio.py:17-145`
- Modify: `src/quant_raas/domain/__init__.py:1-47`
- Create: `tests/unit/test_thesis_contracts.py`
- Modify: `tests/unit/test_csv_imports.py:38-52`

**Interfaces:**
- Consumes: `DomainModel`, `UtcDatetime`, `ThesisImpact`, and `ThesisStatus`.
- Produces: `ThesisContent`, `Thesis`, `ThesisVersion`, `ThesisSignal`, `ThesisNodeContribution`, `ThesisRelevanceAssessment`, and `ThesisVersionSelection` for every later task.

- [ ] **Step 1: Write failing content and lifecycle tests**

Create `tests/unit/test_thesis_contracts.py` with fixed UUIDs and timestamps. Cover exact normalization, cross-collection node uniqueness, threshold order, archive consistency, approval chronology, and assessment lineage:

```python
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from quant_raas.domain.enums import (
    InvalidationComparator,
    ThesisDirection,
    ThesisImpact,
    ThesisRiskSeverity,
    ThesisSelectionStatus,
    ThesisStatus,
)
from quant_raas.domain.research import (
    Thesis,
    ThesisContent,
    ThesisDriver,
    ThesisInvalidationRule,
    ThesisNodeContribution,
    ThesisRelevanceAssessment,
    ThesisRisk,
    ThesisVersion,
    ThesisVersionSelection,
)

THESIS_ID = UUID("71717171-7171-4717-8717-717171717171")
VERSION_ID = UUID("72727272-7272-4727-8727-727272727272")
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2024, 1, 10, 22, 0, tzinfo=UTC)


def thesis_content() -> ThesisContent:
    return ThesisContent(
        summary="Demand durability supports the long-term case.",
        drivers=(
            ThesisDriver(
                node_id="relative_strength",
                statement="Relative strength remains positive.",
                supporting_features=("relative_return_sector_63d",),
                direction=ThesisDirection.POSITIVE,
            ),
        ),
        risks=(
            ThesisRisk(
                node_id="volume_risk",
                statement="Distribution volume may signal weakening sponsorship.",
                watch_features=("dollar_volume_zscore_20d",),
                severity=ThesisRiskSeverity.MEDIUM,
            ),
        ),
        invalidation_rules=(
            ThesisInvalidationRule(
                node_id="relative_break",
                statement="Relative performance falls through the warning range.",
                feature_name="relative_return_sector_63d",
                comparator=InvalidationComparator.LESS_THAN_OR_EQUAL,
                warning_threshold=-0.05,
                breach_threshold=-0.20,
                unit="decimal_return",
            ),
        ),
    )


def test_content_normalizes_features_and_rejects_duplicate_node_ids() -> None:
    content = thesis_content()
    assert content.drivers[0].supporting_features == ("relative_return_sector_63d",)
    with pytest.raises(ValidationError, match="schema_version"):
        ThesisContent.model_validate(
            {**content.model_dump(mode="python"), "schema_version": 2}
        )
    payload = content.model_dump(mode="python")
    payload["risks"][0]["node_id"] = "relative_strength"
    with pytest.raises(ValidationError, match="node IDs must be unique"):
        ThesisContent.model_validate(payload)


def test_invalidation_threshold_order_depends_on_comparator() -> None:
    with pytest.raises(ValidationError, match="breach threshold must be below warning"):
        ThesisInvalidationRule(
            node_id="bad_rule",
            statement="Bad order.",
            feature_name="beta_126d",
            comparator=InvalidationComparator.LESS_THAN_OR_EQUAL,
            warning_threshold=0.8,
            breach_threshold=1.0,
        )


def test_thesis_archive_fields_and_version_approval_are_consistent() -> None:
    with pytest.raises(ValidationError, match="archived theses require"):
        Thesis(
            thesis_id=THESIS_ID,
            thesis_key="example_core",
            security_id=SECURITY_ID,
            title="Example core thesis",
            status=ThesisStatus.ARCHIVED,
            created_by="pm@example.com",
            created_at=NOW,
        )
    version = ThesisVersion(
        thesis_version_id=VERSION_ID,
        thesis_id=THESIS_ID,
        version=1,
        valid_from=NOW,
        content=thesis_content(),
        authored_by="analyst@example.com",
        approved_by="pm@example.com",
        created_at=NOW,
        approved_at=NOW + timedelta(minutes=1),
    )
    assert version.approved_at > version.created_at
    with pytest.raises(ValidationError, match="approved_at cannot precede created_at"):
        ThesisVersion.model_validate(
            {
                **version.model_dump(mode="python"),
                "approved_at": NOW - timedelta(seconds=1),
            }
        )


def test_assessment_and_selection_require_consistent_lineage() -> None:
    contribution = ThesisNodeContribution(
        node_id="relative_strength",
        node_kind="driver",
        score=0.5,
        matched_feature_names=("relative_return_sector_63d",),
    )
    assessment = ThesisRelevanceAssessment(
        thesis_id=THESIS_ID,
        thesis_version_id=VERSION_ID,
        score=0.5,
        impact=ThesisImpact.MODERATE,
        primary_node_id="relative_strength",
        contributions=(contribution,),
        method_version="thesis-relevance-v1",
    )
    assert assessment.primary_node_id == contribution.node_id
    selection = ThesisVersionSelection(
        thesis_id=THESIS_ID,
        effective_at=NOW,
        knowledge_time=NOW,
        status=ThesisSelectionStatus.NOT_YET_EFFECTIVE,
    )
    assert selection.version is None
```

Add a CSV normalization assertion to `tests/unit/test_csv_imports.py`:

```python
assert result.rows[0].thesis_id == "example_core"
```

- [ ] **Step 2: Run the new tests to verify contract failures**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\unit\test_thesis_contracts.py tests\unit\test_csv_imports.py -q
```

Expected: collection fails because the new enums and thesis models do not exist.

- [ ] **Step 3: Add the exact enums and immutable models**

Add these enums to `domain/enums.py`:

```python
class ThesisDirection(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"


class ThesisRiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InvalidationComparator(StrEnum):
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"


class ThesisSelectionStatus(StrEnum):
    SELECTED = "selected"
    NOT_KNOWN_AT_CUTOFF = "not_known_at_cutoff"
    NOT_YET_APPROVED = "not_yet_approved"
    NOT_YET_EFFECTIVE = "not_yet_effective"
    ARCHIVED_AT_CUTOFF = "archived_at_cutoff"
    EXPIRED_AT_CUTOFF = "expired_at_cutoff"
```

In `domain/research.py`, add strict models with `_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,127}$"` and `_FEATURE_PATTERN = r"^[a-z][a-z0-9_]{0,159}$"`. Use tuple-preserving validators to strip/lowercase feature names and stable-dedupe them with `tuple(dict.fromkeys(values))`. Replace the existing thesis boundary with these signatures:

```python
class ThesisDriver(DomainModel):
    node_id: str = Field(pattern=_KEY_PATTERN)
    statement: str = Field(min_length=1, max_length=2000)
    supporting_features: tuple[str, ...] = ()
    direction: ThesisDirection


class ThesisRisk(DomainModel):
    node_id: str = Field(pattern=_KEY_PATTERN)
    statement: str = Field(min_length=1, max_length=2000)
    watch_features: tuple[str, ...] = ()
    severity: ThesisRiskSeverity


class ThesisInvalidationRule(DomainModel):
    node_id: str = Field(pattern=_KEY_PATTERN)
    statement: str = Field(min_length=1, max_length=2000)
    feature_name: str = Field(pattern=_FEATURE_PATTERN)
    comparator: InvalidationComparator
    warning_threshold: float
    breach_threshold: float
    unit: str | None = Field(default=None, max_length=40)


class ThesisContent(DomainModel):
    schema_version: Literal[1] = 1
    summary: str = Field(min_length=1, max_length=5000)
    drivers: tuple[ThesisDriver, ...] = ()
    risks: tuple[ThesisRisk, ...] = ()
    invalidation_rules: tuple[ThesisInvalidationRule, ...] = ()


class Thesis(DomainModel):
    thesis_id: UUID = Field(default_factory=uuid4)
    thesis_key: str = Field(pattern=_KEY_PATTERN)
    security_id: UUID
    title: str = Field(min_length=1, max_length=300)
    status: ThesisStatus = ThesisStatus.ACTIVE
    created_by: str = Field(min_length=1, max_length=160)
    created_at: UtcDatetime = Field(default_factory=utc_now)
    archived_at: UtcDatetime | None = None
    archived_by: str | None = Field(default=None, min_length=1, max_length=160)


class ThesisVersion(DomainModel):
    thesis_version_id: UUID = Field(default_factory=uuid4)
    thesis_id: UUID
    version: int = Field(ge=1)
    valid_from: UtcDatetime
    valid_to: UtcDatetime | None = None
    content: ThesisContent
    authored_by: str = Field(min_length=1, max_length=160)
    approved_by: str = Field(min_length=1, max_length=160)
    approved_at: UtcDatetime
    created_at: UtcDatetime = Field(default_factory=utc_now)


class ThesisSignal(DomainModel):
    feature_name: str = Field(pattern=_FEATURE_PATTERN)
    raw_value: float
    normalized_strength: float = Field(ge=0.0, le=1.0)
    feature_snapshot_id: UUID
    direction: str | None = Field(default=None, max_length=40)
    unit: str | None = Field(default=None, max_length=40)


class ThesisNodeContribution(DomainModel):
    node_id: str = Field(pattern=_KEY_PATTERN)
    node_kind: Literal["driver", "risk", "invalidation_rule"]
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    matched_feature_names: tuple[str, ...] = ()
    feature_snapshot_ids: tuple[UUID, ...] = ()
    unevaluated_reason: str | None = Field(default=None, max_length=80)


class ThesisRelevanceAssessment(DomainModel):
    thesis_id: UUID
    thesis_version_id: UUID
    score: float = Field(ge=0.0, le=1.0)
    impact: ThesisImpact
    primary_node_id: str | None = Field(default=None, pattern=_KEY_PATTERN)
    contributions: tuple[ThesisNodeContribution, ...] = ()
    method_version: str = Field(min_length=1, max_length=80)


class ThesisVersionSelection(DomainModel):
    thesis_id: UUID
    effective_at: UtcDatetime
    knowledge_time: UtcDatetime
    status: ThesisSelectionStatus
    version: ThesisVersion | None = None
```

Import `Literal` for `node_kind`. Validators must enforce finite raw values and
thresholds, aligned matched-feature/snapshot tuples, stable unique feature
names and node IDs, comparator-specific threshold order, `valid_to >
valid_from`, `created_at <= approved_at`, and `created_at <= archived_at`.
Archive fields are present if and only if status is archived. A contribution
with `score=None` requires an `unevaluated_reason`; a scored contribution may
not have one. Assessment score must equal the maximum evaluable contribution
or zero, and its primary node must be the deterministic matched contributor
chosen by `(-score, node_id)`; it is `None` only when no contribution matched a
feature. Selection status is `SELECTED` if and only if `version` is present,
and that version must belong to `thesis_id`. Export all public thesis contracts
from `domain/__init__.py`.

- [ ] **Step 4: Normalize every optional CSV thesis reference**

In `domain/portfolio.py`, apply one reusable validator to `HoldingUploadRow`, `CoverageUploadRow`, `PortfolioPosition`, and `CoverageMember`:

```python
def _normalize_thesis_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", normalized):
        raise ValueError("thesis_id must be a lowercase public thesis key")
    return normalized
```

Use `field_validator("thesis_id")(_normalize_thesis_key)` on all four models.

- [ ] **Step 5: Run focused tests and quality checks**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\unit\test_thesis_contracts.py tests\unit\test_csv_imports.py -q
.\.venv314\Scripts\python.exe -m ruff format src\quant_raas\domain tests\unit\test_thesis_contracts.py tests\unit\test_csv_imports.py
.\.venv314\Scripts\python.exe -m ruff check src\quant_raas\domain tests\unit\test_thesis_contracts.py tests\unit\test_csv_imports.py
.\.venv314\Scripts\python.exe -m mypy src\quant_raas\domain
```

Expected: focused tests pass; Ruff and mypy report no issues.

- [ ] **Step 6: Commit the domain contracts**

```powershell
git add src/quant_raas/domain/enums.py src/quant_raas/domain/research.py src/quant_raas/domain/portfolio.py src/quant_raas/domain/__init__.py tests/unit/test_thesis_contracts.py tests/unit/test_csv_imports.py
git commit -m "feat: define typed thesis contracts"
```

### Task 2: Point-in-time selection and deterministic relevance evaluator

**Files:**
- Modify: `src/quant_raas/research/thesis.py:1-24`
- Create: `configs/thesis/relevance.yaml`
- Create: `tests/unit/test_thesis_relevance.py`
- Create: `tests/point_in_time/test_thesis_versions.py`
- Modify: `tests/conftest.py:1-125`
- Modify: `pyproject.toml:62-80`

**Interfaces:**
- Consumes: Task 1's thesis contracts and existing `FeatureSnapshot`.
- Produces: `select_thesis_version(...)`, the compatibility
  `active_thesis_version(...)` wrapper, `ThesisRelevanceConfig`, and
  `ThesisRelevanceEvaluator.assess(...)` for repository, service, and pipeline
  tasks.

- [ ] **Step 1: Write failing selector tests with separate time axes**

Create `tests/point_in_time/test_thesis_versions.py` using a thesis created on January 5, version 1 effective January 1 and approved January 5, version 2 effective January 8 and approved January 10, and an archive on January 12. Assert:

```python
selection = select_thesis_version(
    thesis,
    (version_1, version_2),
    effective_at=datetime(2024, 1, 9, tzinfo=UTC),
    knowledge_time=datetime(2024, 1, 9, tzinfo=UTC),
)
assert selection.status == ThesisSelectionStatus.SELECTED
assert selection.version == version_1

future_known = select_thesis_version(
    thesis,
    (version_1, version_2),
    effective_at=datetime(2024, 1, 9, tzinfo=UTC),
    knowledge_time=datetime(2024, 1, 10, tzinfo=UTC),
)
assert future_known.version == version_2
```

Also assert `NOT_KNOWN_AT_CUTOFF`, `NOT_YET_APPROVED`, `NOT_YET_EFFECTIVE`, `ARCHIVED_AT_CUTOFF`, and `EXPIRED_AT_CUTOFF`. For expiry, make the newest otherwise eligible legacy version expire and assert the selector does not resurrect an older version.

- [ ] **Step 2: Write failing evaluator and configuration tests**

Create `tests/unit/test_thesis_relevance.py`. Use the Task 1 content fixture and real `FeatureSnapshot` values. Cover:

```python
assessment = evaluator.assess(
    version,
    signals=(
        ThesisSignal(
            feature_name="relative_return_sector_63d",
            raw_value=-0.10,
            normalized_strength=0.50,
            feature_snapshot_id=relative_feature.feature_snapshot_id,
            unit="decimal_return",
        ),
        ThesisSignal(
            feature_name="dollar_volume_zscore_20d",
            raw_value=3.0,
            normalized_strength=0.75,
            feature_snapshot_id=volume_feature.feature_snapshot_id,
            unit="zscore",
        ),
    ),
    features=(relative_feature, volume_feature),
)
assert assessment.score == pytest.approx(0.75)
assert assessment.impact == ThesisImpact.HIGH
assert assessment.primary_node_id == "volume_risk"
assert assessment.method_version == "thesis-relevance-v1"
```

Add focused cases proving maximum-not-sum aggregation, both comparator formulas, warning/breach boundary inclusion, breached score `1.0`, lexicographic tie-breaking, explicit zero for no overlap, missing-feature `unevaluated_reason`, non-finite rejection, and malformed/unsorted configuration rejection.

- [ ] **Step 3: Run tests to verify the missing evaluator**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\point_in_time\test_thesis_versions.py tests\unit\test_thesis_relevance.py -q
```

Expected: collection fails because the selector signature, config, and evaluator are not implemented.

- [ ] **Step 4: Add the versioned YAML configuration**

Create `configs/thesis/relevance.yaml`:

```yaml
schema_version: 1
method_version: thesis-relevance-v1
zero_impact: none
impact_thresholds:
  - {name: high, minimum_score: 0.75}
  - {name: moderate, minimum_score: 0.50}
  - {name: low, minimum_score: 0.00}
```

`impact_for` returns `zero_impact` when the score is exactly zero; otherwise it
evaluates the descending positive-score thresholds. This represents the
specification's `score > 0` low-impact rule without an arbitrary epsilon.

- [ ] **Step 5: Implement pure selection and configuration**

Expand the existing selector boundary by adding:

```python
def select_thesis_version(
    thesis: Thesis,
    versions: Sequence[ThesisVersion],
    *,
    effective_at: datetime,
    knowledge_time: datetime,
) -> ThesisVersionSelection:
    effective = ensure_utc(effective_at)
    known = ensure_utc(knowledge_time)
    base = {"thesis_id": thesis.thesis_id, "effective_at": effective, "knowledge_time": known}
    if thesis.created_at > known:
        return ThesisVersionSelection(**base, status=ThesisSelectionStatus.NOT_KNOWN_AT_CUTOFF)
    if thesis.archived_at is not None and thesis.archived_at <= known:
        return ThesisVersionSelection(**base, status=ThesisSelectionStatus.ARCHIVED_AT_CUTOFF)
    approved = [item for item in versions if item.approved_at <= known]
    if not approved:
        return ThesisVersionSelection(**base, status=ThesisSelectionStatus.NOT_YET_APPROVED)
    effective_versions = [item for item in approved if item.valid_from <= effective]
    if not effective_versions:
        return ThesisVersionSelection(**base, status=ThesisSelectionStatus.NOT_YET_EFFECTIVE)
    selected = max(
        effective_versions,
        key=lambda item: (item.valid_from, item.version, item.approved_at),
    )
    if selected.valid_to is not None and selected.valid_to <= effective:
        return ThesisVersionSelection(**base, status=ThesisSelectionStatus.EXPIRED_AT_CUTOFF)
    return ThesisVersionSelection(
        **base,
        status=ThesisSelectionStatus.SELECTED,
        version=selected,
    )
```

Retain the existing public helper name as a thin two-time-axis compatibility
wrapper, and add a regression assertion for it:

```python
def active_thesis_version(
    thesis: Thesis,
    versions: Sequence[ThesisVersion],
    *,
    effective_at: datetime,
    knowledge_time: datetime,
) -> ThesisVersion | None:
    return select_thesis_version(
        thesis,
        versions,
        effective_at=effective_at,
        knowledge_time=knowledge_time,
    ).version
```

Add frozen Pydantic `ImpactThreshold` and `ThesisRelevanceConfig` models with
`schema_version: Literal[1] = 1`, `from_yaml`, descending-threshold validation,
unique labels, a required `zero_impact=ThesisImpact.NONE`, and
`impact_for(score)`.

- [ ] **Step 6: Implement deterministic node contributions**

Add `ThesisRelevanceEvaluator` with this public signature:

```python
class ThesisRelevanceEvaluator:
    def __init__(self, config: ThesisRelevanceConfig) -> None:
        self.config = config

    def assess(
        self,
        version: ThesisVersion,
        *,
        signals: Sequence[ThesisSignal],
        features: Sequence[FeatureSnapshot],
    ) -> ThesisRelevanceAssessment: ...
```

Use exact-name dictionaries keyed by feature name. Driver/risk overlap uses the maximum matching signal strength. Invalidation uses these formulas:

```python
if rule.comparator == InvalidationComparator.GREATER_THAN_OR_EQUAL:
    proximity = (value - rule.warning_threshold) / (
        rule.breach_threshold - rule.warning_threshold
    )
else:
    proximity = (rule.warning_threshold - value) / (
        rule.warning_threshold - rule.breach_threshold
    )
score = min(max(proximity, 0.0), 1.0)
```

Emit one contribution for every configured node. An unmatched driver/risk has
score `0.0` with empty match lineage. Retain an invalidation contribution with
`score=None` and one exact reason: `feature_missing`, `feature_non_numeric`, or
`feature_non_finite`. A usable invalidation feature populates its matched name
and snapshot ID even when its safe-side score is zero. Reject duplicate signal
or feature-snapshot names. Sort contributions by `(node_kind, node_id)`; choose
the primary only from contributions with non-empty `matched_feature_names`, by
`(-score, node_id)`. The final score is the maximum evaluable contribution or
`0.0`; no matched feature means `primary_node_id=None`.

- [ ] **Step 7: Add shared fixtures and bring thesis logic into coverage**

In `tests/conftest.py`, add `thesis_content`, `thesis`, `thesis_version`, `thesis_relevance_config`, and `thesis_relevance_evaluator` fixtures using fixed UUIDs and the repository config path. Remove `src/quant_raas/research/thesis.py` from the coverage omit list in `pyproject.toml`.

- [ ] **Step 8: Run focused tests and quality checks**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\unit\test_thesis_relevance.py tests\point_in_time\test_thesis_versions.py -q
.\.venv314\Scripts\python.exe -m ruff format src\quant_raas\research\thesis.py tests\unit\test_thesis_relevance.py tests\point_in_time\test_thesis_versions.py tests\conftest.py
.\.venv314\Scripts\python.exe -m ruff check src\quant_raas\research\thesis.py tests\unit\test_thesis_relevance.py tests\point_in_time\test_thesis_versions.py tests\conftest.py
.\.venv314\Scripts\python.exe -m mypy src\quant_raas\research\thesis.py
```

Expected: all selector/evaluator tests pass and static checks are clean.

- [ ] **Step 9: Commit the pure thesis engine**

```powershell
git add configs/thesis/relevance.yaml pyproject.toml src/quant_raas/research/thesis.py tests/conftest.py tests/unit/test_thesis_relevance.py tests/point_in_time/test_thesis_versions.py
git commit -m "feat: evaluate deterministic thesis relevance"
```

### Task 3: Additive thesis and research-lineage migration

**Files:**
- Modify: `src/quant_raas/storage/models.py:421-570`
- Create: `migrations/versions/20260820_0002_thesis_relevance.py`
- Create: `tests/integration/test_thesis_migration.py`

**Interfaces:**
- Consumes: Task 1's domain field names and the existing `20260811_0001` schema.
- Produces: ORM columns and an upgrade-safe database schema for Tasks 4, 8, and 9.

- [ ] **Step 1: Write a failing metadata and legacy-backfill migration test**

Create `tests/integration/test_thesis_migration.py`. Use a file-backed SQLite database so Alembic can reconnect. Upgrade only to `20260811_0001`, insert one security, one legacy thesis, and one legacy version, then upgrade to `head`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from quant_raas.config import get_settings

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def _config(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Config:
    monkeypatch.setenv("QUANT_RAAS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def test_thesis_migration_backfills_legacy_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, "20260811_0001")
    engine = create_engine(url)
    now = datetime(2024, 1, 10, tzinfo=UTC)
    security_id = UUID("11111111-1111-4111-8111-111111111111")
    thesis_id = UUID("71717171-7171-4717-8717-717171717171")
    version_id = UUID("72727272-7272-4727-8727-727272727272")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO security "
                "(security_id,name,security_type,status,primary_currency,created_at,updated_at) "
                "VALUES (:id,'Example','common_stock','active','USD',:now,:now)"
            ),
            {"id": str(security_id), "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO thesis (thesis_id,security_id,title,status,created_at) "
                "VALUES (:id,:security,'Legacy','active',:now)"
            ),
            {"id": str(thesis_id), "security": str(security_id), "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO thesis_version "
                "(thesis_version_id,thesis_id,version,valid_from,nodes,approved_by,approved_at,created_at) "
                "VALUES (:id,:thesis,1,:now,:nodes,'legacy@example.com',:now,:now)"
            ),
            {
                "id": str(version_id),
                "thesis": str(thesis_id),
                "now": now,
                "nodes": json.dumps(
                    {
                        "schema_version": 1,
                        "summary": "Legacy thesis content.",
                        "drivers": [],
                        "risks": [],
                        "invalidation_rules": [],
                    }
                ),
            },
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT thesis_key, created_by FROM thesis WHERE thesis_id=:id"),
            {"id": str(thesis_id)},
        ).mappings().one()
        version = connection.execute(
            text("SELECT authored_by FROM thesis_version WHERE thesis_version_id=:id"),
            {"id": str(version_id)},
        ).mappings().one()
    assert row["thesis_key"] == f"legacy_{thesis_id.hex}"
    assert row["created_by"] == "legacy@example.com"
    assert version["authored_by"] == "legacy@example.com"
    assert "thesis_version_id" in {
        column["name"] for column in inspect(engine).get_columns("research_card")
    }
    engine.dispose()
    get_settings.cache_clear()
```

Add a second test that imports `Base.metadata`, inspects the ORM tables, and asserts non-null `thesis_key`, non-null `created_by`/`authored_by`, nullable lineage FKs, and non-null `thesis_node_ids`.

- [ ] **Step 2: Run the migration test to verify the missing revision**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\integration\test_thesis_migration.py -q
```

Expected: FAIL because the head schema does not contain the new columns.

- [ ] **Step 3: Extend the SQLAlchemy models**

Add these mapped columns:

Add these exact fields inside their existing record classes:

```python
# ThesisRecord
thesis_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
created_by: Mapped[str] = mapped_column(String(160), nullable=False)
archived_at: Mapped[Any | None] = mapped_column(UTCDateTime())
archived_by: Mapped[str | None] = mapped_column(String(160))

# ThesisVersionRecord
authored_by: Mapped[str] = mapped_column(String(160), nullable=False)

# ResearchFindingRecord
thesis_version_id: Mapped[UUID | None] = mapped_column(
    ForeignKey("thesis_version.thesis_version_id", ondelete="RESTRICT")
)
thesis_relevance: Mapped[dict[str, Any] | None] = mapped_column(JSON)

# ResearchCardRecord
thesis_version_id: Mapped[UUID | None] = mapped_column(
    ForeignKey("thesis_version.thesis_version_id", ondelete="RESTRICT")
)
thesis_node_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
```

Keep the existing `nodes` database column; Task 4 serializes `ThesisVersion.content` into it.

- [ ] **Step 4: Implement upgrade and downgrade with deterministic backfill**

Create revision `20260820_0002`, down-revision `20260811_0001`. Add nullable backfill columns first. Fetch legacy thesis IDs and their earliest version approver through the Alembic bind, then execute parameterized updates:

```python
for row in bind.execute(
    sa.text(
        "SELECT t.thesis_id, "
        "(SELECT tv.approved_by FROM thesis_version tv "
        " WHERE tv.thesis_id=t.thesis_id ORDER BY tv.version LIMIT 1) AS approver "
        "FROM thesis t"
    )
).mappings():
    bind.execute(
        sa.text(
            "UPDATE thesis SET thesis_key=:key, created_by=:author "
            "WHERE thesis_id=:thesis_id"
        ),
        {
            "key": f"legacy_{str(row['thesis_id']).replace('-', '').lower()}",
            "author": row["approver"] or "legacy_import",
            "thesis_id": row["thesis_id"],
        },
    )
bind.execute(sa.text("UPDATE thesis_version SET authored_by=approved_by"))
```

Use `op.batch_alter_table` to make `thesis_key`, `created_by`, and `authored_by` non-null and to add the unique/FK constraints on SQLite. Add `thesis_node_ids` with `server_default=sa.text("'[]'")`, then retain the ORM-side default. Downgrade removes FKs/constraints before columns in reverse dependency order.

- [ ] **Step 5: Run migration and schema checks**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\integration\test_thesis_migration.py -q
.\.venv314\Scripts\python.exe -m ruff format src\quant_raas\storage\models.py migrations\versions\20260820_0002_thesis_relevance.py tests\integration\test_thesis_migration.py
.\.venv314\Scripts\python.exe -m ruff check src\quant_raas\storage\models.py migrations\versions\20260820_0002_thesis_relevance.py tests\integration\test_thesis_migration.py
.\.venv314\Scripts\python.exe -m mypy src\quant_raas\storage\models.py
```

Expected: legacy backfill and metadata tests pass; static checks are clean.

- [ ] **Step 6: Commit the schema migration**

```powershell
git add src/quant_raas/storage/models.py migrations/versions/20260820_0002_thesis_relevance.py tests/integration/test_thesis_migration.py
git commit -m "feat: migrate thesis relevance lineage"
```

### Task 4: Thesis repository port and SQLAlchemy adapter

**Files:**
- Modify: `src/quant_raas/domain/protocols.py:1-165`
- Modify: `src/quant_raas/storage/repositories.py:1-1230`
- Create: `tests/unit/test_thesis_repository_sql.py`
- Create: `tests/integration/test_thesis_repository.py`

**Interfaces:**
- Consumes: Task 1 domain contracts, Task 2 selector, and Task 3 records.
- Produces: `ThesisRepository` and `SqlAlchemyThesisRepository` for service, imports, dashboard, and daily research.

- [ ] **Step 1: Write failing repository lifecycle and PIT tests**

Create `tests/integration/test_thesis_repository.py`. Persist `sample_security`, then test:

```python
repository = SqlAlchemyThesisRepository(sqlite_session)
assert repository.add_thesis(thesis) == thesis
assert repository.add_version(thesis_version, expected_version=0) == thesis_version
assert repository.get_by_id(thesis.thesis_id) == thesis
assert repository.get_by_key("example_core") == thesis
assert repository.list_for_security(sample_security.security_id) == (thesis,)
assert repository.list_versions(thesis.thesis_id) == (thesis_version,)
selection = repository.version_as_of(
    thesis,
    effective_at=thesis_version.valid_from,
    knowledge_time=thesis_version.approved_at,
)
assert selection.version == thesis_version
```

Add cases for duplicate key conflict, `expected_version` mismatch,
non-monotonic version number, stable `(version, approved_at)` history order,
archive idempotency, archive-aware selection, and `include_archived`. Assert
both UUID and public-key retrieval return the same immutable identity. The
restrictive finding/card lineage assertion belongs wholly to Task 8, once
those output fields exist.

Create `tests/unit/test_thesis_repository_sql.py` and compile the repository's
identity-lock statement with `sqlalchemy.dialects.postgresql.dialect()`:

```python
statement = _locked_thesis_statement(THESIS_ID)
compiled = str(statement.compile(dialect=postgresql.dialect()))
assert "FOR UPDATE" in compiled
assert "thesis.thesis_id" in compiled
```

The integration test also uses a file-backed temporary SQLite engine and two
caller-owned sessions: session A caches ACTIVE and commits, session B archives
and commits, then session A proves a stale append is rejected after the locked
refresh. Repeated archive returns the original timestamp/actor. The
compiled-statement test covers the PostgreSQL locking primitive that SQLite
intentionally ignores.

- [ ] **Step 2: Run the repository tests to verify the missing adapter**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\unit\test_thesis_repository_sql.py tests\integration\test_thesis_repository.py -q
```

Expected: collection fails because `SqlAlchemyThesisRepository` does not exist.

- [ ] **Step 3: Add the repository protocol**

Import `Thesis`, `ThesisVersion`, and `ThesisVersionSelection` in `domain/protocols.py`, then add:

```python
@runtime_checkable
class ThesisRepository(Protocol):
    def add_thesis(self, thesis: Thesis) -> Thesis: ...
    def get_by_id(self, thesis_id: UUID) -> Thesis | None: ...
    def get_by_key(self, thesis_key: str) -> Thesis | None: ...
    def list_for_security(
        self,
        security_id: UUID,
        *,
        include_archived: bool = False,
    ) -> Sequence[Thesis]: ...
    def add_version(
        self,
        version: ThesisVersion,
        *,
        expected_version: int,
    ) -> ThesisVersion: ...
    def list_versions(self, thesis_id: UUID) -> Sequence[ThesisVersion]: ...
    def version_as_of(
        self,
        thesis: Thesis,
        *,
        effective_at: datetime,
        knowledge_time: datetime,
    ) -> ThesisVersionSelection: ...
    def archive(
        self,
        thesis_id: UUID,
        *,
        archived_at: datetime,
        archived_by: str,
    ) -> Thesis: ...
```

- [ ] **Step 4: Implement hydration and identity operations**

Add `_thesis_from_record` and `_thesis_version_from_record`; hydrate `content`
from `row.nodes`. Non-conforming pre-milestone JSON fails closed with a domain
validation error and is never rewritten during reads. Implement `add_thesis`,
`get_by_id`, `get_by_key`, and `list_for_security` with stable `(thesis_key,
thesis_id)` ordering. Serialize new content with
`version.content.model_dump(mode="json")`. A duplicate public key raises:

```python
raise RepositoryConflictError(f"thesis key {thesis.thesis_key!r} already exists")
```

- [ ] **Step 5: Implement optimistic append, selection, and archive**

Add `_locked_thesis_statement(thesis_id)` as
`select(ThesisRecord).where(...).with_for_update().execution_options(populate_existing=True)`.
The refresh option prevents a long-lived caller session from trusting a stale
ACTIVE identity already present in its identity map. Both `add_version` and
`archive` execute the statement before inspecting identity state. Under that
parent-row lock, `add_version` rejects an archived identity, queries
`coalesce(max(version), 0)`, compares it with `expected_version`, and requires
`version.version == expected_version + 1`; `archive` returns the original row
unchanged when it is already archived. This serializes append versus archive
and prevents concurrent archives from replacing the first timestamp/actor on
PostgreSQL. Identity creation and version append also catch race-time
unique-constraint `IntegrityError` from `flush()` and raise
`RepositoryConflictError` while preserving the original exception as the
cause. `version_as_of` calls Task 2's pure selector over `list_versions`.

- [ ] **Step 6: Run focused repository tests and static checks**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\unit\test_thesis_repository_sql.py tests\integration\test_thesis_repository.py -q
.\.venv314\Scripts\python.exe -m ruff format src\quant_raas\domain\protocols.py src\quant_raas\storage\repositories.py tests\unit\test_thesis_repository_sql.py tests\integration\test_thesis_repository.py
.\.venv314\Scripts\python.exe -m ruff check src\quant_raas\domain\protocols.py src\quant_raas\storage\repositories.py tests\unit\test_thesis_repository_sql.py tests\integration\test_thesis_repository.py
.\.venv314\Scripts\python.exe -m mypy src\quant_raas\domain\protocols.py src\quant_raas\storage\repositories.py
```

Expected: repository tests pass with real SQLite foreign keys; Ruff and mypy are clean.

- [ ] **Step 7: Commit the thesis repository**

```powershell
git add src/quant_raas/domain/protocols.py src/quant_raas/storage/repositories.py tests/unit/test_thesis_repository_sql.py tests/integration/test_thesis_repository.py
git commit -m "feat: persist versioned theses"
```

### Task 5: Thesis application service and runtime composition

**Files:**
- Create: `src/quant_raas/services/theses.py`
- Modify: `src/quant_raas/common/errors.py:1-40`
- Modify: `src/quant_raas/runtime.py:1-52`
- Create: `tests/integration/test_thesis_service.py`

**Interfaces:**
- Consumes: `SecurityRepository`, Task 4's `ThesisRepository`, and Task 2's relevance config.
- Produces: `ThesisService`, `ThesisDetail`, typed thesis errors, `repositories_for(session).theses`, and `thesis_relevance_evaluator(settings)`.

- [ ] **Step 1: Write failing authoring and concurrency tests**

Create `tests/integration/test_thesis_service.py` around a fixed clock. Test creation, append, read, list, reference validation, and archive:

```python
service = ThesisService(securities, theses, clock=lambda: fixed_now)
created = service.create(
    thesis_key="example_core",
    security_id=sample_security.security_id,
    title="Example core thesis",
    content=thesis_content,
    created_by="analyst@example.com",
    authored_by="analyst@example.com",
    approved_by="pm@example.com",
    valid_from=fixed_now - timedelta(days=1),
)
assert created.thesis.created_at == fixed_now
assert created.version.created_at == created.version.approved_at == fixed_now
assert created.version.version == 1

updated = service.append_version(
    "example_core",
    content=thesis_content.model_copy(update={"summary": "Updated summary."}),
    authored_by="analyst@example.com",
    approved_by="pm@example.com",
    expected_version=1,
    valid_from=fixed_now + timedelta(days=1),
)
assert updated.version == 2
```

Assert duplicate key, missing security, stale expected version, non-monotonic
activation, append-after-archive, unknown key, and wrong-security reference all
fail with the correct typed application error. Verify the mutation signatures
expose neither `created_at` nor `approved_at`, and verify old version JSON
remains byte-for-byte unchanged after append.

- [ ] **Step 2: Run the service tests to verify the missing boundary**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\integration\test_thesis_service.py -q
```

Expected: collection fails because `quant_raas.services.theses` does not exist.

- [ ] **Step 3: Define typed errors and service result**

Add `ThesisNotFoundError`, `ThesisConflictError`, and `ThesisReferenceError` under `QuantRaasError`. In `services/theses.py`, add:

```python
@dataclass(frozen=True, slots=True)
class ThesisDetail:
    thesis: Thesis
    selection: ThesisVersionSelection


@dataclass(frozen=True, slots=True)
class CreatedThesis:
    thesis: Thesis
    version: ThesisVersion
```

`ThesisService.__init__` accepts `SecurityRepository`, `ThesisRepository`, and `clock: Callable[[], datetime] = utc_now`.

- [ ] **Step 4: Implement create, append, read, reference, and archive**

Use these public methods:

```python
def create(
    self,
    *,
    thesis_key: str,
    security_id: UUID,
    title: str,
    content: ThesisContent,
    created_by: str,
    authored_by: str,
    approved_by: str,
    valid_from: datetime | None = None,
) -> CreatedThesis: ...

def append_version(
    self,
    thesis_key: str,
    *,
    content: ThesisContent,
    authored_by: str,
    approved_by: str,
    expected_version: int,
    valid_from: datetime | None = None,
) -> ThesisVersion: ...

def detail(
    self,
    thesis_key: str,
    *,
    effective_at: datetime,
    knowledge_time: datetime,
) -> ThesisDetail: ...

def list_for_security(self, security_id: UUID, *, include_archived: bool = False) -> tuple[Thesis, ...]: ...
def history(self, thesis_key: str) -> tuple[ThesisVersion, ...]: ...
def require_reference(self, thesis_key: str, security_id: UUID) -> Thesis: ...
def archive(self, thesis_key: str, *, archived_by: str) -> Thesis: ...
```

Create identity and version 1 through the repository in one caller transaction. Use one `now = ensure_utc(self.clock())` per mutation. Translate `RepositoryConflictError` into `ThesisConflictError`. `append_version` obtains history, checks the last `valid_from`, and passes the current version to `add_version(expected_version=...)`.

- [ ] **Step 5: Compose repository and evaluator factories**

Add `theses: SqlAlchemyThesisRepository` to `runtime.Repositories` and instantiate it in `repositories_for`. Add:

```python
def thesis_relevance_evaluator(settings: Settings) -> ThesisRelevanceEvaluator:
    path = settings.config_directory / "thesis" / "relevance.yaml"
    return ThesisRelevanceEvaluator(ThesisRelevanceConfig.from_yaml(path))
```

- [ ] **Step 6: Run focused tests and quality checks**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\integration\test_thesis_service.py -q
.\.venv314\Scripts\python.exe -m ruff format src\quant_raas\services\theses.py src\quant_raas\common\errors.py src\quant_raas\runtime.py tests\integration\test_thesis_service.py
.\.venv314\Scripts\python.exe -m ruff check src\quant_raas\services\theses.py src\quant_raas\common\errors.py src\quant_raas\runtime.py tests\integration\test_thesis_service.py
.\.venv314\Scripts\python.exe -m mypy src\quant_raas\services\theses.py src\quant_raas\common\errors.py src\quant_raas\runtime.py
```

Expected: service tests pass and runtime composition is type-safe.

- [ ] **Step 7: Commit the application service**

```powershell
git add src/quant_raas/services/theses.py src/quant_raas/common/errors.py src/quant_raas/runtime.py tests/integration/test_thesis_service.py
git commit -m "feat: add thesis lifecycle service"
```

### Task 6: Thesis REST API

**Files:**
- Modify: `apps/api/schemas.py:1-75`
- Modify: `apps/api/routes.py:1-211`
- Create: `tests/integration/test_thesis_api.py`

**Interfaces:**
- Consumes: Task 1 content contracts and Task 5 `ThesisService`/typed errors.
- Produces: create, list, point-in-time detail, history, append, and archive HTTP endpoints for the dashboard and external clients.

- [ ] **Step 1: Write failing end-to-end API tests**

Create `tests/integration/test_thesis_api.py` with an isolated TestClient. Register a security through the existing endpoint, then create a thesis:

```python
create = client.post(
    "/v1/theses",
    json={
        "thesis_key": "example_core",
        "security_id": str(security_id),
        "title": "Example core thesis",
        "content": {
            "summary": "Relative strength supports the case.",
            "drivers": [
                {
                    "node_id": "relative_strength",
                    "statement": "Relative performance remains resilient.",
                    "supporting_features": ["relative_return_sector_63d"],
                    "direction": "positive",
                }
            ],
        },
        "created_by": "analyst@example.com",
        "authored_by": "analyst@example.com",
        "approved_by": "pm@example.com",
        "valid_from": "2024-01-09T21:00:00Z",
    },
)
assert create.status_code == 201
assert create.json()["thesis"]["thesis_key"] == "example_core"
assert create.json()["version"]["version"] == 1
```

Assert list filtering, detail with explicit `effective_at`/`knowledge_time`,
null selected version plus `not_yet_effective`, ordered history, successful
append, `409` stale append, `404` unknown key, `409` duplicate key, archive,
archive idempotency, and `409` append-after-archive. Payloads that add
client-owned `created_at` or `approved_at` return `422` because request schemas
forbid unknown fields. Naive `valid_from`, `effective_at`, or `knowledge_time`,
malformed invalidation thresholds, and a nonexistent security create reference
also return `422`, never `500`. Use `client.request("DELETE", ...,
json={"archived_by": ...})` for archive.

- [ ] **Step 2: Run the API tests to verify routes are absent**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\integration\test_thesis_api.py -q
```

Expected: the first request returns `404 Not Found`.

- [ ] **Step 3: Add strict request schemas**

In `apps/api/schemas.py`, reuse `ThesisContent` as the nested domain boundary and add:

```python
class ThesisCreateRequest(ApiModel):
    thesis_key: str
    security_id: UUID
    title: str = Field(min_length=1, max_length=300)
    content: ThesisContent
    created_by: str = Field(min_length=1, max_length=160)
    authored_by: str = Field(min_length=1, max_length=160)
    approved_by: str = Field(min_length=1, max_length=160)
    valid_from: UtcDatetime | None = None


class ThesisVersionRequest(ApiModel):
    content: ThesisContent
    authored_by: str = Field(min_length=1, max_length=160)
    approved_by: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)
    valid_from: UtcDatetime | None = None


class ThesisArchiveRequest(ApiModel):
    archived_by: str = Field(min_length=1, max_length=160)
```

Import `UtcDatetime` from `quant_raas.common.clock`. The domain layer performs
public-key validation; request schemas normalize aware timestamps to UTC,
reject naive timestamps during FastAPI/Pydantic validation, and forbid unknown
fields. Define thesis read query parameters as
`Annotated[UtcDatetime | None, Query()]` rather than the existing plain
`datetime` alias so invalid cutoffs also fail with `422` before service entry.

- [ ] **Step 4: Add service composition and typed error translation**

In `apps/api/routes.py`, add `_thesis_service(session)` using `repositories_for(session)`. Add one helper:

```python
def _raise_thesis_http(error: QuantRaasError) -> NoReturn:
    if isinstance(error, ThesisNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    if isinstance(error, ThesisConflictError):
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    if isinstance(error, ThesisReferenceError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    raise error
```

Use explicit `try/except QuantRaasError` around every mutation/read requiring translation.

- [ ] **Step 5: Implement all six routes and response envelopes**

Create responses with `jsonable_encoder`. The point-in-time detail response is exactly:

```python
{
    "thesis": detail.thesis,
    "selected_version": detail.selection.version,
    "selection_status": detail.selection.status,
    "effective_at": detail.selection.effective_at,
    "knowledge_time": detail.selection.knowledge_time,
    "max_available_at": (
        detail.selection.version.approved_at if detail.selection.version else None
    ),
    "attribution_authenticated": False,
}
```

The history response includes `thesis`, ordered `versions`, and the maximum `approved_at`. The list response includes `items` and a server `data_cutoff_at`. Compute default effective/knowledge timestamps once per request so they cannot differ by microseconds.

Every thesis response envelope also includes
`"attribution_authenticated": false`; the supplied attribution strings are
audit labels until authentication is implemented. `security_id` is required
on the list route.

- [ ] **Step 6: Run API tests and quality checks**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\integration\test_thesis_api.py tests\integration\test_api_smoke.py -q
.\.venv314\Scripts\python.exe -m ruff format apps\api tests\integration\test_thesis_api.py
.\.venv314\Scripts\python.exe -m ruff check apps\api tests\integration\test_thesis_api.py
.\.venv314\Scripts\python.exe -m mypy src\quant_raas
```

Expected: all thesis and existing smoke endpoints pass; strict package typing remains clean.

- [ ] **Step 7: Commit the API**

```powershell
git add apps/api/schemas.py apps/api/routes.py tests/integration/test_thesis_api.py
git commit -m "feat: expose thesis lifecycle API"
```

### Task 7: Validate CSV thesis references and seed explicit demo theses

**Files:**
- Modify: `src/quant_raas/security_master/service.py:1-280`
- Modify: `apps/api/routes.py:36-44`
- Modify: `apps/dashboard/app.py:125-177`
- Modify: `src/quant_raas/demo.py:106-230`
- Create: `configs/thesis/demo.yaml`
- Modify: `tests/integration/test_security_master.py:1-235`
- Create: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Consumes: Task 4 repository and Task 5 service.
- Produces: atomic import validation and resolvable `asml_core`, `aapl_services`, and `msft_cloud` demo references.

- [ ] **Step 1: Write failing import-reference tests**

Extend `tests/integration/test_security_master.py`. Build `SqlAlchemyThesisRepository`, create an approved thesis for `sample_security`, and inject the repository into `SecurityMasterService`. Assert a matching `thesis_id="example_core"` persists, while these rows produce `ResolutionIssue` and no snapshot/list records:

```python
unknown = HoldingUploadRow(identifier="EXAMPLE US", weight="0.04", thesis_id="missing_core")
wrong_security = CoverageUploadRow(
    identifier="EXAMPLE US",
    thesis_id="other_security_core",
)
```

Assert the issue text distinguishes unknown key from wrong-security ownership
and that a blank reference still imports normally. Add cutoff cases proving a
thesis created after `as_of` is rejected, one archived at or before `as_of` is
rejected, and a historical import before a later archive remains valid.

- [ ] **Step 2: Write a failing demo seed test**

Create `tests/integration/test_demo_seed.py` with a temporary SQLite URL and
fixed `now`. Call `seed_demo`, then query
`ThesisRecord`/`ThesisVersionRecord` and assert three active keys, three
version-1 rows, and successful resolution of every non-blank key in the
bundled coverage and holdings files. Task 9 later extends this same test with
card-lineage assertions.

- [ ] **Step 3: Run focused tests to verify references are not enforced**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\integration\test_security_master.py tests\integration\test_demo_seed.py -q
```

Expected: import tests show unknown keys being persisted and the demo test finds no theses.

- [ ] **Step 4: Inject and enforce the thesis repository in imports**

Extend the service constructor:

```python
def __init__(
    self,
    security_repository: SecurityRepository,
    portfolio_repository: PortfolioRepository,
    thesis_repository: ThesisRepository | None = None,
    *,
    default_benchmark_identifier: str | None = None,
    sector_benchmark_identifiers: Mapping[str, str] | None = None,
) -> None:
    self.theses = thesis_repository
```

After resolving each security and before appending it to `resolved`, call:

```python
def _validate_thesis_reference(
    self,
    thesis_key: str | None,
    security: Security,
    *,
    as_of: datetime,
) -> None:
    if thesis_key is None:
        return
    if self.theses is None:
        raise DomainValidationError("thesis reference validation is unavailable")
    thesis = self.theses.get_by_key(thesis_key)
    if thesis is None:
        raise DomainValidationError(f"unknown thesis key {thesis_key!r}")
    if thesis.security_id != security.security_id:
        raise DomainValidationError(
            f"thesis key {thesis_key!r} belongs to another security"
        )
    if thesis.created_at > as_of:
        raise DomainValidationError(
            f"thesis key {thesis_key!r} was not known at the import cutoff"
        )
    if thesis.archived_at is not None and thesis.archived_at <= as_of:
        raise DomainValidationError(
            f"thesis key {thesis_key!r} was archived at the import cutoff"
        )
```

Call it from both holdings and coverage loops with their normalized `at`
cutoff. This deliberately uses `created_at`/`archived_at`, not mutable current
status, so a historical import before a later archive remains valid. Pass
`repos.theses` from API, dashboard, and demo composition sites.

- [ ] **Step 5: Add explicit demo thesis fixtures**

Create `configs/thesis/demo.yaml` with three entries keyed to the UUIDs in `configs/universes/demo.csv`. Each entry contains a title, summary, one price-feature-linked driver or risk, `authored_by: demo@local`, and `approved_by: demo@local`. For example:

```yaml
schema_version: 1
theses:
  - thesis_key: aapl_services
    security_id: 11111111-1111-4111-8111-111111111111
    title: Apple services durability
    content:
      summary: Services resilience supports the long-term research case.
      drivers:
        - node_id: relative_strength
          statement: Sustained relative strength supports the case.
          supporting_features: [relative_return_sector_63d]
          direction: positive
      risks:
        - node_id: abnormal_distribution
          statement: Abnormal selling volume may indicate weakening sponsorship.
          watch_features: [dollar_volume_zscore_20d]
          severity: medium
```

Include analogous `msft_cloud` and `asml_core` entries. In `seed_demo`, define
`demo_context_at = current - timedelta(days=7)`, load the YAML after security
registration and before coverage/holdings imports, and validate each content
block with `ThesisContent.model_validate`. Build `ThesisService` with
`clock=lambda: demo_context_at` and call `create` with
`created_by=item["authored_by"]` and `valid_from=demo_context_at`. Use that
same `demo_context_at` for the bundled coverage and holdings imports. The
injected demo clock remains server-owned and deterministic; the fixture is
explicit authored input, not generated or client-backdated thesis prose.

- [ ] **Step 6: Run import/demo tests and quality checks**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\integration\test_security_master.py tests\integration\test_demo_seed.py tests\unit\test_csv_imports.py -q
.\.venv314\Scripts\python.exe -m ruff format src\quant_raas\security_master\service.py src\quant_raas\demo.py apps\api\routes.py apps\dashboard\app.py tests\integration\test_security_master.py tests\integration\test_demo_seed.py
.\.venv314\Scripts\python.exe -m ruff check src\quant_raas\security_master\service.py src\quant_raas\demo.py apps\api\routes.py apps\dashboard\app.py tests\integration\test_security_master.py tests\integration\test_demo_seed.py
.\.venv314\Scripts\python.exe -m mypy src\quant_raas
```

Expected: invalid references fail atomically, blank references remain valid, and demo keys resolve.

- [ ] **Step 7: Commit import validation and fixtures**

```powershell
git add src/quant_raas/security_master/service.py src/quant_raas/demo.py apps/api/routes.py apps/dashboard/app.py configs/thesis/demo.yaml tests/integration/test_security_master.py tests/integration/test_demo_seed.py
git commit -m "feat: validate thesis context imports"
```

### Task 8: Persist thesis-aware findings and cards

**Files:**
- Modify: `src/quant_raas/domain/research.py:119-192`
- Modify: `src/quant_raas/research/findings.py:1-160`
- Modify: `src/quant_raas/research/cards.py:1-160`
- Modify: `src/quant_raas/storage/repositories.py:950-1230`
- Modify: `tests/unit/test_materiality_and_cards.py:1-165`
- Modify: `tests/integration/test_storage_roundtrip.py:205-280`
- Modify: `tests/integration/test_thesis_repository.py`

**Interfaces:**
- Consumes: Task 1 assessment contracts and Task 3 lineage columns.
- Produces: `price_signal_strengths`, thesis-aware `build_price_finding`, derived card lineage, and storage round trips for Task 9.

- [ ] **Step 1: Write failing finding/card lineage tests**

In `tests/unit/test_materiality_and_cards.py`, first build the same finding
without an assessment as `baseline`, then build it with one assessment scored
at `0.75`. Assert:

```python
assert finding.score.component_scores["thesis_relevance"] == pytest.approx(0.75)
assert finding.thesis_version_id == assessment.thesis_version_id
assert finding.thesis_relevance == assessment
assert finding.score.raw_score == pytest.approx(
    baseline.score.raw_score + 0.15 * assessment.score
)
assert finding.score.completeness == pytest.approx(
    baseline.score.completeness + 0.15
)
```

Build the card without manually supplying thesis arguments and assert exact
version ID, `HIGH` impact, primary node, sorted matched `thesis_node_ids`, and
rendered version/node text. Add tests proving:

- no assessment leaves `thesis_relevance` absent and completeness unchanged;
- an assessment with score `0.0` includes the component and adds exactly `0.15` completeness;
- mixed thesis-version findings fail closed; and
- primary assessment ties break by node ID.

Extend `test_storage_roundtrip.py` to round-trip every new field. Move the restrictive thesis-version deletion assertion into `test_thesis_repository.py` here, after it can create a finding/card with populated lineage.

- [ ] **Step 2: Run focused tests to verify missing output fields**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\unit\test_materiality_and_cards.py tests\integration\test_storage_roundtrip.py tests\integration\test_thesis_repository.py -q
```

Expected: failures show the missing assessment input, lineage fields, and
persistence mappings.

- [ ] **Step 3: Extend finding/card contracts and validation**

Add to `ResearchFinding`:

```python
thesis_version_id: UUID | None = None
thesis_relevance: ThesisRelevanceAssessment | None = None
```

Add to `ResearchCard`:

```python
thesis_version_id: UUID | None = None
thesis_node_ids: tuple[str, ...] = ()
```

Finding validation requires assessment/version equality and forbids a version
ID without an assessment. Card validation requires primary-node membership
when a primary exists, no node IDs without a version, sorted unique
`thesis_node_ids`, and a version/primary for every non-`NONE` impact. A
version with `NONE`, no primary, and no node IDs remains valid for an explicit
zero-overlap assessment.

- [ ] **Step 4: Share price strength calculation and score the finding**

Expose:

```python
def price_signal_strengths(snapshot: PriceResearchSnapshot) -> dict[str, float]:
    values = {
        "residual_return_zscore_1d": _bounded_anomaly(snapshot.residual_zscore),
        "dollar_volume_zscore_20d": _bounded_anomaly(snapshot.volume_zscore),
        "relative_return_sector_63d": (
            min(abs(snapshot.relative_return_sector_63d) / 0.20, 1.0)
            if snapshot.relative_return_sector_63d is not None
            else None
        ),
    }
    return {name: value for name, value in values.items() if value is not None}
```

Change the builder signature to:

```python
def build_price_finding(
    snapshot: PriceResearchSnapshot,
    *,
    research_run_id: UUID,
    scorer: MaterialityScorer,
    position_weight: float | None = None,
    thesis_assessment: ThesisRelevanceAssessment | None = None,
) -> ResearchFinding:
```

Reuse the strengths for abnormal/factor components, pass
`thesis_assessment.score if thesis_assessment else None` as
`thesis_relevance`, and copy assessment/version fields to the finding.

- [ ] **Step 5: Derive card lineage from findings**

Remove manual `thesis_impact`/`thesis_node_id` inputs from the builder. Collect
non-null assessments, reject more than one version ID, and select
`sorted(assessments, key=lambda item: (-item.score, item.primary_node_id is None,
item.primary_node_id or ""))[0]`. Set the sorted union of node IDs whose
contributions have non-empty `matched_feature_names` across every assessment;
this retains safe-side invalidation matches scored at zero while leaving true
no-overlap assessments empty.
Render:

```python
lineage_parts = []
if card.thesis_version_id is not None:
    lineage_parts.append(f"version {str(card.thesis_version_id)[:8]}")
if card.thesis_node_id is not None:
    lineage_parts.append(f"node {card.thesis_node_id}")
lineage_text = f" ({', '.join(lineage_parts)})" if lineage_parts else ""
```

Keep `ThesisImpact.NONE` and no version/node values on no-thesis cards.
Rendering describes deterministic relevance and lineage only; it must not say
the score proves or disproves the investment case.

Add a rendering assertion that an explicit zero-overlap assessment shows its
short version ID with no node, while a true no-thesis card shows neither. This
keeps the two completeness states visibly distinct.

- [ ] **Step 6: Persist and hydrate all new fields**

In `SqlAlchemyResearchRepository`, write `thesis_version_id`,
`thesis_relevance.model_dump(mode="json")`, and `thesis_node_ids`; hydrate them
in `_finding_from_record` and `_card_from_record`. Keep legacy null/empty
records valid.

- [ ] **Step 7: Run focused tests and static checks**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\unit\test_materiality_and_cards.py tests\integration\test_storage_roundtrip.py tests\integration\test_thesis_repository.py -q
.\.venv314\Scripts\python.exe -m ruff format src\quant_raas\domain\research.py src\quant_raas\research\findings.py src\quant_raas\research\cards.py src\quant_raas\storage\repositories.py tests\unit\test_materiality_and_cards.py tests\integration\test_storage_roundtrip.py tests\integration\test_thesis_repository.py
.\.venv314\Scripts\python.exe -m ruff check src\quant_raas\domain\research.py src\quant_raas\research\findings.py src\quant_raas\research\cards.py src\quant_raas\storage\repositories.py tests\unit\test_materiality_and_cards.py tests\integration\test_storage_roundtrip.py tests\integration\test_thesis_repository.py
.\.venv314\Scripts\python.exe -m mypy src\quant_raas
```

Expected: scoring, lineage, rendering, round trips, and restrictive FK behavior pass.

- [ ] **Step 8: Commit thesis-aware research outputs**

```powershell
git add src/quant_raas/domain/research.py src/quant_raas/research/findings.py src/quant_raas/research/cards.py src/quant_raas/storage/repositories.py tests/unit/test_materiality_and_cards.py tests/integration/test_storage_roundtrip.py tests/integration/test_thesis_repository.py
git commit -m "feat: attach thesis lineage to research outputs"
```

### Task 9: Integrate thesis relevance into daily research

**Files:**
- Modify: `src/quant_raas/services/daily_research.py:1-430`
- Modify: `src/quant_raas/services/close_workflow.py:1-100`
- Modify: `apps/api/routes.py:155-179`
- Modify: `src/quant_raas/demo.py:207-226`
- Modify: `tests/integration/test_daily_research_pipeline.py:1-145`
- Modify: `tests/integration/test_demo_seed.py`

**Interfaces:**
- Consumes: `ThesisRepository`, `ThesisRelevanceEvaluator`, Task 8 signal strengths/output contracts.
- Produces: cutoff-pinned thesis assessments and materiality/card lineage in normal daily runs.

- [ ] **Step 1: Write failing end-to-end pipeline tests**

Extend `test_daily_research_pipeline.py` with a helper that persists a thesis and attaches its public key to the coverage member. Use a risk watching `dollar_volume_zscore_20d`. Assert:

```python
assessment = first.findings[0].thesis_relevance
assert assessment is not None
assert assessment.thesis_version_id == thesis_version.thesis_version_id
assert first.findings[0].score.component_scores["thesis_relevance"] == pytest.approx(
    assessment.score
)
assert first.cards[0].thesis_version_id == thesis_version.thesis_version_id
assert first.cards[0].thesis_impact == assessment.impact
```

Add these integration cases:

- coverage without a thesis retains an absent component;
- a selected thesis with no overlap stores explicit zero and gains 0.15 completeness;
- a version approved after `data_cutoff_at` is excluded;
- unknown, cross-security, archived, not-yet-approved, and not-effective
  explicit references become per-security failures while another valid
  security succeeds; and
- identical reruns retain finding/card IDs and identical assessment JSON.

- [ ] **Step 2: Run the pipeline tests to verify thesis inputs are ignored**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\integration\test_daily_research_pipeline.py tests\integration\test_demo_seed.py -q
```

Expected: thesis assertions fail because `DailyResearchService` neither selects nor evaluates a thesis.

- [ ] **Step 3: Inject thesis dependencies and preserve partial failure isolation**

Extend the constructor with required keyword-only parameters:

```python
theses: ThesisRepository,
thesis_relevance: ThesisRelevanceEvaluator,
```

Store them as `self.thesis_repository` and `self.thesis_relevance`. Update API,
demo, and `run_close_workflow` construction with `repos.theses` and
`thesis_relevance_evaluator(settings)`; the close workflow is the installable
scheduler/CLI path and must not retain the old constructor. Update all tests
that build `DailyResearchService`.

Extend `_run_key` with a required
`thesis_method_version=self.thesis_relevance.config.method_version` input so a
method/configuration change cannot reuse finding, feature, or card IDs from a
different assessment method. Add a regression assertion proving equal inputs
and method versions keep the same run ID while a changed method version changes
it. Build a bounded aggregate label once with
`run_config_version = "bundle:" + hashlib.sha256(f"{request.feature_config_version}|{thesis_method_version}".encode()).hexdigest()`
and store it on `ResearchRun.config_version`; this remains below the existing
80-character storage contract even when both source labels are long. Keep the
plain feature configuration on each `FeatureSnapshot.config_version`, while
the assessment stores the exact thesis method version. The changed-method
regression must assert distinct immutable run, finding, and card IDs rather
than overwriting prior output rows.

- [ ] **Step 4: Select and assess during each security calculation**

Keep `_SecurityCalculation` focused on calculated market data. Change the
pending list to
`list[tuple[CoverageMember, _SecurityCalculation, ThesisRelevanceAssessment | None]]`.
After feature snapshots exist, call a focused helper and append the member,
calculation, and assessment together:

```python
calculation = self._calculate_security(
    member,
    bars_by_security=by_security,
    benchmarks=benchmark_map[member.security_id],
    research_run_id=run_id,
    calculated_at=started_at,
    code_version=request.code_version,
    config_version=request.feature_config_version,
)
assessment = self._assess_thesis(
    member,
    calculation,
    effective_at=as_of,
    knowledge_time=cutoff,
)
calculations.append((member, calculation, assessment))
```

The helper is:

```python
def _assess_thesis(
    self,
    member: CoverageMember,
    calculation: _SecurityCalculation,
    *,
    effective_at: datetime,
    knowledge_time: datetime,
) -> ThesisRelevanceAssessment | None:
    if member.thesis_id is None:
        return None
    thesis = self.thesis_repository.get_by_key(member.thesis_id)
    if thesis is None or thesis.security_id != member.security_id:
        raise ValueError(f"invalid thesis reference {member.thesis_id!r}")
    selection = self.thesis_repository.version_as_of(
        thesis,
        effective_at=effective_at,
        knowledge_time=knowledge_time,
    )
    if selection.version is None:
        raise ValueError(
            f"thesis {member.thesis_id!r} is {selection.status.value} at cutoff"
        )
    strengths = price_signal_strengths(calculation.snapshot)
    by_name = {feature.feature_name: feature for feature in calculation.features}
    signals = tuple(
        ThesisSignal(
            feature_name=name,
            raw_value=float(by_name[name].value),
            normalized_strength=strength,
            feature_snapshot_id=by_name[name].feature_snapshot_id,
            unit=by_name[name].unit,
        )
        for name, strength in sorted(strengths.items())
        if name in by_name
        and isinstance(by_name[name].value, (int, float))
        and not isinstance(by_name[name].value, bool)
        and isfinite(float(by_name[name].value))
    )
    return self.thesis_relevance.assess(
        selection.version,
        signals=signals,
        features=calculation.features,
    )
```

Import `isfinite` from `math`. Call the helper inside the existing per-security
`try` block and catch thesis `QuantRaasError`/`ValueError` as a
`SecurityResearchFailure`. Pass the resulting assessment to
`build_price_finding`; let the card builder derive lineage.

- [ ] **Step 5: Run pipeline, API, and demo regression tests**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\integration\test_daily_research_pipeline.py tests\integration\test_demo_seed.py tests\integration\test_api_smoke.py tests\integration\test_thesis_api.py -q
.\.venv314\Scripts\python.exe -m ruff format src\quant_raas\services\daily_research.py src\quant_raas\services\close_workflow.py apps\api\routes.py src\quant_raas\demo.py tests\integration\test_daily_research_pipeline.py tests\integration\test_demo_seed.py
.\.venv314\Scripts\python.exe -m ruff check src\quant_raas\services\daily_research.py src\quant_raas\services\close_workflow.py apps\api\routes.py src\quant_raas\demo.py tests\integration\test_daily_research_pipeline.py tests\integration\test_demo_seed.py
.\.venv314\Scripts\python.exe -m mypy src\quant_raas
```

Expected: thesis and no-thesis pipeline paths pass, future versions stay excluded, and API/demo composition remains healthy.

- [ ] **Step 6: Commit daily research integration**

```powershell
git add src/quant_raas/services/daily_research.py src/quant_raas/services/close_workflow.py apps/api/routes.py src/quant_raas/demo.py tests/integration/test_daily_research_pipeline.py tests/integration/test_demo_seed.py
git commit -m "feat: rank daily findings by thesis relevance"
```

### Task 10: Company-page thesis authoring and history panel

**Files:**
- Create: `apps/dashboard/thesis_panel.py`
- Modify: `apps/dashboard/app.py:108-155`
- Create: `tests/unit/test_thesis_dashboard_forms.py`
- Create: `tests/integration/test_thesis_dashboard_service.py`

**Interfaces:**
- Consumes: Task 1 `ThesisContent`, Task 5 `ThesisService`, and runtime repositories.
- Produces: pure editor-row conversion plus a Streamlit company-page create/version/archive workflow.

- [ ] **Step 1: Write failing editor conversion tests**

Create `tests/unit/test_thesis_dashboard_forms.py`:

```python
from apps.dashboard.thesis_panel import content_from_editor_rows, editor_rows_from_content


def test_editor_rows_roundtrip_typed_thesis_content(thesis_content) -> None:
    rows = editor_rows_from_content(thesis_content)
    rebuilt = content_from_editor_rows(
        summary=thesis_content.summary,
        driver_rows=rows.drivers,
        risk_rows=rows.risks,
        invalidation_rows=rows.invalidation_rules,
    )
    assert rebuilt == thesis_content


def test_editor_parser_splits_features_and_rejects_invalid_thresholds() -> None:
    content = content_from_editor_rows(
        summary="A typed summary.",
        driver_rows=[
            {
                "node_id": "relative_strength",
                "statement": "Relative strength persists.",
                "supporting_features": "relative_return_sector_63d, beta_126d",
                "direction": "positive",
            }
        ],
        risk_rows=[],
        invalidation_rows=[],
    )
    assert content.drivers[0].supporting_features == (
        "relative_return_sector_63d",
        "beta_126d",
    )
```

Add a validation-error case with an invalid less-than threshold order and assert the Pydantic message is preserved for display.
Add `parse_utc_timestamp` cases proving an ISO-8601 value with `Z` or an
explicit offset is normalized to UTC and a naive value is rejected.

- [ ] **Step 2: Write a failing service-boundary dashboard test**

Create `tests/integration/test_thesis_dashboard_service.py`. Convert editor rows to content, pass it through a real `ThesisService`/SQLite repository, append edited rows with `expected_version=1`, and archive. Assert versions 1 and 2 remain readable and archive changes no content JSON.

- [ ] **Step 3: Run tests to verify the dashboard module is absent**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\unit\test_thesis_dashboard_forms.py tests\integration\test_thesis_dashboard_service.py -q
```

Expected: collection fails because `apps.dashboard.thesis_panel` does not exist.

- [ ] **Step 4: Implement pure editor conversion**

Create a focused module with:

```python
@dataclass(frozen=True, slots=True)
class ThesisEditorRows:
    drivers: list[dict[str, object]]
    risks: list[dict[str, object]]
    invalidation_rules: list[dict[str, object]]


def _features(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip().lower() for part in str(value).split(",") if part.strip())


def content_from_editor_rows(
    *,
    summary: str,
    driver_rows: Sequence[Mapping[str, object]],
    risk_rows: Sequence[Mapping[str, object]],
    invalidation_rows: Sequence[Mapping[str, object]],
) -> ThesisContent:
    return ThesisContent(
        summary=summary,
        drivers=tuple(
            ThesisDriver(
                node_id=str(row["node_id"]),
                statement=str(row["statement"]),
                supporting_features=_features(row.get("supporting_features")),
                direction=ThesisDirection(str(row["direction"])),
            )
            for row in driver_rows
            if str(row.get("node_id", "")).strip()
        ),
        risks=tuple(
            ThesisRisk(
                node_id=str(row["node_id"]),
                statement=str(row["statement"]),
                watch_features=_features(row.get("watch_features")),
                severity=ThesisRiskSeverity(str(row["severity"])),
            )
            for row in risk_rows
            if str(row.get("node_id", "")).strip()
        ),
        invalidation_rules=tuple(
            ThesisInvalidationRule(
                node_id=str(row["node_id"]),
                statement=str(row["statement"]),
                feature_name=str(row["feature_name"]),
                comparator=InvalidationComparator(str(row["comparator"])),
                warning_threshold=float(row["warning_threshold"]),
                breach_threshold=float(row["breach_threshold"]),
                unit=str(row["unit"]) if row.get("unit") else None,
            )
            for row in invalidation_rows
            if str(row.get("node_id", "")).strip()
        ),
    )
```

`editor_rows_from_content` performs the exact inverse and joins feature tuples
with `", "`.

- [ ] **Step 5: Implement the Streamlit panel**

Add `render_thesis_panel(session_factory, security_id)` in the same module. It must:

1. list active and archived identities for the selected security;
2. show identity, selected version, summary, nodes, approval/effective times, and ordered history;
3. render identity inputs (`thesis_key`, immutable title, and `created_by`) for
   creation plus `st.data_editor` tables for drivers, risks, and invalidation
   rules;
4. render `valid_from` as an ISO-8601 text field that requires `Z` or an
   explicit offset, parse it through the tested `parse_utc_timestamp` helper,
   require non-empty `authored_by` and `approved_by`, and require an explicit
   approval checkbox;
5. call `ThesisService.create` or `append_version` inside `factory.begin()`;
6. display typed validation/conflict errors without persisting partial state; and
7. require a separate archive confirmation before `service.archive`.

Use empty row templates with every expected column; do not place raw JSON/YAML in the editor. After a successful mutation, call `st.rerun()`.

- [ ] **Step 6: Compose the panel into the company tab**

In `apps/dashboard/app.py`, call:

```python
render_thesis_panel(_session_factory(), selected)
```

after the current daily snapshot. Keep cards usable when no thesis exists. Import the panel function at module scope and do not duplicate repository/service logic in `app.py`.

- [ ] **Step 7: Run UI-helper and regression checks**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests\unit\test_thesis_dashboard_forms.py tests\integration\test_thesis_dashboard_service.py tests\integration\test_api_smoke.py -q
.\.venv314\Scripts\python.exe -m ruff format apps\dashboard tests\unit\test_thesis_dashboard_forms.py tests\integration\test_thesis_dashboard_service.py
.\.venv314\Scripts\python.exe -m ruff check apps\dashboard tests\unit\test_thesis_dashboard_forms.py tests\integration\test_thesis_dashboard_service.py
.\.venv314\Scripts\python.exe -m mypy src\quant_raas
```

Expected: editor conversion and real service workflow pass; the dashboard imports cleanly; API smoke remains green.

- [ ] **Step 8: Commit the dashboard slice**

```powershell
git add apps/dashboard/thesis_panel.py apps/dashboard/app.py tests/unit/test_thesis_dashboard_forms.py tests/integration/test_thesis_dashboard_service.py
git commit -m "feat: add thesis authoring dashboard"
```

### Task 11: Documentation, full verification, and roadmap status

**Files:**
- Modify: `README.md:9-27`
- Modify: `docs/data_contracts.md:76-188`
- Modify: `docs/wireframes.md:25-91`
- Modify: `PLAN.md:35-58,1350-1406,1750-1760,1820-1865`

**Interfaces:**
- Consumes: every preceding task's final behavior and test output.
- Produces: honest capability documentation and one fully verified feature branch.

- [ ] **Step 1: Write documentation assertions before editing prose**

Run:

```powershell
rg -n "Thesis model \| \*\*BOUNDARY\*\*|research/thesis.py.*BOUNDARY|CRUD /v1/theses" PLAN.md
rg -n "thesis_key|invalidation_rules|not authenticated|append-only" README.md docs\data_contracts.md docs\wireframes.md
```

Expected: the first command finds stale boundary/planned text; the second lacks the complete implemented contract.

- [ ] **Step 2: Update the public data contract**

In `docs/data_contracts.md`, state explicitly:

- CSV `thesis_id` contains a lowercase public `thesis_key`, not the UUID;
- supplied keys must exist, be active, and belong to the resolved security;
- blank remains valid;
- content schema fields and exact feature-name semantics;
- `created_by`, `authored_by`, and `approved_by` are unauthenticated attribution until auth lands;
- updates append immutable versions and archive replaces delete; and
- effective/knowledge cutoffs determine historical selection.

- [ ] **Step 3: Update README and wireframe**

Add versioned thesis authoring and deterministic relevance to README's
implemented capabilities without claiming semantic/AI mapping. Extend the
company-page wireframe with active thesis summary, drivers, risks, invalidation
status, version history, and explicit approve/archive controls. State that
missing thesis never blocks research and that the new 0.15 input raises the
current price-only theoretical ceiling from 0.45 to 0.60, still below the 0.65
`material` threshold.

- [ ] **Step 4: Update only targeted PLAN status and route inventory**

Change the thesis status row and section 24 from `BOUNDARY` to `BUILT` for deterministic authoring/relevance. Keep AI semantic mapping and generated proposals planned. Update the API route inventory with the six exact routes, update the repository tree annotation, and record the exact deterministic test count observed in Step 7. Do not reorder roadmap phases or claim vendor-backed material cards.

- [ ] **Step 5: Run focused documentation and whitespace checks**

```powershell
rg -n "Thesis model \| \*\*BOUNDARY\*\*|research/thesis.py.*BOUNDARY" PLAN.md
rg -n "thesis_key|invalidation_rules|append-only|not authenticated" README.md docs\data_contracts.md docs\wireframes.md PLAN.md
git diff --check
```

Expected: stale boundary patterns return no matches, implemented terms appear in the intended files, and Git reports no whitespace errors.

- [ ] **Step 6: Run formatting, lint, and strict typing gates**

```powershell
.\.venv314\Scripts\python.exe -m ruff format --check .
.\.venv314\Scripts\python.exe -m ruff check .
.\.venv314\Scripts\python.exe -m mypy src\quant_raas
```

Expected: all three commands exit zero.

- [ ] **Step 7: Run the complete deterministic branch-coverage gate**

```powershell
.\.venv314\Scripts\python.exe -m pytest -m "not external" --cov=quant_raas --cov-branch --cov-report=term-missing --cov-report=xml --cov-fail-under=80
```

Expected: every deterministic test passes and branch coverage is at least 80%. Record the exact pass count and coverage percentage in the implementation handoff. Report the known Starlette/httpx TestClient deprecation warning separately if it remains; do not suppress it as application behavior.

- [ ] **Step 8: Verify the migration from an empty database and inspect the final diff**

Run Alembic against a new temporary SQLite database using a task-specific environment value, then inspect status:

```powershell
$env:QUANT_RAAS_DATABASE_URL = "sqlite+pysqlite:///./.tmp_thesis_migration.db"
.\.venv314\Scripts\python.exe -m alembic upgrade head
Remove-Item -LiteralPath .\.tmp_thesis_migration.db
Remove-Item Env:\QUANT_RAAS_DATABASE_URL
git status --short
git diff --check
git diff --stat
```

Expected: migration reaches head; only this milestone's implementation, tests, configuration, demo fixture, and targeted docs are changed; whitespace checks pass. The temporary database is removed after its exact path is verified inside the repository.

- [ ] **Step 9: Commit documentation and verification evidence**

```powershell
git add README.md docs/data_contracts.md docs/wireframes.md PLAN.md
git commit -m "docs: document thesis relevance workflow"
```

- [ ] **Step 10: Review the branch before integration**

Run:

```powershell
git log --oneline --decorate main..HEAD
git diff --check main...HEAD
git diff --stat main...HEAD
```

Expected: eleven coherent implementation commits follow the committed spec/plan, no whitespace errors exist, and the diff contains no vendor, LLM, authentication, tenancy, or unrelated roadmap work.
