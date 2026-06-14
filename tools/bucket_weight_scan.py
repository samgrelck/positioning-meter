"""Scan across-bucket weightings: which maximizes the honest 1m factor-neutral
signal? Recombines the stored bucket scores (no recompute) into a composite for
each scenario and measures 1m, sector+beta-neutral, non-overlapping IC + the
annualized decile long/short spread. Answers: keep technicals? drop options?
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from lib.config import project_path
from lib.db import connect

H = 21


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
    return r


def main():
    conn = connect()
    px = pd.read_sql_query("SELECT ticker,date,adj_close FROM prices", conn, parse_dates=["date"]).pivot(
        index="date", columns="ticker", values="adj_close").sort_index()
    bs = pd.read_sql_query(
        "SELECT date,ticker,score_positioning,score_technical,score_options FROM composite_daily",
        conn, parse_dates=["date"])
    uni = pd.read_csv(project_path("data/universe.csv"))
    conn.close()
    cluster = dict(zip(uni["ticker"], uni["cluster_id"].fillna("NA")))
    dret = px.pct_change(fill_method=None)
    mret = dret["QQQ"] if "QQQ" in dret.columns else dret.mean(axis=1)
    var = mret.var()
    beta = {t: (dret[t].cov(mret) / var if var else np.nan) for t in dret.columns}

    P = bs.pivot(index="date", columns="ticker", values="score_positioning").sort_index()
    T = bs.pivot(index="date", columns="ticker", values="score_technical").sort_index()
    O = bs.pivot(index="date", columns="ticker", values="score_options").sort_index()
    fwd = px.shift(-H) / px - 1.0
    dates = [d for d in P.index[::H] if d in fwd.index]

    # precompute neutralized forward returns per sample date (weight-independent)
    neut = {}
    for d in dates:
        f = fwd.loc[d]
        m = f.notna()
        if m.sum() < 40:
            continue
        r = neutralize(f[m], list(f[m].index), cluster, beta)
        if r is not None:
            neut[d] = r.dropna()

    scenarios = [
        ("current  0.40/0.25/0.35", 0.40, 0.25, 0.35),
        ("rec      0.50/0.15/0.35", 0.50, 0.15, 0.35),
        ("tilt     0.55/0.15/0.30", 0.55, 0.15, 0.30),
        ("aggr     0.60/0.10/0.30", 0.60, 0.10, 0.30),
        ("pos-only 1.00/0.00/0.00", 1.00, 0.00, 0.00),
        ("no-tech  0.60/0.00/0.40", 0.60, 0.00, 0.40),
        ("no-opt   0.65/0.35/0.00", 0.65, 0.35, 0.00),
    ]
    print(f"1-month, factor-neutral, non-overlapping. {len(neut)} periods. (contrarian: IC negative, L/S positive)\n")
    print(f"{'scenario':26} {'IC':>9} {'t':>7} {'L/S ann':>9}")
    for name, wp, wt, wo in scenarios:
        ics, ls = [], []
        for d, fres in neut.items():
            cols = fres.index.intersection(P.columns)
            p, t, o = P.loc[d, cols], T.loc[d, cols], O.loc[d, cols]
            num = p.fillna(0) * wp + t.fillna(0) * wt + o.fillna(0) * wo
            den = p.notna() * wp + t.notna() * wt + o.notna() * wo
            comp = (num / den.replace(0, np.nan)).dropna()
            common = comp.index.intersection(fres.index)
            if len(common) < 40:
                continue
            cc, ff = comp[common], fres[common]
            ics.append(cc.corr(ff, method="spearman"))
            r = cc.rank(pct=True)
            ls.append(ff[r <= 0.1].mean() - ff[r >= 0.9].mean())
        ic = np.array(ics, float)
        n = np.isfinite(ic).sum()
        t = np.nanmean(ic) / np.nanstd(ic) * np.sqrt(n) if n > 1 else np.nan
        print(f"{name:26} {np.nanmean(ic):>+9.4f} {t:>+7.2f} {np.nanmean(ls) * 12:>+9.4f}")


if __name__ == "__main__":
    main()
