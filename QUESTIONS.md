# Open Questions & TBDs

Running list of decisions, unknowns, and follow-ups that came up during build.
Append-only — when resolved, mark with ✅ and a brief note rather than deleting.

---

## Decisions still to make

### ~~EDGAR 13F deferred~~  ✅ RESOLVED — implemented V1.2
- 40-fund curated list, 1,475 filings, 174k holdings rows. CUSIP→ticker mapping at 97% coverage.
- Backtest revealed HF count signals are TREND, not contrarian — they were moved to overlay (V1.3).
- Only `hf_top_concentration` was kept in composite briefly; later moved to overlay too (V1.4).

### NTM P/E only — never TTM (V1.5 follow-up)
- User direction: never use TTM multiples. Switched valuation overlay to NTM P/E (price ÷ forward consensus EPS from yfinance).
- `ttm_pe` and `ev_sales` no longer computed (removed from `OVERLAY_SIGNALS`).
- NTM EV/Sales not computed — Yahoo doesn't expose reliable forward revenue consensus. Skipped rather than fake.
- NTM P/E shown on per-ticker drill-down's live overlay card.
- **TODO if needed:** add NTM EV/Sales when a forward revenue source becomes available (FactSet manual export, or paid feed).

### ~~Valuation in composite~~  ✅ RESOLVED — V1.5 removed
- **Decision:** valuation moved to overlay. Tool is sentiment / positioning / expectations only.
- **Rationale:**
  1. Empirically weakest bucket — ttm_pe IC near zero or wrong sign in V1.4 backtest.
  2. Conceptually fundamental, not behavioral. Analyst does this work separately.
  3. TMT specifically punishes valuation mean-reversion (winner-take-all keeps premium multiples).
- **V1.5 backtest:** composite IC −0.020 at 3m (V1.4 was −0.022). Statistically equivalent — confirms valuation was contributing noise.
- **Still computed and shown:** ttm_pe and ev_sales are visible on per-ticker drill-down as overlay context.

## Things to investigate / verify

### Composite weakness — technical bucket has mixed-direction signals
- **Finding from V1 backtest:** composite IC ≈ 0 at 1m fwd; bot-decile hit rate only 54% (slightly above 50% baseline).
- **Root cause:** technical bucket aggregates contrarian signals (RSI, ret_3m, pct_from_52w_high) with trend signals (ret_12m, rs_vs_qqq_3m, rs_vs_xlk_3m). They cancel each other out.
- **Specifically — signals that work AS contrarian/late ("hot=late"):**
    - rsi_14 (IC −0.028 at 3m, bot hit 58%)
    - ret_3m (IC −0.038 at 3m, bot hit 60%, best in panel)
    - pct_from_52w_high (IC −0.017 at 3m, bot hit 59%)
    - insider_net_90d_signed (weak but right direction)
- **Signals that work AS trend (NOT "hot=late"):**
    - ret_12m (positive IC) — Jegadeesh-Titman 12m momentum
    - rs_vs_qqq_3m, rs_vs_xlk_3m — relative strength persists
    - insider_net_90d_abs — heavy activity in either direction is bullish
    - ttm_pe — high multiples don't mean-revert in TMT (winner-take-all)
- **Proposed remedy (V1.1):** split technical bucket into `technical_late` (contrarian) and `technical_trend` (trend). Trend signals stay in the dashboard as overlay/diagnostic but don't enter the composite. Or: invert the trend signals' percentile in the composite (high = hot interpretation reversed).
- **Decision needed:** how to handle. Three options —
    (a) drop trend signals from composite, leave only contrarian ones
    (b) split into separate buckets, weight each appropriately
    (c) keep all and add a "Compound trend" flag separately from "Compound late"
- **Recommendation:** (a) for V1.1 simplicity; revisit after weights are tuned.

## Data quality / caveats discovered during build

### Short interest vs short volume (FINRA)
- **Free historical:** FINRA Reg SHO daily short SALES VOLUME on CDN. Goes back ~6.5y (cutoff around mid-2018) — pre-2018 daily files are 403/missing.
- **Free current snapshot:** yfinance reports actual SI (positions level) — but no history.
- **What we're using for backtest:** rolling 14d short volume / total volume as a *proxy* for positioning pressure, **2018-08-onward only**. Related but not identical to true SI.
- **What we're using live:** yfinance SI snapshot as overlay alongside the proxy.
- **Backtest implication:** short_volume_ratio_14d signal has 6.5y of history vs other signals' 10y. Backtest results for this signal should be reported on its own window.
- **TODO:** decide later whether to add a paid SI source if proxy underperforms.

### ~~Valuation history depth (yfinance)~~  ✅ RESOLVED
- ~~yfinance gives ~4-5y of quarterly financials, not 10y.~~
- **Switched to Polygon `vx/list_stock_financials`** — 80 reports per fully-listed name back to ~2010, with real `filing_date` for clean point-in-time backtest. Polygon Stocks tier (already subscribed for prices) covers it.
- Valuation backtest is now full 10y for fully-listed names; partial for younger IPOs (NET 2019, MDB 2017).

### FactSet integration
- You have FactSet at work but won't bulk-export. EPS revisions stay as live overlay only — no historical signal contribution. (Already in DESIGN.md as a known V1 limitation.)

### ETF flows backtest depth
- Historical ETF shares-outstanding (the input to true creation/redemption flows) is paid data — not in Polygon free or yfinance.
- **For V1:** flows bucket is **live snapshot only, not backtested**. We start collecting daily ETF AUM today, build forward history.
- Backtestable proxy = relative strength of stock vs its sector ETF (already in technical bucket).
- **Implication for backtest:** flows bucket won't appear in the 10y backtest results. Composite weights for flows tuned by inspection / heuristic only.
- **TODO:** if flows turns out to be a critical signal, consider $200/mo for Polygon's full Stocks tier or scrape ETF.com fund-flows historical pages.
