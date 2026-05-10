"""Grid-search positioning vs technical bucket weights.

Recomputes composite at each weight pair and measures backtest IC.
Picks the (w_pos, w_tech) combo with the most negative composite IC at 3m fwd
(stronger contrarian signal).

Usage: python tools/tune_weights.py
"""
import sys
from pathlib import Path

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.db import connect


def load_panels():
    conn = connect()
    # Load bucket scores from composite_daily (already computed)
    pos = pd.read_sql_query(
        "SELECT ticker, date, score_positioning FROM composite_daily WHERE score_positioning IS NOT NULL",
        conn, parse_dates=["date"],
    ).pivot(index="date", columns="ticker", values="score_positioning")
    tech = pd.read_sql_query(
        "SELECT ticker, date, score_technical FROM composite_daily WHERE score_technical IS NOT NULL",
        conn, parse_dates=["date"],
    ).pivot(index="date", columns="ticker", values="score_technical")
    closes = pd.read_sql_query(
        "SELECT ticker, date, adj_close FROM prices",
        conn, parse_dates=["date"],
    ).pivot(index="date", columns="ticker", values="adj_close")
    conn.close()
    return pos, tech, closes


def compute_composite(pos, tech, w_pos, w_tech):
    """Weighted average of bucket scores. Reweights when one is missing."""
    idx = sorted(set(pos.index) | set(tech.index))
    cols = sorted(set(pos.columns) | set(tech.columns))
    pos_a = pos.reindex(index=idx, columns=cols)
    tech_a = tech.reindex(index=idx, columns=cols)

    pos_present = pos_a.notna()
    tech_present = tech_a.notna()

    weighted = pos_a.fillna(0) * w_pos + tech_a.fillna(0) * w_tech
    weight_sum = pos_present.astype(float) * w_pos + tech_present.astype(float) * w_tech
    composite = weighted.where(weight_sum > 0) / weight_sum

    # Min 2 buckets present (both pos AND tech)
    composite = composite.where(pos_present & tech_present)
    return composite


def backtest_ic(composite, closes, horizon_days=63):
    fwd = closes.shift(-horizon_days) / closes - 1
    common_idx = composite.index.intersection(fwd.index)
    common_cols = composite.columns.intersection(fwd.columns)
    s = composite.loc[common_idx, common_cols]
    f = fwd.loc[common_idx, common_cols]
    s_long = s.stack(future_stack=True).dropna()
    f_long = f.stack(future_stack=True).dropna()
    paired = pd.concat([s_long.rename("s"), f_long.rename("f")], axis=1).dropna()
    if len(paired) < 100:
        return None, None, None
    rho, _ = spearmanr(paired["s"], paired["f"])
    paired["dec"] = pd.qcut(paired["s"], 10, labels=False, duplicates="drop")
    decile_means = paired.groupby("dec")["f"].mean()
    spread = decile_means.iloc[-1] - decile_means.iloc[0] if len(decile_means) >= 10 else None
    bot_hit = (paired[paired["dec"] == paired["dec"].min()]["f"] > 0).mean()
    return rho, spread, bot_hit


def main():
    print("Loading panels...")
    pos, tech, closes = load_panels()
    print(f"  Pos panel: {pos.shape}")
    print(f"  Tech panel: {tech.shape}")

    print(f"\n{'='*70}")
    print(f"Grid search: positioning vs technical weights at 3m forward horizon")
    print(f"{'='*70}")
    print(f"{'w_pos':<8}{'w_tech':<8}{'IC':>10}{'Spread':>10}{'Bot hit':>10}")
    print("-" * 50)

    results = []
    weights_to_try = [(round(p, 2), round(1-p, 2)) for p in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]]
    for w_pos, w_tech in weights_to_try:
        comp = compute_composite(pos, tech, w_pos, w_tech)
        ic, spread, bot_hit = backtest_ic(comp, closes, horizon_days=63)
        if ic is None:
            continue
        results.append({"w_pos": w_pos, "w_tech": w_tech, "ic": ic, "spread": spread, "bot_hit": bot_hit})
        print(f"{w_pos:<8}{w_tech:<8}{ic:>+10.4f}{spread*100:>+9.2f}%{bot_hit:>10.2%}")

    # Best by lowest (most negative) IC
    best_ic = min(results, key=lambda r: r["ic"])
    print(f"\nBest by IC (most contrarian): w_pos={best_ic['w_pos']}, w_tech={best_ic['w_tech']}")
    print(f"  IC = {best_ic['ic']:+.4f}, decile spread = {best_ic['spread']*100:+.2f}%, bot hit = {best_ic['bot_hit']:.1%}")

    # Best by lowest decile spread
    best_spread = min(results, key=lambda r: r["spread"] if r["spread"] is not None else 0)
    print(f"\nBest by decile spread (most contrarian): w_pos={best_spread['w_pos']}, w_tech={best_spread['w_tech']}")
    print(f"  IC = {best_spread['ic']:+.4f}, decile spread = {best_spread['spread']*100:+.2f}%, bot hit = {best_spread['bot_hit']:.1%}")

    # Best by bot hit
    best_bot = max(results, key=lambda r: r["bot_hit"])
    print(f"\nBest by bot decile hit rate: w_pos={best_bot['w_pos']}, w_tech={best_bot['w_tech']}")
    print(f"  IC = {best_bot['ic']:+.4f}, decile spread = {best_bot['spread']*100:+.2f}%, bot hit = {best_bot['bot_hit']:.1%}")


if __name__ == "__main__":
    main()
