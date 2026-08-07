#!/usr/bin/env python3
"""
================================================================================
 QUANTITATIVE RESEARCH MODEL — Statistical Edge Analysis
 Renaissance-style data-driven pattern detection
================================================================================

WHAT THIS SCRIPT DOES
---------------------
This script downloads ~10 years of Apple (AAPL) data and runs ten statistical
checks looking for repeatable, exploitable patterns ("edges"). It prints
everything to the console as tables.

The ten checks are:
  1.  Seasonal patterns — best/worst months historically
  2.  Day-of-week return patterns
  3.  Behavior around Fed (FOMC) meeting dates
  4.  Behavior around CPI release dates
  5.  Insider buying/selling (latest filings, via yfinance)
  6.  Institutional ownership snapshot (via yfinance)
  7.  Short interest & squeeze metrics
  8.  Options activity snapshot (put/call ratios, IV skew)
  9.  Earnings drift — pre-run and post-gap behavior
  10. Sector rotation signal (AAPL vs XLK vs SPY)

Plus a final "Statistical Edge Summary" that highlights which patterns are
statistically significant (p < 0.05).

HOW TO RUN
----------
    pip install yfinance pandas numpy scipy --break-system-packages
    python aapl_quant_research.py

DATA CAVEATS (read these — they matter)
---------------------------------------
- yfinance is free but scrapes Yahoo, so some endpoints (insider trades,
  institutional holders, short interest) can be missing or stale.
- Free data has NO historical options flow. Section 8 uses only the *current*
  option chain — useful as a snapshot, not a time series.
- Fed/CPI dates are hardcoded for the lookback window because there is no
  free, reliable API for historical release timestamps.
- p-values assume returns are roughly independent. They're not perfectly so —
  treat p < 0.05 as "interesting", not "proven".
"""

# ============================================================================
# IMPORTS
# ============================================================================
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

# Make pandas show full tables in the console
pd.set_option("display.max_rows", 100)
pd.set_option("display.max_columns", 20)
pd.set_option("display.width", 140)
pd.set_option("display.float_format", lambda x: f"{x:,.4f}")


# ============================================================================
# CONFIG
# ============================================================================
TICKER = "AAPL"
SECTOR_ETF = "XLK"      # tech sector ETF, used to detect sector rotation
MARKET_ETF = "SPY"      # broad market benchmark
LOOKBACK_YEARS = 10

END_DATE = datetime.today()
START_DATE = END_DATE - timedelta(days=LOOKBACK_YEARS * 365)


# ============================================================================
# UTILITIES
# ============================================================================
def header(title):
    """Print a big section header so output is easy to scan."""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def subheader(title):
    """Print a smaller sub-section header."""
    print(f"\n--- {title} ---")


def annualize_return(daily_mean):
    """Convert a daily mean return into an annualized number (252 trading days)."""
    return (1 + daily_mean) ** 252 - 1


def t_test_vs_zero(series):
    """
    Run a one-sample t-test asking: 'is the mean of this series different from 0?'
    Returns (t-stat, p-value). p < 0.05 = statistically significant.
    """
    clean = series.dropna()
    if len(clean) < 5:
        return np.nan, np.nan
    t, p = stats.ttest_1samp(clean, 0.0)
    return t, p


def safe_download(ticker, start, end):
    """Wrap yfinance download with basic error handling + return calc."""
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"No data returned for {ticker}")
    # If yfinance returns multiindex columns (newer versions), flatten them
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df["Return"] = df["Close"].pct_change()
    df["LogReturn"] = np.log(df["Close"] / df["Close"].shift(1))
    return df


# ============================================================================
# 1. LOAD ALL PRICE DATA
# ============================================================================
header(f"LOADING DATA — {TICKER}, {SECTOR_ETF}, {MARKET_ETF} | "
       f"{START_DATE.date()} → {END_DATE.date()}")

stock = safe_download(TICKER, START_DATE, END_DATE)
sector = safe_download(SECTOR_ETF, START_DATE, END_DATE)
market = safe_download(MARKET_ETF, START_DATE, END_DATE)

print(f"{TICKER}:  {len(stock):>5} rows | first {stock.index[0].date()} | last {stock.index[-1].date()}")
print(f"{SECTOR_ETF}:  {len(sector):>5} rows")
print(f"{MARKET_ETF}:  {len(market):>5} rows")

