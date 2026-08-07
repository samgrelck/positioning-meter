# Positioning Meter — Running Summary

> Single source of truth for current state. Updated after each milestone.
> Sister docs: `DESIGN.md` (architecture), `QUESTIONS.md` (decisions/caveats), `GITHUB_SETUP.md` (publishing), `data/backtest_report.md` (latest backtest).

**Last updated:** 2026-06-26 — **V1.18: self-vs-own-history baseline — Temperature & each bucket ranked vs the SAME name's own trailing 1y/6mo, so structurally cool/hot names (e.g. large-cap semis) are flagged when extreme *for themselves*.** This is a **display/context lens only — the scoring model is unchanged and remains frozen at V1.17** (Pos 0.50 / Tech 0.20 / Opt 0.30; the dashboard's model/backtest banners still read V1.17 by design). No weights, signals, or composite touched.

---

## 🚀 Daily use

```bash
# Just refresh dashboard from current DB (no fresh data, ~1 min):
cd ~/Documents/AI\ workflows/positioning_meter && ./tools/deploy.sh

# Full daily refresh: pull fresh data + recompute + push (~70 min):
cd ~/Documents/AI\ workflows/positioning_meter && ./tools/refresh_data.sh

# Faster: skip Yahoo estimates + options (~16 min):
./tools/refresh_data.sh fast

# Open local dashboard without pushing:
open ~/Documents/AI\ workflows/positioning_meter/data/dashboard.html
```

**→ Full daily-use guide + cadence guidance + troubleshooting + where-things-live: see [USAGE.md](USAGE.md).**

## ✅ System status: fully operational

As of 2026-05-12, the tool is **end-to-end functional and ready for daily use**:

- 358 names have composite temperature today
- 326 names have all 3 buckets (Pos + Tech + Opt) — full V1.7 signal
- 32 names have Pos + Tech only (no listed options or thin chains)
- 4 names triggered 🔥 Late flag, 2 triggered ❄️ Washout, 48 have 📅 Earnings ≤14d
- Dashboard at `data/dashboard.html` + `docs/index.html` (5.5 MB, 358 drilldowns)
- All code committed and pushed to GitHub

## Data licensing decision (V1.7 final — why we're staying on yfinance for options)

After investigating paid options data, **the decision is: stay with yfinance forward-only accumulation.** Rationale:

| Path | Why we ruled it out |
|---|---|
| Polygon Options Non-Pro (~$80-200/mo) | Sam doesn't qualify — FINRA registration + Truist employment trigger the "engaged as investment advisor" + "registered with regulatory body" disqualifiers. Risk of backdated fees / account suspension if declared falsely. |
| Polygon Options Business (Professional) | $1,999/mo — overkill for a personal research tool. |
| FactSet export to personal computer | Violates Truist data policy. Not an option. |
| Alternative vendors (AlphaVantage, etc.) | Same non-pro/pro distinctions. Same disqualifier. |
| Brokerage APIs (IBKR, Tradier) | Same professional/non-pro declarations as a customer. Same disqualifier. |
| CBOE Datashop one-time historical | Possible — historical EOD files sometimes sold under personal-use licensing. **Open for follow-up email inquiry**, but not pursued now. |

**Result:** yfinance ingestion runs daily, accumulating forward-only history.

### What this means concretely

**What works today (3 of 4 options signals via cross-sectional ranking):**
| Options signal | Status today | Status at 6 months |
|---|---|---|
| 25Δ skew | ✅ working (pct_peer) | ✅ working (pct_self + pct_peer) |
| Term slope (IV30 − IV3m) | ✅ working (pct_peer) | ✅ working (pct_self + pct_peer) |
| P/C volume ratio | ✅ working (pct_peer) | ✅ working (pct_self + pct_peer) |
| IV rank (vs 1y history) | ⏳ null (needs 20+ days own history) | ✅ working (~1y window) |

**What we permanently lose without paid historical:**
- Multi-year backtest of options signals vs forward returns (no 2018 vol-mageddon, no 2020 COVID)
- Empirical IC measurement for options bucket
- Empirical weight tuning for options weight (currently a 0.15 placeholder, not backtest-derived)

**For interview / portfolio framing:** the architecture is the impressive part — math layer, providers, ingestion, signal compute, dashboard integration all built. Frame the data limitation honestly as a compliance-driven engineering constraint ("upgradeable to historical options via institutional feed at a future employer"). Strong, defensible.

