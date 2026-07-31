"""Compute all signals + composite for every (ticker, date) in the panel.

Reads raw tables. Writes signals_daily and composite_daily.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load, project_path
from lib.db import connect
from lib.signals import loaders, technical, valuation, positioning
from lib.signals.percentiles import (
    pct_self_panel, pct_peer_panel, zscore_self_panel,
)
from lib.signals.composite import (
    assemble_buckets, assemble_composite, compute_flags,
    compute_conviction, compute_anomaly,
)

# Per V1.1 backtest finding (QUESTIONS.md): trend signals (positive IC) are
# excluded from composite; remain computed and stored for dashboard overlays.
#
# IN composite (contrarian / "hot=late" direction):
# V1.5: valuation moved to overlay. Tool is sentiment/positioning/expectations
# only. Valuation is a fundamental signal — assessed separately by the analyst.
# Plus: empirically weakest bucket in V1.4 backtest (IC near zero or wrong sign).
SIGNAL_TO_BUCKET = {
    # technical (contrarian only — sentiment via price action)
    "ret_1m": "technical",
    "ret_3m": "technical",
    "ret_6m": "technical",
    "dist_200ma": "technical",
    "rsi_14": "technical",
    "pct_from_52w_high": "technical",
    # positioning
    "insider_net_90d_signed": "positioning",
    "insider_buying_90d": "positioning",  # buying-only — inverted at signal level
    "short_volume_ratio_14d": "positioning",
    "si_true_dtc": "positioning",
    # V1.14: long/retail-crowding proxy — heavy float turnover = crowded (HOT).
    # Closes the construct gap where positioning only saw the short + insider side.
    "float_turnover_20d": "positioning",
    # options — populated as data is ingested (yfinance forward-only or
    # Polygon Options Advanced historical backfill)
    "iv_rank_1y": "options",
    "iv_term_slope": "options",
    "skew_25d": "options",
    "pc_volume_ratio": "options",
}

# Computed but excluded from composite — overlay only.
# V1.3: hf_count_13f and hf_count_change_4q showed positive IC in V1.2
# backtest (trend-following, not contrarian). Moved here.
# V1.5: valuation moved here — fundamental, not behavioral.
# V1.5: ttm_pe and ev_sales removed entirely per user direction (never use TTM
# for valuation multiples). NTM P/E is shown on the dashboard's live-overlay
# card, computed at render time from estimates_daily.forward_eps × current price.
# NTM EV/Sales not computed — Yahoo doesn't provide forward revenue consensus.
OVERLAY_SIGNALS = {
    "ret_12m": "technical_trend_overlay",
    "rs_vs_qqq_3m": "technical_trend_overlay",
    "rs_vs_xlk_3m": "technical_trend_overlay",
    "insider_net_90d_abs": "positioning_trend_overlay",
    "hf_count_13f": "positioning_trend_overlay",
    "hf_count_change_4q": "positioning_trend_overlay",
    "hf_top_concentration": "positioning_overlay",
    "inst_own_pct": "positioning_overlay",  # V1.14: 13F shares / shares_out — LOW = retail-heavy
    # Forward-only — null until we accumulate ≥ 20 days of estimates_daily snapshots.
    # Could promote to composite later once backtest data exists.
    "eps_revision_4w": "expectations_overlay",
    # Options raw IV (overlay context — IV30 is shown but iv_rank_1y is the
    # signal that enters composite)
    "iv_30d": "options_overlay",
    "iv_3m": "options_overlay",
    "options_vol_vs_20d": "options_overlay",
}

# All signals to compute and persist (composite + overlay):
ALL_SIGNALS = {**SIGNAL_TO_BUCKET, **OVERLAY_SIGNALS}

STATUS = project_path("logs/06_compute_signals_status.json")


def write_status(d: dict):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(d, indent=2))


def main(slow_window: int | None = None, fast_window: int | None = None):
    cfg = load()
    if slow_window is None:
        slow_window = cfg["signals"]["history_window_days_slow"]
    if fast_window is None:
        fast_window = cfg["signals"]["history_window_days_fast"]

    write_status({"phase": "loading", "started": time.time()})
    print("Loading raw data...")
    closes, volumes = loaders.load_prices()
    fundamentals = loaders.load_fundamentals_q()
    insider_90d = loaders.load_insider_flows(window_days=90)
    insider_buying_90d = loaders.load_insider_flows(window_days=90, buying_only=True)
    short_vol = loaders.load_short_volume()
    si_true = loaders.load_si_true(closes.index)
    hf_panels = loaders.load_hf_holdings_panels(closes.index)
    eps_revisions_4w = loaders.load_eps_revisions_panel(closes.index, lookback_days=20)
    options_panels = loaders.load_options_panels(closes.index)
    universe = loaders.load_universe()

    # Restrict signal computation to our universe (drop ETFs from output panel
    # but keep them in `closes` for benchmark calculations)
    universe_tickers = set(universe["ticker"])
    print(f"Universe: {len(universe_tickers)} names; closes panel: {closes.shape[1]} columns")

    # Build cluster mapping for pct_peer
    ticker_to_cluster = dict(zip(universe["ticker"], universe["cluster_id"].fillna("")))
    ticker_to_cluster = {t: c for t, c in ticker_to_cluster.items() if c}
    # Multi-cluster peer membership (e.g. AMD is in CPUs + GPUs + AI semis)
    from lib.peers import ticker_to_clusters as _ttc, cluster_members as _cm
    ticker_to_clusters_multi = _ttc()
    cluster_members_map = _cm()

    write_status({"phase": "compute_signals"})
    print("Computing technical signals...")
    tech_signals = technical.compute_all(closes)
    # V1.5: valuation signals (ttm_pe, ev_sales) no longer computed.
    # NTM P/E is rendered at dashboard time from estimates_daily.forward_eps.
    val_signals = {}
    print("Computing positioning signals...")
    # Build hf_count_change_4q on the fly from the count panel
    hf_change_4q = positioning.hf_change_signal(hf_panels.get("hf_count_13f", pd.DataFrame()), periods=4)
    aug_hf = {
        "hf_count_13f": hf_panels.get("hf_count_13f", pd.DataFrame()),
        "hf_top_concentration": hf_panels.get("hf_top_concentration", pd.DataFrame()),
        "hf_count_change_4q": hf_change_4q,
    }
    pos_signals = positioning.compute_all(
        insider_90d, short_vol, closes.index,
        hf_panels=aug_hf, si_true=si_true,
    )
    # Rename si_true_pct_adv -> si_true_dtc to match SIGNAL_TO_BUCKET
    if "si_true_pct_adv" in pos_signals:
        pos_signals["si_true_dtc"] = pos_signals.pop("si_true_pct_adv")
    # Add EPS revisions overlay (forward-only — null until we accumulate history)
    if not eps_revisions_4w.empty:
        pos_signals["eps_revision_4w"] = eps_revisions_4w
    # V1.11: insider_buying_90d — buying-only insider net dollars. Per academic
    # literature (Seyhun, Lakonishok-Lee), insider buying carries signal but
    # selling is mostly noise (diversification, tax, 10b5-1 plans). Zeroing
    # the selling days isolates the signal-bearing component.
    # Inverted (see below) — high buying → COLD in our framework (contrarian-bullish).
    if not insider_buying_90d.empty:
        # Reindex calendar -> trading days
        pos_signals["insider_buying_90d"] = insider_buying_90d.reindex(closes.index, method="ffill")
    # V1.14: float turnover (long/retail-crowding) IN composite + institutional
    # ownership % as overlay. Closes the construct gap flagged in review — the
    # positioning bucket previously only measured the short + insider side and
    # was blind to long-side/retail crowding (e.g. read MU/SNDK as "light").
    float_shares = loaders.load_float()
    ft = positioning.float_turnover_signal(volumes, float_shares, window=20)
    if not ft.empty:
        pos_signals["float_turnover_20d"] = ft.reindex(closes.index)
        print(f"  float_turnover_20d: {ft.notna().any().sum()} tickers with float")
    else:
        print("  WARN: float_turnover_20d empty — no share_float data (run setup/19_ingest_float.py)")
    inst_own = loaders.load_inst_own_pct()
    if len(inst_own) > 0:
        io_panel = pd.DataFrame(index=closes.index, columns=closes.columns, dtype=float)
        for t, v in inst_own.items():
            if t in io_panel.columns:
                io_panel[t] = v
        pos_signals["inst_own_pct"] = io_panel
        print(f"  inst_own_pct overlay: {len(inst_own)} tickers")

    # Merge in options signals
    pos_signals.update(options_panels)

    raw_signals: dict[str, pd.DataFrame] = {}
    raw_signals.update(tech_signals)
    raw_signals.update(val_signals)
    raw_signals.update(pos_signals)

    # Filter every panel to universe-only columns for downstream output
    filtered = {}
    for sig_name, panel in raw_signals.items():
        cols = [c for c in panel.columns if c in universe_tickers]
        filtered[sig_name] = panel[cols]
    raw_signals = filtered

    write_status({"phase": "percentiles"})
    print("Computing pct_self...")
    pct_self: dict[str, pd.DataFrame] = {}
    pct_peer: dict[str, pd.DataFrame] = {}
    for sig_name, panel in raw_signals.items():
        bucket = ALL_SIGNALS.get(sig_name, "technical")
        window = fast_window if bucket == "options" else slow_window
        pct_self[sig_name] = pct_self_panel(panel, window)

    # V1.11 intent: signals where HIGH raw = COLD direction must be inverted so
    # high values pull the composite DOWN (contrarian-bullish). insider_buying_90d:
    # high net insider buying = bullish = washout (COLD).
    # NOTE (bugfix): the old code negated pos_signals[...] here, but pct_self had
    # already been computed from raw_signals (a separate reference) and pct_peer
    # was computed from raw_signals too — so the negation never reached the
    # percentiles and the inversion was a no-op (high buying scored HOT, backwards).
    # Fixed by inverting the PERCENTILES after they're computed (see INVERT_PCT
    # below), which also keeps raw_value as the real buying $ for display.
    INVERT_PCT = {"insider_buying_90d"}

    # V1.16: composite TECHNICAL signals now use the 50/50 own-history + universe
    # blend (like positioning/options). The V1.10 own-history-only rule was a 3m,
    # pre-factor-neutral artifact — once returns are factor-neutralized the
    # cross-sectional component is CONTRARIAN (reversion), not trend-following, and
    # walk-forward OOS confirmed the blend beats own-history-only (IC -0.0192 vs
    # -0.0178; tools/wf_techbasis.py). Only the overlay-only trend signals (12m
    # return, RS vs QQQ/XLK) stay own-history — they're display overlays, not in
    # the composite, and are genuinely trend-following cross-sectionally.
    TECH_USE_SELF_ONLY = {
        "ret_12m", "rs_vs_qqq_3m", "rs_vs_xlk_3m",
    }

    print("Computing pct_peer...")
    for sig_name, panel in raw_signals.items():
        # V1.8: pct_peer uses UNIVERSE-WIDE ranking only (blend_universe=1.0).
        # Why: cluster-relative ranking suppresses cluster-wide moves (e.g. if
        # all CPU names are crowded, ranking within CPUs gives each name ~50th
        # percentile, hiding the cluster-wide elevation). Universe-rank picks
        # up "this name is hot vs the rest of TMT today." Combined with
        # pct_self (vs own history), this correctly flags both:
        #   - Name-specific elevation (via pct_self)
        #   - Sector-wide rotation/crowding (via universe pct_peer when sector
        #     stands out from rest of TMT)
        pct_peer[sig_name] = pct_peer_panel(
            panel, ticker_to_cluster,
            ticker_to_clusters=ticker_to_clusters_multi,
            cluster_members=cluster_members_map,
            blend_universe=1.0,  # 1.0 = universe only; 0.0 = cluster only
        )

    # V1.10: For technical signals, replace pct_peer with pct_self so the
    # downstream 50/50 blend collapses to pct_self only (drops the trend-
    # following cross-sectional component).
    for sig_name in TECH_USE_SELF_ONLY:
        if sig_name in pct_self and sig_name in pct_peer:
            pct_peer[sig_name] = pct_self[sig_name]

    # Invert percentiles for HIGH-raw=COLD signals (see INVERT_PCT note above):
    # high insider buying should pull the composite DOWN, so flip 0..100 -> 100..0
    # on both percentile dimensions. raw_value (stored separately) is untouched.
    for sig_name in INVERT_PCT:
        if sig_name in pct_self and pct_self[sig_name] is not None and not pct_self[sig_name].empty:
            pct_self[sig_name] = 100.0 - pct_self[sig_name]
        if sig_name in pct_peer and pct_peer[sig_name] is not None and not pct_peer[sig_name].empty:
            pct_peer[sig_name] = 100.0 - pct_peer[sig_name]

    # Assemble bucket scores + composite
    write_status({"phase": "assemble"})
    # Load within-bucket signal weights (computed by tools/tune_signal_weights.py).
    # If not present, signals are equal-weighted within each bucket.
    signal_weights = None
    sw_path = project_path("data/signal_weights.json")
    if sw_path.exists():
        try:
            signal_weights = json.loads(sw_path.read_text()).get("weights", {})
            print(f"Loaded {len(signal_weights)} per-signal weights from {sw_path.name}")
        except Exception as e:
            print(f"WARN: failed to load signal_weights.json: {e}; using equal weights")

    print("Assembling buckets...")
    bucket_panels = assemble_buckets(
        pct_self, pct_peer, SIGNAL_TO_BUCKET,
        cfg["composite"]["dual_percentile_weights"],
        signal_weights=signal_weights,
    )
    print(f"Buckets computed: {list(bucket_panels.keys())}")
    print("Assembling composite...")
    composite = assemble_composite(bucket_panels, cfg["composite"]["bucket_weights"])

    # V1.20: EX-TECHNICAL composite — the positioning + options buckets only, at
    # their config weights (assemble_composite renormalizes over the buckets it
    # is handed, so 0.50/0.30 becomes 0.625/0.375). Never persisted as a score;
    # it exists only to carry a self-vs-own-history percentile that is free of
    # price/momentum-derived signal.
    #
    # min_buckets_present=1 (vs 2 for temperature) is deliberate: options data
    # only begins 2026-05-12, so requiring both buckets would cap the whole
    # series at ~50 trading days and make a "1y" percentile meaningless. With 1,
    # the series runs the full history — positioning-only before options came
    # online, pos+opt after. The cost is a composition break at that date (the
    # same kind temperature already carries, since it was pos+tech pre-options);
    # the dashboard discloses it in the column tooltip + glossary.
    extech_buckets = {b: p for b, p in bucket_panels.items()
                      if b in ("positioning", "options") and p is not None and not p.empty}
    extech = (assemble_composite(extech_buckets, cfg["composite"]["bucket_weights"],
                                 min_buckets_present=1)
              if extech_buckets else pd.DataFrame())
    print(f"Ex-technical composite: {list(extech_buckets.keys())} -> "
          f"{extech.shape if not extech.empty else '(empty)'}")
    flags = compute_flags(composite, bucket_panels, cfg["composite"]["compound_flags"])
    print("Computing conviction + anomaly...")
    conviction = compute_conviction(bucket_panels)
    anomaly = compute_anomaly(pct_peer)

    # ---- V1.18: self-vs-own-history percentiles + z ----
    # Rank today's Temperature (and each bucket) against the SAME name's own
    # trailing distribution, so a structurally cool name is flagged when it's
    # hot/cold *for itself*. Two horizons: 1y headline + 6mo confirmation.
    # NOTE: the options bucket is forward-only (data from 2026), so temp_self*
    # carries a one-time downward step where options came online — the
    # positioning/technical self-history (clean ~10y) is the robust read until
    # options accrues a full year. (See config.yaml / QUESTIONS.md.)
    sh_cfg = cfg["composite"].get("self_history", {})
    w_1y = sh_cfg.get("primary_window_days", 252)
    w_6m = sh_cfg.get("secondary_window_days", 126)
    print(f"Computing self-history (1y={w_1y}d, 6mo={w_6m}d) for temperature + buckets...")
    self_hist_inputs = {
        "temp": composite,
        "pos": bucket_panels.get("positioning"),
        "tech": bucket_panels.get("technical"),
        "opt": bucket_panels.get("options"),
        # V1.20: positioning+options blend — "Self 1y" with technicals stripped out
        "extech": extech,
    }
    self_hist_panels: dict[str, pd.DataFrame] = {}
    for prefix, panel in self_hist_inputs.items():
        if panel is None or panel.empty:
            continue
        self_hist_panels[f"{prefix}_selfpct_1y"] = pct_self_panel(panel, w_1y)
        self_hist_panels[f"{prefix}_selfpct_6m"] = pct_self_panel(panel, w_6m)
        self_hist_panels[f"{prefix}_selfz_1y"] = zscore_self_panel(panel, w_1y)

    # Persist to SQLite — clear old rows first so dropped signals don't linger
    write_status({"phase": "persist"})
    conn = connect()
    # Ensure the self-history columns exist on pre-V1.18 databases.
    from lib.db import migrate_schema
    added_cols = migrate_schema(conn)
    if added_cols:
        print(f"Migrated composite_daily: added {len(added_cols)} columns ({', '.join(added_cols)})")
    print("Clearing stale rows in signals_daily and composite_daily...")
    conn.execute("DELETE FROM signals_daily")
    conn.execute("DELETE FROM composite_daily")
    conn.commit()
    print("Writing signals_daily...")

    # Materialize the long format for signals_daily
    rows_written_signals = 0
    for sig_name, raw_panel in raw_signals.items():
        bucket = ALL_SIGNALS.get(sig_name, "technical")
        ps = pct_self[sig_name]
        pp = pct_peer.get(sig_name)
        long = raw_panel.stack(future_stack=True).dropna().rename("raw_value").reset_index()
        long.columns = ["date", "ticker", "raw_value"]
        long["signal_name"] = sig_name
        long["bucket"] = bucket
        if ps is not None and not ps.empty:
            ps_long = ps.stack(future_stack=True).rename("pct_self").reset_index()
            ps_long.columns = ["date", "ticker", "pct_self"]
            long = long.merge(ps_long, on=["date", "ticker"], how="left")
        else:
            long["pct_self"] = np.nan
        if pp is not None and not pp.empty:
            pp_long = pp.stack(future_stack=True).rename("pct_peer").reset_index()
            pp_long.columns = ["date", "ticker", "pct_peer"]
            long = long.merge(pp_long, on=["date", "ticker"], how="left")
        else:
            long["pct_peer"] = np.nan
        long["date"] = long["date"].dt.strftime("%Y-%m-%d")
        rows = long[["ticker", "date", "signal_name", "bucket",
                     "raw_value", "pct_self", "pct_peer"]].to_dict("records")
        conn.executemany(
            """
            INSERT OR REPLACE INTO signals_daily
                (ticker, date, signal_name, bucket, raw_value, pct_self, pct_peer)
            VALUES (:ticker, :date, :signal_name, :bucket, :raw_value, :pct_self, :pct_peer)
            """,
            rows,
        )
        conn.commit()
        rows_written_signals += len(rows)
        print(f"  {sig_name:30s}  {len(rows):>9,} rows")

    print("Writing composite_daily...")
    # Long form composite
    if not composite.empty:
        comp_long = composite.stack(future_stack=True).dropna().rename("temperature").reset_index()
        comp_long.columns = ["date", "ticker", "temperature"]

        for bkt, panel in bucket_panels.items():
            b_long = panel.stack(future_stack=True).rename(f"score_{bkt}").reset_index()
            b_long.columns = ["date", "ticker", f"score_{bkt}"]
            comp_long = comp_long.merge(b_long, on=["date", "ticker"], how="left")

        if not conviction.empty:
            c_long = conviction.stack(future_stack=True).rename("conviction").reset_index()
            c_long.columns = ["date", "ticker", "conviction"]
            comp_long = comp_long.merge(c_long, on=["date", "ticker"], how="left")
        if not anomaly.empty:
            a_long = anomaly.stack(future_stack=True).rename("anomaly_count").reset_index()
            a_long.columns = ["date", "ticker", "anomaly_count"]
            comp_long = comp_long.merge(a_long, on=["date", "ticker"], how="left")

        for fname, fpanel in flags.items():
            f_long = fpanel.stack(future_stack=True).rename(fname).reset_index()
            f_long.columns = ["date", "ticker", fname]
            comp_long = comp_long.merge(f_long, on=["date", "ticker"], how="left")

        # V1.18: self-vs-own-history columns (merge while date is still a
        # Timestamp — the stringify happens further below).
        for col_name, sh_panel in self_hist_panels.items():
            sh_long = sh_panel.stack(future_stack=True).rename(col_name).reset_index()
            sh_long.columns = ["date", "ticker", col_name]
            comp_long = comp_long.merge(sh_long, on=["date", "ticker"], how="left")

        # Earnings-soon flag from earnings_calendar (global, not per-date)
        try:
            eearn = pd.read_sql_query(
                "SELECT ticker, next_earnings_date FROM earnings_calendar",
                conn,
            )
        except Exception:
            eearn = pd.DataFrame(columns=["ticker", "next_earnings_date"])
        eearn["next_earnings_date"] = pd.to_datetime(eearn["next_earnings_date"], errors="coerce")
        comp_long_dates = pd.to_datetime(comp_long["date"])
        comp_long = comp_long.merge(eearn, on="ticker", how="left")
        days_to_earnings = (comp_long["next_earnings_date"] - comp_long_dates).dt.days
        comp_long["flag_earnings_soon"] = ((days_to_earnings >= 0) & (days_to_earnings <= 14)).astype(int)
        comp_long.drop(columns=["next_earnings_date"], inplace=True)

        self_hist_cols = [
            "temp_selfpct_1y", "temp_selfpct_6m", "temp_selfz_1y",
            "pos_selfpct_1y", "pos_selfpct_6m", "pos_selfz_1y",
            "tech_selfpct_1y", "tech_selfpct_6m", "tech_selfz_1y",
            "opt_selfpct_1y", "opt_selfpct_6m", "opt_selfz_1y",
            "extech_selfpct_1y", "extech_selfpct_6m", "extech_selfz_1y",
        ]
        for col in ["score_positioning", "score_options", "score_flows",
                    "score_valuation", "score_technical",
                    "conviction", "anomaly_count",
                    "flag_late_signal", "flag_washout", "flag_divergence",
                    "flag_earnings_soon"] + self_hist_cols:
            if col not in comp_long.columns:
                comp_long[col] = None

        comp_long["date"] = comp_long["date"].dt.strftime("%Y-%m-%d") if hasattr(comp_long["date"], "dt") else comp_long["date"].astype(str)
        # NaN -> None so SQLite stores NULL (not the string 'nan')
        comp_long = comp_long.where(pd.notnull(comp_long), None)
        rows = comp_long[[
            "ticker", "date", "temperature",
            "score_positioning", "score_options", "score_flows",
            "score_valuation", "score_technical",
            "conviction", "anomaly_count",
            "flag_late_signal", "flag_washout", "flag_divergence", "flag_earnings_soon",
        ] + self_hist_cols].to_dict("records")
        conn.executemany(
            """
            INSERT OR REPLACE INTO composite_daily
                (ticker, date, temperature,
                 score_positioning, score_options, score_flows,
                 score_valuation, score_technical,
                 conviction, anomaly_count,
                 flag_late_signal, flag_washout, flag_divergence, flag_earnings_soon,
                 temp_selfpct_1y, temp_selfpct_6m, temp_selfz_1y,
                 pos_selfpct_1y, pos_selfpct_6m, pos_selfz_1y,
                 tech_selfpct_1y, tech_selfpct_6m, tech_selfz_1y,
                 opt_selfpct_1y, opt_selfpct_6m, opt_selfz_1y,
                 extech_selfpct_1y, extech_selfpct_6m, extech_selfz_1y)
            VALUES (:ticker, :date, :temperature,
                    :score_positioning, :score_options, :score_flows,
                    :score_valuation, :score_technical,
                    :conviction, :anomaly_count,
                    :flag_late_signal, :flag_washout, :flag_divergence, :flag_earnings_soon,
                    :temp_selfpct_1y, :temp_selfpct_6m, :temp_selfz_1y,
                    :pos_selfpct_1y, :pos_selfpct_6m, :pos_selfz_1y,
                    :tech_selfpct_1y, :tech_selfpct_6m, :tech_selfz_1y,
                    :opt_selfpct_1y, :opt_selfpct_6m, :opt_selfz_1y,
                    :extech_selfpct_1y, :extech_selfpct_6m, :extech_selfz_1y)
            """,
            rows,
        )
        conn.commit()
        rows_written_composite = len(rows)
    else:
        rows_written_composite = 0
    conn.close()

    write_status({
        "phase": "done",
        "signals_rows": rows_written_signals,
        "composite_rows": rows_written_composite,
    })
    print(f"\nDONE. signals_daily={rows_written_signals:,} rows, composite_daily={rows_written_composite:,} rows.")


if __name__ == "__main__":
    main()
