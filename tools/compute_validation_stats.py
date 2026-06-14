"""Compute the model's validation numbers and write data/validation_stats.json,
so the dashboard reads them instead of hard-coded text (which kept going stale).

Produces, at the 1-month factor-neutral non-overlapping horizon:
  - in-sample: composite IC, t, decile long/short (annualized)
  - out-of-sample (walk-forward, per-fold re-tuned weights): IC, t, L/S
Bucket weights come from config.yaml. Run from deploy.sh / refresh.

Usage:  python3 tools/compute_validation_stats.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import yaml

from lib.config import project_path
from lib.db import connect

H, EMBARGO, INIT_TRAIN, TEST_SIZE = 21, 2, 36, 12
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


def _agg(ls):
    a = np.array(ls, float); n = int(np.isfinite(a).sum())
    if n < 2:
        return None
    m = np.nanmean(a)
    return {"ic": round(float(m), 4), "t": round(float(m / np.nanstd(a) * np.sqrt(n)), 2), "n": n}


def main():
    BW = yaml.safe_load(open(project_path("config.yaml")))["composite"]["bucket_weights"]
    conn = connect()
    px = pd.read_sql_query("SELECT ticker,date,adj_close FROM prices", conn, parse_dates=["date"]).pivot(
        index="date", columns="ticker", values="adj_close").sort_index()
    sd = pd.read_sql_query(
        "SELECT date,ticker,signal_name,pct_self,pct_peer FROM signals_daily WHERE signal_name IN (%s)"
        % ",".join("?" * len(ALL)), conn, params=ALL, parse_dates=["date"])
    comp = pd.read_sql_query("SELECT date,ticker,temperature FROM composite_daily", conn, parse_dates=["date"])
    asof = conn.execute("SELECT MAX(date) FROM composite_daily").fetchone()[0]
    uni = pd.read_csv(project_path("data/universe.csv"))
    conn.close()
    sd["dual"] = sd[["pct_self", "pct_peer"]].mean(axis=1)
    panels = {s: g.pivot(index="date", columns="ticker", values="dual").sort_index() for s, g in sd.groupby("signal_name")}
    temp = comp.pivot(index="date", columns="ticker", values="temperature").sort_index()
    cluster = dict(zip(uni["ticker"], uni["cluster_id"].fillna("NA")))
    dret = px.pct_change(fill_method=None)
    mret = dret["QQQ"] if "QQQ" in dret.columns else dret.mean(axis=1)
    var = mret.var(); beta = {t: (dret[t].cov(mret) / var if var else np.nan) for t in dret.columns}
    fwd = px.shift(-H) / px - 1.0
    sample = [d for d in temp.index[::H] if d in fwd.index]
    neut = {}
    for d in sample:
        f = fwd.loc[d].dropna()
        if len(f) >= 40:
            r = neutralize(f, list(f.index), cluster, beta)
            if r is not None and len(r) >= 40:
                neut[d] = r
    sdates = [d for d in sample if d in neut]

    def ls_for(comp_panel, dlist):
        out = []
        for d in dlist:
            if d not in comp_panel.index:
                continue
            c = comp_panel.loc[d].dropna(); b = neut[d]
            common = c.index.intersection(b.index)
            if len(common) >= 40:
                r = c[common].rank(pct=True)
                out.append((c[common].corr(b[common], method="spearman"),
                            b[common][r <= 0.1].mean() - b[common][r >= 0.9].mean()))
        return out

    # in-sample
    isr = ls_for(temp, sdates)
    is_ic = _agg([x[0] for x in isr]); is_ls = float(np.nanmean([x[1] for x in isr])) * 12

    # out-of-sample walk-forward (re-tune within-bucket weights per fold)
    def sig_ic(s, dates):
        p = panels.get(s)
        if p is None:
            return np.nan
        v = [p.loc[d].dropna().corr(neut[d], method="spearman") for d in dates
             if d in p.index and len(p.loc[d].dropna().index.intersection(neut[d].index)) >= 40]
        return np.nanmean(v) if len(v) >= 15 else np.nan

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

    oos = []
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
            c = composite_at(d, w)
            if c is None:
                continue
            cc = c.dropna(); b = neut[d]; common = cc.index.intersection(b.index)
            if len(common) >= 40:
                r = cc[common].rank(pct=True)
                oos.append((cc[common].corr(b[common], method="spearman"),
                            b[common][r <= 0.1].mean() - b[common][r >= 0.9].mean()))
        k += TEST_SIZE
    oos_ic = _agg([x[0] for x in oos]); oos_ls = float(np.nanmean([x[1] for x in oos])) * 12

    out = {
        "as_of": asof,
        "horizon": "1-month, factor-neutral, non-overlapping",
        "bucket_weights": BW,
        "in_sample": {**(is_ic or {}), "ls_ann": round(is_ls, 4)},
        "oos": {**(oos_ic or {}), "ls_ann": round(oos_ls, 4)},
    }
    path = project_path("data/validation_stats.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"wrote {path.name}: in-sample IC {out['in_sample'].get('ic')} (t {out['in_sample'].get('t')}), "
          f"OOS IC {out['oos'].get('ic')} (t {out['oos'].get('t')})")


if __name__ == "__main__":
    main()