# A list to collect statistically significant patterns for the final summary
edges_found = []


# ============================================================================
# 2. SEASONAL PATTERNS — which months are best/worst?
# ============================================================================
header("1. SEASONAL PATTERNS (MONTHLY)")

# Group daily returns by calendar month and compute compounded monthly return
# for each (year, month) pair, then summarize across years.
df = stock.copy()
df["YearMonth"] = df.index.to_period("M")
monthly = df.groupby("YearMonth")["Return"].apply(lambda x: (1 + x).prod() - 1)
monthly.index = monthly.index.to_timestamp()
monthly_by_cal_month = monthly.groupby(monthly.index.month)

month_table = pd.DataFrame({
    "Mean Return": monthly_by_cal_month.mean(),
    "Median":      monthly_by_cal_month.median(),
    "Std Dev":     monthly_by_cal_month.std(),
    "Win Rate":    monthly_by_cal_month.apply(lambda x: (x > 0).mean()),
    "Years":       monthly_by_cal_month.count(),
})

# Run t-tests per month: is this month's mean materially different from 0?
pvals = {}
for m, group in monthly_by_cal_month:
    _, p = t_test_vs_zero(group)
    pvals[m] = p
month_table["p-value"] = pd.Series(pvals)

# Pretty month names
month_table.index = [datetime(2000, m, 1).strftime("%b") for m in month_table.index]

print(month_table.to_string(float_format=lambda x: f"{x:>8.4f}"))

best_month = month_table["Mean Return"].idxmax()
worst_month = month_table["Mean Return"].idxmin()
print(f"\nBest month historically:  {best_month}  "
      f"({month_table.loc[best_month, 'Mean Return']*100:.2f}% avg)")
print(f"Worst month historically: {worst_month}  "
      f"({month_table.loc[worst_month, 'Mean Return']*100:.2f}% avg)")

# Flag any month with p < 0.10 as worth noting
for m in month_table.index:
    p = month_table.loc[m, "p-value"]
    if pd.notna(p) and p < 0.10:
        direction = "positive" if month_table.loc[m, "Mean Return"] > 0 else "negative"
        edges_found.append(
            f"SEASONAL: {m} shows {direction} bias "
            f"(mean={month_table.loc[m,'Mean Return']*100:.2f}%, p={p:.3f})"
        )


# ============================================================================
# 3. DAY-OF-WEEK PATTERNS
# ============================================================================
header("2. DAY-OF-WEEK PATTERNS")

df = stock.copy()
df["DOW"] = df.index.day_name()
dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

dow_table = pd.DataFrame({
    "Mean Daily Return": df.groupby("DOW")["Return"].mean(),
    "Std Dev":           df.groupby("DOW")["Return"].std(),
    "Win Rate":          df.groupby("DOW")["Return"].apply(lambda x: (x > 0).mean()),
    "N":                 df.groupby("DOW")["Return"].count(),
}).reindex(dow_order)

# Significance test per day
dow_table["p-value"] = [t_test_vs_zero(df[df["DOW"] == d]["Return"])[1] for d in dow_order]
dow_table["Annualized"] = dow_table["Mean Daily Return"] * 252

print(dow_table.to_string(float_format=lambda x: f"{x:>9.5f}"))

for d in dow_order:
    p = dow_table.loc[d, "p-value"]
    if pd.notna(p) and p < 0.10:
        direction = "positive" if dow_table.loc[d, "Mean Daily Return"] > 0 else "negative"
        edges_found.append(
            f"DAY-OF-WEEK: {d}s show {direction} drift "
            f"(mean={dow_table.loc[d,'Mean Daily Return']*100:.3f}%, p={p:.3f})"
        )


# ============================================================================
# 4. FED MEETING (FOMC) BEHAVIOR
# ============================================================================
header("3. BEHAVIOR AROUND FED (FOMC) MEETINGS")

