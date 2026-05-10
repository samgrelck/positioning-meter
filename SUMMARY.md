# Positioning Meter — Running Summary

> Single source of truth for current state. Updated after each milestone.
> Sister docs: `DESIGN.md` (architecture), `QUESTIONS.md` (decisions/caveats), `GITHUB_SETUP.md` (publishing), `data/backtest_report.md` (latest backtest).

**Last updated:** 2026-05-10 — **V1.6: positioning-weighted composite (0.7/0.3) + dashboard QoL upgrades**

---

## At a glance

| | Status |
|---|---|
| Universe | 366 TMT names, mcap ≥ $1.5B, drawn from theme_detector |
| Backtest horizon | 10y for most signals; 6.5y for short volume; 1y for true SI |
| Composite output | working — IC **−0.026**, decile spread −2.64%, bot decile hit 56% at 3m fwd (V1.6 — re-weighted to 0.7 pos / 0.3 tech via grid search) |
| Composite scope | **sentiment / positioning only** — valuation is overlay (V1.5 design choice, not backtest-forced) |
| Dashboard | `data/dashboard.html` (also at `docs/index.html` for GitHub Pages) — interactive search, filter, drill-down, CSV export, glossary |
| Backtest report | `data/backtest_report.md` |
| GitHub | local repo committed; see `GITHUB_SETUP.md` to publish |

## V1.5 sample readings (validates design)

Removing valuation cools names whose temperature was inflated by "expensive" alone:

| Ticker | V1.4 temp | V1.5 temp | Why it changed |
|---|---|---|---|
| NVDA | ~67 | **48.4** | Was inflated by val 88. Now pos 30 + tech 66 — true mid-range |
| INTC | 79.5 | **73.3** | Mostly held — pos 47 + tech 100 still hot |
| MU | 60.7 | **62.6** | Roughly unchanged — wasn't valuation-driven |

The composite now reads PURELY sentiment + positioning. Names that look "hot" in V1.5 are stretched on positioning AND price action, not just expensive.

## Composite evolution

| Version | Change | 1m IC | 3m IC | 1m bot hit | 3m bot hit |
|---|---|---|---|---|---|
| V1.0 | Kitchen sink, all signals raw | +0.001 | +0.010 | 54% | 55% |
| V1.1 | Drop trend signals from composite | −0.019 | −0.019 | 56% | 55% |
| V1.2 | +HF count/concentration/Δ4q + true SI | −0.012 | −0.004 | 55% | 57% |
| V1.3 | HF count signals → overlay | −0.016 | −0.010 | 56% | 56% |
| V1.4 | HF concentration → overlay; only `si_true_dtc` kept | −0.020 | −0.021 | 56% | 56% |
| V1.4 + min2 | Require ≥2 buckets present | −0.019 | −0.022 | 56% | 56% |
| V1.5 | Valuation → overlay (sentiment/positioning only) | −0.020 | −0.020 | 55% | 56% |
| **V1.6** | **Re-weight composite via grid search: pos 0.7 / tech 0.3** | **−0.020** | **−0.026** | **55%** | **56%** |

## Data ingestion status

| Provider | Source | Coverage | Rows | Status |
|---|---|---|---|---|
| Prices | Polygon Stocks | 10y, 386 tickers | 757k | ✅ |
| Financials | Polygon `vx/list_stock_financials` | up to 16y w/ filing dates | 16k | ✅ |
| Insider Form 4 | openinsider scrape | 10y, 366 names | 39k | ✅ |
| Short volume (proxy) | FINRA Reg SHO daily | 6.5y | 589k | ✅ |
| Short interest (true) | NASDAQ public API | 1y biweekly, NASDAQ-only | 5k | ✅ |
| 13F holdings | EDGAR (40 curated HFs) | 10y quarterly, 1,475 filings | 174k | ✅ |
| **Estimates (Yahoo)** | **yfinance — fwd EPS, target dispersion, recommendation** | **forward-only daily snapshots** | **growing** | **✅ (re-running)** |
| **Earnings calendar** | **yfinance** | **per-ticker next earnings** | **growing** | **✅** |
| **ETF AUM** | **yfinance totalAssets** | **forward-only daily snapshots** | **growing** | **✅** |
| **Analyst actions** | **yfinance upgrades_downgrades** | **rolling 12m** | **growing** | **✅** |
| Options | (deferred — Polygon $200/mo tier) | — | — | ⏳ |

