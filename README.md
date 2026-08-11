# Quant RaaS

Quant RaaS is an early-stage, point-in-time equity-research platform. It is
designed to turn market and company observations into a small set of ranked,
evidence-linked quantitative findings for a portfolio manager or analyst.
Holdings are relevance context; this repository is not an order-management,
execution, or accounting system.

The repository is being built from [PLAN_codex.md](PLAN_codex.md). Interfaces and
modules present in the tree are foundations, not a claim that every planned data
source, screen, model, or UI is production-ready.

## Current foundation

The Phase 0/1 foundation covers or defines:

- typed securities, identifiers, holdings, events, features, findings, and cards;
- time-aware storage contracts and provider-neutral connector boundaries;
- deterministic price normalization and quantitative calculations;
- materiality and factor configuration examples;
- point-in-time rules that prevent later vintages entering earlier snapshots;
- SQLite development and PostgreSQL-compatible persistence foundations; and
- network-free unit, integration, and point-in-time testing conventions.

Estimate histories, licensed Bloomberg/LSEG feeds, filing/news synthesis, and
production deployment remain dependent on implementation, entitlements, and
validation. Disabled configuration files make those dependencies explicit.

## Requirements

- Python 3.12 or 3.13
- Git
- Docker with Compose only if using the containerized development database

Python 3.14 is intentionally outside the supported range until the numerical and
vendor dependency set has been validated against it.

## Local setup

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

macOS/Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
```

The default database URL uses a local SQLite file. Runtime data and `.env` files
are ignored by Git.

## Optional capabilities

Install only the extras required for the current environment:

```bash
python -m pip install -e ".[dev,api,dashboard,postgres]"
# Explicit prototype-only provider opt-in:
python -m pip install -e ".[public-data]"
```

| Extra | Purpose | Important limitation |
|---|---|---|
| `api` | FastAPI and Uvicorn composition | An API shell is not production security. |
| `dashboard` | Streamlit and Plotly research UI | UI output is only as reliable as its typed inputs. |
| `postgres` | PostgreSQL driver | A deployed database still needs backup and access controls. |
| `calendar` | Exchange-session calendars | Calendar mappings must be validated per security. |
| `public-data` | Opt-in Yahoo prototype connector | Not an authoritative production market-data feed. |
| `lseg` | LSEG Data Library | Requires contracted entitlements and an approved session. |
| `bloomberg` | Bloomberg integration boundary | Install the SDK through the approved Bloomberg channel. |

See [vendor entitlements](docs/vendor_entitlements.md) before enabling an
external connector. The default test suite never uses network or licensed feeds.

## Configuration and sample inputs

Version-controlled research settings live under `configs/`:

- `materiality/default.yaml` defines deterministic score v0;
- `factors/mvp.yaml` records return, regression, and normalization conventions;
- `screens/` contains two Phase-1 screens and one disabled later-phase example;
- `universes/demo.csv` demonstrates canonical and external identifier metadata.

Use [examples/holdings.csv](examples/holdings.csv) for held-name context and
[examples/coverage.csv](examples/coverage.csv) for unheld research coverage.
Weights are decimal fractions: `0.042` means 4.2%.

The full logical schemas and time semantics are in
[data contracts](docs/data_contracts.md). In particular, a historical query may
use only data whose `available_at` is no later than the query's `as_of` cutoff.

## Offline demo

Seed a complete network-free example after installation:

```powershell
.\.venv\Scripts\quant-raas.exe seed-demo
```

The command registers four covered equities plus two benchmark instruments,
ingests 3,000 deterministic synthetic bars, and writes one daily research card
for every covered name. It is safe to rerun against the same local database.
With the `api` or `dashboard` extra installed, inspect the result locally:

```powershell
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --reload
.\.venv\Scripts\python.exe -m streamlit run apps/dashboard/app.py
```

## Development checks

Run deterministic checks without vendor access:

```bash
python -m ruff format --check .
python -m ruff check .
python -m mypy src/quant_raas
python -m pytest -m "not external" --cov=quant_raas --cov-branch --cov-fail-under=80
```

Useful focused commands:

```bash
python -m pytest tests/unit -q
python -m pytest -m point_in_time -q
python -m pytest -m integration -q
```

Tests marked `external` require explicit credentials/network access and are not
run by CI. The coverage gate targets the deterministic Phase 0/1 package;
future AI boundaries, live/vendor adapters, and CLI/demo composition are omitted
explicitly in `pyproject.toml`. Do not turn a failing provider call into a
skipped numerical test.

## Docker development

Copy `.env.example` to `.env`, change the local-only database password, and start
only the database or the API composition:

```bash
docker compose up -d db
docker compose up --build api
```

The API liveness route is `http://localhost:8000/health`. Optional processes are
behind explicit profiles:

```bash
docker compose --profile dashboard up --build dashboard
docker compose --profile worker run --rm worker
```

Application containers are development composition only. The Compose file is
not a production deployment: it does not provide TLS, identity, secret
management, backups, or licensed vendor connectivity.

## Repository guide

```text
apps/                 API, dashboard, and worker composition
configs/              versioned factors, materiality, screens, and universes
docs/                 architecture, contracts, scope, entitlements, wireframes
examples/             safe sample input files
migrations/           database schema migrations
src/quant_raas/        installable application and research package
tests/                 unit, integration, point-in-time, and evaluation tests
workflows/             scheduled/event-driven composition
```

Read [architecture](docs/architecture.md) for module boundaries,
[product scope](docs/product_scope.md) for non-goals, and
[wireframes](docs/wireframes.md) for the intended information hierarchy.

## Legacy prototype

`aapl_quant_research.py` is retained as migration input and a behavioral
reference. It downloads live public data, executes work at import time, and uses
exploratory statistical assumptions. It is intentionally excluded from package
linting and must not be treated as the production research engine.

## Research disclaimer

Outputs from this repository are research aids, not investment advice or a
guarantee of data accuracy. Production use requires independent model, data,
licensing, security, and compliance review.