# Hardcoded FOMC meeting end-dates within our lookback window.
# (No free API gives this reliably across 10 years, so we list them manually.)
fomc_dates = [
    # 2016
    "2016-01-27","2016-03-16","2016-04-27","2016-06-15","2016-07-27","2016-09-21","2016-11-02","2016-12-14",
    # 2017
    "2017-02-01","2017-03-15","2017-05-03","2017-06-14","2017-07-26","2017-09-20","2017-11-01","2017-12-13",
    # 2018
    "2018-01-31","2018-03-21","2018-05-02","2018-06-13","2018-08-01","2018-09-26","2018-11-08","2018-12-19",
    # 2019
    "2019-01-30","2019-03-20","2019-05-01","2019-06-19","2019-07-31","2019-09-18","2019-10-30","2019-12-11",
    # 2020
    "2020-01-29","2020-03-03","2020-03-15","2020-04-29","2020-06-10","2020-07-29","2020-09-16","2020-11-05","2020-12-16",
    # 2021
    "2021-01-27","2021-03-17","2021-04-28","2021-06-16","2021-07-28","2021-09-22","2021-11-03","2021-12-15",
    # 2022
    "2022-01-26","2022-03-16","2022-05-04","2022-06-15","2022-07-27","2022-09-21","2022-11-02","2022-12-14",
    # 2023
    "2023-02-01","2023-03-22","2023-05-03","2023-06-14","2023-07-26","2023-09-20","2023-11-01","2023-12-13",
    # 2024
    "2024-01-31","2024-03-20","2024-05-01","2024-06-12","2024-07-31","2024-09-18","2024-11-07","2024-12-18",
    # 2025
    "2025-01-29","2025-03-19","2025-05-07","2025-06-18","2025-07-30","2025-09-17","2025-11-05","2025-12-17",
    # 2026 (year-to-date)
    "2026-01-28","2026-03-18","2026-04-29",
]
fomc_dates = pd.to_datetime(fomc_dates)
fomc_dates = fomc_dates[(fomc_dates >= START_DATE) & (fomc_dates <= END_DATE)]


def event_window_returns(price_df, event_dates, window_days=5):
    """
    For each event date, compute the cumulative return from D-window to D+window.
    Also compute the day-of-event return and post-event drift.
    """
    rows = []
    for d in event_dates:
        if d not in price_df.index:
            # find next available trading day
            future = price_df.index[price_df.index >= d]
            if len(future) == 0:
                continue
            d = future[0]
        i = price_df.index.get_loc(d)
        lo, hi = max(0, i - window_days), min(len(price_df) - 1, i + window_days)
        pre   = (price_df["Close"].iloc[i]    / price_df["Close"].iloc[lo]) - 1
        same  = price_df["Return"].iloc[i]
        post  = (price_df["Close"].iloc[hi]   / price_df["Close"].iloc[i]) - 1
        rows.append({"Date": price_df.index[i].date(), "Pre-5d": pre,
                     "Event Day": same, "Post-5d": post})
    return pd.DataFrame(rows)


fomc_results = event_window_returns(stock, fomc_dates, window_days=5)
print(f"FOMC meetings analyzed: {len(fomc_results)}")
print("\nReturn statistics around FOMC days (window = ±5 trading days):")
print(fomc_results[["Pre-5d", "Event Day", "Post-5d"]].describe().to_string(
      float_format=lambda x: f"{x:>8.4f}"))

# Significance tests
for col in ["Pre-5d", "Event Day", "Post-5d"]:
    t, p = t_test_vs_zero(fomc_results[col])
    mean = fomc_results[col].mean()
    print(f"  {col:>10}: mean={mean*100:>6.2f}% | t={t:>5.2f} | p={p:>5.3f}")
    if pd.notna(p) and p < 0.10:
        edges_found.append(
            f"FED: {col} around FOMC averages {mean*100:.2f}% (p={p:.3f})"
        )


# ============================================================================
# 5. CPI RELEASE BEHAVIOR
# ============================================================================
header("4. BEHAVIOR AROUND CPI RELEASES")