## V1.5 final composite signals

**In composite (contrarian, "hot=late") — sentiment + positioning only:**

| Bucket | Weight | Signals | Best individual IC |
|---|---|---|---|
| Technical (sentiment via price) | 0.50 | ret_1m, ret_3m, ret_6m, dist_200ma, rsi_14, pct_from_52w_high | ret_3m IC −0.038 @ 3m |
| Positioning | 0.50 | insider_net_90d_signed, short_volume_ratio_14d, si_true_dtc | **si_true_dtc IC −0.064 @ 3m** |
| ~~Valuation~~ | 0.00 | (overlay only — see below) | excluded V1.5 |

**Overlay only (computed but excluded from composite):**

- **Trend signals (positive IC):** ret_12m, rs_vs_qqq_3m, rs_vs_xlk_3m, insider_net_90d_abs, hf_count_13f, hf_count_change_4q
- **Weak signals (~0 IC):** hf_top_concentration
- **Valuation (V1.5 — fundamental, not sentiment):** **NTM P/E** (computed at render time from `estimates_daily.forward_eps` × latest price). TTM multiples explicitly excluded per design choice. NTM EV/Sales not computed — Yahoo doesn't expose forward revenue consensus.

**Live overlays (no backtest, current snapshot only):**
- Forward EPS (consensus)
- Target price + dispersion
- # analyst opinions
- Recommendation key + mean
- Recent analyst actions (rolling 12m)
- Next earnings date (`flag_earnings_soon` triggered if within 14 days)
- ETF AUM + daily flow estimate (forward-only)

**New derived metrics (V2.0):**
- **Conviction** (0–100): how aligned the buckets are. High = all hot or all cold; low = mixed.
- **Anomaly count** (0–N): # of signals where ticker is at 90th+ %ile vs cluster peers today.

## Dashboard features (V2.0)

- 📘 **Glossary** at top — every metric explained
- 🔍 **Search box** — filter by ticker or name across all panels
- 🧬 **Cluster filter** — show only theme_detector cluster X
- 🏷️ **Sector group filter** — 13 hand-curated TMT thematic groups (AI Infra, Cybersecurity, Cloud Infra Software, etc.)
- 🔥/❄️ **Hot/cold panels** — top 25 each direction
- 📈/📉 **7-day mover panels** — names heating up / cooling off
- 🆕 **NEW flag panels** — names that newly entered late_signal or washout in past 7 days
- 📅 **Earnings-soon panel** — names reporting within 14 days
- 👁️ **Watchlist panel** — tickers added to `watchlist` table
- 📥 **CSV export** — current snapshot to clipboard-paste-ready CSV
- 📊 **Backtest summary card** — per-signal IC + composite metrics
- 🕒 **Provenance footer** — last refresh timestamp per provider
- 🔍 **Per-ticker drill-down** — for ALL 366 names, includes:
  - Temperature sparkline (last ~30 days)
  - Per-signal raw value + percentile vs self + percentile vs peer
  - Live overlay (forward EPS, target dispersion, analyst recs)
  - Recent analyst actions (last 90d)
  - Cluster + sector group memberships with anchor links
  - Notes field (read from `ticker_notes` table)
  - Earnings date if soon

## Architecture additions in V2.0

**New tables:**
- `estimates_daily` — Yahoo consensus + recommendation snapshot
- `analyst_actions` — upgrades/downgrades log
- `earnings_calendar` — next earnings date per ticker
- `ticker_notes` — analyst-authored notes per ticker
- `watchlist` — tickers to highlight
- `etf_aum` (rebuilt) — daily AUM + flow estimate

