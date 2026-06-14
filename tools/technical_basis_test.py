"""Own-history vs cross-sectional ranking for the technical signals.

Tests, at the 1-month factor-neutral non-overlapping horizon, whether each
technical signal predicts better when ranked vs the stock's OWN 5y history
(pct_self, mean-reversion) or vs the TMT UNIVERSE cross-section today
(momentum). Contrarian convention: NEGATIVE IC is good. If the cross-section
(peer) IC is POSITIVE, that signal is trend-following cross-sectionally and
would fight the contrarian composite — confirming own-history is correct.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from lib.config import project_path
from lib.db import connect

H = 21
TECH = ["ret_1m", "ret_3m", "ret_6m", "rsi_14", "dist_200ma", "pct_from_52w_high"]


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


def ic(panel, neut, sdates):
    out = []
    for d in sdates:
        if d not in panel.index:
            continue
        a = panel.loc[d].dropna()
        b = neut[d]
        common = a.index.intersection(b.index)
        if len(common) >= 40:
            out.append(a[common].corr(b[common], method="spearman"))
    a = np.array(out, float)
    n = np.isfinite(a).sum()
    return np.nanmean(a), (np.nanmean(a) / np.nanstd(a) * np.sqrt(n) if n > 1 else np.nan)


def main():
    conn = connect()
    px = pd.read_sql_query("SELECT ticker,date,adj_close FROM prices", conn, parse_dates=["date"]).pivot(
        index="date", columns="ticker", values="adj_close").sort_index()
    sd = pd.read_sql_query(
        "SELECT date,ticker,signal_name,raw_value,pct_self FROM signals_daily WHERE signal_name IN (%s)"
        % ",".join("?" * len(TECH)), conn, params=TECH, parse_dates=["date"])
    uni = pd.read_csv(project_path("data/universe.csv"))
    conn.close()
    cluster = dict(zip(uni["ticker"], uni["cluster_id"].fillna("NA")))
    dret = px.pct_change(fill_method=None)
    mret = dret["QQQ"] if "QQQ" in dret.columns else dret.mean(axis=1)
    var = mret.var()
    beta = {t: (dret[t].cov(mret) / var if var else np.nan) for t in dret.columns}
    fwd = px.shift(-H) / px - 1.0
    anyp = sd[sd.signal_name == "ret_1m"].pivot(index="date", columns="ticker", values="raw_value").sort_index()
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

    print(f"1m factor-neutral IC, {len(sdates)} non-overlapping months (contrarian: negative good)\n")
    print(f"{'signal':20} {'OWN-HISTORY':>22} {'CROSS-SECTION (universe)':>26}")
    print(f"{'':20} {'IC':>10} {'t':>10} {'IC':>12} {'t':>12}")
    for s in TECH:
        g = sd[sd.signal_name == s]
        self_p = g.pivot(index="date", columns="ticker", values="pct_self").sort_index()
        raw_p = g.pivot(index="date", columns="ticker", values="raw_value").sort_index()
        peer_p = raw_p.rank(axis=1, pct=True) * 100.0  # true cross-sectional rank of the raw value
        si, st = ic(self_p, neut, sdates)
        pi, pt = ic(peer_p, neut, sdates)
        print(f"{s:20} {si:>+10.4f} {st:>+10.2f} {pi:>+12.4f} {pt:>+12.2f}")


if __name__ == "__main__":
    main()
