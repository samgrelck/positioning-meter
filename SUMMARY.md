# Positioning Meter — Running Summary

> Single source of truth for current state. Updated after each milestone.
> Sister docs: `DESIGN.md` (architecture), `QUESTIONS.md` (decisions/caveats), `data/backtest_report.md` (latest backtest results).

**Last updated:** 2026-05-09 — **V1.4 final + min-buckets filter**

---

## At a glance

| | Status |
|---|---|
| Universe | 366 TMT names, mcap ≥ $1.5B, drawn from theme_detector |
| Backtest horizon | 10y (2016-05 → 2026-05) for most signals; 6.5y for short volume; 1y for true SI |
| Composite output | **working — IC −0.022, decile spread −2.30%, bot decile hit 56%** at 3m fwd |
| Dashboard | `data/dashboard.html` |
| Backtest report | `data/backtest_report.md` |

## Composite evolution (each row = re-tune iteration)

| Version | Change | 1m IC | 3m IC | 1m bot hit | 3m bot hit |
|---|---|---|---|---|---|
| V1.0 | All signals raw, including trend | +0.001 | +0.010 | 54% | 55% |
| V1.1 | Drop trend signals from composite | −0.019 | −0.019 | 56% | 55% |
| V1.2 | +HF count, +HF concentration, +HF Δ4q, +SI true | −0.012 | −0.004 | 55% | 57% |
| V1.3 | HF count signals → overlay (positive IC, trend) | −0.016 | −0.010 | 56% | 56% |
| V1.4 | HF concentration → overlay too; only `si_true_dtc` added to V1.1 | −0.020 | −0.021 | 56% | 56% |
| **V1.4 + min2** | **Require ≥2 buckets present for composite (drops noise)** | **−0.019** | **−0.022** | **55%** | **56%** |

Key empirical finding: **HF crowding by count is a TREND signal, not contrarian.** Including it in a "hot=late" composite hurts. NASDAQ true SI (days-to-cover) is the strongest individual signal in the whole panel (IC −0.064 at 3m).

## Data ingestion status (final)

| Provider | Source | Coverage | Rows | Status |
|---|---|---|---|---|
| Prices | Polygon Stocks | 10y, 386 tickers (univ + ETFs) | 757k | ✅ |
| Financials | Polygon `vx/list_stock_financials` | up to 16y per name w/ filing dates | 16k | ✅ |
| Insider Form 4 | Openinsider scrape | 10y, 366 names | 39k | ✅ |
| Short volume (proxy) | FINRA Reg SHO daily | 6.5y (pre-2018 unavailable on CDN) | 589k | ✅ |
| Short interest (true) | NASDAQ public API | 1y biweekly, NASDAQ-listed only (239 of 366) | 5k | ✅ |
| 13F holdings | EDGAR (curated 40 HF list) | 10y quarterly, 1,475 filings | 174k | ✅ |
| Options | yfinance forward / Polygon stub | — | — | ⏳ Phase 5 |
| ETF flows | derived from prices/AUM | — | — | ⏳ Phase 5 |
| EPS revisions | FactSet (live overlay only) | — | — | ⏳ optional |

## V1.4 final composite signals

**In composite (contrarian, "hot=late"):**

| Bucket | Signals | Best individual IC |
|---|---|---|
| Technical | ret_1m, ret_3m, ret_6m, dist_200ma, rsi_14, pct_from_52w_high | ret_3m IC −0.038 @ 3m |
| Valuation | ttm_pe, ev_sales | weak (ttm_pe IC +0.015 / ev_sales IC ~0) |
| Positioning | insider_net_90d_signed, short_volume_ratio_14d, si_true_dtc | **si_true_dtc IC −0.064 @ 3m** |

**Overlay only (computed but excluded from composite):**

- **Trend signals (positive IC):** ret_12m, rs_vs_qqq_3m, rs_vs_xlk_3m, insider_net_90d_abs, hf_count_13f, hf_count_change_4q
- **Weak signals (~0 IC):** hf_top_concentration

These show on the dashboard as context but don't move the temperature score.

## Top contrarian signals (proven by backtest)

Sorted by best IC:

| Signal | Best IC | Best decile spread | Bot decile hit | N |
|---|---|---|---|---|
| **si_true_dtc** | **−0.064** @ 3m | n/a (no pct_self) | 56% | 35k |
| ret_3m | −0.038 @ 3m | −3.34% | 60% | 579k |
| rsi_14 | −0.030 @ 1m | −0.84% | 57% | 615k |
| short_volume_ratio_14d | −0.025 @ 3m | −2.71% | 56% | 475k |
| insider_net_90d_signed | −0.022 @ 3m peer | n/a | 64% | 174k |
| pct_from_52w_high | −0.019 @ 1m | −0.87% | 57% | 611k |
| ret_1m | −0.013 @ 3m | n/a | 56% | 632k |

