# Autonomous Quant Research-as-a-Service Platform

## Product and Engineering Build Plan

**Working concept:** an autonomous equity research platform that continuously converts market, fundamental, estimate, filing, macro and news data into **ranked, evidence-backed quantitative research findings** for a portfolio manager.

**Primary product:** Quant Research-as-a-Service (RaaS).

**Secondary use of portfolio data:** the PM can upload 30–100 holdings and weights so the system understands relevance and can prioritize research. The platform is **not primarily a portfolio-position monitoring or order-management system**.

**Initial asset class assumption:** listed equities / ADRs, with the architecture designed so ETFs and equity indices can be added later.

**Commercial intent:** this is a product sold to external portfolio managers, not an internal tool. That single fact drives the entitlement, tenancy and audit constraints in sections 7 and 9.

---

# 0. Document status and how to read it

## 0.1 What this document is

This is the product and engineering specification plus the build roadmap. It is a living document: sections 11–36 describe the target system, section 0.3 records what is actually built today, and section 38 sequences the remaining work.

**Rule:** when the code and this document disagree, the code wins and this document gets corrected. Do not let the plan drift into fiction.

## 0.2 Status legend

| Mark | Meaning |
|---|---|
| **BUILT** | Implemented, tested, and covered by the deterministic CI suite |
| **PARTIAL** | Real implementation exists but does not yet cover the specified scope |
| **BOUNDARY** | Interface/protocol exists and fails loudly; no working implementation behind it |
| **PLANNED** | Specified here, no code |
| **BLOCKED** | Cannot proceed until a decision in section 0.4 or an entitlement is resolved |

## 0.3 Implementation status as of 2026-08-19

The repository contains roughly 13,700 lines of Python across `src/quant_raas`, `apps`, `workflows` and `tests`. The deterministic suite is 89 passing tests under `mypy --strict`, Ruff, and an 80% branch-coverage gate. Phase 0 and most of Phase 1 are real.

| Area | Status | Notes |
|---|---|---|
| Typed domain contracts (`domain/`) | **BUILT** | Securities, identifiers, holdings, events, features, findings, cards, protocols |
| Point-in-time model | **BUILT** | `effective_at` / `available_at` / `ingested_at`; vintage tests in `tests/point_in_time/` |
| Security master | **BUILT** | Temporal identifier resolution, CSV importer, benchmark mappings |
| Persistence | **BUILT** | 19 SQLAlchemy tables, Alembic migration, SQLite dev / PostgreSQL target |
| Price ingestion + normalization | **BUILT** | Adjusted OHLCV, quality checks, batch-level failure isolation |
| Feature store | **PARTIAL** | Registry and `feature_snapshot` persistence; no cross-sectional panel retrieval API |
| Quant pure functions (`quant/`) | **BUILT** | returns, risk, anomalies, factors, event_study, statistics, seasonality, earnings, estimates, valuation, macro, options, ownership |
| Daily research pipeline | **PARTIAL** | `DailyResearchService` emits **price/risk findings only**. The estimate, valuation, options, ownership and macro functions exist but nothing feeds them data |
| Materiality v0 | **BUILT** | Config-driven weights (`configs/materiality/default.yaml`), `sqrt` position priority modifier, tier labels, completeness tracking |
| Research cards + evidence | **BUILT** | Evidence-linked, deterministic IDs, idempotent re-runs |
| Screens | **PARTIAL** | Engine and models exist; the "same definition runs live and historical" property is not yet proven by a test |
| Backtest | **PARTIAL** | Cross-sectional quantile engine with PIT assertions, costs, turnover, lagged execution. No event-study backtest, no bootstrap/HAC, no multiple-testing control |
| Connectors: fixture, Yahoo | **BUILT** | Deterministic fixture provider; Yahoo behind an explicit opt-in extra |
| Connectors: Bloomberg, LSEG, SEC, macro | **BOUNDARY** | Placeholders that raise rather than report false success. This is correct behavior, but it means no real vendor data exists yet |
| AI layer (`ai/`) | **BOUNDARY** | `guardrails.py` is real (~129 lines). Synthesizer, filing diff, query agent, backtest agent, evals are stubs. No LLM provider is wired |
| Apps | **PARTIAL** | FastAPI with 9 routes, Streamlit dashboard, worker entrypoint, CLI (`init-db`, `seed-demo`, `daily`) |
| Multi-tenancy / auth | **PLANNED** | **No tenant concept exists anywhere.** `user_id` is a free-text feedback attribution field, not an isolation boundary |
| Thesis model | **BOUNDARY** | `thesis` / `thesis_version` tables exist; `research/thesis.py` is 24 lines and excluded from coverage. `thesis_relevance_score` is a materiality input with nothing producing it |

### What this means

The engine is genuinely good and the discipline is high — loud failures, no silent fallbacks, real PIT enforcement. Two things are missing, and both are structural rather than incremental:

1. **There is no real data.** Every finding family beyond price/risk is blocked on a vendor connector. The quant functions were written ahead of the data that feeds them.
2. **There is no product shell.** No tenancy, no auth, no entitlement enforcement — all of which are much cheaper to add now than after 19 tables and 1,100 lines of repositories accumulate more callers.

## 0.4 Open decision register

These block or reshape downstream work. Each needs an owner and a date.

| ID | Decision | Why it blocks | Status |
|---|---|---|---|
| **D1** | Commercial data model: BYO-entitlement, licensed redistribution, or redistributable mid-tier vendor (section 9.0) | Determines whether the product can ship at all, and whether deployment is SaaS or customer-hosted | **OPEN — highest priority** |
| **D2** | Tenancy model: single-tenant-per-deployment vs shared multi-tenant schema (section 7) | Retrofitting tenant isolation across 19 tables gets more expensive every week | **OPEN** |
| **D3** | LLM provider, model, and data-handling terms (section 34) | Sending customer holdings or licensed vendor content to a third-party model has both licensing and confidentiality consequences | **OPEN** |
| **D4** | Workflow scheduler: Prefect, Dagster, or plain cron + queue | `workflows/` are currently plain Python modules with no scheduler behind them | **OPEN** |
| **D5** | Initial coverage region and universe (US only vs US + Europe) | Drives identifier symbology, calendars, filing sources, and vendor cost | **OPEN** |
| **D6** | Whether derived values (z-scores, residuals, percentiles) may be redistributed under the chosen contract even when raw fields may not | Could make a cheaper hybrid data model viable — see section 9.0 | **OPEN — ask vendor counsel** |

---

# 1. Executive summary

The goal is to build a research system that behaves less like an alert terminal and more like an always-on quantitative analyst.

A PM uploads a portfolio or coverage list. The system continuously monitors:

- earnings and guidance;
- analyst estimates and revisions;
- price, volume, volatility and liquidity;
- regulatory filings;
- macroeconomic releases and market regimes;
- company and industry news;
- valuation and relative valuation;
- factor exposures and factor returns;
- options, short interest and positioning;
- peer and sector behavior;
- unusual / statistically abnormal market movements;
- thesis-relevant developments.

The critical product feature is **compression**. The system should not send hundreds of atomic alerts. It should combine related events, quantify their significance, connect them to the PM's research thesis, and surface only the developments that are likely to matter.

Illustrative output:
ASML — MATERIAL RESEARCH DEVELOPMENT

Why it matters
Consensus FY27 EPS: -4.1% since prior guidance update
Revision breadth: 18 of 24 analysts cutting estimates
Abnormal return today: -2.3σ after controlling for semiconductor factor moves
30d residual momentum: -1.1σ

Portfolio context
Position: 4.2% NAV
Contribution today: -38 bps

Valuation
Forward P/E: 27.4x
5Y company median: 31.2x
Peer-relative valuation z-score: -0.6

Factor / risk change
Momentum exposure: deteriorating
Quality exposure: unchanged
China revenue / policy sensitivity: elevated

Thesis impact: MODERATE
Key risk: tighter China semiconductor restrictions
Evidence confidence: HIGH

Suggested PM action
Review FY27 volume assumptions and China scenario before next rebalance.



# 2. How the AAPL prototype should evolve

It currently includes:

1. monthly seasonality;
2. day-of-week patterns;
3. FOMC event behavior;
4. CPI event behavior;
5. insider activity;
6. institutional ownership;
7. short-interest / squeeze measures;
8. options snapshot / put-call and IV skew;
9. earnings-event drift;
10. sector-relative strength;
11. p-value-driven edge detection;
12. basic annualized return, volatility and Sharpe metrics.

The production platform should **not throw these ideas away**. It should generalize them into reusable research services and make the statistical methodology considerably stronger.

### Prototype → production mapping

| Current script concept | Production RaaS equivalent |
|---|---|
| Single `TICKER` | Security master + configurable universe / portfolio / peer sets |
| `yfinance` | Vendor abstraction layer: Bloomberg, LSEG, SEC, macro APIs, fallback public feeds |
| Hardcoded FOMC/CPI dates | Economic calendar and timestamped macro event store |
| Monthly / weekday tests | Generic calendar-effect research module |
| Event-window function | General event-study engine |
| Earnings drift | Point-in-time earnings-surprise and post-event return research |
| Options snapshot | Full volatility / skew / term-structure / unusual activity feature set |
| Sector rotation | Multi-factor residual return and peer-relative analysis |
| `edges_found` strings | Typed `ResearchFinding` objects with scores, evidence and lineage |
| Console tables | API + research dashboard + daily brief + material-event cards |
| Simple t-tests | HAC / bootstrap / multiple-testing control / walk-forward validation |
| AAPL only | 30–100 holdings plus peers and a broader factor-screen universe |

---

# 3. Product definition

## 3.1 What the customer is buying

The customer is a portfolio manager or research analyst covering 30–100 held names plus a larger watch list. They already have a terminal, a news feed, and more alerts than they can read. They are not short of data.

What they are short of is **attention allocation**. The product sells one thing:

> A defensible, evidence-linked answer to "what actually changed today that I should spend time on, and why."

Everything else — the factor lab, the screens, the backtester — exists to make that answer credible and to let the PM interrogate it. If the daily brief is not trusted, no other feature rescues the product.

### The three claims the product must be able to defend

1. **This is unusual.** Quantified against the security's own history and its peers, not against a fixed percentage threshold.
2. **This is why.** A causal chain from catalyst to estimate change to price reaction, with each link sourced and timestamped.
3. **This is what it's worth.** Prior instances of this pattern behaved a certain way, with an honest sample size and confidence.

A competitor can replicate claim 1 in a weekend. Claims 2 and 3 are the moat, and both depend on point-in-time data integrity rather than on model sophistication.

## 3.2 The unit of value is the research finding

The atomic product object is a `ResearchFinding`: a typed, scored, evidence-linked assertion that something changed. Findings are aggregated into `ResearchCard`s (section 26), which are what the PM actually reads.

Design consequences, all of which the current code already honors and must continue to:

- a finding without evidence references is a bug, not a low-confidence finding;
- a finding must be reproducible from its stored inputs and code version;
- re-running an unchanged input produces the same finding ID, not a duplicate;
- a finding may assert "insufficient evidence" — that is a valid output, not a failure;
- the number displayed to the PM and the number in the evidence object are the same number.

### Success metric

