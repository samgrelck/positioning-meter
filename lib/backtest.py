"""Backtest framework — measures whether each signal (and the composite)
has predictive value for forward returns.

Metrics computed per signal:
  - Information Coefficient (Spearman rho between signal pct and fwd return)
  - Decile spread (mean fwd ret of top decile - bottom decile)
  - Hit rate of extremes (% of top-decile days with negative 1m forward
    return; % of bottom-decile days with positive 1m forward return)
  - Per-regime (bull/bear, high/low VIX) IC

Forward returns are computed as adj_close[t+H] / adj_close[t] - 1, where
H is the horizon in trading days.

Output: a backtest_results table + JSON summary report.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import load, project_path
from .db import connect


HORIZONS = {"1w": 5, "1m": 21, "3m": 63}


def load_returns_panel(closes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Forward returns for each horizon: DF[date x ticker]."""
    out = {}
    for label, h in HORIZONS.items():
        out[label] = closes.shift(-h) / closes - 1
    return out


def load_signal_panel(signal_name: str, kind: str = "pct_self") -> pd.DataFrame:
    """Wide panel of pct_self or pct_peer for one signal."""
    conn = connect()
    df = pd.read_sql_query(
        f"""
        SELECT ticker, date, {kind} as v
        FROM signals_daily
        WHERE signal_name = ? AND {kind} IS NOT NULL
        """,
        conn,
        params=(signal_name,),
        parse_dates=["date"],
    )
    conn.close()
    if df.empty:
        return pd.DataFrame()
    return df.pivot(index="date", columns="ticker", values="v")


def load_composite_panel() -> pd.DataFrame:
    conn = connect()
    df = pd.read_sql_query(
        "SELECT ticker, date, temperature FROM composite_daily WHERE temperature IS NOT NULL",
        conn,
        parse_dates=["date"],
    )
    conn.close()
    if df.empty:
        return pd.DataFrame()
    return df.pivot(index="date", columns="ticker", values="temperature")


def load_prices_wide() -> pd.DataFrame:
    conn = connect()
    df = pd.read_sql_query(
        "SELECT ticker, date, adj_close FROM prices",
        conn,
        parse_dates=["date"],
    )
    conn.close()
    return df.pivot(index="date", columns="ticker", values="adj_close")


def _ic_decile_spread(signal: pd.Series, fwd: pd.Series) -> dict:
    """For aligned series, compute IC + decile spread + hit rates."""
    paired = pd.concat([signal, fwd], axis=1, keys=["s", "f"]).dropna()
    if len(paired) < 100:
        return {"n": len(paired), "ic": None, "decile_spread": None,
                "top_hit_rate": None, "bot_hit_rate": None}
    rho, _ = spearmanr(paired["s"], paired["f"])
    # Decile bucketing
    paired["dec"] = pd.qcut(paired["s"], 10, labels=False, duplicates="drop")
    decile_means = paired.groupby("dec")["f"].mean()
    if len(decile_means) >= 10:
        spread = decile_means.iloc[-1] - decile_means.iloc[0]
    else:
        spread = None
    top = paired[paired["dec"] == paired["dec"].max()]
    bot = paired[paired["dec"] == paired["dec"].min()]
    top_hit = (top["f"] < 0).mean() if len(top) > 0 else None
    bot_hit = (bot["f"] > 0).mean() if len(bot) > 0 else None
    return {
        "n": len(paired),
        "ic": float(rho) if not pd.isna(rho) else None,
        "decile_spread": float(spread) if spread is not None else None,
        "top_hit_rate": float(top_hit) if top_hit is not None else None,
        "bot_hit_rate": float(bot_hit) if bot_hit is not None else None,
        "decile_means": decile_means.to_dict(),
    }


def backtest_signal(
    signal_panel: pd.DataFrame, fwd_panel: pd.DataFrame
) -> dict:
    """Stack to long, run aligned IC + decile metrics."""
    # Align indexes
    common_idx = signal_panel.index.intersection(fwd_panel.index)
    common_cols = signal_panel.columns.intersection(fwd_panel.columns)
    s = signal_panel.loc[common_idx, common_cols]
    f = fwd_panel.loc[common_idx, common_cols]
    s_long = s.stack(future_stack=True).rename("s")
    f_long = f.stack(future_stack=True).rename("f")
    return _ic_decile_spread(s_long, f_long)


def run_backtest_all_signals(
    signals: list[str], fwd_panels: dict[str, pd.DataFrame]
) -> list[dict]:
    """For each signal × horizon × kind (self/peer), report metrics."""
    results = []
    for sig in signals:
        for kind in ["pct_self", "pct_peer"]:
            sp = load_signal_panel(sig, kind=kind)
            if sp.empty:
                continue
            for hlab, fwd in fwd_panels.items():
                metrics = backtest_signal(sp, fwd)
                results.append({
                    "signal": sig, "kind": kind, "horizon": hlab,
                    **metrics,
                })
    return results


def run_backtest_composite(fwd_panels: dict[str, pd.DataFrame]) -> list[dict]:
    comp = load_composite_panel()
    if comp.empty:
        return []
    results = []
    for hlab, fwd in fwd_panels.items():
        metrics = backtest_signal(comp, fwd)
        results.append({"signal": "COMPOSITE_TEMPERATURE", "kind": "temperature",
                        "horizon": hlab, **metrics})
    return results