## Files

```
positioning_meter/
├── DESIGN.md           — architecture decisions
├── SUMMARY.md          — THIS FILE
├── QUESTIONS.md        — decisions log
├── config.yaml         — runtime config
├── requirements.txt
├── data/
│   ├── universe.csv         — 366 names with cluster_id
│   ├── cusip_to_ticker.csv  — 471 CUSIP→ticker mappings (97% coverage)
│   ├── hf_filers.csv        — 40 curated HF CIKs
│   ├── positioning.db       — SQLite store (11 tables, 1.6M+ rows)
│   ├── dashboard.html       — daily ranked snapshot
│   ├── backtest_report.md   — latest backtest metrics
│   └── backtest_results.json
├── lib/
│   ├── config.py
│   ├── db.py
│   ├── peers.py
│   ├── backtest.py
│   └── signals/
│       ├── loaders.py
│       ├── technical.py
│       ├── valuation.py
│       ├── positioning.py
│       ├── percentiles.py
│       └── composite.py
├── providers/
│   ├── base.py
│   ├── polygon_prices.py
│   ├── polygon_financials.py
│   ├── finra_short.py
│   ├── nasdaq_si.py         — V1.2 add
│   ├── openinsider.py
│   ├── edgar_13f.py         — V1.2 add
│   └── yfinance_fundamentals.py (deprecated)
├── setup/
│   ├── 01_build_universe.py
│   ├── 02_ingest_prices.py
│   ├── 03_ingest_financials.py
│   ├── 04_ingest_short_volume.py
│   ├── 05_ingest_insider.py
│   ├── 06_compute_signals.py     — V1.4 weights
│   ├── 07_run_backtest.py
│   ├── 08_render_dashboard.py
│   ├── 09_ingest_nasdaq_si.py    — V1.2 add
│   ├── 10_build_cusip_map.py     — V1.2 add
│   ├── 11_build_hf_list.py       — V1.2 add
│   └── 12_ingest_13f.py          — V1.2 add
└── tools/
    └── validate_providers.py
```

## Open questions still active

See `QUESTIONS.md` for full list. Headline:

- **Polygon $200/mo Options tier** — confirm pricing & subscribe (solves options bucket fully)
- **Compound flag thresholds** (currently 85/85/80) — empirical from backtest still TBD
- **HF list expansion** — 40 funds is V1; could grow to 100-200 over time, but backtest suggests count signal isn't valuable so V1 list is sufficient
- **NASDAQ SI history depth** — 1y is short. Could supplement with a paid source (S3, Ortex) if SI signal continues to perform

## Build phases — final state

| Phase | Status |
|---|---|
| 0. Skeleton | ✅ done |
| 1A. Data ingestion | ✅ done — 6 providers, ~1.6M rows |
| 1B. Signal compute | ✅ done — 18 signals, 13 in composite |
| 2. Backtest | ✅ done — 4 iterations, V1.4 final |
| 3. Daily pipeline | 🟡 scripts done, cron not configured |
| 4. Dashboard | ✅ done |
| 4b. V1.1 (drop trend) | ✅ done |
| 4c. NASDAQ SI scraper | ✅ done |
| 4d. EDGAR 13F | ✅ done |
| 4e. V1.4 retune | ✅ done |
| 5. Options snapshots | ⏳ deferred (Polygon $200/mo when ready) |

## How to run

```bash
cd ~/Documents/AI\ workflows/positioning_meter

# Daily refresh (one-shot, after providers have been built)
python3 setup/02_ingest_prices.py        # 5 min
python3 setup/03_ingest_financials.py    # 3 min
python3 setup/04_ingest_short_volume.py  # daily delta only — fast
python3 setup/05_ingest_insider.py       # daily delta — fast
python3 setup/09_ingest_nasdaq_si.py     # NASDAQ-only, 16 min
python3 setup/12_ingest_13f.py           # quarterly only — 25 min

# Once daily after data refresh:
python3 setup/06_compute_signals.py      # 3 min
python3 setup/07_run_backtest.py         # 2 min (re-tune)
python3 setup/08_render_dashboard.py     # 30 sec
open data/dashboard.html
```