The single product metric is **PM-rated precision at the top of the inbox**: of the findings shown in the daily brief, what fraction does the PM mark `Useful` or `Investigate` rather than `Noise` or `Already known`. Target for a credible beta is ≥60% on the top 5 cards. Recall matters less than precision; a missed event costs less than a brief the PM stops opening.

This metric requires the feedback controls in section 4.1 to exist from the first beta, not to be added later.

## 3.3 The holdings file is context, not the product

The PM can upload:

```csv
identifier,weight,thesis_id,benchmark
ASML NA,0.042,asml_core,MSCI_EUROPE
AAPL US,0.035,aapl_services,SPX
...
```

The holdings are used to:

- prioritize the order of research;
- calculate simple NAV relevance / contribution context;
- identify concentrated factor or macro sensitivities;
- suppress low-impact noise;
- personalize the research brief.

The platform should also support a **coverage universe that is not held**. A PM may want to research 200 names while holding only 50.

## 3.4 Non-goals for the first version

Do not build as:

- an OMS / EMS;
- a trade execution engine;
- a full accounting-grade performance attribution system;
- a compliance book-of-record;
- a generic news aggregator;
- a chatbot that invents financial analysis from text.

---

# 4. User experience and research workflow

## 4.1 Main screens

### A. Research Inbox

A ranked queue of research developments, not raw alerts.

Each card contains:

- company;
- materiality tier;
- what changed;
- quantitative evidence;
- estimate / valuation / factor impact;
- thesis impact;
- source evidence;
- confidence;
- time since event;
- PM feedback controls: `Useful`, `Noise`, `Already known`, `Wrong`, `Investigate`.

### B. Company Quant Research Page

For each security:

- price / residual-price diagnostics;
- earnings and estimate history;
- valuation history;
- factor exposures;
- peer comparison;
- macro sensitivities;
- options / positioning;
- filing changes;
- news clusters;
- historical analogues;
- backtested event behavior;
- active thesis and risks;
- all recent research findings.

### C. Factor & Risk Lab

Primarily a **research diagnostic** rather than portfolio risk management.

Show:

- individual-stock factor exposures;
- factor rankings across coverage universe;
- factor-return regime;
- residual versus factor-driven moves;
- correlation clusters;
- macro betas;
- crowding / momentum / volatility diagnostics;
- optional portfolio-weighted aggregation for PM context.

### D. Screen Builder

Examples:

- cheap + positive revisions + improving momentum;
- high quality + negative price dislocation;
- EPS revisions accelerating but stock not responding;
- valuation >2σ below history with stable fundamentals;
- residual drawdown >2.5σ with no fundamental deterioration;
- earnings in next 10 days + options-implied move below historical realized move;
- high China exposure + negative policy-news score;
- factor-neutral long / short candidate screens.

### E. Backtest Lab

The PM can turn a screen or signal into a test:

```text
Universe: STOXX Europe 600
Signal: 20d EPS revision breadth > +30%
Filter: P/E z-score < 0
Rebalance: weekly
Holding period: 20 trading days
Neutralize: sector + beta
Costs: 20 bps round trip
Period: 2012–2026
```

Output:

- long-short spread;
- CAGR / vol / Sharpe;
- max drawdown;
- hit rate;
- rank IC / ICIR;
- turnover;
- capacity proxy;
- exposures;
- regime breakdown;
- sub-period stability;
- significance / bootstrap confidence;
- post-cost performance;
- parameter sensitivity.

### F. Morning / Intraday Research Brief

The system should produce a concise morning brief and event-driven intraday cards.

A typical morning brief should contain perhaps:

1. 3–8 genuinely material company developments;
2. relevant macro regime changes;
3. factor moves that affect the coverage universe;
4. top positive / negative revision changes;
5. unusual residual moves from the prior session;
6. upcoming events requiring preparation.

The target is **high information density**, not comprehensive alert coverage.

---

# 5. Core system architecture

```text
                         ┌───────────────────────────┐
                         │ PM / Analyst UI           │
                         │ Web + Brief + API         │
                         └─────────────┬─────────────┘
                                       │
                              Research API Layer
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
     Materiality Engine        Research Query API       Backtest Service
              │                        │                        │
              └──────────────┬─────────┴──────────┬─────────────┘
                             │                    │
                     Research Findings       Feature Store
                             │                    │
               ┌─────────────┴────────────────────┴────────────┐
               │           Quant Research Engine              │
               │                                              │
               │  Factor  Estimates  Event Study  Valuation  │
               │  Macro   Options    Anomaly      Earnings   │
               └───────────────┬──────────────────────────────┘
                               │
                    Normalized Point-in-Time Data
                               │
            ┌──────────────────┼───────────────────────┐
            │                  │                       │
       Market Data        Fundamentals /          Text / Events
                         Estimates / Ownership
            │                  │                       │
  Bloomberg / LSEG /     Bloomberg / LSEG /    SEC / News / IR /
  exchanges / fallback   SEC / other vendors   macro calendars
            └──────────────────┼───────────────────────┘
                               │
                       Raw Data / Audit Lake
```

---

# 6. Technology stack

Decisions already made and encoded in `pyproject.toml`:

| Concern | Choice | Status |
|---|---|---|
| Language | Python `>=3.12,<3.14` | **Settled.** 3.14 excluded until the numerical/vendor set is validated |
| API | FastAPI + Uvicorn | **Settled** (`api` extra) |
| Tabular analytics | pandas 2.x | **Settled** |
| Statistics | NumPy, SciPy, statsmodels | **Settled** |
| Database | SQLAlchemy 2.x; SQLite dev, PostgreSQL target | **Settled** |
| Migrations | Alembic | **Settled** |
| Config | Pydantic + pydantic-settings, YAML under `configs/` | **Settled** |
| Research UI | Streamlit + Plotly | **Settled for MVP.** React/Next.js is a later decision, not a commitment |
| Testing | pytest, hypothesis, `mypy --strict`, Ruff, 80% branch coverage | **Settled** |

Still open:

| Concern | Options | Blocked on |
|---|---|---|
| Workflow scheduler | Prefect, Dagster, or cron + a queue | **D4.** `workflows/` are currently plain Python modules that nothing schedules |
| Time-series storage | Plain PostgreSQL vs TimescaleDB | Volume estimates in section 8. Do not add Timescale before the data justifies it |
| Vector search | pgvector | Not needed until filings/news land (Phase 7) |
| Object storage | S3-compatible + Parquet | Needed when raw vendor payload retention begins; check contract first |
| ML | scikit-learn | Not yet required. Nothing in the current spec needs it — resist adding it before something does |
| LLM provider | — | **D3** |

## 6.1 Architectural stance

Do **not** begin with a large microservice architecture. A modular monolith with clean interfaces is the fastest route to a credible research product, and the existing package boundaries (`docs/architecture.md`) already enforce the important separations:

- vendor SDKs may be imported only by their own connector module;
- `quant/` and `domain/` must stay importable with no network, no database, and no licensed extras;
- `apps/` and `workflows/` contain composition only, never financial formulas.

Those three rules are what make provider substitution and later process splitting possible. They matter more than the choice of scheduler or UI framework.

---

# 7. Tenancy, deployment and access model

**Status: PLANNED. Nothing in this section exists in code. Blocked on D1 and D2.**

Because the product is sold to external PMs (not used internally), this section is a precondition for Phase 7 onward — and the schema decision in 7.2 should be made *now*, while there are 19 tables rather than 40.

## 7.1 Deployment topologies

The commercial data model (section 9.0) largely determines the topology:

| Topology | Description | Fits data model |
|---|---|---|
| **T1 — Customer-hosted** | The customer runs the stack in their own environment, against their own vendor session | BYO-entitlement |
| **T2 — Single-tenant hosted** | One isolated deployment and database per customer, operated by us | Any |
| **T3 — Shared multi-tenant SaaS** | One deployment, tenant-scoped rows, operated by us | Licensed redistribution or redistributable vendor only |

T1 removes almost all data-licensing risk and is the fastest path to a first paying customer who already has Bloomberg or LSEG. Its cost is deployment and support friction, and the loss of cross-customer telemetry for tuning materiality.

T2 is the pragmatic middle: full isolation, no schema changes required, higher per-customer operating cost.

T3 is the only model with SaaS economics and the only one that requires redistribution rights.

**Recommendation:** design for T2 now (a `tenant_id` on every row, one database per customer initially) so that collapsing to T3 later is a deployment change rather than a migration. Do not build T3-specific machinery until D1 resolves.

## 7.2 Tenant isolation

Whichever topology is chosen, add the isolation boundary before more callers accumulate:

- a `tenant` table, and a non-nullable `tenant_id` on every row that holds customer data — coverage lists, portfolios, theses, findings, cards, feedback, backtest specs;
- reference data that is not customer-specific (securities, identifiers, price bars, corporate actions, factor definitions) stays shared, since duplicating price history per tenant is wasteful and creates reconciliation drift;
- tenant scoping enforced in the repository layer, not in route handlers, so a forgotten filter is impossible rather than merely unlikely;
- an integration test that asserts a tenant-scoped query cannot return another tenant's rows. This test is the deliverable, not the schema change.

If PostgreSQL row-level security is used, it supplements repository scoping — it does not replace it. Application-level bugs and RLS bypass via a superuser role are both real.

## 7.3 Authentication and authorization

Minimum viable for a beta with external customers:

- authentication via an identity provider (OIDC), not homegrown password storage;
- roles: `admin`, `pm`, `analyst`, `read_only`;
- API keys scoped per tenant for programmatic access, revocable, with last-used tracking;
- every mutation records actor, tenant, and timestamp in an append-only audit log;
- the audit log is the same lineage store described in section 36 — do not build a second one.

## 7.4 Entitlement enforcement

Under BYO-entitlement, the platform must be able to answer "is this customer allowed to see this field?" That means:

- an entitlement profile per tenant, listing permitted datasets, fields, regions and history depth;
- features tagged with the source fields they consume;
- a card that cannot be rendered within a tenant's entitlements is **suppressed with a visible reason**, never silently degraded to a partial number.

This is why section 34's rule "every number comes from a typed feature object" matters commercially and not only for correctness: field-level provenance is what makes entitlement enforcement mechanically possible.

---

# 8. Non-functional requirements

**Status: PLANNED. These numbers are targets to validate, not measurements.**

The plan previously specified no scale, latency, or cost envelope, which makes it impossible to judge whether PostgreSQL suffices, whether Timescale is warranted, or what a customer costs to serve. Initial targets:

## 8.1 Scale

| Dimension | Beta target | Design headroom |
|---|---|---|
| Securities per tenant (held + coverage) | 300 | 1,000 |
| Tenants | 5 | 50 |
| Distinct securities across all tenants | 2,000 | 10,000 |
| Daily price history depth | 15 years | 25 years |
| Price bars stored | ~7.5M rows | ~60M rows |
| Feature snapshots/day | ~2,000 securities × ~50 features = 100k rows/day | ~35M rows/year |

Feature snapshots, not price bars, are the row-count problem. Decide early whether every feature is persisted every day or only on change — the latter cuts volume by an order of magnitude but complicates as-of retrieval. **Persist every day initially**; correctness first, then optimize with evidence.

At these volumes plain PostgreSQL with correct indexing is sufficient. Revisit Timescale only if measured query latency fails 8.2.

## 8.2 Latency