# Hardcoded CPI release dates (BLS schedule)
cpi_dates = [
    # 2016
    "2016-01-20","2016-02-19","2016-03-16","2016-04-14","2016-05-17","2016-06-16",
    "2016-07-15","2016-08-16","2016-09-16","2016-10-18","2016-11-17","2016-12-15",
    # 2017
    "2017-01-18","2017-02-15","2017-03-15","2017-04-14","2017-05-12","2017-06-14",
    "2017-07-14","2017-08-11","2017-09-14","2017-10-13","2017-11-15","2017-12-13",
    # 2018
    "2018-01-12","2018-02-14","2018-03-13","2018-04-11","2018-05-10","2018-06-12",
    "2018-07-12","2018-08-10","2018-09-13","2018-10-11","2018-11-14","2018-12-12",
    # 2019
    "2019-01-11","2019-02-13","2019-03-12","2019-04-10","2019-05-10","2019-06-12",
    "2019-07-11","2019-08-13","2019-09-12","2019-10-10","2019-11-13","2019-12-11",
    # 2020
    "2020-01-14","2020-02-13","2020-03-11","2020-04-10","2020-05-12","2020-06-10",
    "2020-07-14","2020-08-12","2020-09-11","2020-10-13","2020-11-12","2020-12-10",
    # 2021
    "2021-01-13","2021-02-10","2021-03-10","2021-04-13","2021-05-12","2021-06-10",
    "2021-07-13","2021-08-11","2021-09-14","2021-10-13","2021-11-10","2021-12-10",
    # 2022
    "2022-01-12","2022-02-10","2022-03-10","2022-04-12","2022-05-11","2022-06-10",
    "2022-07-13","2022-08-10","2022-09-13","2022-10-13","2022-11-10","2022-12-13",
    # 2023
    "2023-01-12","2023-02-14","2023-03-14","2023-04-12","2023-05-10","2023-06-13",
    "2023-07-12","2023-08-10","2023-09-13","2023-10-12","2023-11-14","2023-12-12",
    # 2024
    "2024-01-11","2024-02-13","2024-03-12","2024-04-10","2024-05-15","2024-06-12",
    "2024-07-11","2024-08-14","2024-09-11","2024-10-10","2024-11-13","2024-12-11",
    # 2025
    "2025-01-15","2025-02-12","2025-03-12","2025-04-10","2025-05-13","2025-06-11",
    "2025-07-15","2025-08-12","2025-09-11","2025-10-15","2025-11-13","2025-12-10",
    # 2026
    "2026-01-14","2026-02-11","2026-03-12","2026-04-15",
]
cpi_dates = pd.to_datetime(cpi_dates)
cpi_dates = cpi_dates[(cpi_dates >= START_DATE) & (cpi_dates <= END_DATE)]

cpi_results = event_window_returns(stock, cpi_dates, window_days=3)
print(f"CPI releases analyzed: {len(cpi_results)}")
print("\nReturn statistics around CPI release days (window = ±3 trading days):")
print(cpi_results[["Pre-5d", "Event Day", "Post-5d"]].describe().to_string(
      float_format=lambda x: f"{x:>8.4f}"))

for col in ["Pre-5d", "Event Day", "Post-5d"]:
    t, p = t_test_vs_zero(cpi_results[col])
    mean = cpi_results[col].mean()
    label = "Pre-3d" if col == "Pre-5d" else ("Post-3d" if col == "Post-5d" else col)
    print(f"  {label:>10}: mean={mean*100:>6.2f}% | t={t:>5.2f} | p={p:>5.3f}")
    if pd.notna(p) and p < 0.10:
        edges_found.append(
            f"CPI: {label} around CPI averages {mean*100:.2f}% (p={p:.3f})"
        )


# ============================================================================
# 6. INSIDER TRADING (LATEST FILINGS)
# ============================================================================
header("5. INSIDER BUYING / SELLING (yfinance, last few quarters)")