### What changes if you ever DO get historical options data

If you change firms, get an academic affiliation, or buy CBOE Datashop personal-use files:
1. Fill in the boto3 / parsing logic in `setup/16_ingest_options_polygon.py` (currently stubbed)
2. Run historical backfill (~2-5 days wall-clock)
3. Re-run `setup/06_compute_signals.py` + `setup/07_run_backtest.py`
4. Re-tune bucket weights via `tools/tune_weights.py` (now with 3 buckets including options)
5. Re-render dashboard

The infrastructure is **fully ready** — only the data is gated.

## At a glance

| | Status |
|---|---|
| Universe | 366 TMT names, mcap ≥ $1.5B, drawn from theme_detector |
| Backtest horizon | 10y for most signals; 6.5y for short volume; 1y for true SI |
| Composite output | working — IC **−0.033**, decile spread **−3.00%**, bot decile hit **57%** at 3m fwd (V1.8 — IC-weighted within-bucket signals) |
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
| V1.6 | Re-weight composite via grid search: pos 0.7 / tech 0.3 | −0.020 | −0.026 | 55% | 56% |
| V1.7 | +Options bucket: yfinance forward-only (no historical backtest — see "Data licensing decision" above) | n/a* | n/a* | n/a* | n/a* |
| V1.8 | Within-bucket signals IC-weighted via tools/tune_signal_weights.py | −0.023 | −0.033 | 57% | 57% |
| V1.9 | Inverted options signal directions (P/C, skew, term, IV rank all "fear" measures → high = COLD); options weight 0.15 → 0.30 | −0.022 | −0.031 | 56% | 57% |
| V1.10 | Technical signals use pct_self only (cross-section was cancelling self-history contrarian signal) | −0.025 | −0.040* | 57% | 58% |
| V1.11 | FINRA SI backfill 2018+, universe-wide, 365/366 names (replaced 1y NASDAQ API). insider_buying_90d added but doesn't replicate as contrarian | −0.022 | −0.036 | 56% | 57% |
| V1.12 | Conservative cut: dropped pre-June-2021 SI (FINRA docs say pre-2021 is OTC-only). Verified post-2021 data. Grid optimum: Pos 0.30 / Tech 0.40 / Opt 0.30 | −0.026 | −0.037 | 57% | 59% |
| **V1.13** | **Positioning-leaning weights (Pos 0.40 / Tech 0.25 / Opt 0.35) per conceptual prior: positioning + options are harder to fake than reflexive price signals** | **−0.023** | **−0.034** | **57%** | **59%** |

*V1.10 IC was inflated by si_true_dtc IC of −0.103 measured on only 1y of NASDAQ-only data. After FINRA backfill exposed it as overfit, the more credible measurement is −0.030 (V1.12+).

*Options bucket can't be backtested without paid historical data, which we've decided not to pursue. Composite IC numbers are unchanged from V1.6 (−0.020 / −0.026) for the positioning+technical signals; options contributes to today's live composite via cross-sectional ranking but doesn't have a backtested IC.

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
| Options (live snapshot) | yfinance options chains | Forward-only daily, 355 names | 355 | ✅ accumulating |
| Options (historical) | Polygon Options Advanced ($199-299/mo) | Pending subscription | — | ⏳ ready to fire |

### ⚠️ Form 4 duplication bug — found and fixed 2026-07-31

`insider_form4` had grown to **2,736,968 rows for 76,874 actual transactions (97.2%
duplicates)**, adding one full copy of the table per daily run since launch.

**Root cause:** the table's primary key was
`(accession, filer_cik, transaction_date, transaction_code, shares)`, but the openinsider
provider never populates `filer_cik` — it was **NULL in 100% of rows**, and SQLite (unlike the
SQL standard) treats NULLs in a primary key as *distinct*. So the PK never matched, and the
`INSERT OR REPLACE` in `setup/05_ingest_insider.py` appended instead of replacing. `direct_indirect`
was NULL on every row too, for the same reason.

