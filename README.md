# Positioning Meter

A daily-run sentiment/positioning analysis tool for individual TMT stocks.

Measures how **crowded, hot, and stretched** each name is across positioning, valuation, and technical buckets — to help judge how early or late we are in a move.

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

## Backtest results (V1.4)

- **Composite IC −0.022** at 3-month forward (Spearman)
- **Decile spread −2.30%** (top minus bottom decile mean fwd return)
- **Bottom decile hit rate 56%** (positive forward return when temperature is low)
- Strongest individual signal: `si_true_dtc` (NASDAQ days-to-cover) IC −0.064 at 3m

See `data/backtest_report.md` for full per-signal metrics.

## Setup

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
python3 setup/09_ingest_nasdaq_si.py      # NASDAQ true SI, 1y
python3 setup/12_ingest_13f.py            # EDGAR 13F, 10y
python3 setup/13_ingest_estimates.py      # Yahoo estimates snapshot
python3 setup/14_ingest_etf_flows.py      # ETF AUM snapshot

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
| Short interest (true) | NASDAQ public API | 1y biweekly, NASDAQ-only |
| Insider Form 4 | openinsider.com (pre-parsed) | 10y |
| 13F holdings | SEC EDGAR | 10y, 40 curated HFs |
| Estimates / actions / earnings | Yahoo Finance | live snapshot |
| ETF AUM | Yahoo Finance | forward-only |

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

- **Options bucket** — not implemented (would require Polygon Options $200/mo). 4 signals would augment positioning bucket.
- **EPS revisions historical** — FactSet has it but no bulk export; live snapshot only.
- **ETF flows historical** — paid data needed; forward-only without it.
- **NASDAQ true SI** — only NASDAQ-listed names (~65% of universe).
- **13F** — 45-day reporting lag, long-only blind spot.
- **Pre-2018 short volume** — FINRA CDN doesn't host it.

## License

Personal research tool. No license — not for redistribution.