| Operation | Target |
|---|---|
| Daily research run, 300 securities | < 10 min |
| Research card retrieval (API) | < 300 ms p95 |
| Company research page load | < 2 s p95 |
| Cross-sectional screen over 2,000 names | < 5 s |
| Backtest, 10 years × 500 names, cross-sectional | < 60 s |
| Event-driven card, from vendor event to persisted card | < 5 min |

The intraday path in section 29 exists precisely to hit the last row. A design that recomputes everything cannot.

## 8.3 Availability and correctness

- The daily brief must be complete before the customer's market open. Define this per tenant timezone, not in UTC.
- A failed run must be re-runnable and produce identical output — already guaranteed by deterministic IDs and idempotent persistence; keep it that way.
- Partial vendor failure degrades coverage for affected securities only, never corrupts a successful security. Already implemented; keep the test.
- Stale data is shown as stale. There is no acceptable path where the UI presents an old number as current.

## 8.4 Cost envelope

Track cost per tenant per month across vendor data, compute, storage, and LLM inference. LLM cost in particular scales with card volume and is the one line item that a materiality-threshold change can move by 10x — instrument it from the first synthesis call, not after the first surprising invoice.

---

# 9. Data-provider integration strategy

## 9.0 The entitlement constraint — read this before designing anything else

**This is the highest-risk item in the plan and it is a commercial constraint, not a technical one.**

The available access today is a **Bloomberg Terminal (desktop)** and an **LSEG Workspace (desktop)** session. Both are individual desktop licenses. Their standard terms:

- permit the named licensed user to consume data interactively on their own machine;
- prohibit redistribution of data to third parties;
- prohibit server-side, headless, or unattended systematic extraction;
- prohibit using the data to power a service delivered to other people.

Since the product is **sold to external PMs**, the conclusion is unavoidable:

> Desktop Terminal and Workspace entitlements can be used to **build, calibrate and validate** the research engine. They cannot supply data to the shipped product.

The previous version of this plan placed Bloomberg/LSEG connectors in the final phase, which conflated two entirely different pieces of work. They must be separated:

- **Research-mode connectors** — desktop sessions, analyst machine, used to develop and validate the estimate/valuation/factor engines against real data. Legitimate under existing licenses. Needed early (see revised Phase 2).
- **Product-mode data** — whatever legally feeds a customer-facing deliverable. A separate connector track, a separate contract, and a gate on shipping to any customer.

Building the engine against fixtures and Yahoo and hoping to swap in a vendor at the end is the failure mode this separation prevents. Real vendor data has gaps, restatements, symbology drift, and timestamp semantics that fixtures never reproduce.

### Commercial data models (Decision D1)

