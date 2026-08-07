"""Setup-grid cell returns: positioning tercile x technical tercile.

Reproduces the figures hardcoded in setup/08_render_dashboard.py's QUAD_DEFS
(V1.21 computed them ad hoc; this makes them re-runnable). For each
non-overlapping 1-month period, names are sorted into a 3x3 grid on that date's
cross-sectional positioning and technical scores, and each cell's mean forward
return is measured against sector+beta-residualized returns.

Also reports the same grid with SIZE added to the return-side neutralization.
That is the direct test of whether a cell's edge is a size premium: the
positioning bucket's inputs scale with liquidity, so before the V1.22
size-neutral rank the cold cells were substantially a large-cap bucket. If a
cell's figure survives size-residualization, it is not just size.

Contrarian convention: positive residual return is good for a cold cell.

Usage:  python3 tools/quad_cell_returns.py [--periods 21]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from lib.config import project_path
from lib.db import connect
from lib.signals import loaders

H = 21  # 1 month in trading days
CELLS = [
    ("cold", "weak", "Under-owned ↓"),
    ("cold", "strong", "Under-owned ↑"),
    ("hot", "weak", "Crowded ↓"),
    ("hot", "strong", "Crowded ↑"),
]


def load():
    conn = connect()
    px = pd.read_sql_query(
        "SELECT ticker,date,adj_close FROM prices", conn, parse_dates=["date"]
    ).pivot(index="date", columns="ticker", values="adj_close").sort_index()
    cd = pd.read_sql_query(
        "SELECT date,ticker,score_positioning,score_technical FROM composite_daily",
        conn, parse_dates=["date"])
    conn.close()
    pos = cd.pivot(index="date", columns="ticker", values="score_positioning").sort_index()
    tech = cd.pivot(index="date", columns="ticker", values="score_technical").sort_index()
    uni = pd.read_csv(project_path("data/universe.csv"))
    cluster = dict(zip(uni["ticker"], uni["cluster_id"].fillna("NA")))
    return px, pos, tech, cluster


def betas(px, bench="QQQ"):
    dret = px.pct_change(fill_method=None)
    mret = dret[bench] if bench in dret.columns else dret.mean(axis=1)
    var = mret.var()
    return pd.Series({t: (dret[t].cov(mret) / var if var else np.nan) for t in dret.columns})


def neutralize(f, tickers, cluster, beta, log_mcap=None):
    """Residualize forward returns on sector + beta (+ log size when given)."""
    cols = [np.ones(len(f)), np.array([beta.get(t, np.nan) for t in tickers])]
    if log_mcap is not None:
        cols.append(np.array([log_mcap.get(t, np.nan) for t in tickers]))
    cl = pd.Series([cluster.get(t, "NA") for t in tickers], index=tickers)
    dummies = pd.get_dummies(cl, drop_first=True).values.astype(float)
    if dummies.shape[1]:
        cols.extend(dummies.T)
    X = np.column_stack(cols)
    y = f.values.astype(float)
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if ok.sum() < X.shape[1] + 5:
        return pd.Series(np.nan, index=f.index)
    coef, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    resid = pd.Series(np.nan, index=f.index)
    resid.iloc[np.where(ok)[0]] = y[ok] - X[ok] @ coef
    return resid


def _tercile(s, labels):
    valid = s.dropna()
    if len(valid) < 6:
        return pd.Series(dtype=object)
    return pd.qcut(valid.rank(method="first"), 3, labels=list(labels)).astype(object)


def run(px, pos, tech, cluster, beta, mcap=None, with_size=False):
    fwd = px.shift(-H) / px - 1.0
    idx = pos.index.intersection(fwd.index)
    per_cell = {c[2]: [] for c in CELLS}
    strong_gap = []
    n_periods = 0
    for d in idx[::H]:
        cols = pos.columns.intersection(fwd.columns)
        p, t, f = pos.loc[d, cols], tech.loc[d, cols], fwd.loc[d, cols]
        m = p.notna() & t.notna() & f.notna()
        if m.sum() < 40:
            continue
        tick = list(p[m].index)
        lm = None
        if with_size and mcap is not None and d in mcap.index:
            lm = np.log(mcap.loc[d, [c for c in tick if c in mcap.columns]].replace(0, np.nan))
        r = neutralize(f[m], tick, cluster, beta, lm)
        pt = _tercile(p[m], ("cold", "mid", "hot"))
        tt = _tercile(t[m], ("weak", "mid", "strong"))
        n_periods += 1
        cell_means = {}
        for pl, tl, name in CELLS:
            sel = [k for k in tick if pt.get(k) == pl and tt.get(k) == tl]
            vals = r.reindex(sel).dropna()
            if len(vals) >= 3:
                per_cell[name].append(vals.mean())
                cell_means[name] = vals.mean()
        if "Under-owned ↑" in cell_means and "Crowded ↑" in cell_means:
            strong_gap.append(cell_means["Under-owned ↑"] - cell_means["Crowded ↑"])
    return per_cell, strong_gap, n_periods


def report(per_cell, strong_gap, n_periods, title):
    print(f"\n=== {title}  ({n_periods} non-overlapping 1m periods) ===")
    print(f"{'cell':>16}  {'ann. resid':>11}  {'t':>6}  {'n':>4}")
    for _, _, name in CELLS:
        a = np.array(per_cell[name], float)
        a = a[np.isfinite(a)]
        if len(a) < 2:
            print(f"{name:>16}  {'n/a':>11}")
            continue
        mu, t = a.mean(), a.mean() / a.std(ddof=1) * np.sqrt(len(a))
        print(f"{name:>16}  {mu * 12 * 100:>+10.1f}%  {t:>+6.2f}  {len(a):>4}")
    g = np.array(strong_gap, float)
    g = g[np.isfinite(g)]
    if len(g) > 1:
        t = g.mean() / g.std(ddof=1) * np.sqrt(len(g))
        print(f"{'light-heavy | strong':>16}  {g.mean() * 12 * 100:>+10.1f}%  {t:>+6.2f}  {len(g):>4}")


def main():
    ap = argparse.ArgumentParser()
    ap.parse_args()
    px, pos, tech, cluster = load()
    beta = betas(px)
    mcap = loaders.load_market_cap_panel(px.sort_index())
    for with_size, title in [
        (False, "sector + beta neutral (as published)"),
        (True, "sector + beta + SIZE neutral (is the edge just size?)"),
    ]:
        pc, sg, n = run(px, pos, tech, cluster, beta, mcap, with_size)
        report(pc, sg, n, title)


if __name__ == "__main__":
    main()