try:
    tk = yf.Ticker(TICKER)
    insider = tk.insider_transactions
    if insider is None or insider.empty:
        print("No insider transaction data returned by yfinance.")
    else:
        # Standardize columns we care about
        cols_wanted = [c for c in ["Start Date", "Insider", "Position",
                                   "Transaction", "Shares", "Value", "URL"]
                       if c in insider.columns]
        ins = insider[cols_wanted].copy()
        ins = ins.head(25)  # most recent 25 only
        print(ins.to_string(index=False))

        # Quick aggregation: buy vs sell value
        if "Transaction" in insider.columns and "Value" in insider.columns:
            tx = insider.copy()
            tx["Value"] = pd.to_numeric(tx["Value"], errors="coerce")
            buys = tx[tx["Transaction"].astype(str).str.contains("Buy",  case=False, na=False)]["Value"].sum()
            sells = tx[tx["Transaction"].astype(str).str.contains("Sale|Sell", case=False, na=False)]["Value"].sum()
            print(f"\nTotal insider BUY value:  ${buys:>15,.0f}")
            print(f"Total insider SELL value: ${sells:>15,.0f}")
            if sells > 0 and buys > 0:
                ratio = buys / sells
                print(f"Buy/Sell ratio:           {ratio:.3f}")
                if ratio < 0.1:
                    edges_found.append(f"INSIDERS: Heavy net selling (buy/sell ratio = {ratio:.3f})")
                elif ratio > 2:
                    edges_found.append(f"INSIDERS: Heavy net buying (buy/sell ratio = {ratio:.3f})")
except Exception as e:
    print(f"Insider data unavailable: {e}")


# ============================================================================
# 7. INSTITUTIONAL OWNERSHIP
# ============================================================================
header("6. INSTITUTIONAL OWNERSHIP SNAPSHOT")

try:
    holders = yf.Ticker(TICKER).institutional_holders
    if holders is None or holders.empty:
        print("No institutional holder data returned.")
    else:
        print(holders.to_string(index=False))
        # Try to detect direction of recent change if a pctChange column exists
        if "pctHeld" in holders.columns:
            avg_change = holders.get("Change", pd.Series([0])).mean()
            print(f"\nMean position change across top holders: {avg_change:,.0f} shares")
except Exception as e:
    print(f"Institutional holder data unavailable: {e}")

try:
    info = yf.Ticker(TICKER).info
    inst_pct = info.get("heldPercentInstitutions", None)
    if inst_pct is not None:
        print(f"\n% of shares held by institutions: {inst_pct*100:.2f}%")
except Exception:
    pass


# ============================================================================
# 8. SHORT INTEREST / SQUEEZE METRICS
# ============================================================================
header("7. SHORT INTEREST & SQUEEZE METRICS")

try:
    info = yf.Ticker(TICKER).info
    short_metrics = {
        "Shares Short":              info.get("sharesShort"),
        "Short Ratio (Days to Cover)": info.get("shortRatio"),
        "Short % of Float":           info.get("shortPercentOfFloat"),
        "Short % of Shares Out":      info.get("sharesPercentSharesOut"),
        "Shares Short Prior Month":   info.get("sharesShortPriorMonth"),
        "Float":                      info.get("floatShares"),
    }
    for k, v in short_metrics.items():
        if v is None:
            print(f"  {k:>32}: n/a")
        elif isinstance(v, float) and v < 1:
            print(f"  {k:>32}: {v*100:.2f}%")
        else:
            print(f"  {k:>32}: {v:,}")

    # Heuristic squeeze flag — AAPL almost never qualifies, but generic logic:
    sp = info.get("shortPercentOfFloat") or 0
    sr = info.get("shortRatio") or 0
    if sp and sp > 0.15 and sr and sr > 5:
        edges_found.append(
            f"SHORT SQUEEZE: Float short {sp*100:.1f}%, "
            f"days-to-cover {sr:.1f} — squeeze risk elevated"
        )
    else:
        print("\nSqueeze risk: LOW (typical for AAPL — float short < 1%).")
except Exception as e:
    print(f"Short data unavailable: {e}")


# ============================================================================
# 9. OPTIONS ACTIVITY (current chain only — free data has no flow history)
# ============================================================================
header("8. OPTIONS ACTIVITY SNAPSHOT (current chain)")

