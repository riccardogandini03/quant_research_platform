# Initial UX wireframes

These low-fidelity layouts define information hierarchy, not a finished visual
design. Labels marked “planned” require later-phase data.

## Upload and coverage setup

```text
┌──────────────────── Quant RaaS / Coverage setup ────────────────────┐
│ Holdings CSV [Choose file]       Coverage CSV [Choose file]         │
│ As-of: 2026-08-10 21:00 UTC      [Validate] [Import]                │
├──────────────────────── Validation ──────────────────────────────────┤
│ ✓ 48 holdings resolved       ✓ weights use decimal fractions        │
│ ! 2 coverage IDs ambiguous   ! 1 benchmark mapping missing          │
│                                                                    │
│ Row  Identifier  Resolution                    Action                │
│ 12   ABC LN      two time-valid matches        [select] [exclude]    │
└────────────────────────────────────────────────────────────────────┘
```

Import is blocked for ambiguous identifiers and invalid weights. A missing
optional thesis does not block coverage import. Validation must show the exact
rows changed by canonicalization before persistence.

## Research inbox

```text
┌──────────────────── Quant RaaS / Research inbox ────────────────────┐
│ As-of 2026-08-10 close  Filters: [Material+] [Held + Coverage]      │
│ Data freshness: prices 18h  factors 18h  estimates not configured   │
├────────────────────────────────────────────────────────────────────┤
│ ASML NA                                    MATERIAL   confidence HIGH│
│ Residual return -2.4σ; sector-adjusted decline exceeds threshold    │
│ Evidence 3  | Position 4.2% | updated 2026-08-10 21:15 UTC          │
│ [Open evidence] [Useful] [Noise] [Investigate]                      │
├────────────────────────────────────────────────────────────────────┤
│ AAPL US                                    WATCH      confidence MED │
│ 63-session relative strength weakened; volume is not unusual        │
│ Evidence 2  | Position 3.5% | updated 2026-08-10 21:15 UTC          │
└────────────────────────────────────────────────────────────────────┘
```

Cards are ranked by priority, but display the unmodified materiality score and
the position modifier separately. “No finding” is a valid daily result.

## Company quant page

```text
┌────────────────────────── ASML Holding N.V. ────────────────────────┐
│ XAMS · EUR · Information Technology     As-of [2026-08-10 close]    │
│ Freshness [prices 18h] [events 18h] [estimates not configured]      │
├──────── Price and anomaly ────────┬──────── Factor context ─────────┤
│ 1d total return        -4.8%      │ Market beta          1.12       │
│ sector-relative        -2.1%      │ sector exposure      0.84       │
│ residual z-score       -2.4σ      │ 63d rel. strength   -6.2%       │
│ realized vol (20d)     31.0%      │ model window       126 obs      │
├──────── Event studies ────────────┴──────── Evidence lineage ───────┤
│ Event     N  Mean +5d  Warning       Source ID   Available at        │
│ Earnings  8    +0.7%   SMALL SAMPLE  px-...      2026-08-10 20:05Z  │
│                                                                    │
│ [Download typed snapshot] [View calculation conventions]           │
└────────────────────────────────────────────────────────────────────┘
```

The page always exposes sample size, as-of time, units, and calculation window.
Unavailable later-phase panels show “not configured,” never a fabricated zero.

## Factor and risk lab

```text
┌────────────────────── Factor & risk lab ────────────────────────────┐
│ Universe [Coverage]  As-of [latest complete session]  Region [All] │
├────────────────────────────────────────────────────────────────────┤
│ Exposure heatmap        │ Outliers                                  │
│ name  market sector mom │ 1 ASML residual decline -2.4σ             │
│ ...                     │ 2 AAPL rel. strength    -6.2%             │
├─────────────────────────┴───────────────────────────────────────────┤
│ Optional holdings overlay: weighted context only [show]             │
│ [Open screen configuration] [Export point-in-time snapshot]         │
└────────────────────────────────────────────────────────────────────┘
```

## Essential error and empty states

- Stale data shows its last valid timestamp and suppresses claims that require
  fresher observations.
- A provider failure identifies affected securities without discarding valid
  results for the rest of the batch.
- Insufficient history shows the required and observed sample counts.
- Conflicting identifiers or sources remain unresolved until a deterministic
  rule or a user decision is recorded.
- Accessibility does not rely on materiality color alone; every state has text.