**Why it mattered:** `lib/signals/loaders.load_insider_net` does a plain `SUM(value_usd)`, so
every duplicate counted. DDOG showed **$11.8B** of 90-day insider flow against a ~$45B market cap
(true figure: ~$398M). Inflation was **non-uniform** across tickers (~36× for AAPL, ~76× for GTM,
since older transactions had accumulated more copies), so it distorted the cross-section, not just
the scale.

**Fix:** `tools/fix_insider_dupes.py` rebuilds the table with a PK made only of columns the
provider actually fills — `(accession, ticker, transaction_date, transaction_code, shares,
price_per_share, filer_name)` — keeping the most recent copy of each transaction. `lib/db.py`
carries the same PK for fresh DBs, with a comment recording the trap. Verified idempotent:
re-inserting 5,000 existing rows no longer grows the table. DB shrank **2.74 GB → 2.15 GB**.

**Measured impact on scores** (after re-running `06_compute_signals.py`): small, as expected —
`insider_net_90d_signed` is only 11.4% of the positioning bucket = 5.7% of the composite. Mean
absolute temperature change **0.09 pts**, max **1.73 pts** (CALX), **zero** names moved >2 pts,
pre/post rank correlation **0.9998**. Real bug, correctly fixed, but it was never the reason
readings looked muted — that was the scale compression addressed in V1.21.

**Still open:** 35 rows (one ticker) carry `value_usd = 2147483647` — exactly INT32_MAX, a
source-side overflow sentinel rather than a real dollar amount. Not touched by default; run
`tools/fix_insider_dupes.py --fix-sentinels` to null them.

## V1.5 final composite signals

**In composite (V1.7) — sentiment + positioning + options:**

| Bucket | Weight | Signals | Best individual IC |
|---|---|---|---|
| Positioning | 0.60 | insider_net_90d_signed, short_volume_ratio_14d, si_true_dtc | **si_true_dtc IC −0.064 @ 3m** |
| Technical (sentiment via price) | 0.25 | ret_1m, ret_3m, ret_6m, dist_200ma, rsi_14, pct_from_52w_high | ret_3m IC −0.038 @ 3m |
| **Options (new V1.7)** | **0.15** | **iv_rank_1y, iv_term_slope, skew_25d, pc_volume_ratio** | **Pending historical backfill** |
| ~~Valuation~~ | 0.00 | (overlay only) | excluded V1.5 |

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

## Self-vs-own-history (V1.18 — display lens, model still frozen at V1.17)

**Problem it solves:** Temperature and every bucket are scored partly cross-sectionally (`pct_peer` vs the full TMT universe) and partly vs own 5y signal history (`pct_self`), but the *resulting* Temperature was only ever shown cross-sectionally. Structurally quiet names — large-cap semis whose realized vol / positioning churn / options activity stay low (ADI, AMD, MU, ALAB were the motivating examples) — therefore sit persistently mid/cool and never stand out, even on the days they're as active as they ever get *for themselves*.

**What was added:** for the composite Temperature and each bucket (positioning / technical / options), `setup/06_compute_signals.py` now computes a **self-history percentile + z-score vs the name's own trailing 1y (252d, headline) and 6mo (126d)** — `rolling_percentile_rank` / `rolling_zscore` in `lib/signals/percentiles.py`, applied to the composite + bucket panels (which already exist as `date×ticker` time series). Stored in `composite_daily` as `{temp,pos,tech,opt}_selfpct_1y / _selfpct_6m / _selfz_1y` (12 columns; `lib/db.migrate_schema()` ALTERs existing DBs). Window in `config.yaml` → `composite.self_history`.

**Where it shows:** a sortable **"Self 1y"** column in the All-Names / Watchlist / movers / flag tables (sort it to surface names extreme *for themselves*); the drill-down "In a nutshell" narrative adds a "Vs its own past year" line for Temp + a "vs own 1y" tag on each bucket pillar; new glossary card; CSV export includes the fields.

**Caveat (built in):** options data is forward-only (bucket history ~1 month so far), so `opt_selfpct_1y` is correctly NULL until ≥50 obs accrue, and the *Temperature* self-history carries a one-time downward step where options came online in 2026 (biases it slightly cool). The **positioning & technical** self-histories use clean ~10y data and are the robust reads; the dashboard says so inline.

### Ex-technical self-history (V1.20 — display lens, model still frozen at V1.17)