try:
    tk = yf.Ticker(TICKER)
    expiries = tk.options
    if not expiries:
        print("No option expiries returned.")
    else:
        # Use the nearest expiry as a sentiment proxy
        nearest = expiries[0]
        chain = tk.option_chain(nearest)
        calls, puts = chain.calls, chain.puts

        call_vol = calls["volume"].fillna(0).sum()
        put_vol  = puts["volume"].fillna(0).sum()
        call_oi  = calls["openInterest"].fillna(0).sum()
        put_oi   = puts["openInterest"].fillna(0).sum()

        pc_vol = put_vol / call_vol if call_vol else np.nan
        pc_oi  = put_oi  / call_oi  if call_oi  else np.nan

        # IV skew: 25-delta-ish proxy = compare OTM put IV vs OTM call IV at ~5% out
        spot = stock["Close"].iloc[-1]
        otm_puts  = puts [puts ["strike"] < spot * 0.95]
        otm_calls = calls[calls["strike"] > spot * 1.05]
        put_iv  = otm_puts ["impliedVolatility"].mean()
        call_iv = otm_calls["impliedVolatility"].mean()
        skew = put_iv - call_iv if pd.notna(put_iv) and pd.notna(call_iv) else np.nan

        print(f"Nearest expiry:          {nearest}")
        print(f"Spot price:              ${spot:,.2f}")
        print(f"Call volume:             {call_vol:,.0f}")
        print(f"Put volume:              {put_vol:,.0f}")
        print(f"Put/Call vol ratio:      {pc_vol:.3f}   (>1 = bearish lean)")
        print(f"Call OI:                 {call_oi:,.0f}")
        print(f"Put OI:                  {put_oi:,.0f}")
        print(f"Put/Call OI ratio:       {pc_oi:.3f}")
        print(f"OTM put avg IV:          {put_iv*100:.2f}%")
        print(f"OTM call avg IV:         {call_iv*100:.2f}%")
        print(f"IV skew (put - call):    {skew*100:+.2f}%   (positive = downside fear)")

        if pd.notna(pc_vol) and pc_vol > 1.2:
            edges_found.append(f"OPTIONS: P/C volume {pc_vol:.2f} — bearish sentiment skew")
        if pd.notna(pc_vol) and pc_vol < 0.6:
            edges_found.append(f"OPTIONS: P/C volume {pc_vol:.2f} — bullish positioning")
        if pd.notna(skew) and skew > 0.05:
            edges_found.append(f"OPTIONS: IV skew +{skew*100:.1f}% — elevated downside hedging")
except Exception as e:
    print(f"Options data unavailable: {e}")


# ============================================================================
# 10. EARNINGS DRIFT — pre-run and post-gap
# ============================================================================
header("9. PRICE BEHAVIOR AROUND EARNINGS")

try:
    earnings_dates = yf.Ticker(TICKER).earnings_dates
    if earnings_dates is None or earnings_dates.empty:
        # Fall back: use get_earnings_dates() which sometimes returns more history
        earnings_dates = yf.Ticker(TICKER).get_earnings_dates(limit=40)

    earnings_dates = earnings_dates.reset_index().rename(
        columns={earnings_dates.index.name or "Earnings Date": "Date"})
    earnings_dates["Date"] = pd.to_datetime(earnings_dates["Date"]).dt.tz_localize(None)
    earnings_dates = earnings_dates[
        (earnings_dates["Date"] >= START_DATE) & (earnings_dates["Date"] <= END_DATE)
    ]
    print(f"Earnings events found: {len(earnings_dates)}")

    rows = []
    for d in earnings_dates["Date"]:
        # Find nearest trading day
        future = stock.index[stock.index >= d]
        past   = stock.index[stock.index <= d]
        if len(future) == 0 or len(past) == 0:
            continue
        anchor = future[0]
        i = stock.index.get_loc(anchor)
        if i < 5 or i + 5 >= len(stock):
            continue
        pre5    = (stock["Close"].iloc[i-1] / stock["Close"].iloc[i-5]) - 1   # 4-day pre-run
        gap     = (stock["Open"].iloc[i]    / stock["Close"].iloc[i-1]) - 1   # overnight gap
        day_of  = stock["Return"].iloc[i]
        post5   = (stock["Close"].iloc[i+5] / stock["Close"].iloc[i])    - 1
        rows.append({
            "Date": anchor.date(),
            "Pre-run (-5 to -1)": pre5,
            "Earnings gap":       gap,
            "Day-of":             day_of,
            "Post-5d drift":      post5,
        })

    er = pd.DataFrame(rows)
    if len(er):
        print("\nSummary across all earnings events:")
        print(er.drop(columns="Date").describe().to_string(
              float_format=lambda x: f"{x:>8.4f}"))
        for col in ["Pre-run (-5 to -1)", "Earnings gap", "Day-of", "Post-5d drift"]:
            t, p = t_test_vs_zero(er[col])
            mean = er[col].mean()
            win  = (er[col] > 0).mean()
            print(f"  {col:>22}: mean={mean*100:>6.2f}% | win-rate={win*100:>5.1f}% | t={t:>5.2f} | p={p:>5.3f}")
            if pd.notna(p) and p < 0.10:
                edges_found.append(
                    f"EARNINGS: {col} averages {mean*100:.2f}% (p={p:.3f}, n={len(er)})"
                )
