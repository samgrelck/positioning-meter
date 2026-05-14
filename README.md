# Positioning Meter

A daily-run **sentiment / positioning** analysis tool for individual TMT stocks.

Measures how **crowded, hot, and stretched** each name is via the positioning bucket (insider, short interest, 13F), technical bucket (sentiment via price action: momentum, RSI, distance from MAs), and options bucket (IV rank, skew, term slope, P/C ratio). Valuation is shown as overlay context but excluded from the composite — fundamental analysis is done separately.

---

## 🚀 Quick reference

```bash
# Just refresh the dashboard from current DB (no fresh data, ~1 min):
cd ~/Documents/AI\ workflows/positioning_meter && ./tools/deploy.sh

# Full refresh: pull fresh daily data + recompute + push (~70 min):
cd ~/Documents/AI\ workflows/positioning_meter && ./tools/refresh_data.sh

# Faster version that skips Yahoo estimates + options (~16 min):
./tools/refresh_data.sh fast

# Open the dashboard locally:
open ~/Documents/AI\ workflows/positioning_meter/data/dashboard.html
```

**→ For full daily-use guide, cadence guidance, troubleshooting, and where everything lives, see [USAGE.md](USAGE.md).**

---

## What it shows

- **Temperature** (0–100) per name — composite contrarian score
- **Bucket scores** — positioning / valuation / technical breakdown
- **Compound flags** — late-signal, washout, divergence, earnings-soon
- **Conviction** — how aligned the buckets are
- **Anomaly count** — # of signals where name stands out from cluster peers
- **Per-ticker drill-down** — every signal with raw value + percentile, plus live overlay (consensus EPS, target dispersion, recent analyst actions, earnings date)

## Output

- `data/dashboard.html` — interactive daily snapshot (search, filter, drill-down, CSV export)
- `data/backtest_report.md` — IC, decile spreads, hit rates per signal
- `SUMMARY.md` — running build state

## Universe

366 TMT names, market cap ≥ $1.5B, drawn from sister `theme_detector` project. Theme_detector clusters serve as peer groups for cross-sectional percentile ranking.

## Backtest results (V1.13)

- Composite IC **−0.034** at 3-month forward (Spearman)
- Decile spread **−2.4%** (top minus bottom decile mean fwd return)
- Bottom decile hit rate **59%** (positive forward return when temperature is low)
- Bucket weights: **Positioning 0.40 / Technical 0.25 / Options 0.35** (positioning-leaning per conceptual prior)
- Strongest individual signal: `si_true_dtc` (FINRA biweekly days-to-cover) IC **−0.030** at 3m

**Key history:**
- V1.10 had an inflated IC of −0.040 driven by si_true_dtc IC of −0.103 measured on only 1y of NASDAQ-only data. Out-of-sample testing with FINRA's full universe-wide SI history revealed that figure was overfit; the more credible IC is −0.030.
- V1.11 added FINRA biweekly SI files (2018-05 onward) covering 365/366 universe tickers including all NYSE-listed names.
- V1.12 applied conservative cut per FINRA's own documentation ("Prior to June 2021, the data contains positions in OTC securities only"), retaining only post-June-2021 data — 5 years verified universe-wide.
- V1.13 adopted positioning-leaning weights to reflect the conceptual case that positioning + options data are harder to fake than reflexive price signals.

**Options bucket** (IV rank, 25Δ skew, term slope, P/C ratio) accumulates forward-only via yfinance. Cannot be backtested without paid historical options data — gets equal-weight within bucket and 0.35 bucket weight as a placeholder. See Limitations.

See `data/backtest_report.md` for full per-signal metrics.

## 🚀 Daily use — the one command you need

After initial setup is complete, refreshing the dashboard is a single command:

```bash
cd ~/Documents/AI\ workflows/positioning_meter
./tools/deploy.sh
```

That does the full daily refresh:
1. Recomputes all signals from current DB state
2. Re-runs the backtest
3. Renders `data/dashboard.html`
4. Copies to `docs/index.html` for GitHub Pages
5. Commits and pushes to GitHub
6. GitHub Pages rebuilds in ~30 seconds — your dashboard is live at `https://samgrelck.github.io/positioning-meter/`

**Note:** `deploy.sh` does not run the data ingestion scripts (which can take minutes to hours). To pull new daily data first, see the "Refreshing source data" section below.

```bash
# Open the dashboard locally (no GitHub push needed)
open data/dashboard.html
```

## Refreshing source data (run as often as you want — daily, weekly, etc.)