**Problem it solves:** `Self 1y` ranks *Temperature*, which is 20% technicals — the fastest-moving, most price-reflexive bucket. A name can therefore print a hot Self 1y largely because it has rallied, which is the opposite of what a positioning read is for. There was no way to ask "is the **crowding / options-hedging** setup extreme for this name, independent of price?"

**What was added:** `setup/06_compute_signals.py` builds an **ex-technical composite** from the positioning + options buckets only, at their config weights renormalized over the two kept buckets (0.50/0.30 → **0.625 Pos / 0.375 Opt**), and runs the same self-history transform over it. Stored in `composite_daily` as `extech_selfpct_1y / _selfpct_6m / _selfz_1y` (3 columns, added to `lib/db.migrate_schema()`). It is a read-out only — it never feeds the composite, the flags, or the backtest.

**Design choice — `min_buckets_present=1`** (Temperature uses 2). Options history begins **2026-05-12**; requiring both buckets would cap the whole series at ~50 trading days and make a "1y" percentile meaningless. With 1, the series runs the full history: positioning-only before options came online, pos+opt after. The cost is a composition break at that date — the same kind Temperature already carries — disclosed in the column tooltip, the glossary card, and the drill-down narrative.

**Where it shows:** a **"Self 1y P+O"** column beside Self 1y in the All-Names (sortable, `data-sort=xself1y`) / Watchlist / hot-cold / movers / flag tables; an "Ex-technicals" line in the drill-down "In a nutshell" that calls out the **gap vs the headline Self 1y** (≥15pts below ⇒ the headline reading is mostly price action; ≥15 above ⇒ positioning is more stretched than price); a glossary card; CSV export.

## Interpretability pass (V1.21 — display only, model still frozen at V1.17)

Prompted by the observation that watchlist readings all looked muted and it was
unclear what to focus on. Nothing in the model changed; four things changed on screen.

**1. `Univ %ile` column, beside Temp everywhere.** Temperature is the weighted average
of ~15 percentile signals, so the central limit compresses it toward 50: cross-sectional
**std ~12.9, effective range ~20–89, only ~6% of names above 70 and ~6% below 30** — and
that has held every year since 2016 (yearly std 12.0–17.6), so it is structural, not a
current-tape artifact. A 0–100 scale therefore *reads* like a percentile without being one:
**Temp 38 is the 19th percentile, Temp 55 is the 65th, Temp 65 is the 87th.** The new column
is the real cross-sectional percentile. It is a monotone per-date transform of Temp, so it
provably cannot change any ordering, IC or backtest number — `temp_univpct` was already
computed in `load_data()` for the drill-down; it is now surfaced everywhere.

**2. `Setup` quadrant column.** Positioning tercile × technical tercile, universe-ranked,
tagging only the four corners (`assign_quadrants` in `08_render_dashboard.py`). Word =
crowding, arrow = price. Mean 1m factor-neutral residual return per cell, 121 non-overlapping
periods 2016–2026:

| | price weak | price strong |
|---|---|---|
| **positioning light** | `Under-owned ↓` **+4.3%/yr** (t 2.01) | `Under-owned ↑` **+1.7%/yr** (t 0.70) |
| **positioning heavy** | `Crowded ↓` **+0.2%/yr** (t 0.08) | `Crowded ↑` **−4.9%/yr** (t −2.63) |

Within strong price action, light-positioning beats heavy-positioning by **+6.6%/yr (t 2.03)**.
Middle terciles are deliberately untagged — no measurable edge there. **Caveat carried on the
dashboard:** that cell was picked after inspecting a 3×3 grid, so it carries a
multiple-comparison discount, and walk-forward already showed decile L/S does not survive OOS.

*Figures restated on the V1.22 size-neutral scores (`tools/quad_cell_returns.py`, which also
makes them re-runnable — V1.21 computed them ad hoc). The two strong corners strengthened;
`Crowded ↓` went flat and `Under-owned ↑` is no longer distinguishable from zero.*

**3. `Conv` column removed** from all tables (field still computed, still in the CSV). Tested
as a filter and it does not work: composite IC flat from no filter through conviction ≥70
(−0.0235 → −0.0207), then degraded at ≥80 (−0.0146, t −1.65). Screening on bucket agreement
discarded signal rather than sharpening it.