| | **M1 — BYO entitlement** | **M2 — Licensed redistribution** | **M3 — Redistributable vendor** |
|---|---|---|---|
| Mechanism | Connector runs inside the customer's environment against *their* Bloomberg/LSEG session | We buy B-PIPE / Data License or an LSEG platform contract with redistribution rights | A mid-tier vendor whose contract explicitly permits derived-data redistribution |
| Data leaves customer | No | Yes | Yes |
| Licensing risk | Lowest | Low, but contract-dependent | Medium — verify the clause, do not assume |
| Cost to us | Near zero | High (typically six figures/year) | Low to moderate |
| Deployment | T1 customer-hosted | T3 SaaS | T3 SaaS |
| Coverage/quality | Excellent (customer's own entitlement) | Excellent | Variable, generally weaker outside US large-cap |
| Time to first customer | Fast — if the customer already has a terminal | Slow — contract negotiation | Moderate |

**Recommendation:** start with **M1**. The target customer is a PM who already pays for Bloomberg or LSEG; asking them to point the connector at their own session is a smaller ask than it appears, and it converts the single largest legal risk into a deployment question. Revisit M2 once there are enough customers to justify the contract, or M3 if customer-hosted deployment proves to be the sales blocker.

**M1 has a real cost worth naming:** customer-hosted deployments mean no central telemetry, harder support, slower iteration, and materiality tuning that cannot learn across the customer base. Section 35.3's feedback loop becomes per-tenant rather than global. Plan for that.

### The derived-data question (Decision D6)

Many vendor contracts distinguish raw field redistribution from **derived value** redistribution. A z-score, a residual return, a percentile rank, or a regression coefficient may be distributable where the underlying field is not.

This matters more than it first appears: the research card in section 26 is mostly derived numbers. If derived-data redistribution is permitted, a hybrid becomes viable — compute against a licensed source, ship only derived values, and show raw fields only to customers whose own entitlement covers them.

**Action:** put this question to vendor counsel in writing before committing to D1. The answer can change the recommended model. Do not rely on an informal answer from a sales representative.

### Non-negotiable connector rules

These are already enforced in `docs/vendor_entitlements.md` and in the placeholder connectors. Keep them:

- entitlement and quota failures raise explicit errors — never a zero, a stale value, or a silent fallback to another provider;
- quant modules never import a vendor SDK;
- every record stores provider, source identifier, source timestamp, `available_at`, and ingestion time;
- raw vendor payloads are retained only where the contract permits, and retention is configured per provider rather than assumed;
- secrets live in environment or secret stores, never in YAML, logs, cards, or fixtures.

## 9.1 Bloomberg

Build a connector interface so the research engine does not care whether data comes from Bloomberg, LSEG or another source. **Status: BOUNDARY** — `connectors/bloomberg/provider.py` raises rather than reporting false success, which is correct and should not be "fixed" by returning stub data.

### Research mode (available now)

With an entitled Terminal running locally, `blpapi` can serve research development: pulling estimate history, fundamentals, and reference data for the securities used to build and validate the estimate/valuation engines.

Constraints to encode in the connector itself, so they are structural rather than remembered:

- desktop session only; refuse to start if a server-mode configuration is detected;
- respect daily and monthly data-point limits; surface remaining quota rather than discovering exhaustion mid-run;
- rate-limit and cache aggressively — repeated identical requests during development waste finite quota;
- tag every record produced in research mode with `entitlement_mode="research"` so it can never be served into a customer-facing card by accident.

That last rule is the important one. It is the mechanism that keeps the licensing boundary from depending on developer discipline.

### Product mode (blocked on D1)

B-PIPE, Data License, or Server API, subject to a contract with explicit redistribution terms. Not started; do not start before D1.

## 9.2 LSEG

Use the LSEG Data Library for Python behind the same provider interface. **Status: BOUNDARY.** The `lseg` extra installs the library, but access requires an approved session.

Two operating modes, mapping onto the same research/product split:

- **desktop / Workspace session** — analyst development and validation. Available now, research mode only;
- **platform / cloud session** — server-side production. Requires a separate contract. Blocked on D1.

Apply the same `entitlement_mode` tagging as Bloomberg.

Create explicit mappings for:

- RICs;
- fundamentals;
- estimates;
- pricing;
- news;
- economic data;
- ownership / ESG / other content

## 9.3 SEC and regulatory data

For U.S. issuers:

- use SEC EDGAR submissions APIs for filing metadata;
- use Company Facts / XBRL data for structured financial facts;
- retain the filing text or relevant sections for document-diff analysis;
- respect SEC fair-access guidance.

For Europe and other regions, add local regulatory / issuer feeds as separate connectors.

## 9.4 Macro data

Use a canonical macro-event schema even if multiple providers are used.

Potential sources:

- Bloomberg / LSEG economic calendars;
- FRED for many U.S. macro time series;
- official central-bank and statistical-agency APIs;
- ECB / Eurostat / BLS / BEA where needed.

Every macro observation should distinguish:

```text
period_end
release_timestamp
actual
consensus
prior
revised_prior
surprise
revision
source
```

The distinction between `release_timestamp` and `period_end` is the entire point. A CPI print for period_end 2026-07-31 released on 2026-08-12 must not be visible to a backtest on 2026-08-01. `available_at` is the release timestamp, never the period end.

---

# 10. Data quality, reconciliation and symbology

**Status: PARTIAL.** `ingestion/quality.py` and `normalization/` implement validation and canonicalization for prices. Nothing yet handles multi-provider disagreement, because there has never been more than one real provider.

This section exists because the plan previously jumped from "integrate vendors" to "calculate features" with no account of what happens when the data is wrong — which, with real vendor feeds, is routinely.

## 10.1 Symbology and identifier drift

The security master already models time-bounded external identifiers, which is the right foundation. The operational hazards to handle:

- **Ticker reuse.** A ticker freed by a delisting gets reassigned. Identifier resolution must be as-of, never "latest wins."
- **Cross-vendor identifier mismatch.** Bloomberg tickers, RICs, ISINs, CUSIPs, FIGIs and internal IDs all disagree at the edges — dual listings, ADRs vs ordinaries, share classes.
- **Corporate action symbology changes.** Mergers, spin-offs, redomiciliations.
- **The ADR/ordinary trap.** A finding calculated on the ordinary line and displayed against the ADR position is wrong in both price and currency.

Anchor on a vendor-neutral internal UUID (already the case) and treat every vendor identifier as a time-bounded mapping (already the case). Add: an unresolvable or ambiguous identifier is a **loud ingestion failure for that security**, never a silent skip and never a best guess.

## 10.2 Cross-provider reconciliation

When two entitled sources disagree, the system must not silently pick one.

- store **both** observations with their provider tags;
- apply a configured, versioned precedence rule per field family, recorded alongside the result;
- when the discrepancy exceeds a configured tolerance, emit a **data-quality finding** rather than a research finding;
- surface material unresolved conflicts on the card rather than reconciling them invisibly (this is already product guardrail 3 and rule 8 of section 34).

Tolerances differ by field: prices should agree to a few basis points, consensus estimates will legitimately differ between vendors because contributor panels differ. Do not apply one threshold to everything — and do not treat a consensus difference as an error when it is really a methodology difference.

## 10.3 Restatements and vintages

Fundamentals get restated; estimates get revised; macro series get revised. The point-in-time model already handles this correctly: a revision creates a **new vintage** and never overwrites what was knowable historically.

The gap is that nothing yet **detects** a restatement and asks whether it invalidates prior research. Add: when a new vintage materially changes a value that a published card relied on, flag the affected cards rather than rewriting them. A card is a record of what was known at a time; it should not be retroactively edited.

## 10.4 Corporate actions

The `corporate_action` table exists and price normalization uses adjusted close. Remaining work, in rough order of how badly each one corrupts research if missed:

- splits and reverse splits (silently corrupts every return series);
- dividends, special dividends (corrupts total return);
- spin-offs (corrupts both the parent series and the child's history);
- mergers, delistings (survivorship bias in backtests — see section 22);
- share class changes, redomiciliations, currency redenominations.

Every one of these needs a regression test with a known real-world example. A split-adjustment bug is invisible in unit tests and catastrophic in a backtest.

## 10.5 Operational data-quality checks

Run on every ingestion batch, failing loudly:

- staleness: no bar for a security on a session its exchange calendar says was open;
- outliers: single-session return beyond a configured sigma without a matching corporate action;
- gaps: missing sessions within a requested window;
- monotonicity: `available_at >= effective_at`, timestamps timezone-aware;
- coverage: securities requested vs securities returned, per provider;
- duplicate vintages for the same `(security, field, effective_at, provider)`.

Note the interaction with section 11: an unflagged corporate action produces exactly the same signature as a genuine abnormal return. The data-quality check must run **before** the anomaly engine, or the platform will confidently report a 3-sigma move that is actually a 2-for-1 split.

---

# 11. Quant module 1 — Price, volume and anomaly engine

For each stock calculate:

### Returns

- 1d / 2d / 5d / 20d / 63d / 126d / 252d total return;
- overnight gap;
- intraday return;
- relative return versus sector, industry, country and market;
- residual return after factor regression.

### Volatility

- realized volatility over multiple horizons;
- downside volatility;
- EWMA volatility;
- GARCH optionally for research, not required for MVP;
- volatility percentile versus own history;
- idiosyncratic volatility.

### Volume / liquidity

- volume z-score;
- dollar-volume z-score;
- turnover;
- Amihud-style illiquidity;
- bid/ask metrics if licensed intraday data exists;
- gap + volume combinations.

### Abnormal-move model

Instead of “stock fell 5%”, calculate:

```text
Expected return = market + sector + style factors + known event beta
Residual = actual - expected
Abnormality = residual / expected residual volatility
```

Alert logic should care much more about a **-3σ residual move** than a -3% move in a day when the entire sector is down 4%.

### Suggested research findings

- abnormal residual return > 2σ;
- unusual gap;
- unusual volume;
- realized-vol regime break;
- correlation breakdown;
- price / fundamental divergence.

---

# 12. Quant module 2 — Factor model and factor screens

## 12.1 Initial style factors

Build transparent factors before buying / licensing a complex commercial model.

Suggested equity factors:

- market beta;
- size;
- value;
- momentum 12-1;
- short-term reversal;
- quality;
- profitability;
- growth;
- leverage;
- low volatility;
- earnings revisions;
- earnings quality / accruals;
- dividend / shareholder yield;
- liquidity;
- crowding proxies where data permits.

Normalize signals by region / sector where appropriate.

## 12.2 Exposure estimation

For each stock retain:

```text
raw feature
winsorized feature
cross-sectional z-score
sector-neutral z-score
factor exposure
percentile
change over 1m / 3m
```

## 12.3 Factor returns

Estimate daily / weekly factor returns through cross-sectional regression or construct factor-mimicking portfolios.

This lets the platform answer:

> “Was the move company-specific, sector-driven, or simply a momentum / value factor move?”

## 12.4 Factor screen examples

- positive revisions + cheap + improving momentum;
- quality compounders with temporary residual drawdowns;
- expensive momentum names with deteriorating revisions;
- factor-neutral industry pairs;
- crowded high-beta names with volatility breakout;
- low-vol names becoming high residual-vol outliers.

## 12.5 Factor risk dashboard

For a stock:

- current exposures;
- 1m / 3m exposure changes;
- expected volatility decomposition;
- top factor sensitivities;
- peer percentile;
- historical factor regime performance.

For uploaded holdings, optionally aggregate:

- weighted style exposures;
- sector / country exposure;
- factor contribution to predicted variance;
- concentration by correlated cluster;
- major macro sensitivities.

Again, this is contextual research, not a replacement for a risk-management system.

---

# 13. Quant module 3 — Estimate revision engine

Track point-in-time estimates for:

- sales;
- EBITDA / EBIT;
- EPS;
- FCF;
- capex;
- segment KPIs where available;
- next quarter, FY1, FY2, FY3;
- guidance where machine-readable or extracted from filings / transcripts.

Features:

### Revision magnitude

```text
revision_1d  = consensus_now / consensus_1d_ago - 1
revision_7d
revision_30d
revision_since_last_earnings
```

### Revision breadth

```text
(# analysts raising - # analysts cutting) / # analysts changing
```

### Revision diffusion / acceleration

- 7d breadth versus 30d breadth;
- number of consecutive estimate cuts;
- FY1 versus FY2 divergence;
- revenue versus margin revision mismatch.

### Dispersion

- analyst estimate dispersion;
- dispersion change;
- outlier analysts;
- uncertainty proxy.

### Price-response mismatch

Example research insight:

> EPS consensus -5% over 30 days but shares +2%; historically this combination has produced negative subsequent residual returns in this peer group.

This becomes testable in the Backtest Lab.

---

# 14. Quant module 4 — Earnings and guidance research

Generalize the prototype's earnings-event window into a full point-in-time event-study engine.

For each earnings event calculate:

- EPS / sales surprise;
- margin surprise;
- guidance surprise;
- estimate revisions immediately after the event;
- open gap;
- day-0 residual return;
- day +1 / +5 / +20 drift;
- volume surprise;
- options-implied move versus realized move;
- peer sympathy reaction;
- sector-adjusted and factor-adjusted return.

Historical conditional questions:

- What happens after this stock misses EPS but raises revenue guidance?
- What is the average 5d residual drift after >2σ earnings gaps?
- Does positive guidance matter more when the valuation is below its 5Y median?
- How do high-revision-breadth events perform versus low-breadth events?
- Is post-earnings drift stronger in high-momentum regimes?

Use sample-size warnings and avoid presenting tiny-N results as reliable edges.

---

# 15. Quant module 5 — Valuation engine

Store point-in-time valuation metrics, not only the latest values.

Suggested metrics:

- P/E NTM / FY1 / FY2;
- EV/EBITDA;
- EV/EBIT;
- EV/Sales;
- P/FCF;
- FCF yield;
- earnings yield;
- dividend yield;
- price/book where relevant;
- PEG / growth-adjusted multiples;
- sum-of-the-parts components where user-defined.

For each metric calculate:

- 3Y / 5Y / 10Y median;
- z-score;
- percentile;
- premium / discount to industry peers;
- premium / discount after controlling for quality / growth;
- sensitivity to forecast revisions.

### Valuation decomposition

A useful research object is:

```text
Price change ≈ earnings revision + multiple re-rating + FX / other
```

Example:

```text
Stock -14% over 3 months
NTM EPS -3%
NTM P/E -11%
Conclusion: drawdown is mainly multiple compression, not earnings deterioration.
```

---

# 16. Quant module 6 — Macro sensitivity engine

The attached script's FOMC and CPI event studies should become a generalized macro research framework.

## 16.1 Macro factors

Examples:

- 2Y / 10Y rates;
- yield-curve slope;
- real yields;
- inflation breakevens;
- USD / EUR / JPY / CNY;
- oil / gas / copper;
- credit spreads;
- VIX / volatility regime;
- PMI / ISM;
- CPI / PPI;
- payrolls;
- central-bank decisions.

## 16.2 Rolling sensitivities

Estimate stock sensitivity to macro factors using rolling regressions and shrinkage.

For example:

```text
ASML 126d sensitivity:
EURUSD: +0.31
US 10Y real yield: -0.42
SOX index: +1.18
China semiconductor basket: +0.37
```

Use standardized changes so coefficients are interpretable.

---

# 17. Quant module 7 — Filings and fundamental-change engine

## 17.1 Structured filing changes

From regulatory data and vendor fundamentals detect:

- revenue / margin / cash-flow changes;
- debt issuance / maturity changes;
- share count changes;
- capex changes;
- working-capital anomalies;
- segment-mix changes;
- restructuring charges;
- buyback authorization;
- insider transactions;
- accounting-policy changes.

## 17.2 AI-assisted filing diff

For each new filing:

1. segment document into logical sections;
2. compare against previous filing;
3. identify new / removed / materially altered statements;
4. extract named risks and quantitative claims;
5. map changes to the stored thesis;
6. generate a compact evidence-backed finding.

### Good AI task

> “Risk Factors added a new paragraph stating that China export restrictions may delay shipment of advanced lithography systems.”

### Bad AI task

> “Estimate ASML FY27 EPS based purely on prose.”

Numerical forecasts should come from models and validated datasets, not ungrounded language generation.

---

# 18. Quant module 8 — News intelligence

Raw news volume is not research.

The news pipeline should:

1. ingest licensed news;
2. identify entities and securities;
3. cluster duplicate / syndicated stories;
4. identify the original catalyst;
5. classify catalyst type;
6. measure novelty versus recent coverage;
7. estimate thesis relevance;
8. combine with market / estimate response;
9. create a research finding only when the combined materiality is high enough.

Catalyst taxonomy:

- earnings;
- guidance;
- product;
- customer;
- supplier;
- regulation;
- litigation;
- management;
- capital allocation;
- M&A;
- geopolitics;
- industry data;
- analyst revision;
- macro exposure.

Do not use raw sentiment as a primary signal. “Positive / negative” sentiment is less useful than **what changed, how novel it is, and whether prices / estimates responded**.

---

# 19. Quant module 9 — Options / positioning research

Where historical options data is licensed, move well beyond the current-chain snapshot in the prototype.

Features:

- ATM implied volatility;
- IV term structure;
- 25-delta risk reversal;
- put / call skew;
- IV percentile;
- implied versus realized spread;
- earnings implied move;
- volume / open-interest changes;
- unusual strike concentration;
- downside skew changes;
- volatility-of-volatility proxy.

Research questions:

- Is the options market pricing an unusually large earnings move?
- Did downside skew jump without a corresponding stock move?
- Is IV rich or cheap versus the stock's own earnings history?
- Are large volume changes explained by roll activity or genuinely unusual positioning?

Do not label option activity “bullish” or “bearish” from a single put/call ratio without context.

---

# 20. Quant module 10 — Ownership, short interest and crowding

Generalize the existing ownership / short-interest sections.

Potential features:

- short % float;
- days to cover;
- change in short interest;
- borrow cost where licensed;
- ownership concentration;
- institutional ownership change;
- insider buy / sell intensity;
- ETF ownership;
- passive ownership;
- factor crowding proxies;
- correlation to crowded baskets.

Use these mainly as conditioning variables and risk diagnostics rather than simplistic trading signals.

---

# 21. Statistical research standards

The current prototype's t-tests are fine for exploration, but production research needs stricter standards.

## 21.1 Avoid naive p-value mining

Use:

- minimum sample sizes;
- bootstrap confidence intervals;
- Newey-West / HAC standard errors where appropriate;
- block bootstrap for serially dependent returns;
- false-discovery-rate control when testing many signals;
- out-of-sample testing;
- walk-forward validation;
- sub-period stability;
- regime analysis;
- parameter sensitivity.

## 21.2 Report economic significance

A statistically significant 3 bps effect may be useless.

Every signal report should include:

- effect size;
- t-stat / confidence interval;
- sample size;
- turnover;
- estimated transaction costs;
- capacity / liquidity proxy;
- stability across time;
- stability across regions / sectors;
- sensitivity to parameter choices.

## 21.3 Multiple hypothesis control

If the platform automatically tests hundreds of patterns, it must store the number of hypotheses tested and apply a multiple-testing framework. Otherwise the autonomous research engine will manufacture false “edges.”

---

# 22. Point-in-time backtesting architecture

This is a core product capability, not an optional add-on.

## 22.1 Hard rule

A backtest may only use information that was **actually available at the simulated time**.

Required controls:

- historical index membership;
- delisted securities;
- corporate actions;
- split-adjusted prices;
- publication timestamps;
- estimate snapshots / vintages;
- filing timestamps;
- macro revisions and initial releases;
- fundamental restatements;
- survivorship-bias control;
- look-ahead-bias tests.

## 22.2 Signal lifecycle

raw data
→ normalized point-in-time record
→ feature calculation
→ signal
→ portfolio / rank rule
→ execution assumption
→ costs
→ performance
→ diagnostics


## 22.3 Backtest types

### Cross-sectional factor test

- sort universe by signal;
- deciles / quintiles;
- top-minus-bottom;
- sector neutralization;
- beta neutralization;
- rank IC.

### Event study

- earnings;
- estimate revision;
- filing;
- macro surprise;
- management change;
- regulatory announcement.

### Screen simulation

Test combinations of filters and factors.

### Security-specific historical analogue

Example:

> “For ASML, find prior sessions where the stock had a < -2σ residual return and FY2 EPS consensus had fallen >2% in the preceding 10 days.”

This is particularly useful for the RaaS product because it can appear directly inside a material-development card.

---

# 23. Signal and screen definition language

**Status: PARTIAL.** `screens/models.py` and `screens/engine.py` exist. What is missing is the property that makes them valuable.

Section 33 asserts the design principle — "live research and backtesting should share feature definitions" — but the plan never specified the object that makes it true. This section does.

## 23.1 The shared-definition property

A screen is a **declarative, versioned, serializable object** that names features, thresholds and combination logic. It never contains code paths that differ between live and historical evaluation.

This object already exists as `ScreenDefinition` in `screens/models.py`, with `extra="forbid"` so an unrecognized key is a validation error rather than a silently ignored field. The implemented contract:

```yaml
schema_version: 1
screen_id: abnormal-residual-decline-v0      # version is carried in the id
name: Abnormal residual decline
description: ""
enabled: true                                 # disabled until inputs exist
universe: coverage
as_of_policy: latest_complete_session
minimum_history_sessions: 126
requires_features: []                         # declared dependencies
conditions:                                   # min 1
  - feature: residual_return_zscore_1d
    operator: less_than_or_equal              # or greater_than[_or_equal],
    value: -2.0                               #    less_than, between, is_finite
rank:
  feature: residual_return_zscore_1d
  direction: ascending                        # ascending | descending
limit: 25
missing_policy: exclude                       # exclude | fail
```

Every referenced feature must exist in the feature registry with a declared name, parameters, units, horizon and code version. A screen referencing an unregistered feature fails validation rather than evaluating to empty.

### Fields still to add

The current schema covers filtering and ranking but not the neutralization the Backtest Lab spec in section 4.1 E requires. Extend `ScreenDefinition` with:

- `neutralize: [sector, beta, country]` — applied identically in live and historical evaluation;
- universe liquidity filters (`min_adv_usd`), so a screen cannot select names that could not be traded;
- an explicit `feature_config_version` so a stored result names the feature definitions that produced it.

Add these as new optional fields with defaults, so existing screen configs keep validating.

## 23.2 The test that proves it

This property is worth nothing unless it is enforced mechanically. The deliverable is a test, not a design note:

> Evaluate screen S at historical date D through the **live** path, using only data with `available_at <= D`. Evaluate the same screen at the same date through the **backtest** path. Assert the selected security sets and ranks are identical.

If those paths ever diverge, backtest results stop predicting live behavior and the Backtest Lab becomes actively misleading — worse than not having one, because it manufactures false confidence.

## 23.3 Versioning

Screens and features are versioned and immutable once used. Changing a threshold creates a new version rather than mutating the existing one, because a stored backtest result must remain interpretable — a result whose definition has since changed underneath it is unreproducible.

Store with every backtest run: screen version, feature code versions, config versions, universe definition, and the data vintage cutoff.

## 23.4 Guarding against generated specs

Section 34 rule 10 requires AI-generated backtest specifications to be validated against an allowed schema before execution. This is that schema. The natural-language-to-backtest assistant emits **this object and nothing else** — never executable code, never SQL. Validation happens before execution, and an invalid spec is rejected with a reason rather than repaired by guessing.

---

# 24. Thesis model

**Status: BOUNDARY.** `thesis` and `thesis_version` tables exist; `research/thesis.py` is 24 lines and excluded from coverage.

This is the plan's largest unspecified dependency. `thesis_relevance_score` carries a 0.15 weight — the joint-second heaviest component in the materiality formula of section 25, behind only `estimate_change` at 0.20 — and nothing currently produces it. "Thesis impact" appears on every research card in section 26. Until this section is implemented, the materiality score runs on 85% of its intended weight and the most differentiated field on the card cannot be populated.

Crucially, thesis relevance is **not blocked on any vendor**. The deterministic path in 24.2 needs only PM-authored text and features the system already computes. See section 25.2 for why that makes it the highest-leverage unblocked work in the plan.

## 24.1 What a thesis is

A thesis is the PM's structured, versioned statement of why they own (or watch) a security and what would change their mind. It is **PM-authored**; the system never invents or silently edits one (product guardrail; section 34 rule 9).

```yaml
thesis_id: asml_core
security: ASML NA
created_by: pm@customer.com
version: 4
summary: >
  EUV monopoly supports pricing power and above-consensus FY27 volumes;
  China restrictions are a manageable headwind, not a structural break.
drivers:
  - id: euv_volumes
    statement: FY27 EUV unit shipments >= 60
    supporting_features: [eps_revision_fy3, revenue_estimate_fy3]
    direction: positive
  - id: china_exposure
    statement: China revenue share declines gradually, not abruptly
    supporting_features: [china_revenue_pct, policy_news_score]
    direction: negative
risks:
  - id: export_controls
    statement: Tighter export restrictions delay advanced system shipments
    watch_features: [filing_risk_factor_delta, policy_news_score]
    severity: high
invalidation:
  - FY27 consensus EPS falls more than 15% from thesis-inception level
  - EUV order backlog declines for two consecutive quarters
```

## 24.2 How relevance is computed

`thesis_relevance_score` is the mapping from a finding to the thesis nodes it touches. Deterministic first, AI-assisted only for the text-to-node mapping:

1. **Feature overlap (deterministic).** A finding whose driving features appear in a driver's `supporting_features` or a risk's `watch_features` is relevant. This alone covers the numeric finding families and requires no LLM.
2. **Invalidation proximity (deterministic).** How close the finding moves a stated invalidation condition to being met. A finding that crosses an invalidation threshold scores maximum relevance by construction.
3. **Semantic mapping (AI-assisted).** For filings and news where there is no feature linkage, map the extracted statement to thesis nodes. This is a *classification* task over PM-authored text — a good AI task by section 17's standard. The model selects among existing nodes; it never creates one.

Keep 1 and 2 deterministic and auditable. They are enough to unblock materiality v1 without any LLM dependency, which matters because D3 is unresolved.

## 24.3 Thesis lifecycle

- versioned and append-only; a card always references the version current when it was produced;
- PM edits create a new version, never mutate the old one;
- the system may **propose** an update in response to an invalidation trigger, but it lands only on explicit PM approval;
- a security with no thesis is legitimate — findings then score with `thesis_relevance_score` absent, and the existing `completeness` field on `MaterialityScore` already records that honestly.

That last point matters for adoption. Requiring a PM to author 100 theses before the product produces anything is a non-starter. The product must be useful with zero theses and get sharper as they are added.

---

# 25. Materiality engine — the heart of the product

## 25.1 Two-stage approach

### Stage 1 — deterministic quantitative score

Illustrative:

```text
Q =
  0.20 × estimate_change_score
+ 0.15 × abnormal_price_score
+ 0.10 × abnormal_volume_score
+ 0.10 × valuation_change_score
+ 0.10 × factor_change_score
+ 0.10 × fundamental_change_score
+ 0.10 × event_novelty_score
+ 0.15 × thesis_relevance_score
```

Portfolio weight can be applied as a **priority modifier**, not as the definition of research materiality.

```text
priority = Q × (1 + k × sqrt(position_weight))
```

This prevents the system from ignoring a major development in a small position while still placing a 5% holding above a 20 bps holding when evidence is otherwise similar.

### Stage 2 — AI synthesis / deduplication

The LLM receives the top structured findings and:

- merges correlated events;
- removes duplication;
- identifies the main causal chain;
- maps to thesis;
- produces one research card.

Example event chain:

```text
Company cuts guidance
→ 14 analysts cut FY27 EPS
→ stock falls 7%
→ sector falls 2%
→ residual move -2.4σ
→ P/E compresses from 30x to 27x
```

This should become **one** material development, not five alerts.

## 25.2 The score is currently capped below its own thresholds

This is the sharpest available illustration of the "no real data" problem in section 0.3, and it is worth stating numerically because it converts a vague gap into a measurable one.

The implemented config (`configs/materiality/default.yaml`) matches the formula above exactly, and its own comment records the consequence. Grouping components by what unblocks them:

| Component | Weight | Available today? |
|---|---|---|
| `abnormal_price` | 0.15 | Yes |
| `abnormal_volume` | 0.10 | Yes |
| `factor_change` | 0.10 | Yes |
| `event_novelty` | 0.10 | Yes |
| **Subtotal — no dependency** | **0.45** | |
| `thesis_relevance` | 0.15 | Blocked on §24 only — **no vendor needed** |
| **Subtotal — after thesis** | **0.60** | |
| `estimate_change` | 0.20 | Blocked on vendor connector |
| `valuation_change` | 0.10 | Blocked on vendor connector |
| `fundamental_change` | 0.10 | Blocked on vendor connector |
| **Total** | **1.00** | |

Against thresholds of `critical` 0.80, `material` 0.65 and `watch` 0.30:

> **Today the system cannot produce a `material` or `critical` card at all.** Even a perfect price/volume/factor/novelty signal reaches 0.45 and lands in `watch`.

Implementing the thesis model lifts the ceiling to 0.60 — still short of `material`. **Only vendor data can produce a `material` card.** That single fact is the strongest argument for the roadmap reordering in section 38: no amount of engineering on the existing modules can produce the product's headline output.

Two corollaries worth acting on:

- the `watch` threshold comment in the config is honest engineering and should stay, but the thresholds must be **recalibrated when each component group lands** — otherwise the inbox goes from empty to flooded the day estimates arrive;
- `completeness` (already implemented on `MaterialityScore`) should be surfaced on the card. A 0.45 score built from four of eight components is a different claim from a 0.45 built from all eight, and the PM should be able to see which they are looking at.

## 25.3 Calibration — how the weights get set

**Status: BUILT for the mechanism, PLANNED for the calibration.**

The weights in 25.1 are already implemented as configuration (`configs/materiality/default.yaml`), validated to sum to one, and versioned via `score_version`. The mechanism is right. What the plan never said is **where the numbers come from**, and "0.20 / 0.15 / 0.10 …" is currently an educated guess presented with unwarranted precision.

Honest sequencing:

1. **v0 (now).** Uniform-ish judgment weights. State plainly that they are unvalidated. Track `completeness` so a score built from two of eight components is not mistaken for a confident one — already implemented.
2. **v1.** Once several finding families exist, calibrate against a **labeled historical set**: real events over a past window, each rated by a PM for whether it deserved attention. Fit weights to maximize top-of-inbox precision (section 3.2).
3. **v2.** Incorporate live PM feedback per section 35.3.

Two guardrails on the learning loop:

- feedback tunes **ranking and suppression only**. It never alters a deterministic financial calculation (section 35.3 already says this — it is worth repeating because it is the rule most likely to be broken under pressure to "make the inbox better").
- weights are versioned and every card records the version that produced it, so a ranking change is attributable rather than mysterious.

### Threshold selection

The push threshold is a product decision disguised as a parameter. Too low and the product becomes the alert firehose it exists to replace; too high and the PM misses something and stops trusting it.

Set the initial threshold by **target volume, not by score**: calibrate so the daily brief contains 3–8 cards for a 100-name portfolio (section 4.1's own target). Then let feedback move it. Instrument the distribution of scores from day one — the threshold cannot be chosen sensibly without knowing the shape of that distribution.

## 25.4 Stage-2 failure modes

The AI synthesis stage is where fabrication risk concentrates. Specific failure modes to test for, beyond the general rules in section 34:

- **Over-merging.** Two genuinely independent developments compressed into one card, hiding one of them. Test with known-independent same-day events.
- **Causal invention.** Asserting that A caused B when the data shows only that both occurred. The causal chain must be constructed from timestamps and evidence links, not inferred by the model from co-occurrence.
- **Number drift.** A figure in the prose differing from the evidence object. Rule 3 requires cross-checking; make it a hard gate that blocks release, not a logged warning.
- **Silent dropping.** A high-scoring finding omitted from the merged card. Assert that every input finding is either represented in the output or explicitly recorded as suppressed with a reason.

If stage 2 is unavailable or fails validation, the system falls back to publishing the **deterministic stage-1 findings, unmerged**. Degraded compression is an acceptable outcome; no output, or unvalidated output, is not.

---

# 26. Research-card schema

Every pushed card should have a consistent structure.

```text
[Security] — [Materiality label]

CHANGE
What objectively changed?

QUANT EVIDENCE
Estimate revisions
Residual move
Volume / volatility
Valuation
Factor changes
Historical analogue

CONTEXT
Position weight if available
Sector / peer move
Relevant macro event

THESIS IMPACT
Low / Moderate / High
Which thesis node changed?

KEY RISK / OPPORTUNITY
One concise statement

CONFIDENCE
High / Medium / Low

SOURCES
Timestamped source references

NEXT RESEARCH QUESTION
The most useful follow-up for the PM.
```

---

# 27. Risk dashboards

## 27.1 Security-level risk dashboard

For every researched stock:

- beta;
- residual vol;
- downside vol;
- VaR / expected shortfall as contextual diagnostics;
- factor exposures;
- correlation to sector / market;
- macro sensitivities;
- gap risk history;
- earnings-event risk;
- valuation percentile;
- options-implied risk;
- liquidity;
- crowding / short interest;
- drawdown profile.

## 27.2 Coverage-universe dashboard

Across all researched stocks:

- exposure heatmap;
- correlation clustering;
- factor outliers;
- volatility outliers;
- revision outliers;
- valuation outliers;
- residual momentum leaders / laggards;
- upcoming event density.

## 27.3 Optional holdings overlay

If weights are provided:

- factor-weighted exposure;
- top correlated clusters by NAV;
- macro sensitivity concentration;
- contribution from abnormal moves;
- upcoming earnings weight.

Keep this concise so the platform remains a research product.

---

# 28. Research scheduler

Different research tasks require different cadences.

## Intraday / event-driven

- price anomalies;
- volume anomalies;
- news clusters;
- filings;
- estimate revisions where feed permits;
- earnings;
- macro releases;
- options changes where data permits.

## End of day

- factor exposures;
- factor returns;
- residual moves;
- valuation percentiles;
- screen refresh;
- risk diagnostics.

## Weekly

- deeper factor screens;
- correlation / cluster changes;
- medium-term estimate trends;
- signal decay diagnostics;
- thesis-risk summary.

## Monthly / quarterly

- full research refresh;
- backtest revalidation;
- factor-definition review;
- model calibration;
- materiality-threshold tuning.

---

# 29. Event-driven orchestration

Flow:

```text
Vendor event
→ ingest
→ normalize
→ update relevant features
→ run affected quant modules only
→ emit candidate findings
→ materiality ranking
→ AI synthesis
→ persist research card
→ push only if threshold exceeded
```

Do not recalculate every feature for every stock whenever a single news article arrives.

---

# 30. Codebase structure

This is the **actual** tree, annotated with status, rather than a proposal. The package lives at `src/quant_raas/` (a `src` layout, so tests import the installed package rather than repository files).

```text
quant-raas/
│
├── apps/                          composition only — no financial formulas
│   ├── api/                       BUILT (9 routes; no auth, no tenancy)
│   ├── dashboard/                 BUILT (Streamlit)
│   └── worker/                    PARTIAL (entrypoint; nothing schedules it)
│
├── src/quant_raas/
│   ├── config.py                  BUILT
│   ├── runtime.py                 BUILT   (composition root)
│   ├── cli.py                     BUILT   (init-db, seed-demo, daily)
│   ├── demo.py                    BUILT   (deterministic offline demo)
│   │
│   ├── domain/                    BUILT   — typed contracts, no vendor deps
│   │   ├── base.py  enums.py  events.py  market.py
│   │   ├── portfolio.py  protocols.py  research.py  security.py
│   │
│   ├── security_master/           BUILT   (temporal resolution + importer)
│   ├── storage/                   BUILT   (19 tables, repositories, session)
│   ├── ingestion/                 BUILT   (prices, events, quality)
│   ├── normalization/             BUILT   (price_bars, identifiers,
│   │                                       economic_releases, snapshots)
│   ├── feature_store/             PARTIAL (registry; no panel retrieval API)
│   ├── services/                  PARTIAL — daily_research is price-only
│   │   ├── daily_research.py  close_workflow.py  portfolio_import.py
│   │
│   ├── connectors/
│   │   ├── base.py                BUILT   (provider protocol)
│   │   ├── fixture.py             BUILT   (deterministic, network-free)
│   │   ├── public_fallback/       BUILT   (Yahoo, opt-in extra)
│   │   ├── bloomberg/             BOUNDARY — raises; see section 9.1
│   │   ├── lseg/                  BOUNDARY
│   │   ├── sec/                   BOUNDARY
│   │   └── macro/                 BOUNDARY
│   │
│   ├── quant/                     BUILT — pure functions, no I/O
│   │   ├── returns.py  risk.py  anomalies.py  factors.py
│   │   ├── estimates.py  earnings.py  valuation.py  macro.py
│   │   ├── options.py  ownership.py  event_study.py
│   │   ├── statistics.py  seasonality.py
│   │
│   ├── screens/                   PARTIAL (models, engine; see section 23.2)
│   │   ├── models.py  engine.py
│   │
│   ├── backtest/                  PARTIAL — cross-sectional only
│   │   ├── engine.py  models.py  universe.py
│   │   ├── execution.py  costs.py  metrics.py  validation.py
│   │
│   ├── research/                  BUILT except thesis
│   │   ├── findings.py  materiality.py  cards.py
│   │   ├── evidence.py  reports.py  ids.py
│   │   └── thesis.py              BOUNDARY — see section 24
│   │
│   ├── ai/                        BOUNDARY except guardrails
│   │   ├── guardrails.py          BUILT
│   │   ├── structured_extract.py  filing_diff.py  synthesizer.py
│   │   ├── query_agent.py  backtest_agent.py  evals.py
│   │
│   └── common/                    BUILT (clock, errors, logging)
│
├── workflows/                     PARTIAL — plain modules, no scheduler (D4)
│   └── intraday.py  close.py  earnings.py  weekly_research.py
│
├── configs/                       BUILT
│   └── factors/  screens/  materiality/  universes/
│
├── migrations/                    BUILT (Alembic)
├── examples/                      BUILT (holdings.csv, coverage.csv)
├── docs/                          BUILT (architecture, data_contracts,
│                                        product_scope, vendor_entitlements,
│                                        wireframes)
├── tests/                         89 passing
│   ├── unit/  integration/  point_in_time/
│   └── backtest/  ai_evals/       PLANNED — directories not yet created
│
└── aapl_quant_research.py         legacy prototype; migration input only
```

### Deltas from the earlier proposal

Worth noting because they were good decisions that the plan should record rather than contradict:

- **`domain/`** was added and is the most important structural improvement — typed contracts with no vendor or I/O dependencies, which is what lets `quant/` stay pure and testable.
- **`storage/`** was split out from an implied persistence layer, keeping SQLAlchemy out of `research/` and `quant/`.
- **`services/`** holds orchestration that is neither pure calculation nor app composition.
- **`screens/`** became its own package rather than living under `research/`.
- **`notebooks/`** was not created. Leave it that way unless there is a real need; notebooks tend to accumulate untested logic that belongs in `quant/`.

---

# 31. Database tables

19 of the planned tables exist today. The gap between built and planned is a precise map of the remaining data work — and it lines up exactly with "every finding family except price/risk is blocked."

## 31.1 Built

```text
security                    security_identifier         benchmark_mapping
coverage_list               coverage_member             portfolio_snapshot
portfolio_position          ingestion_batch             price_bar
corporate_action            company_event               research_run
evidence_reference          feature_snapshot            research_finding
research_card               thesis                      thesis_version
materiality_feedback
```

## 31.2 Planned

| Table | Unblocks | Depends on |
|---|---|---|
| `fundamental_snapshot` | Valuation engine (§15) | Vendor connector |
| `estimate_snapshot` | Revision engine (§13) | Vendor connector |
| `estimate_contributor_snapshot` | Revision **breadth** and dispersion (§13) | Vendor connector, contributor-level entitlement |
| `valuation_snapshot` | Valuation history and z-scores (§15) | `fundamental_snapshot` + `estimate_snapshot` |
| `economic_release` | Macro sensitivity engine (§16) | Macro connector — FRED is free, start here |
| `filing` | Filing diff engine (§17) | SEC connector — free, start here |
| `news_document` | News intelligence (§18) | Licensed news feed |
| `options_snapshot` | Options/positioning (§19) | Historical options data — expensive, defer |
| `ownership_snapshot` | Ownership/crowding (§20) | Vendor connector |
| `factor_definition` / `factor_exposure` / `factor_return` | Factor Lab (§12) | Fundamentals for value/quality factors |
| `backtest_spec` / `backtest_run` / `backtest_metric` | Backtest Lab persistence (§22) | Nothing external — buildable now |
| `model_registry` | AI versioning and audit (§34, §36) | D3 |
| `tenant` + `tenant_id` on customer-owned rows | Everything commercial (§7) | D2 — **do this early** |
| `data_quality_event` | Reconciliation and staleness (§10) | Nothing external — buildable now |

### Two observations

**Contributor-level estimates are the expensive dependency.** Revision *breadth* — arguably the single most valuable signal in the whole spec, and the one that drives the ASML example in section 1 — needs per-analyst estimates, not just consensus. That is a materially more expensive entitlement than consensus alone. Confirm it is included before planning the revision engine around it, and design a consensus-only fallback for breadth-unavailable tenants.

**Three tables need no vendor at all**: `backtest_spec`/`run`/`metric`, `data_quality_event`, and the tenancy tables. Plus `filing` and `economic_release` via free sources (SEC EDGAR, FRED). That is real, unblocked work available regardless of how D1 resolves — which is why the revised roadmap in section 38 pulls it forward.

---

# 32. API surface

**Status: PARTIAL.** Nine routes exist under `/v1`, with no authentication and no tenant scoping.

## 32.1 Existing

```text
GET  /health
GET  /v1/securities
POST /v1/securities
POST /v1/coverage/validate        POST /v1/coverage/import
POST /v1/holdings/validate        POST /v1/holdings/import
POST /v1/research/runs
GET  /v1/research/cards
POST /v1/research/cards/{id}/feedback
```

The validate-then-import pairing is a good pattern — a PM uploading a holdings file gets errors before anything is persisted. Keep it for every future import.

## 32.2 Planned

```text
GET  /v1/securities/{id}/research      company research page (§4.1 B)
GET  /v1/securities/{id}/features      as-of feature retrieval
GET  /v1/securities/{id}/factors       exposures and changes (§12.5)
GET  /v1/brief                         morning brief (§4.1 F)
POST /v1/screens                       create/validate a screen (§23)
POST /v1/screens/{id}/run              evaluate live
POST /v1/backtests                     submit a spec (§22)
GET  /v1/backtests/{id}                status and results
CRUD /v1/theses                        PM-authored thesis (§24)
GET  /v1/data-quality                  freshness and conflicts (§10, §36)
GET  /v1/lineage/{card_id}             "why did this appear?" (§36)
```

## 32.3 Conventions

- **As-of is a first-class parameter.** Any research endpoint accepts an `as_of`; omitting it means "now" rather than "latest available regardless of availability." This is what makes the API honest about point-in-time and it must be uniform.
- Every response carries the data cutoff used and the maximum source `available_at`, so a client can always tell how fresh the answer is.
- Long-running work (backtests, full research runs) is submit-and-poll, not a blocking request.
- Errors are explicit and typed. An entitlement failure, a stale-data condition, and an empty result are three different responses — never one generic empty payload.
- Versioned under `/v1`; breaking changes get `/v2` rather than silent field changes, since customers integrate against this.

---

# 33. Example quantitative screen definitions

The same screen object should be executable both **today** and historically in the backtest engine.

This is an important design principle: **live research and backtesting should share feature definitions**. Section 23 specifies the object and the test that enforces this.

## 33.1 Worked examples

The section previously had a title and no examples. These use the implemented `ScreenDefinition` schema of section 23.1 and will validate as written.

`configs/screens/` currently holds three: `abnormal_residual_decline` and `relative_strength_breakout` are `enabled: true` because they need only price and benchmark data; `cheap_positive_revisions` is `enabled: false` pending estimates and valuation histories. That convention is good practice — it makes the data dependency visible instead of letting a screen silently return nothing.

### Dislocation without fundamental deterioration

The "residual drawdown with stable fundamentals" idea from section 4.1 D. Requires Phase 3.

```yaml
schema_version: 1
screen_id: unexplained-residual-drawdown-v0
name: Unexplained residual drawdown
description: Large company-specific decline without matching estimate deterioration.
enabled: false          # requires estimate + fundamental snapshots
universe: coverage
as_of_policy: latest_complete_session
minimum_history_sessions: 252
requires_features:
  - residual_return_zscore_20d
  - eps_revision_30d
  - gross_margin_change_2q
conditions:
  - {feature: residual_return_zscore_20d, operator: less_than_or_equal, value: -2.5}
  - {feature: eps_revision_30d, operator: greater_than_or_equal, value: -0.01}
  - {feature: gross_margin_change_2q, operator: greater_than_or_equal, value: -0.005}
rank:
  feature: residual_return_zscore_20d
  direction: ascending
limit: 25
missing_policy: exclude
```

### Estimate–price mismatch

The testable form of the research insight in section 13: consensus falling while the stock rises. Requires Phase 3.

```yaml
schema_version: 1
screen_id: revision-price-mismatch-v0
name: Estimate-price mismatch
description: FY2 consensus cut materially while the shares rose.
enabled: false          # requires estimate snapshots
universe: coverage
as_of_policy: latest_complete_session
minimum_history_sessions: 252
requires_features:
  - eps_revision_fy2_30d
  - total_return_30d
conditions:
  - {feature: eps_revision_fy2_30d, operator: less_than_or_equal, value: -0.05}
  - {feature: total_return_30d, operator: greater_than, value: 0.0}
rank:
  feature: eps_revision_fy2_30d
  direction: ascending
limit: 25
missing_policy: exclude
```

Note that `missing_policy: exclude` is the right default here but carries a subtlety worth stating: a name excluded for a missing feature is silently absent from results. For a screen a PM relies on, the count of excluded names must be reported alongside the results, or an entitlement gap will look like a genuinely empty screen.

---

# 34. AI safety and numerical integrity

For investment research, the system must be designed to minimize fabricated facts.

## Rules

1. LLM never calculates official P&L, valuation or risk metrics from prose.
2. All numbers passed to the LLM come from typed, validated feature objects.
3. Generated statements with numbers are cross-checked against the input object before release.
4. Every research card retains evidence IDs.
5. Every prompt and model version is logged.
6. AI can say “insufficient evidence.”
7. Data staleness is visible to the model and the user.
8. Conflicting sources are surfaced rather than silently reconciled.
9. Internal thesis updates require explicit PM approval.
10. AI-generated backtest specifications are validated against an allowed schema before execution.

## 34.1 Provider and data-handling decision (D3)

**Status: OPEN. No LLM provider is wired; `ai/guardrails.py` is the only real module in `ai/`.**

For a product sold to external PMs, the provider choice is a data-handling decision before it is a capability decision. What must be settled before the first synthesis call:

- **What leaves the customer's boundary.** Prompts will contain holdings, thesis text, and vendor-derived numbers. Under BYO-entitlement (M1), sending vendor content to a third-party model may breach the customer's own vendor contract, not just ours. Confirm this explicitly — it is a plausible reason to require a customer-hosted or customer-keyed model endpoint.
- **Training and retention.** Use an enterprise tier with no-training guarantees and defined retention. A consumer tier is not acceptable for customer portfolio data.
- **Residency.** European customers may require EU processing.
- **Fallback.** The system must degrade to deterministic stage-1 output when the provider is unavailable (§25.4). No LLM dependency may sit on the critical path of producing *some* useful output.

Structural rules regardless of provider:

- all model calls go through one narrow interface so the provider is swappable and every call is logged centrally;
- prompt version, model ID, input object hash, and output are persisted per card (`model_registry`, §31);
- the AI layer receives **typed feature objects**, never raw vendor payloads or free-form database dumps — this is what makes rule 2 mechanically enforceable rather than aspirational;
- cost and latency are recorded per call (§8.4).

---

# 35. Evaluation framework

## 35.1 Quant evaluation

For every feature:

- unit tests;
- known-value tests;
- vendor cross-checks;
- time-zone tests;
- corporate-action tests;
- point-in-time leakage tests;
- missing-data behavior;
- extreme-value behavior.

## 35.2 Research-card evaluation

Create a historical evaluation set of real events.

Score:

- factual accuracy;
- numerical accuracy;
- correct catalyst;
- correct thesis mapping;
- materiality ranking;
- duplication rate;
- missed-critical-event rate;
- concision;
- evidence quality.

## 35.3 PM feedback loop

Each card should collect feedback.

Use that feedback to tune:

- materiality weights;
- preferred event types;
- verbosity;
- thesis mapping;
- suppression rules.

Do not allow feedback learning to silently alter deterministic financial calculations.

---

# 36. Observability and auditability

For every research card the system should answer:

> “Why did this appear?”

Store:

```text
source events
raw records
normalized records
feature values
prior feature values
feature code version
materiality score components
AI input object
AI output
AI model / prompt version
user feedback
```

This creates a complete research lineage.

Operational monitoring:

- data-feed freshness;
- ingestion failures;
- missing securities;
- vendor quota / entitlement errors;
- stale estimates;
- scheduler delays;
- AI failure / refusal / malformed output rates;
- backtest job health.

---

# 37. Risk register

Ordered by expected damage. Each risk needs an owner and a review date.

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | **Desktop entitlements cannot legally feed a sold product** (§9.0) | Fatal — no shippable product | Certain, already true | Resolve D1. Default to BYO-entitlement (M1). Get D6 answered in writing |
| R2 | **Contributor-level estimates not entitled**, so revision breadth is unavailable | Severe — removes the flagship signal | Medium | Confirm entitlement before designing §13 around breadth. Build a consensus-only fallback |
| R3 | **Materiality never becomes trustworthy**; PM stops opening the brief | Fatal to adoption | Medium | Calibrate against labeled history (§25.3), instrument precision from the first beta, tune by target volume |
| R4 | **Tenancy retrofit** becomes prohibitively expensive | High — blocks commercial launch | High if deferred | Add `tenant_id` and repository-level scoping now, while the schema is 19 tables |
| R5 | **Look-ahead leak reaches production**, making backtests fraudulent | Severe — destroys credibility permanently | Low today, rises with each data source | Keep PIT assertions in the engine. Add the live-vs-backtest equivalence test (§23.2) as a merge gate |
| R6 | **Corporate-action bug** silently corrupts return series | High — every downstream number is wrong | Medium | Regression tests with known real-world splits/spins (§10.4). Run data-quality checks *before* the anomaly engine |
| R7 | **AI fabricates a number** that reaches a customer card | Severe — reputational, possibly regulatory | Medium without gating | Hard cross-check gate that blocks release (§34 rule 3, §25.4); evidence IDs on every claim |
| R8 | **Multiple-testing false edges** — autonomous testing manufactures spurious signals | High — the product confidently recommends noise | High by construction | FDR control, minimum sample sizes, hypothesis counting (§21.3). Store the number of hypotheses tested |
| R9 | **Quant modules built ahead of data** never get validated against reality | Medium — rework | Already occurring | Pull research-mode connectors forward (revised Phase 2); validate each quant module against real vendor data as it lands |
| R10 | **LLM cost scales unexpectedly** with card volume | Medium | Medium | Instrument per-call cost from the first call (§8.4); threshold changes move this by 10x |
| R11 | **Scheduler never chosen**, workflows stay manual | Medium — no autonomous product | Medium | Resolve D4. "Autonomous" is in the product name; a manual pipeline is not the product |
| R12 | **Single-developer key-person risk** on a 13.7k-line codebase | Medium | Medium | The existing discipline (strict typing, high coverage, documented contracts) is the mitigation. Maintain it — it is what makes the code transferable |

---

# 38. Build roadmap

## 38.0 What changed from the previous roadmap, and why

The earlier roadmap ordered work P0 spec → P1 quant MVP → P2 estimates + AI → P3 factor lab → P4 backtest → P5 Bloomberg/LSEG → P6 hardening. Three problems made it unbuildable as written:

1. **A circular dependency.** Phase 2 built "point-in-time estimate snapshots" while the estimates data source arrived in Phase 5. The estimates engine cannot be built before the estimates data. This is the defect that most needs fixing, and it is already visible in the codebase: `quant/estimates.py`, `valuation.py`, `options.py` and `ownership.py` are all written and tested against synthetic inputs, with no data source feeding any of them.
2. **Integration risk deferred to the end.** Building the entire engine against fixtures and swapping in real vendors last means every vendor surprise — symbology drift, restatements, timestamp semantics, gaps — lands at the point of maximum sunk cost.
3. **Licensing treated as a hardening task.** For a product sold externally, the entitlement model determines the architecture (§9.0). It belongs at the front, not in Phase 6.

The revised sequence separates research-mode from product-mode data (§9.0), pulls the vendor work forward, and front-loads the commercial gates.

## 38.1 Sequencing principles

- **Unblock data before building engines that consume it.**
- **Prove the differentiator early.** Compression (§1) is the product. It cannot be demonstrated until 2–3 finding families exist, so getting there is the priority — ahead of the factor lab and the backtester, both of which are supporting features.
- **Do the unblocked work in parallel.** Backtest persistence, data-quality events, tenancy, SEC and FRED connectors need no vendor decision and can proceed while D1 is open.
- **Every phase exits on a runnable assertion**, not a feeling of completeness.

---

## Phase 0 — Product specification and data contracts — **LARGELY COMPLETE**

Delivered: canonical security IDs, point-in-time data model, `ResearchFinding` and research-card schemas, materiality v0, holdings/coverage upload format, vendor-entitlement inventory template, architecture and scope docs.

Remaining:

- [ ] **Resolve D1** (commercial data model) — blocks Phase 6 and every customer conversation;
- [ ] **Resolve D6** (derived-data redistribution) in writing from vendor counsel;
- [ ] **Resolve D2** (tenancy model);
- [ ] initial UX wireframes beyond `docs/wireframes.md`;
- [ ] thesis schema (§24) — specified in this revision, not yet implemented.

**Exit criterion:** D1, D2 and D6 are recorded with an owner and a date, and the chosen data model is written into `docs/vendor_entitlements.md`.

---

## Phase 1 — Quant research MVP — **LARGELY COMPLETE**

Delivered: security master, price ingestion, benchmark mappings, event-study framework, abnormal-return engine, rolling risk metrics, simple factor exposures, Streamlit dashboard, research-card persistence, deterministic offline demo, 89 passing tests under strict typing.

Remaining:

- [ ] feature-store panel retrieval (cross-sectional as-of queries) — needed by screens and backtests;
- [ ] `data_quality_event` table and the checks in §10.5;
- [ ] the live-vs-backtest screen equivalence test (§23.2).

**Exit criterion (already met for the core):** upload 30–100 equities and receive reproducible daily research snapshots for every name, with identical output on re-run. Verify with `quant-raas seed-demo` followed by two `quant-raas daily` runs at the same `as_of` producing byte-identical cards.

---

## Phase 2 — Research-mode vendor connectors — **NEXT. Was Phase 5.**

The unblocking phase. Uses the existing desktop Bloomberg and LSEG entitlements for **research and validation only** (§9.0).

Build:

- `BloombergProvider` against a local Terminal session (desktop mode enforced in code);
- `LSEGProvider` against a Workspace session;
- field-mapping registry across RICs, tickers, ISINs, and internal UUIDs;
- request cache and quota tracking — surface remaining quota, never discover exhaustion mid-run;
- `entitlement_mode` tagging on every record (§9.1) so research-mode data can never reach a customer card;
- `fundamental_snapshot`, `estimate_snapshot`, `estimate_contributor_snapshot` tables;
- cross-provider reconciliation and the conflict rules in §10.2;
- SEC EDGAR and FRED connectors — free, no entitlement question, and they unblock `filing` and `economic_release`.

**Exit criterion:** pull five years of point-in-time consensus EPS for 30 securities from both Bloomberg and LSEG, reconcile them, and produce a report of every discrepancy above tolerance. Assert that no record tagged `entitlement_mode="research"` can be retrieved by a card-rendering path.

---

## Phase 3 — Estimates and valuation engines — was Phase 2

Now buildable, because Phase 2 supplies the data. Most of the pure functions already exist and finally get validated against real inputs.

Build: revision magnitude, breadth, diffusion and dispersion (§13); point-in-time valuation metrics, medians, z-scores and peer premia (§15); valuation decomposition (price change ≈ earnings revision + re-rating); `valuation_snapshot`; wire estimate and valuation findings into `DailyResearchService`.

**Exit criterion:** for a security with a known historical guidance cut, the pipeline produces an estimate-revision finding and a valuation finding whose numbers match an independently calculated reference, using only data available at the time.

---

## Phase 4 — AI synthesis and materiality v1 — was Phase 2

The first point at which the product's differentiator can be demonstrated: three finding families (price, estimates, valuation) now exist, so there is something to compress.

Build: thesis model and PM-authored thesis CRUD (§24); deterministic thesis relevance via feature overlap and invalidation proximity (§24.2, no LLM required); AI synthesizer behind the guardrails in §34; deduplication and causal-chain construction; number cross-check gate; `model_registry`; materiality v1 calibrated against labeled history (§25.3); PM feedback controls end to end.

**Exit criterion:** a historical guidance-cut event that generates five or more atomic findings produces **one** research card, every number in the prose matches its evidence object, and every input finding is either represented or explicitly recorded as suppressed. Falling back to unmerged stage-1 output when the provider is unavailable is verified by test.

---

## Phase 5 — Factor Lab, risk diagnostics and backtesting — was Phases 3 and 4

Merged, because both consume the same cross-sectional feature panel and splitting them duplicates that infrastructure.

Build: full factor definitions and cross-sectional normalization; factor returns via cross-sectional regression; residual returns replacing the simpler market/sector adjustment; `factor_definition`/`factor_exposure`/`factor_return`; correlation clustering and macro betas; event-study backtests; bootstrap and HAC statistics; FDR control with hypothesis counting (§21.3); `backtest_spec`/`run`/`metric`; natural-language-to-spec assistant validated against the §23 schema; backtest report UI.

**Exit criterion:** any live screen reruns historically from the same definition with no look-ahead leakage — enforced by the §23.2 equivalence test — and every reported edge carries effect size, sample size, cost assumptions, and a multiple-testing-adjusted significance level.

---

## Phase 6 — Product-mode data and multi-tenancy — was Phase 6

Gated on D1. Nothing here should start before it resolves.

Build: the chosen product-mode data path (BYO-entitlement connector, licensed redistribution feed, or redistributable vendor); `tenant` table and `tenant_id` scoping enforced in the repository layer; the cross-tenant isolation test; OIDC authentication and roles; per-tenant API keys; entitlement profiles and field-level suppression with visible reasons (§7.4); append-only audit log unified with the lineage store (§36).

**Exit criterion:** two tenants with different entitlement profiles receive correctly different cards from the same underlying data, an integration test proves cross-tenant queries return nothing, and no research-mode record appears in any customer-facing output.

---

## Phase 7 — Filings, news and full coverage

Build: filing-diff engine (§17); document store and `news_document`; licensed news ingestion, entity resolution, clustering and novelty scoring (§18); ownership and short-interest (§20); options history if the data cost is justified (§19 — defer until a customer asks).

**Exit criterion:** a new 10-K produces an evidence-backed finding identifying materially changed risk-factor language, mapped to a thesis node, with the source passage linked.

---

## Phase 8 — Production hardening

Build: production web UI; scheduler (D4); retries and dead-letter queue; observability and freshness dashboards; AI eval suite; disaster recovery, backup and restore; deployment pipeline; security review; licensing review sign-off; PM beta workflow.

**Exit criterion:** the daily brief is delivered before market open, unattended, for five consecutive sessions, with alerting on every failure mode in §36.

---

## 38.2 Critical path

```text
D1 (data model) ──────────────────────────────► Phase 6 ──► customers
                                                    ▲
D6 (derived data) ──► informs D1                    │
                                                    │
Phase 2 (research connectors) ──► Phase 3 ──► Phase 4 ──► Phase 5
        │                                                    │
        └──► SEC + FRED (free, unblocked) ──────────► Phase 7
D2 (tenancy) ──► schema change ─────────────────────► Phase 6
D3 (LLM) ─────────────────────────────────────► Phase 4
D4 (scheduler) ───────────────────────────────► Phase 8
```

**The binding constraint is D1**, not engineering capacity. Phases 2–5 can proceed under existing desktop licenses and produce a genuinely valuable research engine, but none of it can be sold until the product-mode data question is answered. Resolve it in parallel with Phase 2 rather than after Phase 5.

## 38.3 Work available today regardless of any decision

If everything else stalls, these are unblocked and worth doing:

- `data_quality_event` table and the §10.5 checks;
- feature-store cross-sectional panel retrieval;
- the live-vs-backtest equivalence test (§23.2);
- `backtest_spec`/`run`/`metric` persistence;
- SEC EDGAR and FRED connectors;
- `tenant_id` schema change and repository scoping (cheapest now, most expensive later);
- corporate-action regression tests with real examples (§10.4).

## Phase 0 — Product specification and data contracts

Deliverables:

- define initial equity universe and regions;
- holdings / coverage upload format;
- canonical security IDs;
- point-in-time data model;
- `ResearchFinding` schema;
- research-card schema;
- materiality score v0;
- thesis schema;
- vendor-entitlement inventory;
- initial UX wireframes.

---

## Phase 1 — Quant research MVP

Build:

- security master;
- price ingestion;
- factor / benchmark mappings;
- general event-study framework;
- prototype modules migrated from `aapl_quant_research.py`;
- abnormal return engine;
- rolling risk metrics;
- simple factor exposures;
- Streamlit research dashboard;
- research-card persistence.

Upgrade the existing script first into reusable functions/classes rather than rewriting everything at once.

Exit criterion:

Upload 30–100 equities and receive reproducible daily quantitative research snapshots for every name.

---

## Phase 2 — Estimates, valuation, filings and AI synthesis

Build:

- point-in-time estimate snapshots;
- revision breadth / acceleration;
- valuation history and z-scores;
- SEC filing connector;
- document store;
- filing-diff engine;
- thesis memory;
- AI research synthesizer;
- evidence linking;
- deduplication;
- materiality v1.

Exit criterion:

A new earnings / filing / estimate-revision event produces one evidence-backed material research card instead of several raw alerts.

---

## Phase 3 — Factor Lab and risk diagnostics

Build:

- full factor definitions;
- cross-sectional normalization;
- factor returns;
- residual returns;
- factor exposure dashboard;
- correlation / clustering;
- macro betas;
- coverage-universe screens;
- optional holdings-weighted factor overlay.

Exit criterion:

The PM can distinguish company-specific moves from sector / style / macro moves and run reusable factor screens.

---

## Phase 4 — Point-in-time backtesting

Build:

- historical universe handling;
- point-in-time feature retrieval;
- cross-sectional and event backtests;
- transaction-cost assumptions;
- factor neutralization;
- IC / rank IC;
- bootstrap / HAC statistics;
- multiple-testing controls;
- natural-language → backtest-spec assistant;
- backtest report UI.

Exit criterion:

Any live screen can be rerun historically from the same feature definition without look-ahead leakage.

---

## Phase 5 — Bloomberg / LSEG production connectors

Build:

- `BloombergProvider`;
- `LSEGProvider`;
- field mapping registry;
- request cache;
- quota / entitlement handling;
- source reconciliation rules;
- desktop development mode;
- server / platform mode where contracted;
- data-quality comparisons;
- failover logic for non-proprietary fields where permitted.

Exit criterion:

The research engine can switch providers through configuration without changing quant logic.

---

## Phase 6 — Production hardening

Build:

- role-based access;
- production web UI;
- observability;
- retries / dead-letter queue;
- model and prompt registry;
- AI eval suite;
- data freshness dashboard;
- disaster recovery;
- deployment pipeline;
- backup / restore;
- security review;
- licensing review;
- PM beta-testing workflow.
