# Positioning Meter — Design Document

> **V1.5 status:** sentiment / positioning / expectations only. Valuation moved to overlay (still shown on drill-down). See `SUMMARY.md` for current state.

A daily-run system that measures **how crowded, hot, and stretched** individual TMT stocks are along sentiment + positioning dimensions, to help a discretionary L/S analyst judge how early or late we are in a move. Valuation is assessed separately by the analyst.

> **Project name TBD.** Working name `positioning_meter`. Alternatives: `crowding_monitor`, `temperature_meter`, `sentiment_gauge`. Easy to rename later.

---

## 1. Purpose & non-goals

**Purpose.** For each name in the TMT universe, output a **percentile-vs-own-history composite score** ("temperature") plus per-bucket subscores (positioning, technical/sentiment, eventually options + flows), so the analyst can quickly answer: *how crowded is the trade, where in the sentiment cycle are we, how stretched is positioning?*

**V1.5 scope clarification:** valuation is computed and visible on drill-downs as overlay, but does NOT enter the composite. The composite is purely sentiment/positioning/expectations.

**Use cases.**
- Triage: which names on the long/short watchlist are stretched vs. quiet?
- Timing: combined with thesis, identify late-stage longs to trim or fade, and washed-out shorts to cover
- Cross-confirmation: when positioning + momentum + valuation %ile all extreme, weight the contrarian read more

**Non-goals.**
- Not a thesis generator. Doesn't tell you *why* anything is moving (theme_detector does that).
- Not an alpha factor model. Doesn't try to forecast forward returns directly.
- Not real-time intraday. Daily close cadence, like theme_detector.
- Not multi-asset. Equity (and equity options) only, TMT only.

---

## 2. Universe

**Source:** `~/Documents/AI workflows/theme_detector/data/universe.csv` (516 names, refreshed quarterly there).

**Filter:** `market_cap >= $1.5B` → ~366 names.

**Per-signal eligibility filters** (applied at signal computation, not universe construction):
- Options-derived signals require **avg daily options volume ≥ 1,000 contracts** OR **mcap ≥ $3B** (whichever stricter, TBD after measuring). Names failing this get `null` for options signals, which the composite handles via reweighting.
- 13F crowding requires ≥ 50 institutional holders to be meaningful.

**Refresh cadence:** weekly pull from theme_detector universe; weekly re-check of options eligibility.

