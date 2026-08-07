# Open Questions & TBDs

Running list of decisions, unknowns, and follow-ups that came up during build.
Append-only — when resolved, mark with ✅ and a brief note rather than deleting.

---

## Decisions still to make

### ~~Positioning bucket was partly a size factor~~  ✅ RESOLVED — size-neutral rank (V1.22)
- **Trigger (user, 2026-08-06):** PANW, CRWD and IBM all tagged `Under-owned`. Not credible for two of the most widely-held names in software.
- **Root cause — construct, not a bug.** `si_true_dtc` is short interest ÷ ADV and `float_turnover_20d` is ADV ÷ float. Both scale with liquidity, so mega caps read structurally light. Measured on the old scores: `score_positioning` **−0.37** rank-correlated with log mcap (p 3e-13); mean positioning **64.5** in the smallest mcap decile → **39.8** in the largest; **76%** of the top decile in the "under-owned" tercile vs **14%** of the bottom. NVDA, MSFT, AMZN, META, AVGO, ORCL, CSCO all tagged light.
- **Fix:** `percentiles.size_neutral_rank` — per date, rank the signal, regress the rank on log mcap, re-rank the residual. Rank space (raw values are heavily skewed); regression not quintile buckets (a name drifting across a boundary would flip its tag daily). Positioning composite signals ONLY — technical/options aren't liquidity-scaled, and overlays keep the plain rank so the ownership guard stays absolute.
- **Result:** size corr −0.369 → **−0.119** (positioning), −0.288 → **−0.053** (Temperature); top-decile share of the cold tercile 76% → **61%**. Residual is all in `pct_self` (`pct_peer` now ~0.00) — mega caps genuinely sit low in their *own* trailing ranges on short volume/turnover right now. Real condition, left alone.
- **Was the edge just the size premium? No.** 1m factor-neutral IC unchanged (−0.0205 t −3.45 → −0.0208 t −3.43, measured against the pre-change DB), decile L/S **+4.1% → +10.1%/yr**. Grid cells re-checked with size added to the *return*-side neutralization and they barely move.
- **Size panel gotchas (both cost real time — don't re-derive):** `fundamentals_q.shares_out` is UNUSABLE for a historical mcap panel — as-reported counts against a split-adjusted price series (NVDA's 2021 count reads as a $4bn company), plus duplicate `period_end` rows and junk values (CRWD 2026-01-31 = 671,000). And `prices.close` == `adj_close` (Polygon returns adjusted), so there is no raw close to pair with as-reported shares. `universe.csv` market_cap is ~2x light on split/re-rated names (PANW, CRWD, FTNT, DDOG). `loaders.load_market_cap_panel` therefore anchors on `share_float` and walks back along the adjusted price path.

### ~~"Under-owned" label overclaimed~~  ✅ RESOLVED — ownership guard (V1.22)
- The positioning bucket has **no long-ownership input** — short volume, days-to-cover, float turnover and insider flow all measure the short side or churn. A consensus long that simply isn't shorted lands in the light row. CRWD sat at the 90th percentile of the universe by HF holder count while being tagged under-owned; PANW 84th.
- **Fix:** cold-corner names in the top quartile of active-manager ownership are relabelled `Quiet ↑/↓` — claims only what the bucket measured. Ownership stays OUT of the score (the 13F panels are trend-following, not contrarian — see the EDGAR entry below); a guard only needs ownership to *measure*, not *predict*, and since it only weakens wording it changes no ranking, IC or backtest number.
- **`heldPercentInstitutions` was tried as the primary source and REJECTED — do not retry.** On the first full pull: universe median **92%** of shares outstanding, 75th pct **102%**, max **128%** (yfinance divides 13F shares by a share count that disagrees with its own), and in a universe where everything is 60–95% institutionally held it doesn't discriminate crowding. Ranks **−0.21** vs log mcap and **−0.15** vs `hf_count_13f`, putting CRWD/PANW/NVDA/MSFT in the bottom third — it would never fire on the names the guard exists for. Still ingested (job 19, now rejecting >100%) as drill-down context only; flagged in code as not-a-crowding-proxy. Guard uses `hf_count_13f`.
- **Caveat kept:** `hf_count_13f` is +0.68 rank-correlated with log mcap, so the guard does fire more on large caps. Largely the true relationship, and acceptable for wording only.

