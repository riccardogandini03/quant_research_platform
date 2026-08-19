# Point-in-Time Feature Panel and Screen Equivalence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a version-pinned, cross-sectional point-in-time feature query and make one-off and historical screen evaluation use the same execution path.

**Architecture:** Extend the typed feature repository with one batched as-of query that returns `FeatureSnapshot` objects, then convert those objects to the existing pandas screen contract in a focused feature-store adapter. A repository-backed screen service validates version pins and delegates both one-off and historical evaluation to the existing pure `run_screen` engine.

**Tech Stack:** Python 3.12–3.13, Pydantic 2, SQLAlchemy 2, pandas 2, pytest 8, Ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-08-19-feature-panel-screen-equivalence-design.md`

## Global Constraints

- Do not modify `PLAN.md`.
- Keep the supported runtime at `Python >=3.12,<3.14`; do not add dependencies.
- Do not add database tables, migrations, HTTP endpoints, or vendor integrations.
- Reject naive timestamps; all persisted and queried cutoffs remain timezone-aware UTC instants.
- Repository-backed screens must pin every referenced feature version and one configuration version.
- Preserve the pure DataFrame-based `run_screen` API and the existing `latest_as_of` repository method.
- Use `.venv314\Scripts\python.exe` for local verification because it is the only complete local environment; Python 3.12 CI remains authoritative.

---

### Task 1: Batched, version-pinned feature repository query

**Files:**
- Modify: `src/quant_raas/domain/protocols.py:5-142`
- Modify: `src/quant_raas/storage/repositories.py:7-18,739-835`
- Create: `tests/integration/test_feature_panel_repository.py`

**Interfaces:**
- Consumes: persisted `FeatureSnapshot` rows and `ensure_utc(datetime)`.
- Produces:

```python
def panel_as_of(
    self,
    security_ids: Sequence[UUID],
    feature_versions: Mapping[str, str],
    *,
    config_version: str,
    as_of: datetime,
) -> Sequence[FeatureSnapshot]: ...
```

- [ ] **Step 1: Write integration fixtures and a failing batched-retrieval test**

Create `tests/integration/test_feature_panel_repository.py` with a focused snapshot factory and a test containing two securities, an older eligible value, a newer eligible value, a future correction, a competing feature version, and a competing configuration version:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from quant_raas.common.errors import RepositoryConflictError
from quant_raas.domain.market import FeatureSnapshot
from quant_raas.domain.research import ResearchRun
from quant_raas.domain.security import Security
from quant_raas.storage.repositories import (
    SqlAlchemyFeatureRepository,
    SqlAlchemyResearchRepository,
    SqlAlchemySecurityRepository,
)

pytestmark = [pytest.mark.integration, pytest.mark.point_in_time]


def _snapshot(
    identifier: int,
    *,
    security_id: UUID,
    research_run_id: UUID,
    feature_name: str = "signal",
    feature_version: str = "v1",
    config_version: str = "panel-v1",
    effective_at: datetime,
    available_at: datetime,
    calculated_at: datetime | None = None,
    value: float,
    code_version: str = "code-v1",
) -> FeatureSnapshot:
    return FeatureSnapshot(
        feature_snapshot_id=UUID(int=identifier),
        security_id=security_id,
        feature_name=feature_name,
        feature_version=feature_version,
        effective_at=effective_at,
        available_at=available_at,
        calculated_at=calculated_at or available_at + timedelta(minutes=1),
        value=value,
        research_run_id=research_run_id,
        code_version=code_version,
        config_version=config_version,
    )


def test_panel_as_of_returns_latest_requested_vintage_for_each_security(
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    second_security = sample_security.model_copy(
        update={"security_id": UUID(int=2), "name": "Second Corp"}
    )
    securities = SqlAlchemySecurityRepository(sqlite_session)
    securities.add_security(sample_security)
    securities.add_security(second_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)

    effective_old = datetime(2024, 1, 8, 21, 0, tzinfo=UTC)
    effective_new = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available_old = effective_old + timedelta(minutes=5)
    available_new = effective_new + timedelta(minutes=5)
    cutoff = datetime(2024, 1, 9, 22, 0, tzinfo=UTC)
    future = datetime(2024, 1, 10, 9, 0, tzinfo=UTC)

    repository = SqlAlchemyFeatureRepository(sqlite_session)
    repository.upsert_many(
        [
            _snapshot(101, security_id=sample_security.security_id, research_run_id=research_run.research_run_id, effective_at=effective_old, available_at=available_old, value=1.0),
            _snapshot(102, security_id=sample_security.security_id, research_run_id=research_run.research_run_id, effective_at=effective_new, available_at=available_new, value=2.0),
            _snapshot(103, security_id=sample_security.security_id, research_run_id=research_run.research_run_id, effective_at=effective_new, available_at=future, value=99.0),
            _snapshot(104, security_id=sample_security.security_id, research_run_id=research_run.research_run_id, feature_version="v2", effective_at=effective_new, available_at=available_new, value=200.0),
            _snapshot(105, security_id=sample_security.security_id, research_run_id=research_run.research_run_id, config_version="panel-v2", effective_at=effective_new, available_at=available_new, value=300.0),
            _snapshot(106, security_id=second_security.security_id, research_run_id=research_run.research_run_id, effective_at=effective_new, available_at=available_new, value=-1.0),
        ]
    )

    panel = repository.panel_as_of(
        [second_security.security_id, sample_security.security_id],
        {"signal": "v1"},
        config_version="panel-v1",
        as_of=cutoff,
    )

    assert [(item.security_id, item.feature_name, item.value) for item in panel] == [
        (second_security.security_id, "signal", -1.0),
        (sample_security.security_id, "signal", 2.0),
    ]
```