**Survivorship handling for backtest:** V1 accepts survivorship bias and documents it. V2 reconstructs point-in-time universe from delisting datasets (TBD source — may require Polygon's reference data or CRSP via WRDS).

---

## 3. Signal taxonomy

Five buckets, each producing a 0–100 percentile-vs-own-history subscore. Composite is a weighted average of bucket scores.

### 3.1 Positioning (slow-moving, structural)

| Signal | Formula | Source | Update | Backtest history |
|---|---|---|---|---|
| HF crowding | % of float held by HFs (top 200 by 13F AUM) | SEC EDGAR 13F | Quarterly (45-day lag) | Yes, 10y+ |
| HF concentration | Σ (top-10 HF weights) | SEC EDGAR 13F | Quarterly | Yes, 10y+ |
| Short interest % float | SI / float | FINRA biweekly | Biweekly | Yes, 10y+ |
| Days-to-cover | SI / 20d avg vol | FINRA + yfinance | Biweekly | Yes, 10y+ |
| Insider net activity | Σ Form 4 net $ buys − net $ sells, 90d | EDGAR / openinsider | Daily | Yes, 10y+ |

**Subscore:** average of percentile ranks of each signal vs. own 5y history.

**Insider polarity decision** — included in composite for V1, polarity decided by backtest. Two candidate encodings will be evaluated:
- (a) raw net insider $ — "hot" = heavy *selling* (insider distribution to public)
- (b) absolute net insider $ — "hot" = unusual activity in either direction
Backtest forward returns at top decile of each encoding will pick the winner. If neither shows signal, demote to overlay.

### 3.2 Options-implied (fast-moving)

| Signal | Formula | Source | Update | Backtest history |
|---|---|---|---|---|
| IV rank | (current 30d IV − 1y min) / (1y max − 1y min) | Polygon (paid) or yfinance (forward only) | Daily | Polygon: 10y. Free: forward only. |
| IV term slope | front-month IV − 3m IV | Polygon / yfinance | Daily | Same |
| 25-Δ skew | IV(25Δ put) − IV(25Δ call) | Polygon / yfinance | Daily | Same |
| P/C volume ratio | put vol / call vol, 5d avg | Polygon / yfinance | Daily | Same |
| Options vol vs avg | today / 20d avg | Polygon / yfinance | Daily | Same |

**Subscore:** percentile rank of skew, IV rank, term slope, and P/C vs own 1y history. Bucket weighted lower or null'd for names failing options eligibility filter.

### 3.3 Flows

| Signal | Formula | Source | Update | Backtest history |
|---|---|---|---|---|
| Sector ETF AUM Δ | 1w / 4w shares-outstanding Δ for parent ETFs (XLK, SOXX, IGV, SMH, XLC, ARKK, etc.) | yfinance + iShares/SPDR JSON | Daily | Yes, 10y+ |
| Single-stock leveraged ETF AUM Δ | TSLL, NVDL, MSFU, etc. | yfinance | Daily | Limited (most launched 2022+) |
| ETF inclusion weight Δ | name's % weight in parent ETFs | iShares/SPDR JSON | Weekly | 5y+ |

**Subscore:** percentile of weighted flow into the name's parent ETFs.

### 3.4 Valuation expectations

| Signal | Formula | Source | Update | Backtest history |
|---|---|---|---|---|
| NTM P/E percentile | NTM P/E vs own 5y history | yfinance + computed NTM EPS | Daily | Yes, 5y+ (NTM EPS may be sparse for smaller names) |
| EV/Sales percentile | vs own 5y history | yfinance fundamentals | Daily | Yes, 5y+ |
| Implied move into earnings vs realized | ATM straddle implied vol-of-event vs trailing 8q realized | Options provider | Pre-earnings | With Polygon |

**Subscore:** average percentile rank.

### 3.5 Price / technical

| Signal | Formula | Source | Update | Backtest history |
|---|---|---|---|---|
| Trailing returns | 1m, 3m, 6m, 12m | yfinance | Daily | Yes, 10y+ |
| Distance from 200d MA | (price − MA200) / MA200 | yfinance | Daily | Yes |
| RSI(14) | standard | yfinance | Daily | Yes |
| % from 52w high | standard | yfinance | Daily | Yes |
| Relative strength vs sector ETF | trailing-3m return − sector ETF 3m return | yfinance | Daily | Yes |
| Relative strength vs QQQ | trailing-3m return − QQQ 3m return | yfinance | Daily | Yes |

**Subscore:** percentile rank composite. Note this bucket measures "how stretched" not "good or bad" — extreme reading (very high or very low) signals extreme positioning regardless of direction.

### 3.6 NOT included in composite (live overlays only)

| Signal | Why not in composite |
|---|---|
| **EPS revision breadth** (4w/12w % up vs down) | Validated in literature but no free historical data; FactSet live-only. Show alongside composite as overlay. |
| Sell-side rating distribution | Lagged, conflicted, low signal. Glance at FactSet directly. |
| Target price dispersion | Same. |
| Social media sentiment | S/N too poor for fundamental TMT names. Scrap unless V3 sees a vendor worth paying for. |

---

## 4. Composite scoring

**Per-signal scoring — dual percentile.** Every signal produces TWO percentile ranks:
- **`pct_self`** — vs own trailing history (5y for slow signals, 1y for options)
- **`pct_peer`** — vs theme_detector cluster peers at same date (cross-sectional)

Per-bucket score = average of `0.5 · pct_self + 0.5 · pct_peer` across constituent signals. The 50/50 weight is initial — backtest may retune.

**Peer-group source:** `~/Documents/AI workflows/theme_detector/data/clusters.json`. Already curated for TMT, far better than SIC. Names not in any cluster (e.g. outliers, very small) get `pct_peer = null` and fall back to `pct_self` only.

**Per-bucket score:** average of constituent dual-percentiles, 0–100.

**Composite:**
```
temperature = w_positioning · S_pos
            + w_options    · S_opt
            + w_flows      · S_flow
            + w_valuation  · S_val
            + w_technical  · S_tech
```

**V1.5 weights:**
- Positioning: 0.50
- Technical: 0.50
- Options: 0.00 (placeholder for Phase 5)
- Flows: 0.00 (placeholder)
- ~~Valuation~~: 0.00 (excluded — see V1.5 decision in QUESTIONS.md)

**Original (V1.0) weights** were 0.25/0.25/0.10/0.20/0.20. Backtest iterations narrowed scope.

**Missing-data handling:** if a bucket is null (e.g. options for thinly-traded names), redistribute its weight proportionally across remaining buckets.

**Output per ticker per day:**
```json
{
  "ticker": "NVDA",
  "date": "2026-05-08",
  "temperature": 87,
  "buckets": {
    "positioning": 92,
    "options":     85,
    "flows":       78,
    "valuation":   95,
    "technical":   84
  },
  "flags": {
    "extreme_crowding": true,
    "extreme_valuation": true,
    "stretched_momentum": true,
    "compound_late_signal": true
  },
  "overlays": {
    "eps_revision_breadth_4w": 0.65,
    "rating_distribution": {"buy": 18, "hold": 7, "sell": 2}
  }
}
```

**Compound flags** are where this becomes decision-useful:
- `compound_late_signal`: positioning ≥ 85 AND technical ≥ 85 AND valuation ≥ 80
- `compound_washout`: positioning ≤ 15 AND technical ≤ 15 AND valuation ≤ 25
- `divergence_warning`: technical ≥ 80 AND options ≤ 30 (price up, options not buying it)

---

## 5. Data architecture

### 5.1 Provider abstraction

Each external data source behind an abstract provider class. Day-one implementations:

```
providers/
  prices.py
    YFinanceProvider           # free, daily OHLCV + fundamentals
    PolygonProvider            # already used by theme_detector — reuse client
  options.py
    YahooOptionsProvider       # free, snapshot only — accumulates forward
    PolygonOptionsProvider     # stub, $200/mo Options Starter — switch via config
  ownership.py
    EdgarProvider              # 13F + Form 4 from SEC EDGAR (reuse theme_detector cache)
    OpenInsiderProvider        # supplemental Form 4 enrichment
  short_interest.py
    FinraProvider              # biweekly settlement files
  flows.py
    EtfHoldingsProvider        # iShares/SPDR/Invesco JSON endpoints
  estimates.py                 # OVERLAY ONLY, not in composite
    YahooEstimatesProvider     # free scrape of consensus snapshot
    FactSetProvider            # stub for future, manual export workflow
```

### 5.2 Storage

- **SQLite**, mirroring theme_detector's pattern (`prices.db`, `descriptions.db`).
- One DB: `data/positioning.db`
- Tables: `prices`, `options_daily`, `holdings_13f`, `insider_form4`, `short_interest`, `etf_flows`, `valuation_daily`, `signals_daily`, `composite_daily`
- All tables include `(ticker, date)` PK or composite PK as appropriate.
- Raw provider responses cached as JSON in `data/cache/` for replay/debug.

### 5.3 Daily pipeline

```
daily/
  01_fetch_prices.py        # yfinance / Polygon
  02_fetch_options.py       # yfinance snapshots → options_daily
  03_fetch_short_interest.py # FINRA, run on settlement days
  04_fetch_insider.py       # EDGAR Form 4 daily delta
  05_fetch_etf_flows.py     # ETF AUM Δ
  06_compute_signals.py     # math, no LLM
  07_compute_composite.py   # buckets → temperature + flags
  08_render_dashboard.py    # HTML + CSV outputs
```

13F holdings refresh runs separately (quarterly trigger), not in the daily loop.

---

## 6. Backtest methodology

### 6.1 Horizon

**10 years (2016-05 → present).** Justified in conversation: covers 4 Fed cycles, 2018 vol-mageddon, COVID, 2022 bear, 2023-24 AI bull. Matches Polygon options history depth. Pre-2016 TMT composition is too different from today's market.

For free-data signals (positioning, technical, flows) we *can* extend to 15y as a robustness check. For options signals we cannot without paying.

### 6.2 Validation framework

For each signal and the composite, compute:
- **Forward returns** at 1w / 1m / 3m horizons, conditional on signal percentile bucket (deciles)
- **Hit rate**: % of times top-decile reading led to negative 1m forward return (for "hot" signals) and bottom-decile to positive (for "cold")
- **Information coefficient (IC)**: Spearman correlation of signal percentile vs forward return
- **Decile spread**: top decile − bottom decile forward return
- **Regime conditioning**: re-run within (a) bull/bear regimes via QQQ 200d MA, (b) high/low VIX regimes

Goal isn't to forecast; goal is to confirm each signal has *some* contrarian or trend-confirming value at extremes, and the composite improves on individual signals.

### 6.3 Survivorship bias

V1 accepts current universe, documents bias. V2 considers Polygon delisted-tickers reference or CRSP.

### 6.4 What can't be backtested in V1

- Options bucket — no historical IV/skew without Polygon Options Starter or CBOE Datashop
- EPS revision overlay — no historical FactSet without manual export

These get backtested only after data is acquired. The composite backtest in V1 runs **without options bucket** and reports results "free-data signals only." This is honest and still useful.

---

## 7. V1 / V2 split + phased implementation

### Phase 0 — Skeleton (1 day)
- Project structure mirroring theme_detector
- Universe filter ($1.5B) → `data/universe.csv`
- Config (`config.yaml`), requirements
- Abstract provider interfaces with method signatures
- SQLite schema migrations
- Empty daily pipeline scripts

### Phase 1 — Free-data signals (~1 week)
- Implement: prices, technical, valuation (yfinance), short interest (FINRA), insider (EDGAR + openinsider), 13F (EDGAR), ETF flows (iShares JSON)
- Compute per-signal and per-bucket scores
- Composite *without* options bucket
- Daily run → SQLite + JSON output
- Simple HTML dashboard (top 25 hottest / coldest, compound flags)

### Phase 2 — Options snapshots (~3 days)
- yfinance options snapshot accumulation → start building forward history
- Polygon adapter stub (returns NotImplemented)
- Composite gains options bucket once ≥ 60d snapshot history exists per name

### Phase 3 — Backtest framework (~1 week)
- Backtest harness: signal → forward returns → IC, hit rate, decile spread
- Run on 10y free-data signals
- Tune composite weights
- Generate backtest report

### Phase 4 — FactSet overlays (~2 days, when ready)
- EPS revision breadth fetcher (live, no history)
- Display alongside composite, not in score

### Phase 5 — Polygon options (when subscribed)
- Flip Polygon adapter from stub to real
- Backfill 10y options bucket
- Re-run backtest with options included

---

## 8. Open questions / TBDs

1. **Project name** — `positioning_meter` confirmed.
2. **Options eligibility threshold** — $3B mcap or 1k contract avg volume; will measure once data is in.
3. ~~**Insider polarity in composite**~~ — RESOLVED: in composite for V1, polarity decided by backtest (see §3.1).
4. **Compound-flag thresholds** — currently 85/85/80; should be set empirically from backtest.
5. **Bucket weights** — initial guess 0.25/0.25/0.10/0.20/0.20; should be set by backtest.
6. **Survivorship reconstruction** — V1 accepts bias; revisit after V1.
7. ~~**Sector/peer relative scoring**~~ — RESOLVED: dual percentile (own history + cluster peers from theme_detector). See §4.
8. **Your other-computer signal list** — anything in there not covered above? Worth a sync before Phase 1 starts (non-blocking — can add signals later).
9. **ETF list for flows bucket** — initial: XLK, SOXX, IGV, SMH, XLC, ARKK, QQQ, IYW, VGT, FDN, SKYY, CIBR, BOTZ, ROBO. Plus single-stock leveraged: TSLL, NVDL, MSFU, AMZU, GGLL. Add/remove?

---

## 9. Reuse from theme_detector

- `data/universe.csv` (filter to $1.5B+)
- `lib/polygon_client.py` pattern for prices
- EDGAR metadata cache (`data/_edgar_metadata_cache.json`)
- SQLite + daily-cron + reports/ pattern
- Project layout (setup/, daily/, lib/, tools/, data/, logs/)
