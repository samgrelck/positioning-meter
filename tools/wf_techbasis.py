"""Walk-forward (out-of-sample) comparison of the technical percentile basis:
own-history (current) vs cross-section (universe) vs 50/50 blend. Same fold
machinery as walk_forward.py; only the technical signals' panels change. Tells
us whether switching returns to cross-sectional ranking actually holds OOS.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from lib.config import project_path
from lib.db import connect

H, EMBARGO, INIT_TRAIN, TEST_SIZE = 21, 2, 36, 12
BW = {"positioning": 0.50, "technical": 0.15, "options": 0.35}
BUCKETS = {
    "technical": ["ret_1m", "ret_3m", "ret_6m", "dist_200ma", "rsi_14", "pct_from_52w_high"],
    "positioning": ["insider_net_90d_signed", "insider_buying_90d", "short_volume_ratio_14d",
                    "si_true_dtc", "float_turnover_20d"],
    "options": ["iv_rank_1y", "iv_term_slope", "skew_25d", "pc_volume_ratio"],
}
ALL = [s for v in BUCKETS.values() for s in v]


def neutralize(f, tickers, cluster, beta):
    cols = [np.ones(len(f)), np.array([beta.get(t, np.nan) for t in tickers])]
    cl = pd.Series([cluster.get(t, "NA") for t in tickers], index=tickers)
    d = pd.get_dummies(cl, drop_first=True).values.astype(float)
    if d.shape[1]:
        cols.extend(d.T)
    X = np.column_stack(cols); y = f.values.astype(float)
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if ok.sum() < X.shape[1] + 5:
        return None
    coef, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    r = pd.Series(np.nan, index=f.index); r.iloc[np.where(ok)[0]] = y[ok] - X[ok] @ coef
    return r.dropna()


def build_panels(tech_basis):
    conn = connect()
    sd = pd.read_sql_query(
        "SELECT date,ticker,signal_name,raw_value,pct_self,pct_peer FROM signals_daily WHERE signal_name IN (%s)"
        % ",".join("?" * len(ALL)), conn, params=ALL, parse_dates=["date"])
    conn.close()
    panels = {}
    for s, g in sd.groupby("signal_name"):
        if s in BUCKETS["technical"]:
            self_p = g.pivot(index="date", columns="ticker", values="pct_self").sort_index()
            if tech_basis == "self":
                panels[s] = self_p
            else:
                raw = g.pivot(index="date", columns="ticker", values="raw_value").sort_index()
                peer = raw.rank(axis=1, pct=True) * 100.0
                panels[s] = peer if tech_basis == "peer" else (self_p + peer) / 2.0
        else:
            g = g.copy(); g["dual"] = g[["pct_self", "pct_peer"]].mean(axis=1)
            panels[s] = g.pivot(index="date", columns="ticker", values="dual").sort_index()
    return panels


def run(tech_basis):
    conn = connect()
    px = pd.read_sql_query("SELECT ticker,date,adj_close FROM prices", conn, parse_dates=["date"]).pivot(
        index="date", columns="ticker", values="adj_close").sort_index()
    uni = pd.read_csv(project_path("data/universe.csv"))
    conn.close()
    cluster = dict(zip(uni["ticker"], uni["cluster_id"].fillna("NA")))
    dret = px.pct_change(fill_method=None)
    mret = dret["QQQ"] if "QQQ" in dret.columns else dret.mean(axis=1)
    var = mret.var(); beta = {t: (dret[t].cov(mret) / var if var else np.nan) for t in dret.columns}
    fwd = px.shift(-H) / px - 1.0
    panels = build_panels(tech_basis)
    sample = [d for d in panels["ret_1m"].index[::H] if d in fwd.index]
    neut = {}
    for d in sample:
        f = fwd.loc[d].dropna()
        if len(f) < 40:
            continue
        r = neutralize(f, list(f.index), cluster, beta)
        if r is not None and len(r) >= 40:
            neut[d] = r
    sdates = [d for d in sample if d in neut]

    def sig_ic(s, dates):
        p = panels.get(s)
        if p is None:
            return np.nan
        ics = []
        for d in dates:
            if d not in p.index:
                continue
            a = p.loc[d].dropna(); b = neut[d]
            common = a.index.intersection(b.index)
            if len(common) >= 40:
                ics.append(a[common].corr(b[common], method="spearman"))
        return np.nanmean(ics) if len(ics) >= 15 else np.nan

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
        cn = cd = None
        for bucket, sc in bs.items():
            cn = sc.fillna(0) * BW[bucket] if cn is None else cn.add(sc.fillna(0) * BW[bucket], fill_value=0)
            cd = sc.notna() * BW[bucket] if cd is None else cd.add(sc.notna() * BW[bucket], fill_value=0)
        return cn / cd.replace(0, np.nan)

    oos_ic, oos_ls = [], []
    k = INIT_TRAIN
    while k < len(sdates):
        train, test = sdates[:max(0, k - EMBARGO)], sdates[k:k + TEST_SIZE]
        if len(test) < 4 or len(train) < 20:
            break
        w = {}
        for bucket, sigs in BUCKETS.items():
            ics = {s: sig_ic(s, train) for s in sigs}
            raw = {s: (abs(v) if (v is not None and np.isfinite(v) and v < 0) else 0.0) for s, v in ics.items()}
            tot = sum(raw.values())
            for s in sigs:
                w[s] = raw[s] / tot if tot else 0.0
        for d in test:
            comp = composite_at(d, w)
            if comp is None:
                continue
            b = neut[d]; common = comp.dropna().index.intersection(b.index)
            if len(common) < 40:
                continue
            cc, bb = comp[common], b[common]
            oos_ic.append(cc.corr(bb, method="spearman"))
            r = cc.rank(pct=True)
            oos_ls.append(bb[r <= 0.1].mean() - bb[r >= 0.9].mean())
        k += TEST_SIZE
    ic = np.array(oos_ic, float); n = np.isfinite(ic).sum()
    t = np.nanmean(ic) / np.nanstd(ic) * np.sqrt(n) if n > 1 else np.nan
    return np.nanmean(ic), t, np.nanmean(oos_ls) * 12, n


def main():
    print("Walk-forward OUT-OF-SAMPLE by technical percentile basis (1m factor-neutral)\n")
    print(f"{'tech basis':14} {'OOS IC':>9} {'t':>7} {'L/S ann':>9} {'months':>7}")
    for basis in ["self", "peer", "blend"]:
        ic, t, ls, n = run(basis)
        lab = {"self": "own-history", "peer": "cross-section", "blend": "50/50 blend"}[basis]
        print(f"{lab:14} {ic:>+9.4f} {t:>+7.2f} {ls:>+9.4f} {n:>7}")


if __name__ == "__main__":
    main()