Use `sorted(..., key=lambda item: str(item.security_id))` in the assertion setup if the fixed UUID fixture sorts before `UUID(int=2)`; the production contract itself must return `str(UUID)` order.

- [ ] **Step 2: Run the focused test and confirm the interface is missing**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/integration/test_feature_panel_repository.py::test_panel_as_of_returns_latest_requested_vintage_for_each_security -v
```

Expected: FAIL with `AttributeError: 'SqlAlchemyFeatureRepository' object has no attribute 'panel_as_of'`.

- [ ] **Step 3: Add failing validation, empty-input, and ambiguity tests**

Add these behaviors to the same file:

```python
def test_panel_as_of_validates_cutoff_and_version_pins(
    sqlite_session: Session,
) -> None:
    repository = SqlAlchemyFeatureRepository(sqlite_session)
    with pytest.raises(ValueError, match="explicit timezone"):
        repository.panel_as_of([], {}, config_version="panel-v1", as_of=datetime(2024, 1, 9))
    with pytest.raises(ValueError, match="config_version cannot be empty"):
        repository.panel_as_of([], {}, config_version=" ", as_of=datetime(2024, 1, 9, tzinfo=UTC))
    with pytest.raises(ValueError, match="feature names and versions cannot be empty"):
        repository.panel_as_of([], {"signal": " "}, config_version="panel-v1", as_of=datetime(2024, 1, 9, tzinfo=UTC))
    assert repository.panel_as_of(
        [], {"signal": "v1"}, config_version="panel-v1", as_of=datetime(2024, 1, 9, tzinfo=UTC)
    ) == ()


