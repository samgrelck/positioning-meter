# Open Questions & TBDs

Running list of decisions, unknowns, and follow-ups that came up during build.
Append-only — when resolved, mark with ✅ and a brief note rather than deleting.

---

## Decisions still to make

### EDGAR 13F deferred from V1 — confirm OK
- **Why deferred:** ~20k filings (top 200-500 HF CIKs × 40 quarters × 10y), bespoke XML parsing, multi-day ingestion. Single biggest piece of code in the project.
- **Impact on positioning bucket:** drops from 5 signals (HF crowding, HF concentration, SI%float, days-to-cover, insider) to **2 signals (short volume proxy + insider activity)** for V1.
- **Backtest impact:** positioning bucket's IC/decile-spread will be weaker than it could be. Composite still produces output, but the "crowding" interpretation is more limited.
- **Remediation path:** Phase 6 — add 13F provider in dedicated session. Or pay $200-400/yr for whalewisdom/insidertrades CSV exports of pre-aggregated 13F data.
- **TODO:** confirm V1 ships without 13F, or pause and build it now (~1 full session).

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
