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
    px, cluster, bsc = load()
    beta = betas(px)
    print(f"1-month, factor-neutral, non-overlapping IC per signal (contrarian: negative is good)\n")
    weights = {}
    for bucket, sigs in BUCKETS.items():
        print(f"=== {bucket} ===")
        ics = {}
        for s in sigs:
            panel = sig_panel(s)
            if panel.empty:
                print(f"  {s:24s}  (no data)")
                ics[s] = None
                continue
            ic, t, n = ic_1m(panel, px, cluster, beta)
            ics[s] = ic
            flag = "contrarian" if (ic is not None and ic < 0) else "WRONG-SIGN (->0)"
            print(f"  {s:24s} IC {ic:+.4f}  t {t:+.2f}  n={n:<3}  {flag}")
        # weight = |IC| for negative-IC signals, else 0; normalize within bucket
        raw = {s: (abs(v) if (v is not None and v < 0) else 0.0) for s, v in ics.items()}
        tot = sum(raw.values())
        norm = {s: (raw[s] / tot if tot else 0.0) for s in sigs}
        for s in sigs:
            weights[s] = round(norm[s], 4)
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