def test_panel_as_of_rejects_ambiguous_top_vintage(
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available = effective + timedelta(minutes=5)
    calculated = available + timedelta(minutes=1)
    repository = SqlAlchemyFeatureRepository(sqlite_session)
    repository.upsert_many(
        [
            _snapshot(201, security_id=sample_security.security_id, research_run_id=research_run.research_run_id, effective_at=effective, available_at=available, calculated_at=calculated, value=1.0, code_version="code-a"),
            _snapshot(202, security_id=sample_security.security_id, research_run_id=research_run.research_run_id, effective_at=effective, available_at=available, calculated_at=calculated, value=2.0, code_version="code-b"),
        ]
    )
    with pytest.raises(RepositoryConflictError, match="ambiguous latest feature vintage"):
        repository.panel_as_of(
            [sample_security.security_id],
            {"signal": "v1"},
            config_version="panel-v1",
            as_of=calculated,
        )
```

- [ ] **Step 4: Extend the protocol and implement the minimal batched query**

Import `Mapping` from `collections.abc` in both `domain/protocols.py` and
`storage/repositories.py`, add the exact interface above to `FeatureRepository`,
then implement it in `SqlAlchemyFeatureRepository`. Import `and_` from
SQLAlchemy and use one statement:

```python
def panel_as_of(
    self,
    security_ids: Sequence[UUID],
    feature_versions: Mapping[str, str],
    *,
    config_version: str,
    as_of: datetime,
) -> Sequence[FeatureSnapshot]:
    cutoff = ensure_utc(as_of)
    if not config_version.strip():
        raise ValueError("config_version cannot be empty")
    if any(not name.strip() or not version.strip() for name, version in feature_versions.items()):
        raise ValueError("feature names and versions cannot be empty")
    requested_ids = tuple(sorted(set(security_ids), key=str))
    requested_features = tuple(sorted(feature_versions.items()))
    if not requested_ids or not requested_features:
        return ()

    requested_pairs = tuple(
        and_(
            FeatureSnapshotRecord.feature_name == name,
            FeatureSnapshotRecord.feature_version == version,
        )
        for name, version in requested_features
    )
    statement = (
        select(FeatureSnapshotRecord)
        .where(
            FeatureSnapshotRecord.security_id.in_(requested_ids),
            or_(*requested_pairs),
            FeatureSnapshotRecord.config_version == config_version,
            FeatureSnapshotRecord.effective_at <= cutoff,
            FeatureSnapshotRecord.available_at <= cutoff,
        )
        .order_by(
            FeatureSnapshotRecord.security_id,
            FeatureSnapshotRecord.feature_name,
            FeatureSnapshotRecord.effective_at.desc(),
            FeatureSnapshotRecord.available_at.desc(),
            FeatureSnapshotRecord.calculated_at.desc(),
        )
    )
    latest: dict[tuple[UUID, str], FeatureSnapshotRecord] = {}
    for row in self.session.scalars(statement):
        key = (row.security_id, row.feature_name)
        selected = latest.get(key)
        if selected is None:
            latest[key] = row
            continue
        precedence = (row.effective_at, row.available_at, row.calculated_at)
        selected_precedence = (
            selected.effective_at,
            selected.available_at,
            selected.calculated_at,
        )
        if precedence == selected_precedence:
            raise RepositoryConflictError(
                f"ambiguous latest feature vintage for security {row.security_id} "
                f"feature {row.feature_name!r}"
            )
    return tuple(_feature_from_record(latest[key]) for key in sorted(latest, key=lambda item: (str(item[0]), item[1])))
```

- [ ] **Step 5: Run repository tests, formatting, and typing**

Run:

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/integration/test_feature_panel_repository.py tests/integration/test_storage_roundtrip.py -v
.\.venv314\Scripts\python.exe -m ruff format --check src/quant_raas/domain/protocols.py src/quant_raas/storage/repositories.py tests/integration/test_feature_panel_repository.py
.\.venv314\Scripts\python.exe -m mypy src/quant_raas
```

Expected: all focused tests pass, formatting reports no changes needed after applying Ruff formatting, and mypy reports no issues.

- [ ] **Step 6: Commit the repository contract**

```powershell
git add src/quant_raas/domain/protocols.py src/quant_raas/storage/repositories.py tests/integration/test_feature_panel_repository.py
git commit -m "feat: add point-in-time feature panel query"
```

---

### Task 2: Canonical typed-snapshot-to-panel adapter

**Files:**
- Create: `src/quant_raas/feature_store/panel.py`
- Modify: `src/quant_raas/feature_store/__init__.py`
- Create: `tests/unit/test_feature_panel.py`

**Interfaces:**
- Consumes: `Sequence[FeatureSnapshot]` and a timezone-aware decision cutoff.
- Produces:

```python
FEATURE_PANEL_COLUMNS: tuple[str, ...]

def snapshots_to_frame(
    snapshots: Sequence[FeatureSnapshot],
    *,
    decision_at: datetime,
) -> pd.DataFrame: ...
```

- [ ] **Step 1: Write failing adapter tests**

Create `tests/unit/test_feature_panel.py` with one empty-panel test and one populated-panel test:

```python
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pandas as pd
import pytest

from quant_raas.domain.market import FeatureSnapshot
from quant_raas.feature_store.panel import FEATURE_PANEL_COLUMNS, snapshots_to_frame


def test_empty_feature_panel_has_stable_columns() -> None:
    decision = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    frame = snapshots_to_frame((), decision_at=decision)
    assert tuple(frame.columns) == FEATURE_PANEL_COLUMNS
    assert frame.empty


def test_feature_panel_is_stably_ordered_and_keeps_lineage() -> None:
    decision = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available = decision - timedelta(minutes=1)
    run_id = UUID(int=100)
    snapshots = [
        FeatureSnapshot(feature_snapshot_id=UUID(int=2), security_id=UUID(int=2), feature_name="z", feature_version="v1", effective_at=available, available_at=available, calculated_at=decision, value=2.0, research_run_id=run_id, code_version="code-v1", config_version="config-v1"),
        FeatureSnapshot(feature_snapshot_id=UUID(int=1), security_id=UUID(int=1), feature_name="a", feature_version="v1", effective_at=available, available_at=available, calculated_at=decision, value=1.0, research_run_id=run_id, code_version="code-v1", config_version="config-v1"),
    ]
    frame = snapshots_to_frame(snapshots, decision_at=decision)
    assert frame[["security_id", "feature_name", "value"]].to_records(index=False).tolist() == [
        (str(UUID(int=1)), "a", 1.0),
        (str(UUID(int=2)), "z", 2.0),
    ]
    assert frame["decision_at"].tolist() == [pd.Timestamp(decision)] * 2
    assert frame["feature_version"].tolist() == ["v1", "v1"]
    assert frame["config_version"].tolist() == ["config-v1", "config-v1"]


def test_feature_panel_rejects_naive_decision_time() -> None:
    with pytest.raises(ValueError, match="explicit timezone"):
        snapshots_to_frame((), decision_at=datetime(2024, 1, 9, 21, 0))
```

- [ ] **Step 2: Run the focused tests and confirm the module is absent**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/unit/test_feature_panel.py -v
```

Expected: collection ERROR with `ModuleNotFoundError: No module named 'quant_raas.feature_store.panel'`.

- [ ] **Step 3: Implement the adapter with a stable empty schema**

Create `feature_store/panel.py`:

```python
"""Canonical tabular representation of typed feature snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd

from quant_raas.common.clock import ensure_utc
from quant_raas.domain.market import FeatureSnapshot

FEATURE_PANEL_COLUMNS = (
    "decision_at",
    "security_id",
    "feature_name",
    "feature_version",
    "value",
    "effective_at",
    "available_at",
    "calculated_at",
    "config_version",
    "code_version",
)


def snapshots_to_frame(
    snapshots: Sequence[FeatureSnapshot],
    *,
    decision_at: datetime,
) -> pd.DataFrame:
    cutoff = ensure_utc(decision_at)
    rows = [
        {
            "decision_at": cutoff,
            "security_id": str(item.security_id),
            "feature_name": item.feature_name,
            "feature_version": item.feature_version,
            "value": item.value,
            "effective_at": item.effective_at,
            "available_at": item.available_at,
            "calculated_at": item.calculated_at,
            "config_version": item.config_version,
            "code_version": item.code_version,
        }
        for item in snapshots
    ]
    frame = pd.DataFrame.from_records(rows, columns=FEATURE_PANEL_COLUMNS)
    if frame.empty:
        return frame
    return frame.sort_values(["security_id", "feature_name"], kind="mergesort").reset_index(drop=True)
```

Export `FEATURE_PANEL_COLUMNS` and `snapshots_to_frame` from `feature_store/__init__.py` alongside the registry types.

- [ ] **Step 4: Run the adapter tests and static checks**

```powershell
.\.venv314\Scripts\python.exe -m ruff format src/quant_raas/feature_store/panel.py src/quant_raas/feature_store/__init__.py tests/unit/test_feature_panel.py
.\.venv314\Scripts\python.exe -m pytest tests/unit/test_feature_panel.py -v
.\.venv314\Scripts\python.exe -m ruff check src/quant_raas/feature_store tests/unit/test_feature_panel.py
.\.venv314\Scripts\python.exe -m mypy src/quant_raas
```

Expected: three tests pass; Ruff and mypy report no issues.

- [ ] **Step 5: Commit the adapter**

```powershell
git add src/quant_raas/feature_store tests/unit/test_feature_panel.py
git commit -m "feat: add canonical feature panel adapter"
```

---

### Task 3: Explicit screen feature pins and complete dependency discovery

**Files:**
- Modify: `src/quant_raas/screens/models.py:5-91`
- Modify: `src/quant_raas/screens/engine.py:45-105`
- Modify: `configs/screens/abnormal_residual_decline.yaml`
- Modify: `configs/screens/relative_strength_breakout.yaml`
- Modify: `configs/screens/cheap_positive_revisions.yaml`
- Modify: `tests/unit/test_screens.py`

**Interfaces:**
- Consumes: existing conditions, `requires_features`, and optional ranking definition.
- Produces:

```python
class ScreenDefinition(BaseModel):
    feature_config_version: str | None = None
    feature_versions: dict[str, str] = Field(default_factory=dict)

    @property
    def referenced_features(self) -> tuple[str, ...]: ...
```

- [ ] **Step 1: Write failing schema and ranking-dependency tests**

Extend `tests/unit/test_screens.py`:

```python
def test_repository_screens_pin_feature_and_configuration_versions() -> None:
    definitions = [
        ScreenDefinition.from_yaml(path)
        for path in sorted((REPOSITORY_ROOT / "configs" / "screens").glob("*.yaml"))
    ]
    assert all(item.feature_config_version for item in definitions)
    assert all(set(item.feature_versions) == set(item.referenced_features) for item in definitions)


def test_ranking_feature_is_loaded_even_when_not_a_condition() -> None:
    definition = ScreenDefinition(
        screen_id="rank-only-v1",
        name="Rank-only dependency",
        conditions=[{"feature": "signal", "operator": "greater_than", "value": 0.0}],
        rank={"feature": "rank_only", "direction": "descending"},
    )
    features = pd.DataFrame(
        [
            ("A", "signal", 1.0, "2024-01-05T20:00:00Z"),
            ("A", "rank_only", 1.0, "2024-01-05T20:00:00Z"),
            ("B", "signal", 1.0, "2024-01-05T20:00:00Z"),
            ("B", "rank_only", 2.0, "2024-01-05T20:00:00Z"),
        ],
        columns=["security_id", "feature_name", "value", "available_at"],
    )
    result = run_screen(features, definition, as_of=datetime(2024, 1, 5, 21, 0, tzinfo=UTC))
    assert definition.referenced_features == ("signal", "rank_only")
    assert result.matches == ("B", "A")
```

- [ ] **Step 2: Run the two tests and confirm both missing behaviors**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/unit/test_screens.py::test_repository_screens_pin_feature_and_configuration_versions tests/unit/test_screens.py::test_ranking_feature_is_loaded_even_when_not_a_condition -v
```

Expected: FAIL because `ScreenDefinition` has no `referenced_features` property and the YAML files do not contain pins.

- [ ] **Step 3: Extend `ScreenDefinition` and make the engine use its complete dependency set**

Import `field_validator` and add:

```python
feature_config_version: str | None = Field(default=None, min_length=1)
feature_versions: dict[str, str] = Field(default_factory=dict)

@field_validator("feature_versions")
@classmethod
def validate_feature_versions(cls, value: dict[str, str]) -> dict[str, str]:
    if any(not name.strip() or not version.strip() for name, version in value.items()):
        raise ValueError("feature version names and values cannot be empty")
    return value

@property
def referenced_features(self) -> tuple[str, ...]:
    names = [criterion.feature for criterion in self.criteria]
    names.extend(self.requires_features)
    if self.rank is not None:
        names.append(self.rank.feature)
    return tuple(dict.fromkeys(names))
```

In `run_screen`, replace the local condition/dependency union with:

```python
wanted = set(definition.referenced_features)
```

- [ ] **Step 4: Add explicit pins to every checked-in screen**

For both enabled price screens, add:

```yaml
feature_config_version: equity-mvp-v0
feature_versions:
  residual_return_zscore_1d: price-mvp-v0
  dollar_volume_zscore_20d: price-mvp-v0
```

Use the two actual names in each file. For `relative_strength_breakout.yaml`, pin `relative_return_sector_63d` and `realized_volatility_20d` to `price-mvp-v0`.

For the disabled estimates/valuation screen, add:

```yaml
feature_config_version: equity-estimates-v0
feature_versions:
  eps_revision_breadth_20d: estimates-mvp-v0
  forward_pe_zscore_5y: valuation-mvp-v0
  residual_momentum_20d: price-mvp-v0
```

- [ ] **Step 5: Run screen tests and static checks**

```powershell
.\.venv314\Scripts\python.exe -m ruff format src/quant_raas/screens/models.py src/quant_raas/screens/engine.py tests/unit/test_screens.py
.\.venv314\Scripts\python.exe -m pytest tests/unit/test_screens.py -v
.\.venv314\Scripts\python.exe -m ruff check src/quant_raas/screens tests/unit/test_screens.py
.\.venv314\Scripts\python.exe -m mypy src/quant_raas
```

Expected: all screen tests pass; Ruff and mypy report no issues.

- [ ] **Step 6: Commit versioned screen definitions**

```powershell
git add src/quant_raas/screens/models.py src/quant_raas/screens/engine.py configs/screens tests/unit/test_screens.py
git commit -m "feat: pin screen feature versions"
```

---

### Task 4: Shared repository-backed one-off and historical screen execution

**Files:**
- Create: `src/quant_raas/screens/service.py`
- Modify: `src/quant_raas/screens/__init__.py`
- Create: `tests/integration/test_screen_equivalence.py`

**Interfaces:**
- Consumes: `FeatureRepository.panel_as_of`, `FeatureRegistry`, `snapshots_to_frame`, `ScreenDefinition`, and `run_screen`.
- Produces:

```python
class ScreenExecutionService:
    def evaluate(
        self,
        definition: ScreenDefinition,
        security_ids: Sequence[UUID],
        *,
        as_of: datetime,
    ) -> ScreenResult: ...

    def evaluate_history(
        self,
        definition: ScreenDefinition,
        security_ids: Sequence[UUID],
        *,
        cutoffs: Sequence[datetime],
    ) -> tuple[ScreenResult, ...]: ...
```

- [ ] **Step 1: Write the failing live-versus-history equivalence integration test**

Create `tests/integration/test_screen_equivalence.py`. Persist two securities and
one research run. Give security A a qualifying residual decline and volume
spike, give security B only a non-qualifying residual decline so its missing
volume input is observable, then add a future correction that would remove A
and a competing feature version that would add B. Use the checked-in
`abnormal_residual_decline.yaml` and `mvp_price_features()`.

Define the fixture helper explicitly:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from quant_raas.domain.market import FeatureSnapshot
from quant_raas.domain.research import ResearchRun
from quant_raas.domain.security import Security
from quant_raas.feature_store.registry import mvp_price_features
from quant_raas.screens.models import ScreenDefinition
from quant_raas.screens.service import ScreenExecutionService
from quant_raas.storage.repositories import (
    SqlAlchemyFeatureRepository,
    SqlAlchemyResearchRepository,
    SqlAlchemySecurityRepository,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _screen_snapshot(
    identifier: int,
    security_id: UUID,
    research_run_id: UUID,
    feature_name: str,
    value: float,
    effective_at: datetime,
    available_at: datetime,
    *,
    feature_version: str = "price-mvp-v0",
) -> FeatureSnapshot:
    return FeatureSnapshot(
        feature_snapshot_id=UUID(int=identifier),
        security_id=security_id,
        feature_name=feature_name,
        feature_version=feature_version,
        effective_at=effective_at,
        available_at=available_at,
        calculated_at=max(available_at, effective_at) + timedelta(minutes=1),
        value=value,
        research_run_id=research_run_id,
        code_version="test-code-v1",
        config_version="equity-mvp-v0",
    )
```

Then add the equivalence test:

```python
@pytest.mark.integration
@pytest.mark.point_in_time
def test_one_off_and_historical_screen_paths_are_identical_at_same_cutoff(
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    second_security = sample_security.model_copy(
        update={"security_id": UUID(int=2), "name": "Second Corp"}
    )
    securities = SqlAlchemySecurityRepository(sqlite_session)
    securities.add_security(sample_security)
    securities.add_security(second_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)

    cutoff = datetime(2024, 1, 9, 22, 0, tzinfo=UTC)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available = effective + timedelta(minutes=5)
    future = cutoff + timedelta(hours=1)
    feature_repository = SqlAlchemyFeatureRepository(sqlite_session)
    feature_repository.upsert_many(
        [
            _screen_snapshot(301, sample_security.security_id, research_run.research_run_id, "residual_return_zscore_1d", -2.5, effective, available),
            _screen_snapshot(302, sample_security.security_id, research_run.research_run_id, "dollar_volume_zscore_20d", 1.2, effective, available),
            _screen_snapshot(303, second_security.security_id, research_run.research_run_id, "residual_return_zscore_1d", -1.0, effective, available),
            _screen_snapshot(304, sample_security.security_id, research_run.research_run_id, "residual_return_zscore_1d", 0.0, effective, future),
            _screen_snapshot(305, second_security.security_id, research_run.research_run_id, "residual_return_zscore_1d", -3.0, effective, available, feature_version="price-mvp-v1"),
        ]
    )

    definition = ScreenDefinition.from_yaml(
        REPOSITORY_ROOT / "configs" / "screens" / "abnormal_residual_decline.yaml"
    )
    service = ScreenExecutionService(feature_repository, mvp_price_features())
    one_off = service.evaluate(
        definition,
        [second_security.security_id, sample_security.security_id],
        as_of=cutoff,
    )
    historical = service.evaluate_history(
        definition,
        [second_security.security_id, sample_security.security_id],
        cutoffs=[cutoff],
    )[0]

    assert one_off.matches == (str(sample_security.security_id),)
    assert one_off.excluded_for_missing_data == (str(second_security.security_id),)
    assert historical.matches == one_off.matches
    assert historical.excluded_for_missing_data == one_off.excluded_for_missing_data
    pd.testing.assert_frame_equal(historical.evaluated, one_off.evaluated)
```

- [ ] **Step 2: Run the equivalence test and confirm the service is missing**

```powershell
.\.venv314\Scripts\python.exe -m pytest tests/integration/test_screen_equivalence.py::test_one_off_and_historical_screen_paths_are_identical_at_same_cutoff -v
```

Expected: collection ERROR with `ModuleNotFoundError: No module named 'quant_raas.screens.service'`.

- [ ] **Step 3: Add failing validation tests**

Add a repository double that must never be reached by invalid input and a
factory for fully explicit definitions:

```python
class _NeverCalledFeatureRepository:
    def panel_as_of(self, *args: object, **kwargs: object) -> tuple[FeatureSnapshot, ...]:
        raise AssertionError("repository must not be called")


def _versioned_definition(
    *,
    config_version: str | None = "equity-mvp-v0",
    pins: dict[str, str] | None = None,
) -> ScreenDefinition:
    return ScreenDefinition(
        screen_id="validation-v1",
        name="Validation screen",
        feature_config_version=config_version,
        feature_versions=pins
        or {
            "residual_return_zscore_1d": "price-mvp-v0",
            "dollar_volume_zscore_20d": "price-mvp-v0",
        },
        conditions=[
            {
                "feature": "residual_return_zscore_1d",
                "operator": "less_than",
                "value": -2.0,
            },
            {
                "feature": "dollar_volume_zscore_20d",
                "operator": "greater_than",
                "value": 1.0,
            },
        ],
    )
```

Then cover every fail-closed branch before implementation:

```python
def test_repository_backed_screen_validation_fails_before_data_access() -> None:
    service = ScreenExecutionService(_NeverCalledFeatureRepository(), mvp_price_features())
    security_ids = [UUID(int=1)]
    cutoff = datetime(2024, 1, 9, 22, 0, tzinfo=UTC)
    complete = {
        "residual_return_zscore_1d": "price-mvp-v0",
        "dollar_volume_zscore_20d": "price-mvp-v0",
    }

    with pytest.raises(ValueError, match="feature_config_version is required"):
        service.evaluate(
            _versioned_definition(config_version=None), security_ids, as_of=cutoff
        )
    with pytest.raises(ValueError, match="missing feature version pins"):
        service.evaluate(
            _versioned_definition(
                pins={"residual_return_zscore_1d": "price-mvp-v0"}
            ),
            security_ids,
            as_of=cutoff,
        )
    with pytest.raises(ValueError, match="unused feature version pins"):
        service.evaluate(
            _versioned_definition(pins={**complete, "unused": "v1"}),
            security_ids,
            as_of=cutoff,
        )
    with pytest.raises(ValueError, match="unknown feature"):
        service.evaluate(
            _versioned_definition(
                pins={**complete, "residual_return_zscore_1d": "missing-v9"}
            ),
            security_ids,
            as_of=cutoff,
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        service.evaluate_history(
            _versioned_definition(), security_ids, cutoffs=[cutoff, cutoff]
        )
```

- [ ] **Step 4: Implement `ScreenExecutionService`**

Create `src/quant_raas/screens/service.py`:

```python
"""Repository-backed execution shared by current and historical screens."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from quant_raas.common.clock import ensure_utc
from quant_raas.domain.protocols import FeatureRepository
from quant_raas.feature_store.panel import snapshots_to_frame
from quant_raas.feature_store.registry import FeatureRegistry
from quant_raas.screens.engine import ScreenResult, run_screen
from quant_raas.screens.models import ScreenDefinition


class ScreenExecutionService:
    def __init__(self, features: FeatureRepository, registry: FeatureRegistry) -> None:
        self.features = features
        self.registry = registry

    def evaluate(
        self,
        definition: ScreenDefinition,
        security_ids: Sequence[UUID],
        *,
        as_of: datetime,
    ) -> ScreenResult:
        cutoff = ensure_utc(as_of)
        if not definition.enabled:
            raise ValueError(f"screen {definition.screen_id!r} is disabled")
        versions = self._validated_versions(definition)
        assert definition.feature_config_version is not None
        snapshots = self.features.panel_as_of(
            security_ids,
            versions,
            config_version=definition.feature_config_version,
            as_of=cutoff,
        )
        return run_screen(
            snapshots_to_frame(snapshots, decision_at=cutoff),
            definition,
            as_of=cutoff,
        )

    def evaluate_history(
        self,
        definition: ScreenDefinition,
        security_ids: Sequence[UUID],
        *,
        cutoffs: Sequence[datetime],
    ) -> tuple[ScreenResult, ...]:
        normalized = tuple(ensure_utc(cutoff) for cutoff in cutoffs)
        if any(current >= following for current, following in zip(normalized, normalized[1:], strict=False)):
            raise ValueError("historical screen cutoffs must be strictly increasing")
        return tuple(
            self.evaluate(definition, security_ids, as_of=cutoff) for cutoff in normalized
        )

    def _validated_versions(self, definition: ScreenDefinition) -> dict[str, str]:
        if definition.feature_config_version is None:
            raise ValueError("feature_config_version is required for repository-backed screens")
        required = set(definition.referenced_features)
        provided = set(definition.feature_versions)
        missing = sorted(required - provided)
        unused = sorted(provided - required)
        if missing:
            raise ValueError(f"missing feature version pins: {', '.join(missing)}")
        if unused:
            raise ValueError(f"unused feature version pins: {', '.join(unused)}")
        for name in sorted(required):
            try:
                self.registry.get(name, definition.feature_versions[name])
            except KeyError as error:
                raise ValueError(str(error)) from error
        return {name: definition.feature_versions[name] for name in sorted(required)}
```

Export `ScreenExecutionService` from `screens/__init__.py`.

- [ ] **Step 5: Run equivalence, screen, and repository tests**

```powershell
.\.venv314\Scripts\python.exe -m ruff format src/quant_raas/screens/service.py src/quant_raas/screens/__init__.py tests/integration/test_screen_equivalence.py
.\.venv314\Scripts\python.exe -m pytest tests/integration/test_screen_equivalence.py tests/integration/test_feature_panel_repository.py tests/unit/test_feature_panel.py tests/unit/test_screens.py -v
.\.venv314\Scripts\python.exe -m ruff check src/quant_raas/screens tests/integration/test_screen_equivalence.py
.\.venv314\Scripts\python.exe -m mypy src/quant_raas
```

Expected: all focused tests pass; Ruff and mypy report no issues.

- [ ] **Step 6: Commit shared screen execution**

```powershell
git add src/quant_raas/screens tests/integration/test_screen_equivalence.py
git commit -m "feat: unify current and historical screen execution"
```

---

### Task 5: Documentation correction and full verification

**Files:**
- Modify: `README.md:12`
- Verify unchanged: `PLAN.md`

**Interfaces:**
- Consumes: the completed implementation and repository verification commands.
- Produces: a correct README plan link and fresh evidence that the complete deterministic suite passes without modifying `PLAN.md`.

- [ ] **Step 1: Demonstrate the stale README link**

Run:

```powershell
rg -n 'PLAN_codex\.md' README.md
```

Expected: one match in the sentence describing which plan drives the repository.

- [ ] **Step 2: Correct only the README link**

Change:

```markdown
The repository is being built from [PLAN_codex.md](PLAN_codex.md).
```

to:

```markdown
The repository is being built from [PLAN.md](PLAN.md).
```

- [ ] **Step 3: Verify documentation scope**

Run:

```powershell
rg -n 'PLAN_codex\.md' README.md
git diff --name-only -- PLAN.md
git diff --check
```

Expected: the first command returns no matches, the second prints nothing, and `git diff --check` exits successfully.

- [ ] **Step 4: Run the complete deterministic verification gate**

Run each command independently:

```powershell
.\.venv314\Scripts\python.exe -m ruff format --check .
.\.venv314\Scripts\python.exe -m ruff check .
.\.venv314\Scripts\python.exe -m mypy src/quant_raas
.\.venv314\Scripts\python.exe -m pytest -m "not external" --cov=quant_raas --cov-branch --cov-fail-under=80
```

Expected: Ruff formatting and linting pass, mypy reports no issues, all deterministic tests pass, and branch coverage remains at or above 80%. Record any third-party deprecation warning separately rather than treating it as an application warning.

- [ ] **Step 5: Review the final diff against the design**

Run:

```powershell
git diff --stat 37f6397
git diff --check 37f6397
git status --short
git diff 37f6397 -- PLAN.md
```

Expected: implementation, tests, screen configuration, README, and plan/spec artifacts are visible; no whitespace errors exist; `PLAN.md` has no diff.

- [ ] **Step 6: Commit the documentation correction**

```powershell
git add README.md
git commit -m "docs: repair plan link"
```
