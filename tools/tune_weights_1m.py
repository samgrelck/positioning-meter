"""Re-tune within-bucket signal weights to the 1-month, factor-neutral horizon.

For each signal that enters the composite, compute its 1-month IC against
sector+beta-neutral residual returns over NON-OVERLAPPING periods (the same
honest methodology as tools/factor_neutral_backtest.py). Within-bucket weight =
|IC| for correctly-signed (negative/contrarian) signals, 0 for wrong-signed
(trend-following at this horizon), normalized within bucket. Also reports each
bucket score's own 1m IC to inform the across-bucket weights.

Prints a proposed signal_weights.json weights block; does NOT write it (review
first). Reuses each signal's composite transform: dual = mean(pct_self, pct_peer)
— which already equals pct_self for technical signals (pct_peer is stored as
pct_self for them).

Usage:  python3 tools/tune_weights_1m.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import numpy as np
import pandas as pd

from lib.config import project_path
from lib.db import connect

H = 21  # 1 month in trading days

BUCKETS = {
    "technical": ["ret_1m", "ret_3m", "ret_6m", "dist_200ma", "rsi_14", "pct_from_52w_high"],
    "positioning": ["insider_net_90d_signed", "insider_buying_90d", "short_volume_ratio_14d",
                    "si_true_dtc", "float_turnover_20d"],
    "options": ["iv_rank_1y", "iv_term_slope", "skew_25d", "pc_volume_ratio"],
}


def load():
    conn = connect()
    px = pd.read_sql_query("SELECT ticker,date,adj_close FROM prices", conn, parse_dates=["date"]).pivot(
        index="date", columns="ticker", values="adj_close").sort_index()
    uni = pd.read_csv(project_path("data/universe.csv"))
    bucket_scores = pd.read_sql_query(
        "SELECT date,ticker,score_positioning,score_technical,score_options FROM composite_daily",
        conn, parse_dates=["date"])
    conn.close()
    cluster = dict(zip(uni["ticker"], uni["cluster_id"].fillna("NA")))
    return px, cluster, bucket_scores


def sig_panel(name):
    conn = connect()
    df = pd.read_sql_query(
        "SELECT date,ticker,pct_self,pct_peer FROM signals_daily WHERE signal_name=?",
        conn, params=(name,), parse_dates=["date"])
    conn.close()
    if df.empty:
        return pd.DataFrame()
    df["dual"] = df[["pct_self", "pct_peer"]].mean(axis=1)
    return df.pivot(index="date", columns="ticker", values="dual").sort_index()


def betas(px, bench="QQQ"):
    dret = px.pct_change(fill_method=None)
    mret = dret[bench] if bench in dret.columns else dret.mean(axis=1)
    var = mret.var()
    return pd.Series({t: (dret[t].cov(mret) / var if var else np.nan) for t in dret.columns})


def neutralize(f, tickers, cluster, beta):
    cols = [np.ones(len(f)), np.array([beta.get(t, np.nan) for t in tickers])]
    cl = pd.Series([cluster.get(t, "NA") for t in tickers], index=tickers)
    dummies = pd.get_dummies(cl, drop_first=True).values.astype(float)
    if dummies.shape[1]:
        cols.extend(dummies.T)
    X = np.column_stack(cols)
    y = f.values.astype(float)
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if ok.sum() < X.shape[1] + 5:
        return f
    coef, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    resid = pd.Series(np.nan, index=f.index)
    resid.iloc[np.where(ok)[0]] = y[ok] - X[ok] @ coef
    return resid


def ic_1m(sig, px, cluster, beta):
    fwd = px.shift(-H) / px - 1.0
    idx = sig.index.intersection(fwd.index)
    cols = sig.columns.intersection(fwd.columns)
    ics = []
    for d in idx[::H]:  # non-overlapping
        s, f = sig.loc[d, cols], fwd.loc[d, cols]
        m = s.notna() & f.notna()
        if m.sum() < 40:
            continue
        s2 = s[m]
        f2 = neutralize(f[m], list(s2.index), cluster, beta)
        mm = f2.notna()
        if mm.sum() < 40:
            continue
        ics.append(s2[mm].corr(f2[mm], method="spearman"))
    ic = np.array(ics, float)
    n = np.isfinite(ic).sum()
    return (np.nanmean(ic), np.nanmean(ic) / np.nanstd(ic) * np.sqrt(n) if n > 1 else np.nan, int(n))


def main():
    ap = argparse.ArgumentParser()
    # V1.22: a signal must be correctly signed AND distinguishable from noise to
    # earn weight. Before this gate, weight = |IC| for any negative IC, so a
    # t = -0.51 signal still drew 8% of its bucket. That is how
    # insider_net_90d_signed held 11.4% of positioning: its IC was almost entirely
    # the market-cap tilt in the old cross-sectional rank (raw rank was -0.37
    # correlated with log mcap), and once the rank was size-neutralized its IC
    # fell from -0.024 to -0.004.
    ap.add_argument("--min-t", type=float, default=1.0,
                    help="minimum |t| on the IC to earn weight (default 1.0)")
    ap.add_argument("--min-n", type=int, default=20,
                    help="minimum non-overlapping periods to tune on (default 20)")
    args = ap.parse_args()

    px, cluster, bsc = load()
    beta = betas(px)
    print(f"1-month, factor-neutral, non-overlapping IC per signal (contrarian: negative is good)")
    print(f"gate: IC < 0 and |t| >= {args.min_t} and n >= {args.min_n}\n")
    weights = {}
    for bucket, sigs in BUCKETS.items():
        print(f"=== {bucket} ===")
        keep = {}
        for s in sigs:
            panel = sig_panel(s)
            if panel.empty:
                print(f"  {s:24s}  (no data)")
                keep[s] = 0.0
                continue
            ic, t, n = ic_1m(panel, px, cluster, beta)
            if ic is None or not np.isfinite(ic):
                verdict, w = "no IC (->0)", 0.0
            elif n < args.min_n:
                verdict, w = f"n<{args.min_n}, untunable (->0)", 0.0
            elif ic >= 0:
                verdict, w = "WRONG-SIGN (->0)", 0.0
            elif not np.isfinite(t) or abs(t) < args.min_t:
                verdict, w = f"|t|<{args.min_t}, noise (->0)", 0.0
            else:
                verdict, w = "contrarian, kept", abs(ic)
            keep[s] = w
            print(f"  {s:24s} IC {ic:+.4f}  t {t:+.2f}  n={n:<4} {verdict}")
        tot = sum(keep.values())
        if tot == 0:
            # Nothing in this bucket is tunable (e.g. options, whose yfinance
            # history is far too short for non-overlapping 1m periods). Equal-
            # weight rather than emit zeros, and say so.
            eq = round(1.0 / len(sigs), 4)
            for s in sigs:
                weights[s] = eq
            print(f"  -> no signal cleared the gate; EQUAL-WEIGHTING {eq} each\n")
        else:
            for s in sigs:
                weights[s] = round(keep[s] / tot, 4)
            print(f"  -> weights: {{{', '.join(f'{s}: {weights[s]}' for s in sigs)}}}\n")

    # bucket-level ICs (from stored bucket scores) to inform across-bucket weights
    print("=== bucket-level 1m factor-neutral IC (informs across-bucket weights) ===")
    for col, label in [("score_positioning", "positioning"), ("score_technical", "technical"), ("score_options", "options")]:
        panel = bsc.pivot(index="date", columns="ticker", values=col).sort_index()
        ic, t, n = ic_1m(panel, px, cluster, beta)
        print(f"  {label:12s} IC {ic:+.4f}  t {t:+.2f}  n={n}")

    print("\nproposed within-bucket weights block:")
    print(json.dumps(weights, indent=2))


if __name__ == "__main__":
    main()
