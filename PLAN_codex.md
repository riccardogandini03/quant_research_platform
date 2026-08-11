# Autonomous Quant Research-as-a-Service Platform

## Product and Engineering Build Plan

**Working concept:** an autonomous equity research platform that continuously converts market, fundamental, estimate, filing, macro and news data into **ranked, evidence-backed quantitative research findings** for a portfolio manager.

**Primary product:** Quant Research-as-a-Service (RaaS).

**Secondary use of portfolio data:** the PM can upload 30–100 holdings and weights so the system understands relevance and can prioritize research. The platform is **not primarily a portfolio-position monitoring or order-management system**.

**Initial asset class assumption:** listed equities / ADRs, with the architecture designed so ETFs and equity indices can be added later.

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

# 6. Recommended technology stack

- **Language:** Python 3.12+
- **API:** FastAPI
- **Tabular analytics:** pandas
- **Core database:** PostgreSQL
- **Time-series extension:** TimescaleDB optional
- **Vector / semantic search:** pgvector initially
- **Object storage:** S3-compatible storage using Parquet
- **Workflow scheduler:** Prefect or Dagster
- **UI:** Streamlit for research MVP, then React / Next.js for production
- **Charts:** Plotly in UI
- **Statistics:** NumPy, SciPy, statsmodels
- **ML:** scikit-learn
- **Testing:** pytest + hypothesis where useful

Do **not** begin with a large microservice architecture. A modular monolith with clean interfaces is likely the fastest route to a credible research product.

---

# 9. Data-provider integration strategy

## 9.1 Bloomberg

Build a connector interface so the research engine does not care whether data comes from Bloomberg, LSEG or another source.

### Prototype mode

Where the user has a Bloomberg Terminal and appropriate entitlements, a local Bloomberg API connector can be used for research development.

## 9.2 LSEG

Use the LSEG Data Library for Python behind the same provider interface.

Support two operating modes where licensed:

- desktop / Workspace session for analyst development;
- platform / cloud session for server-side production.

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

# 30. Suggested codebase structure

```text
quant-raas/
│
├── apps/
│   ├── api/
│   ├── dashboard/
│   └── worker/
│
├── src/
│   ├── config/
│   ├── security_master/
│   ├── connectors/
│   │   ├── bloomberg/
│   │   ├── lseg/
│   │   ├── sec/
│   │   ├── macro/
│   │   └── public_fallback/
│   │
│   ├── ingestion/
│   ├── normalization/
│   ├── feature_store/
│   │
│   ├── quant/
│   │   ├── returns.py
│   │   ├── anomalies.py
│   │   ├── factors.py
│   │   ├── estimates.py
│   │   ├── earnings.py
│   │   ├── valuation.py
│   │   ├── macro.py
│   │   ├── options.py
│   │   ├── ownership.py
│   │   ├── event_study.py
│   │   └── statistics.py
│   │
│   ├── backtest/
│   │   ├── engine.py
│   │   ├── universe.py
│   │   ├── execution.py
│   │   ├── costs.py
│   │   ├── metrics.py
│   │   └── validation.py
│   │
│   ├── research/
│   │   ├── findings.py
│   │   ├── materiality.py
│   │   ├── thesis.py
│   │   ├── evidence.py
│   │   └── reports.py
│   │
│   ├── ai/
│   │   ├── structured_extract.py
│   │   ├── filing_diff.py
│   │   ├── synthesizer.py
│   │   ├── query_agent.py
│   │   ├── backtest_agent.py
│   │   ├── guardrails.py
│   │   └── evals.py
│   │
│   └── common/
│
├── workflows/
│   ├── intraday.py
│   ├── close.py
│   ├── earnings.py
│   └── weekly_research.py
│
├── configs/
│   ├── factors/
│   ├── screens/
│   ├── materiality/
│   └── universes/
│
├── notebooks/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── point_in_time/
│   ├── backtest/
│   └── ai_evals/
│
└── docs/
```

---

# 31. Key database tables

Minimum useful tables:

```text
security
security_identifier
portfolio_snapshot
portfolio_position
coverage_list
price_bar
corporate_action
fundamental_snapshot
estimate_snapshot
estimate_contributor_snapshot
valuation_snapshot
economic_release
company_event
filing
news_document
options_snapshot
ownership_snapshot
factor_definition
factor_exposure
factor_return
feature_snapshot
thesis
thesis_version
research_finding
research_card
evidence_reference
materiality_feedback
backtest_spec
backtest_run
backtest_metric
model_registry
```

# 33. Example quantitative screen definitions

The same screen object should be executable both **today** and historically in the backtest engine.

This is an important design principle: **live research and backtesting should share feature definitions**.

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

# 38. Build roadmap

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