### ~~FINRA SI pre-June-2021 data quality~~  ✅ RESOLVED — conservative cut applied (V1.12)
- **Issue caught by user (2026-05-13):** FINRA's own documentation states "Prior to June 2021, the data contains short interest positions in over-the-counter securities only and does not reflect short interest data in exchange-listed securities."
- **Our downloaded data** appears to contain NYSE-listed names with realistic SI values pre-2021 — contradicts FINRA's own docs.
- **Possible explanations:**
    1. Docs are stale or refer to a different FINRA dataset
    2. FINRA backfilled historical files with exchange-listed data after June 2021
    3. Pre-2021 NYSE names appear because they had OTC trading reported through FINRA, but the SI numbers may represent only OTC subset (not full exchange-listed SI)
- **Decision:** trust the docs. `setup/18_ingest_finra_si.py` now automatically drops all pre-June-2021 SI data after ingestion.
- **Result:** 5 years of verified universe-wide SI (June 2021 - present) instead of 8 years of partly-suspect data. si_true_dtc IC at 3m settled at **−0.030** (was −0.103 on 1y NASDAQ subsample = overfit, was −0.010 on full FINRA = diluted by suspect pre-2021).

### ~~Insider buying as a contrarian signal~~  ✅ RESOLVED — doesn't replicate in TMT
- **User hypothesis:** insider buying is a bullish signal per Seyhun/Lakonishok-Lee literature; selling is mostly noise (10b5-1 plans, RSU vesting, taxes).
- **Built** `insider_buying_90d` = max(0, net_insider_$) — zeros out selling days.
- **Backtest:** IC +0.025 (pct_self) to +0.092 (pct_peer) at 3m forward. Positive IC = signal works as TREND not contrarian in our framework.
- **Conclusion:** the literature doesn't replicate cleanly in TMT (insider buying is rare; the rare cases don't predict outperformance robustly).
- **Status:** signal kept in compute pipeline; gets 0 weight in composite via IC-weighted within-bucket scheme.
- **UPDATE (V1.22, 2026-08-06) — `insider_net_90d_signed` also went to 0 weight, and the sibling signal's sign was never a bug.** The two insider signals carried opposite empirical signs on purpose: `insider_buying_90d` was inverted, `insider_net_90d_signed` was not, each per its own backtest. What changed is that `insider_net_90d_signed`'s IC turned out to be the **size effect**. Its `pct_peer` was −0.24 to −0.39 rank-correlated with log mcap across 2024–2026; ALL of its IC sat there (1m −0.024) and none in the size-neutral `pct_self` (−0.007). Net insider dollars scale with mcap × stock comp × price, and 76% of the universe is net-selling, so the signal was reading "big company whose insiders sold a lot of dollars" — which is why CRWD's $203m of 90d net selling was pushing it toward *under-owned*. Once the peer rank was size-neutralized: IC **−0.0036 (t −0.51)**. Weight 0.1139 → **0**.
- **Methodology change it forced:** `tools/tune_weights_1m.py` gained a **significance gate** (`--min-t 1.0`, `--min-n 20`) on top of the correct-sign rule. Previously weight = |IC| for any negative IC, so a t −0.51 signal still drew 8% of its bucket. Side effects beyond positioning: also drops `ret_6m` (t −0.25) and `dist_200ma` (t −0.45) from technical, and it now derives the long-standing manual options decision automatically (n=1–2 → untunable → explicit equal weights, instead of handing `skew_25d` a 1.0 weight off n=2).
- **Survivors all strengthened:** `si_true_dtc` t −1.77 (w 0.362), `short_volume_ratio_14d` t −1.80 (w 0.326), `float_turnover_20d` t −2.23 (w 0.312).

