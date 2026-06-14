"""Factor/sector-neutral backtest for the Positioning Meter composite.

Raw cross-sectional IC is swamped by the market + sector + beta common factors
that the signal never tried to predict. This measures the composite's IC against
RESIDUAL forward returns (after stripping sector + beta cross-sectionally per
date, Fama-MacBeth style), which isolates the actual alpha. Also reports the
tail-decile long/short spread (where contrarian signals actually live) and
re-checks float_turnover once neutralized.

Sector-demean (cluster) has no look-ahead. Beta uses a full-sample estimate —
a diagnostic approximation (documented), since the headline neutralization is
the sector one. Contrarian convention: NEGATIVE IC is good (high temp -> low fwd
return); long-short = bottom-decile minus top-decile (positive is good).

Usage:  python3 tools/factor_neutral_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from lib.config import project_path
from lib.db import connect

HORIZONS = {"1m": 21, "3m": 63}


def _pivot(conn, sql, params=()):
    df = pd.read_sql_query(sql, conn, params=params, parse_dates=["date"])
    return df


def load():
    conn = connect()
    px = _pivot(conn, "SELECT ticker,date,adj_close FROM prices").pivot(
        index="date", columns="ticker", values="adj_close").sort_index()
    temp = _pivot(conn, "SELECT ticker,date,temperature FROM composite_daily").pivot(
        index="date", columns="ticker", values="temperature").sort_index()
    ft = pd.read_sql_query(
        "SELECT date,ticker,pct_self,pct_peer FROM signals_daily WHERE signal_name='float_turnover_20d'",
        conn, parse_dates=["date"])
    ft["dual"] = ft[["pct_self", "pct_peer"]].mean(axis=1)
    ftp = ft.pivot(index="date", columns="ticker", values="dual").sort_index()
    uni = pd.read_csv(project_path("data/universe.csv"))
    conn.close()
    cluster = dict(zip(uni["ticker"], uni["cluster_id"].fillna("NA")))
    return px, temp, ftp, cluster


def betas(px, bench="QQQ"):
    dret = px.pct_change()
    mret = dret[bench] if bench in dret.columns else dret.mean(axis=1)
    var = mret.var()
    b = {}
    for t in dret.columns:
        cov = dret[t].cov(mret)
        b[t] = cov / var if var else np.nan
    return pd.Series(b)


def neutralize(f, tickers, cluster, beta, mode):
    """Residualize a cross-section of forward returns. mode: 'raw'|'sector'|'full'."""
    if mode == "raw":
        return f
    X_cols = [np.ones(len(f))]
    if mode == "full":
        X_cols.append(np.array([beta.get(t, np.nan) for t in tickers]))
    # cluster dummies
    cl = pd.Series([cluster.get(t, "NA") for t in tickers], index=tickers)
    dummies = pd.get_dummies(cl, drop_first=True).values.astype(float)
    if dummies.shape[1]:
        X_cols.extend(dummies.T)
    X = np.column_stack(X_cols)
    y = f.values.astype(float)
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if ok.sum() < X.shape[1] + 5:
        return f
    coef, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    resid = pd.Series(np.nan, index=f.index)
    resid.iloc[np.where(ok)[0]] = y[ok] - X[ok] @ coef
    return resid


def fm_ic(sig, px, cluster, beta, h, mode, deciles=False):
    fwd = px.shift(-h) / px - 1.0
    idx = sig.index.intersection(fwd.index)
    cols = sig.columns.intersection(fwd.columns)
    ics, ls = [], []
    for d in idx:
        s = sig.loc[d, cols]
        f = fwd.loc[d, cols]
        m = s.notna() & f.notna()
        if m.sum() < 40:
            continue
        s2, f2 = s[m], f[m]
        f2 = neutralize(f2, list(s2.index), cluster, beta, mode)
        mm = f2.notna()
        s2, f2 = s2[mm], f2[mm]
        if len(s2) < 40:
            continue
        ics.append(s2.corr(f2, method="spearman"))
        if deciles:
            r = s2.rank(pct=True)
            bot = f2[r <= 0.1].mean()
            top = f2[r >= 0.9].mean()
            ls.append(bot - top)  # contrarian: low temp minus high temp
    ic = np.array(ics, dtype=float)
    out = {"ic": np.nanmean(ic), "t": np.nanmean(ic) / np.nanstd(ic) * np.sqrt(np.isfinite(ic).sum()) if np.isfinite(ic).sum() > 1 else np.nan, "n_days": int(np.isfinite(ic).sum())}
    if deciles:
        out["ls_spread"] = np.nanmean(ls)
    return out


def main():
    px, temp, ftp, cluster = load()
    beta = betas(px)
    print(f"Loaded: {temp.shape[1]} names, {temp.shape[0]} dates. beta computed for {beta.notna().sum()}.\n")
    print("COMPOSITE TEMPERATURE — IC vs forward returns (contrarian: negative is good)")
    print(f"{'horizon':8} {'raw IC':>10} {'sector-neut':>12} {'full-neut':>11} {'(t-stat)':>10}")
    for hn, h in HORIZONS.items():
        raw = fm_ic(temp, px, cluster, beta, h, "raw")
        sec = fm_ic(temp, px, cluster, beta, h, "sector")
        full = fm_ic(temp, px, cluster, beta, h, "full", deciles=True)
        print(f"{hn:8} {raw['ic']:>+10.4f} {sec['ic']:>+12.4f} {full['ic']:>+11.4f} {full['t']:>+10.2f}")
    # tail spread at 3m, full-neutral
    full3 = fm_ic(temp, px, cluster, beta, 63, "full", deciles=True)
    print(f"\n3m full-neutral tail long/short (bottom-decile minus top-decile mean fwd return): {full3['ls_spread']:+.4f}  ({full3['n_days']} days)")
    print("  (positive = washed-out names beat crowded names, contrarian working)")
    # float_turnover standalone, raw vs full-neutral
    print("\nFLOAT_TURNOVER_20d alone — does neutralization change its signal? (3m)")
    fr = fm_ic(ftp, px, cluster, beta, 63, "raw")
    ff = fm_ic(ftp, px, cluster, beta, 63, "full")
    print(f"  raw IC {fr['ic']:+.4f}   full-neutral IC {ff['ic']:+.4f}  (t={ff['t']:+.2f})")


if __name__ == "__main__":
    main()