**New providers:**
- `providers/yahoo_estimates.py` — fwd EPS, target prices, recommendations, actions, earnings date
- `providers/etf_flows.py` — daily ETF AUM snapshot

**New ingestion scripts:**
- `setup/13_ingest_estimates.py`
- `setup/14_ingest_etf_flows.py`

**New compute additions:**
- `compute_conviction()` in `lib/signals/composite.py`
- `compute_anomaly()` in `lib/signals/composite.py`
- Earnings-soon flag joined in `setup/06_compute_signals.py`

**New data files:**
- `data/sector_groups.json` — 13 hand-curated TMT thematic groups
- `data/cusip_to_ticker.csv` — 471 CUSIP→ticker mappings
- `data/hf_filers.csv` — 40 curated HF CIKs

## Open questions still active

See `QUESTIONS.md`. Headlines:
- **Polygon Options $200/mo** — biggest unbuilt feature
- **NASDAQ SI extension** — NYSE-listed names (35% of universe) lack true SI
- **HF list size** — 40 funds for V1; backtest showed count signals don't help so probably not worth growing
- **Notes/watchlist editing UI** — currently SQL-only; could add inline editing with form POST

## Build phases — final state

| Phase | Status |
|---|---|
| 0. Skeleton | ✅ |
| 1A. Data ingestion (8 providers) | ✅ |
| 1B. Signal compute (18 signals) | ✅ |
| 2. Backtest (4 iterations) | ✅ |
| 3. Daily pipeline (manual run via `tools/deploy.sh`) | ✅ |
| 4. Dashboard V2 (glossary, drill-down, filters, CSV, sparklines) | ✅ |
| 4b. V1.1 retune (drop trend signals) | ✅ |
| 4c. NASDAQ SI scraper | ✅ |
| 4d. EDGAR 13F + curation | ✅ |
| 4e. V1.4 retune (HF → overlay) | ✅ |
| 4f. min-buckets filter | ✅ |
| 4g. Yahoo estimates + ETF flows + earnings calendar | ✅ |
| 4h. Conviction + anomaly metrics | ✅ |
| 4i. Sector groups + per-ticker drill-down + watchlist + CSV export | ✅ |
| 4j. GitHub repo init + Pages-ready (`docs/index.html`) | ✅ |
| 5. Options snapshots | ⏳ deferred |

## How to publish online

See `GITHUB_SETUP.md`. Two-line summary:

```bash
gh repo create positioning-meter --public --source=. --push
gh repo edit --enable-pages --pages-branch=main --pages-path=/docs
```

Then dashboard lives at `https://USERNAME.github.io/positioning-meter/`.

## How to refresh

```bash
./tools/deploy.sh
```

Re-renders + commits + pushes. Pages updates in ~30 seconds.

## Files

```
positioning_meter/
├── README.md                — public-facing project description
├── DESIGN.md                — architecture decisions
├── SUMMARY.md               — THIS FILE
├── QUESTIONS.md             — decisions log + caveats
├── GITHUB_SETUP.md          — publish-to-Pages instructions
├── config.yaml              — runtime config
├── requirements.txt
├── .gitignore
├── data/
│   ├── universe.csv         — 366 names with cluster_id
│   ├── sector_groups.json   — 13 hand-curated TMT thematic groups
│   ├── cusip_to_ticker.csv  — 471 CUSIP→ticker mappings
│   ├── hf_filers.csv        — 40 curated HF CIKs
│   ├── positioning.db       — SQLite store (~14 tables, 1.6M+ rows)
│   ├── dashboard.html       — interactive daily snapshot
│   ├── backtest_report.md
│   └── backtest_results.json
├── docs/
│   └── index.html           — copy of dashboard.html for GitHub Pages
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
│   ├── nasdaq_si.py
│   ├── openinsider.py
│   ├── edgar_13f.py
│   ├── yahoo_estimates.py
│   └── etf_flows.py
├── setup/                   — 14 scripts (universe build, ingestion, compute, backtest, render)
└── tools/
    ├── validate_providers.py
    └── deploy.sh            — one-command refresh + push
```