### ~~Polygon Options subscription~~  ✅ RESOLVED — staying on yfinance forward-only
- **Decision:** do NOT subscribe to Polygon Options.
- **Reasons (in order):**
    1. **Sam doesn't qualify for non-professional rates.** Polygon's declaration disqualifies anyone "registered with a securities exchange, association or regulatory body" (FINRA registration triggers this) or "engaged as an investment advisor" (Truist Wealth's business). Risk of false declaration = backdated fees + account suspension.
    2. **Professional rate is $1,999/mo (Options Business)** — overkill for a personal research tool.
    3. **FactSet export to personal computer violates Truist data policy.** Not viable.
    4. Alternative vendors (AlphaVantage, brokerage APIs) have the same non-pro/pro distinctions.
- **What we keep:** yfinance forward-only daily snapshot. 3 of 4 composite options signals work today via cross-sectional ranking; 4th (IV rank) starts populating after 20 days.
- **What we lose:** multi-year backtest of options signals (no 2018 vol-mageddon, 2020 COVID coverage). Cannot empirically tune the options bucket weight via grid search — staying at 0.15 placeholder.
- **Infrastructure preserved for future:** `setup/16_ingest_options_polygon.py` is stubbed with NotImplementedError and ready to fill in if/when institutional data access becomes available (e.g. future employer or CBOE Datashop one-time purchase under personal-use licensing).
- **Possible future angle:** CBOE Datashop sells historical EOD options summary files on a pay-per-file basis, sometimes under more permissive personal-use licensing than streaming SIP data. Worth a one-paragraph email inquiry if backtest history becomes important later. Not pursued now.

### ~~EDGAR 13F deferred~~  ✅ RESOLVED — implemented V1.2
- 40-fund curated list, 1,475 filings, 174k holdings rows. CUSIP→ticker mapping at 97% coverage.
- Backtest revealed HF count signals are TREND, not contrarian — they were moved to overlay (V1.3).
- Only `hf_top_concentration` was kept in composite briefly; later moved to overlay too (V1.4).
- **RE-EXAMINED (V1.22, 2026-08-06) — decision upheld, do not put 13F back in the score.** Numbers: `hf_count_13f` pct_self IC **+0.008 / +0.019 / +0.027** (1w/1m/3m) = trend; pct_peer ~0 to −0.011. Beyond the IC there's an unresolvable dilemma — the direction you'd *want* semantically (many HFs → hot) is the direction with positive IC, so it would degrade the composite; inverting fixes the IC but then means "many HF holders → under-owned", which is nonsense. And the data can't carry a daily signal anyway: 40 curated filers (30–33 with data per quarter), quarterly, +45d lag, zero long-only coverage (no Fidelity/Vanguard/T. Rowe/Capital) — which is why `inst_own_pct` reads CRWD at 0.3%.
- **But it IS the right input for the V1.22 ownership guard on the Setup tag**, because a guard only needs ownership to *measure*, not to *predict*. See the "Under-owned label overclaimed" entry above.
- **Worth a look someday:** `hf_top_concentration` pct_self IC is −0.021 at 3m — right-signed and *larger* than `insider_net_90d_signed` ever was. It measures concentration among holders, not ownership level, so it doesn't answer "is this crowded"; but it's the one HF signal that was never wrong-signed.

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

### `float_turnover_20d` uses the LATEST float for all history — costs backtest coverage on delisted names
- **Found as a side effect of V1.22.** `loaders.load_float()` returns the float from `MAX(asof_date)` in `share_float`, i.e. the current weekly yfinance pull, and that one number divides the entire 10y volume history. Names not in the *current* universe pull (delisted) therefore get no float at all, so no `float_turnover_20d`.
- **Why it surfaced now:** zeroing `insider_net_90d_signed` removed the one positioning signal that still had coverage for those names. Positioning had been surviving on insider alone for them; without it the bucket goes NaN, and `min_buckets_present=2` then nulls the composite (options is empty pre-2026, so only technical remains).
- **Size of it:** `composite_daily` 756,202 → 737,945 rows (−2.4%), concentrated in ~17 tickers — VISN −2050, Q −1997, P −1807, NATL −1738, IHS −1320. Today's board is unaffected (all 367 names scored).
- **Why it's not being reverted:** the alternative is keeping an 11.4% weight on a t −0.51 size proxy purely to preserve rows on dead tickers.
- **Real fix if it matters:** make float point-in-time (store the snapshot per date and `ffill`) rather than one current scalar. That would also fix the smaller existing distortion where today's float is applied to 2016 volumes. **Mild survivorship concern** for the backtest sample — delisted names dropping out is the direction that flatters results — so worth doing before leaning harder on the historical numbers.

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

### ~~Self-vs-own-history baseline~~  ✅ RESOLVED — added V1.18 (2026-06-26; model unchanged, still frozen at V1.17)
- **Motivation (user):** structurally cool names — large-cap semis whose positioning/options keep realized churn low (ADI, AMD, MU, ALAB) — print persistently mid/cool Temperature and never stand out cross-sectionally, even when they're as active as they get *for themselves*. Wanted a "score vs its own history" lens.
- **Built:** self-history percentile + z of Temperature and each bucket vs the name's own trailing **1y (252d)** + **6mo (126d)** (`setup/06`, `lib/signals/percentiles.py`, stored in `composite_daily`; surfaced as the sortable **Self 1y** column + drill-down narrative). Distinct from the existing per-*signal* `pct_self` (which is one input to the score, blended 50/50 with `pct_peer`); this ranks the *resulting* Temperature/bucket against its own past.
- **Options-composition caveat (important):** the options bucket is forward-only (data from 2026). It entered the composite at 0.30 weight, which mechanically stepped Temperature down ~5pts for affected names when it came online. So the 1y **Temperature** self-history spans a mixed-composition window and is biased slightly *cool* until options accrues a full year (~Jan 2027); `opt_selfpct_1y` is NULL until ≥50 obs exist (currently ~31 days → only the 6mo read populates). **Decision:** ship the Temperature self-history with the caveat surfaced inline, and lean on the **positioning/technical** bucket self-histories (clean ~10y) as the robust reads. Revisit relabeling once options has 252d.
- **Not backtested:** this is a *contextual lens*, not a new return-predictive signal — it doesn't change the composite or its weights. No IC claim attached.

### ~~Self-history contaminated by price action~~  ✅ RESOLVED — added V1.20 (2026-07-28; model unchanged, still frozen at V1.17)
- **Motivation (user):** wanted the own-1y-history read **excluding the technical pillar**, kept alongside the existing composite-based Self 1y rather than replacing it.
- **Why it matters:** Temperature is 20% technicals, the fastest-moving and most price-reflexive bucket — so a hot Self 1y can simply mean "this name has rallied," which is exactly the confound a positioning gauge should avoid. Measured on the 2026-07-27 snapshot, the ex-technical percentile correlates **0.80** with the headline Self 1y but differs by **>15 percentile points on 163 of 365 names** — i.e. related, not redundant.
- **Built:** `setup/06` assembles an **ex-technical composite** from the positioning + options bucket panels at their config weights renormalized over the two (0.50/0.30 → **0.625/0.375**) and runs the same `pct_self_panel` / `zscore_self_panel` transform. Stored as `extech_selfpct_1y / _selfpct_6m / _selfz_1y`; surfaced as the sortable **Self 1y P+O** column beside Self 1y, plus an "Ex-technicals" line in the drill-down that names the gap vs the headline.
- **Decision — `min_buckets_present=1`, not 2 (the temperature convention).** Options history begins 2026-05-12 (~50 trading days). Requiring both buckets would have capped the entire series at that length, making a "1y" percentile a ~2.5-month percentile in disguise. Choosing 1 keeps the full ~10y window — positioning-only before options came online, pos+opt after — at the cost of a **composition break** on 2026-05-12, so today's blended value is ranked against a partly positioning-only past. Same class of caveat Temperature already carries (it was pos+tech pre-options), and positioning dominates the blend either way. Disclosed in the column tooltip, glossary card, drill-down line, and footer methodology. **Revisit ~2027-05** once options has a clean 252d, at which point `min_buckets_present=2` becomes the honest setting.
- **Alternatives rejected:** (a) require both pillars → mislabels a 2.5-month read as 1-year; (b) positioning-only column → drops the options pillar the user explicitly asked to include.
- **Not backtested:** display lens only. It never enters the composite, the flags, or the backtest.
