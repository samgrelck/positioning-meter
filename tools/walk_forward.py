"""Walk-forward (out-of-sample) validation of the composite.

The in-sample IC (−0.021) is optimistic because the weights were tuned on the
same data. This tunes the within-bucket weights on a TRAIN window only, freezes
them, and measures the 1-month factor-neutral IC + decile long/short on a
held-out TEST block the tuning never saw — then pools all test blocks. An
embargo gap prevents overlapping forward returns from leaking train into test.

Bucket weights are held fixed at 0.50/0.15/0.35 (a prior; options is
unidentifiable in-sample so it can't be tuned anyway). Only the within-bucket
signal weights — the main fitted component — are re-derived each fold.

Usage:  python3 tools/walk_forward.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from lib.config import project_path
from lib.db import connect

H = 21              # 1-month forward horizon (trading days)
EMBARGO = 2         # drop this many trailing sample-steps from train (gap to test)
INIT_TRAIN = 36     # initial train size in sample-steps (~3 years of monthly samples)
TEST_SIZE = 12      # test block size in sample-steps (~1 year)
BW = {"positioning": 0.50, "technical": 0.15, "options": 0.35}
BUCKETS = {
    "technical": ["ret_1m", "ret_3m", "ret_6m", "dist_200ma", "rsi_14", "pct_from_52w_high"],
    "positioning": ["insider_net_90d_signed", "insider_buying_90d", "short_volume_ratio_14d",
                    "si_true_dtc", "float_turnover_20d"],
    "options": ["iv_rank_1y", "iv_term_slope", "skew_25d", "pc_volume_ratio"],
}
ALL_SIGS = [s for v in BUCKETS.values() for s in v]


def load():
    conn = connect()
    px = pd.read_sql_query("SELECT ticker,date,adj_close FROM prices", conn, parse_dates=["date"]).pivot(
        index="date", columns="ticker", values="adj_close").sort_index()
    sd = pd.read_sql_query(
        "SELECT date,ticker,signal_name,pct_self,pct_peer FROM signals_daily WHERE signal_name IN (%s)"
        % ",".join("?" * len(ALL_SIGS)), conn, params=ALL_SIGS, parse_dates=["date"])
    uni = pd.read_csv(project_path("data/universe.csv"))
    conn.close()
    sd["dual"] = sd[["pct_self", "pct_peer"]].mean(axis=1)
    panels = {s: g.pivot(index="date", columns="ticker", values="dual").sort_index()
              for s, g in sd.groupby("signal_name")}
    cluster = dict(zip(uni["ticker"], uni["cluster_id"].fillna("NA")))
    return px, panels, cluster


def neutralize(f, tickers, cluster, beta):
    cols = [np.ones(len(f)), np.array([beta.get(t, np.nan) for t in tickers])]
    cl = pd.Series([cluster.get(t, "NA") for t in tickers], index=tickers)
    d = pd.get_dummies(cl, drop_first=True).values.astype(float)
    if d.shape[1]:
        cols.extend(d.T)
    X = np.column_stack(cols)
    y = f.values.astype(float)
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if ok.sum() < X.shape[1] + 5:
        return None
    coef, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    r = pd.Series(np.nan, index=f.index)
    r.iloc[np.where(ok)[0]] = y[ok] - X[ok] @ coef
    return r.dropna()


def main():
    px, panels, cluster = load()
    dret = px.pct_change(fill_method=None)
    mret = dret["QQQ"] if "QQQ" in dret.columns else dret.mean(axis=1)
    var = mret.var()
    beta = {t: (dret[t].cov(mret) / var if var else np.nan) for t in dret.columns}
    fwd = px.shift(-H) / px - 1.0

    # universe of dates common to signals + prices, sampled non-overlapping
    anyp = next(iter(panels.values()))
    sample = [d for d in anyp.index[::H] if d in fwd.index]
    neut = {}
    for d in sample:
        f = fwd.loc[d].dropna()
        if len(f) < 40:
            continue
        r = neutralize(f, list(f.index), cluster, beta)
        if r is not None and len(r) >= 40:
            neut[d] = r
    sdates = [d for d in sample if d in neut]
    print(f"{len(sdates)} non-overlapping monthly samples with neutralized returns.\n")

    def sig_ic(s, dates):
        p = panels.get(s)
        if p is None:
            return np.nan
        ics = []
        for d in dates:
            if d not in p.index:
                continue
            a = p.loc[d]
            b = neut[d]
            common = a.dropna().index.intersection(b.index)
            if len(common) >= 40:
                ics.append(a[common].corr(b[common], method="spearman"))
        return np.nanmean(ics) if len(ics) >= 15 else np.nan

    def fold_weights(train):
        w = {}
        for bucket, sigs in BUCKETS.items():
            ic = {s: sig_ic(s, train) for s in sigs}
            raw = {s: (abs(v) if (v is not None and np.isfinite(v) and v < 0) else 0.0) for s, v in ic.items()}
            tot = sum(raw.values())
            for s in sigs:
                w[s] = raw[s] / tot if tot else 0.0
        return w

    def composite_at(d, w):
        bs = {}
        for bucket, sigs in BUCKETS.items():
            num = den = None
            for s in sigs:
                p = panels.get(s)
                if p is None or d not in p.index or w[s] == 0:
                    continue
                v = p.loc[d]
                num = v.fillna(0) * w[s] if num is None else num.add(v.fillna(0) * w[s], fill_value=0)
                den = v.notna() * w[s] if den is None else den.add(v.notna() * w[s], fill_value=0)
            if num is not None:
                bs[bucket] = num / den.replace(0, np.nan)
        if not bs:
            return None
        cnum = cden = None
        for bucket, sc in bs.items():
            cnum = sc.fillna(0) * BW[bucket] if cnum is None else cnum.add(sc.fillna(0) * BW[bucket], fill_value=0)
            cden = sc.notna() * BW[bucket] if cden is None else cden.add(sc.notna() * BW[bucket], fill_value=0)
        return cnum / cden.replace(0, np.nan)

    oos_ic, oos_ls = [], []
    print(f"{'fold':6} {'train':>7} {'test':>7} {'OOS IC':>9} {'L/S ann':>9}")
    k = INIT_TRAIN
    fold = 0
    while k < len(sdates):
        train = sdates[:max(0, k - EMBARGO)]
        test = sdates[k:k + TEST_SIZE]
        if len(test) < 4 or len(train) < 20:
            break
        fold += 1
        w = fold_weights(train)
        f_ic, f_ls = [], []
        for d in test:
            comp = composite_at(d, w)
            if comp is None:
                continue
            b = neut[d]
            common = comp.dropna().index.intersection(b.index)
            if len(common) < 40:
                continue
            cc, bb = comp[common], b[common]
            f_ic.append(cc.corr(bb, method="spearman"))
            r = cc.rank(pct=True)
            f_ls.append(bb[r <= 0.1].mean() - bb[r >= 0.9].mean())
        oos_ic += f_ic
        oos_ls += f_ls
        print(f"{fold:6} {len(train):>7} {len(test):>7} {np.nanmean(f_ic):>+9.4f} {np.nanmean(f_ls) * 12:>+9.4f}")
        k += TEST_SIZE

    ic = np.array(oos_ic, float)
    n = np.isfinite(ic).sum()
    t = np.nanmean(ic) / np.nanstd(ic) * np.sqrt(n) if n > 1 else np.nan
    print("\n" + "=" * 50)
    print(f"POOLED OUT-OF-SAMPLE: IC {np.nanmean(ic):+.4f}  t {t:+.2f}  "
          f"L/S {np.nanmean(oos_ls) * 12:+.4f}/yr  ({n} test months)")
    print(f"In-sample reference: IC -0.021, +7.5%/yr")
    print("If OOS holds near in-sample -> robust. If it collapses toward 0 -> the weights were overfit.")


if __name__ == "__main__":
    main()