**4. New `📖 How to read it` tab** (`render_reading_guide`). Five sections: the scale illusion
with a live Temp→percentile table; which pillars to trust (positioning IC −0.022 t −3.9 and its
own decile L/S +8.2%/yr t 2.74 vs the composite's +4.8%/yr t 1.47; technical −0.011 t −1.3;
options has **one** measurable non-overlapping 1m period, so its 0.30 weight is a prior and the
`Self 1y P+O` column is 37.5% unvalidated); the Setup grid; an **auto-selected worked example**
(today's widest positioning-vs-technicals divergence, so it never goes stale) walked through in
five steps; and what not to lean on. Deliberately does **not** change any output — it describes
the evidence and leaves the frozen weights alone.

## Size-neutral positioning + ownership guard (V1.22 — model change)

**Trigger.** PANW, CRWD and IBM were all tagged `Under-owned`, which is not a credible
statement about two of the most widely-held names in software. Two distinct causes, one real
model defect and one labelling defect.

**1. The positioning bucket was partly a size factor.** `si_true_dtc` is short interest ÷ ADV
and `float_turnover_20d` is ADV ÷ float — both scale with liquidity, so mega caps read
structurally light. Measured on the old scores: `score_positioning` was **−0.37** rank-correlated
with log market cap (p 3e-13), mean positioning ran **64.5** in the smallest market-cap decile
down to **39.8** in the largest, and **76%** of the top decile sat in the "under-owned" tercile
vs **14%** of the bottom. NVDA, MSFT, AMZN, META, AVGO, ORCL and CSCO were all tagged light.

**Fix** (`lib/signals/percentiles.size_neutral_rank`): per date, rank the signal
cross-sectionally, regress that rank on log market cap, re-rank the residual. Rank space, not
raw space, because raw values are heavily skewed; regression, not within-quintile buckets, so a
name drifting across a boundary doesn't flip its tag daily. Applied to the **positioning
composite signals only** — technical and options signals are not liquidity-scaled, and the
overlays (including `hf_count_13f`, which drives the ownership guard) keep the plain rank so
"well-held" stays an absolute statement. Size comes from `loaders.load_market_cap_panel`:
current market cap walked back along the adjusted price path, anchored on `share_float`.
`fundamentals_q.shares_out` is unusable for this — it is as-reported against a split-adjusted
price series (NVDA's 2021 count read as a $4bn company), with duplicate rows and junk values.

**Result.** Size correlation −0.369 → **−0.119** on positioning, −0.288 → **−0.053** on
Temperature; top-decile share of the cold tercile 76% → **61%**. The residual comes from
`pct_self`, not `pct_peer` (which is now ~0.00): mega caps genuinely sit low in their *own*
trailing ranges on short volume and turnover right now. That is a real market condition and
`pct_self` should keep reporting it.

**The edge was not the size premium.** 1m factor-neutral IC is unchanged (−0.0205 t −3.45 →
**−0.0208 t −3.43**, measured against the pre-change DB), but the decile long/short spread
**more than doubled: +4.1%/yr → +10.1%/yr**; 3m went +0.0% → +1.9%/yr. Previously the cold
decile was diluted with mega caps that were there on size; now it holds genuinely washed-out
names. Raw (non-neutral) IC fell −0.0143 → −0.0082, which is the expected signature of removing
an unintended long-large-cap bet from a decade in which mega-cap tech won. Cell returns were
also re-checked with **size added to the return-side neutralization** and barely move
(`Under-owned ↓` +4.3% → +4.4%, `Crowded ↑` −4.9% → −4.9%), so the grid is not a size premium
either.

**The one result that cuts the other way — walk-forward OOS did not improve.**
`tools/compute_validation_stats.py`: in-sample IC −0.0229 → **−0.0232** (t −3.81) with L/S
**+4.9%/yr → +11.0%/yr**, but out-of-sample IC −0.0186 → **−0.0172** (t −2.27) and the OOS
decile L/S went **−0.1%/yr → −1.4%/yr**. So the doubling of the long/short spread is an
in-sample result; the tradeable decile spread still does not survive walk-forward, and is
marginally worse than before. The pre-existing caveat therefore stands unchanged and is if
anything reinforced: **use the tool to rank and to generate ideas, not as a decile L/S
strategy.** What V1.22 fixes is the *construct* — the score no longer says "under-owned" when
it means "large" — not the out-of-sample tradeability, which was never there.

**2. `insider_net_90d_signed` dropped from 11.4% to 0.** Its entire IC lived in the
contaminated component: `pct_peer` was −0.24 to −0.39 correlated with log mcap across
2024–2026, IC was −0.024 there and −0.007 in the size-neutral `pct_self`. Net insider dollars
scale with market cap × stock comp × price, and 76% of the universe is net-selling, so the
signal was reading "big company whose insiders sold a lot of dollars" — which is why CRWD's
$203m of 90-day net insider selling was pushing it toward *under-owned*. Once the rank was
neutralized its IC collapsed to **−0.0036 (t −0.51)**. The sign was never a bug — it was
empirically chosen (negative IC in 6 of 6 horizon × kind cells, QUESTIONS.md) — but the IC it
was chosen on was the size effect. The three survivors all hold up: `short_volume_ratio_14d`
t −1.80, `si_true_dtc` t −1.77, `float_turnover_20d` t −2.23.

`tools/tune_weights_1m.py` gained a **significance gate** (`--min-t 1.0`, `--min-n 20`) on top
of the existing correct-sign rule — previously weight = |IC| for any negative IC, so a t −0.51
signal still drew 8%. Side effect beyond the positioning work: it also drops `ret_6m` (t −0.25)
and `dist_200ma` (t −0.45) from technical, and it now reproduces the long-standing manual
options decision automatically (n = 1–2 periods → untunable → explicit equal weights, instead
of handing `skew_25d` a 1.0 weight off n=2). Bucket weights unchanged at 0.50 / 0.20 / 0.30.

**3. Ownership guard on the Setup tag.** The positioning bucket has **no long-ownership input** —
short volume, days-to-cover, float turnover and insider flow all measure the short side or the
rate of churn. A consensus long that simply is not shorted therefore lands in the light row.
When a cold-corner name is **top-quartile on institutional ownership**, the tag is relabelled
`Quiet ↑/↓`, which claims only what the bucket measured. Ownership stays **out of the score**:
the 13F panels were trend-following rather than contrarian in backtest (V1.3), and a guard only
needs ownership to *measure*, not to *predict*. Because the guard only ever weakens a claim and
never assigns a cell, it changes no ranking, IC or backtest number.

Source is **`hf_count_13f`** (how many of the 40 curated HF filers hold the name), universe-ranked.
`share_float.inst_held_pct` (yfinance `heldPercentInstitutions`) was added to weekly job 19 and
**tested as the intended primary source, then rejected on the data**: on the first full pull the
universe median was 92% of shares outstanding with a 75th percentile of **102%** and a max of
**128%** — yfinance divides 13F shares by a share count that disagrees with its own — and in a
universe where nearly every name is 60–95% institutionally held it does not discriminate
crowding at all. It ranks **−0.21** against log market cap and **−0.15** against `hf_count_13f`,
putting CRWD, PANW, NVDA and MSFT in the bottom third — it would never fire on the consensus
longs the guard exists for. The field is still ingested (now rejecting impossible >100% values)
as drill-down context only, flagged in code as not-a-crowding-proxy. Honest caveat on the
measure actually used: `hf_count_13f` is +0.68 rank-correlated with log market cap, so the guard
does fire more on large caps — largely the true relationship, and acceptable for wording.

## Dashboard features (V2.0)

- 📐 **Univ %ile column** (V1.21) — Temperature's percentile vs the whole TMT universe today. Judge extremity on this, not raw Temp; the composite is compressed toward 50 by construction.
- 🎯 **Setup column** (V1.21, guarded V1.22) — positioning × technical corner tag (`Crowded ↑/↓`, `Under-owned ↑/↓`, or `Quiet ↑/↓` when a cold corner is top-quartile institutionally owned); sortable via `data-sort=quadrank`, hover for the historical cell return.
- 🌡️ **Self 1y column** (V1.18) — Temperature vs the name's own trailing 1-year range (percentile); sortable; hover for z-score + 6mo. See "Self-vs-own-history" above.
- 🧊 **Self 1y P+O column** (V1.20) — the same own-history percentile with **technicals excluded** (positioning + options only, 0.625/0.375); sortable. Read against Self 1y to split "extreme because it rallied" from "extreme on crowding/hedging".
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
├── USAGE.md                 — daily-use guide + cadence + troubleshooting
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
