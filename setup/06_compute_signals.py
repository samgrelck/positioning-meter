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
from lib.signals.percentiles import pct_self_panel, pct_peer_panel
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
    "short_volume_ratio_14d": "positioning",
    "si_true_dtc": "positioning",
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

    print("Computing pct_peer...")
    for sig_name, panel in raw_signals.items():
        pct_peer[sig_name] = pct_peer_panel(panel, ticker_to_cluster)

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
    flags = compute_flags(composite, bucket_panels, cfg["composite"]["compound_flags"])
    print("Computing conviction + anomaly...")
    conviction = compute_conviction(bucket_panels)
    anomaly = compute_anomaly(pct_peer)

    # Persist to SQLite — clear old rows first so dropped signals don't linger
    write_status({"phase": "persist"})
    conn = connect()
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

        for col in ["score_positioning", "score_options", "score_flows",
                    "score_valuation", "score_technical",
                    "conviction", "anomaly_count",
                    "flag_late_signal", "flag_washout", "flag_divergence", "flag_earnings_soon"]:
            if col not in comp_long.columns:
                comp_long[col] = None

        comp_long["date"] = comp_long["date"].dt.strftime("%Y-%m-%d") if hasattr(comp_long["date"], "dt") else comp_long["date"].astype(str)
        rows = comp_long[[
            "ticker", "date", "temperature",
            "score_positioning", "score_options", "score_flows",
            "score_valuation", "score_technical",
            "conviction", "anomaly_count",
            "flag_late_signal", "flag_washout", "flag_divergence", "flag_earnings_soon",
        ]].to_dict("records")
        conn.executemany(
            """
            INSERT OR REPLACE INTO composite_daily
                (ticker, date, temperature,
                 score_positioning, score_options, score_flows,
                 score_valuation, score_technical,
                 conviction, anomaly_count,
                 flag_late_signal, flag_washout, flag_divergence, flag_earnings_soon)
            VALUES (:ticker, :date, :temperature,
                    :score_positioning, :score_options, :score_flows,
                    :score_valuation, :score_technical,
                    :conviction, :anomaly_count,
                    :flag_late_signal, :flag_washout, :flag_divergence, :flag_earnings_soon)
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