```bash
# Most-frequent (lightweight, run daily):
python3 setup/02_ingest_prices.py         # ~4 min — Polygon prices
python3 setup/13_ingest_estimates.py      # ~35 min — Yahoo estimates + analyst actions
python3 setup/14_ingest_etf_flows.py      # ~2 min — ETF AUM snapshot
python3 setup/15_ingest_options_yahoo.py  # ~18 min — Yahoo options chains
python3 setup/05_ingest_insider.py        # ~10 min — openinsider Form 4 (only need fresh if Form 4s file daily)

# Less-frequent (run weekly or as needed):
python3 setup/04_ingest_short_volume.py   # ~10 min — FINRA daily (biweekly settlement source)
python3 setup/09_ingest_nasdaq_si.py      # ~16 min — NASDAQ true SI (biweekly cadence)
python3 setup/03_ingest_financials.py     # ~3 min — Polygon financials (quarterly cadence)

# Quarterly only:
python3 setup/12_ingest_13f.py            # ~25 min — EDGAR 13F (filings come out 45d after quarter-end)

# After any data refresh, run deploy.sh to recompute + render + push:
./tools/deploy.sh
```

## Setup (one-time)

```bash
pip install -r requirements.txt

# Set environment variables (or place in .env at project root)
export POLYGON_API_KEY=...
export SEC_EDGAR_USER_AGENT="Your Name your@email.com"

# One-time setup
python3 setup/01_build_universe.py        # 366 names from theme_detector
python3 setup/10_build_cusip_map.py       # CUSIP→ticker mapping (97% coverage)
python3 setup/11_build_hf_list.py         # Resolve 40 HF CIKs from SEC

# Backfill historical data (slow on first run)
python3 setup/02_ingest_prices.py         # 10y Polygon prices
python3 setup/03_ingest_financials.py     # Polygon financials, ~16y
python3 setup/04_ingest_short_volume.py   # FINRA Reg SHO, 6.5y
python3 setup/05_ingest_insider.py        # openinsider Form 4, 10y
python3 setup/12_ingest_13f.py            # EDGAR 13F, 10y
python3 setup/13_ingest_estimates.py      # Yahoo estimates snapshot
python3 setup/14_ingest_etf_flows.py      # ETF AUM snapshot
python3 setup/15_ingest_options_yahoo.py  # Yahoo options chains (forward-only)
python3 setup/17_download_finra_si.py     # FINRA biweekly SI files 2018+
python3 setup/18_ingest_finra_si.py       # Parse FINRA SI, drop pre-June-2021
# (setup/09_ingest_nasdaq_si.py — RETIRED in V1.11 — replaced by FINRA full-universe)

# Compute + render (run daily after ingestion)
python3 setup/06_compute_signals.py
python3 setup/07_run_backtest.py
python3 setup/08_render_dashboard.py
open data/dashboard.html
```

## Data sources

| Provider | Source | Coverage |
|---|---|---|
| Prices | Polygon Stocks | 10y daily, split-adjusted |
| Financials | Polygon `vx/list_stock_financials` | up to 16y w/ filing dates |
| Short volume | FINRA Reg SHO daily files | 6.5y |
| **Short interest (true)** | **FINRA biweekly Short Interest files** | **~5y universe-wide (post-June-2021, exchange-listed confirmed per FINRA docs)** |
| Insider Form 4 | openinsider.com (pre-parsed) | 10y |
| 13F holdings | SEC EDGAR | 10y, 40 curated HFs |
| Estimates / actions / earnings | Yahoo Finance | live snapshot |
| ETF AUM | Yahoo Finance | forward-only |
| Options chains | Yahoo Finance (yfinance) | forward-only |

## Architecture

See [`DESIGN.md`](DESIGN.md) and [`SUMMARY.md`](SUMMARY.md) for full context.

```
positioning_meter/
├── DESIGN.md       — architecture decisions
├── SUMMARY.md      — running build state
├── QUESTIONS.md    — decisions log + caveats
├── config.yaml
├── lib/            — config, db, peer mapping, backtest, signal modules
├── providers/      — Polygon, FINRA, NASDAQ, openinsider, EDGAR, Yahoo
├── setup/          — one-time + ingestion scripts
├── tools/          — validation scripts
└── data/
    ├── universe.csv            — 366-name universe with cluster_id
    ├── sector_groups.json      — hand-curated TMT thematic groups
    ├── cusip_to_ticker.csv     — CUSIP→ticker map for 13F mapping
    ├── hf_filers.csv           — 40 HF CIKs
    ├── positioning.db          — SQLite store
    ├── dashboard.html          — daily output
    └── backtest_report.md      — backtest metrics
```

## Limitations & deferred items

- **Options backtest** — not possible without paid historical data. Author doesn't qualify for non-professional rates due to FINRA registration + Truist Wealth employment; professional rate ($1,999/mo Polygon Options Business) not justified for personal research; FactSet export to personal computer violates employer policy. **Decision:** stay on yfinance forward-only accumulation. 3 of 4 composite options signals work today via cross-sectional ranking; IV rank populates after 20+ days. Infrastructure for paid historical (`setup/16_ingest_options_polygon.py`) is stubbed and ready if/when institutional access becomes available.
- **EPS revisions historical** — FactSet has it but no bulk export; live snapshot only.
- **ETF flows historical** — paid data needed; forward-only via yfinance.
- **NASDAQ true SI** — only NASDAQ-listed names (~65% of universe).
- **13F** — 45-day reporting lag, long-only blind spot.
- **Pre-2018 short volume** — FINRA CDN doesn't host it.

## License

Personal research tool. No license — not for redistribution.