except Exception as e:
    print(f"Earnings data unavailable: {e}")


# ============================================================================
# 11. SECTOR ROTATION SIGNAL
# ============================================================================
header("10. SECTOR ROTATION (AAPL vs XLK vs SPY)")

# Build a single DataFrame of returns
ret = pd.DataFrame({
    TICKER:     stock["Return"],
    SECTOR_ETF: sector["Return"],
    MARKET_ETF: market["Return"],
}).dropna()

# Relative strength: cumulative outperformance vs sector & market
rel_to_xlk = (1 + ret[TICKER]).cumprod() / (1 + ret[SECTOR_ETF]).cumprod()
rel_to_spy = (1 + ret[TICKER]).cumprod() / (1 + ret[MARKET_ETF]).cumprod()

print(f"Cumulative return  | {TICKER}: {((1+ret[TICKER]).prod()-1)*100:>7.1f}%")
print(f"                   | {SECTOR_ETF}: {((1+ret[SECTOR_ETF]).prod()-1)*100:>7.1f}%")
print(f"                   | {MARKET_ETF}: {((1+ret[MARKET_ETF]).prod()-1)*100:>7.1f}%")

# Rolling 63-day (≈3-month) relative-strength change
rs_change_xlk_3m = rel_to_xlk.iloc[-1] / rel_to_xlk.iloc[-63] - 1
rs_change_spy_3m = rel_to_spy.iloc[-1] / rel_to_spy.iloc[-63] - 1
print(f"\n3-month relative strength vs {SECTOR_ETF}: {rs_change_xlk_3m*100:+.2f}%")
print(f"3-month relative strength vs {MARKET_ETF}: {rs_change_spy_3m*100:+.2f}%")

# Beta & correlation
cov = np.cov(ret[TICKER], ret[MARKET_ETF])
beta_spy = cov[0, 1] / cov[1, 1]
corr_spy = ret[TICKER].corr(ret[MARKET_ETF])
corr_xlk = ret[TICKER].corr(ret[SECTOR_ETF])
print(f"\nBeta vs SPY:       {beta_spy:.3f}")
print(f"Corr vs SPY:       {corr_spy:.3f}")
print(f"Corr vs XLK:       {corr_xlk:.3f}")

if rs_change_xlk_3m > 0.05:
    edges_found.append(
        f"SECTOR ROTATION: AAPL outperforming sector by {rs_change_xlk_3m*100:.1f}% over 3mo "
        "— positive momentum vs peers"
    )
elif rs_change_xlk_3m < -0.05:
    edges_found.append(
        f"SECTOR ROTATION: AAPL underperforming sector by {abs(rs_change_xlk_3m)*100:.1f}% over 3mo "
        "— rotation away from name"
    )


# ============================================================================
# 12. STATISTICAL EDGE SUMMARY
# ============================================================================
header("STATISTICAL EDGE SUMMARY — patterns worth watching")

if not edges_found:
    print("No statistically significant patterns surfaced at p < 0.10.")
    print("This is normal for large-cap, heavily-arbitraged names like AAPL.")
else:
    for i, e in enumerate(edges_found, 1):
        print(f"  {i:>2}. {e}")

# Risk-adjusted summary
sharpe = ret[TICKER].mean() / ret[TICKER].std() * np.sqrt(252)
ann_vol = ret[TICKER].std() * np.sqrt(252)
ann_ret = annualize_return(ret[TICKER].mean())
print(f"\nBaseline {TICKER} risk profile over lookback:")
print(f"  Annualized return:     {ann_ret*100:>6.2f}%")
print(f"  Annualized volatility: {ann_vol*100:>6.2f}%")
print(f"  Sharpe (rf=0):         {sharpe:>6.2f}")

print("\nDone.")
