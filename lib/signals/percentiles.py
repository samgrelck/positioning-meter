"""Percentile transforms for the dual-percentile scoring.

For each signal value we compute:
  - pct_self: percentile rank within own trailing window (5y slow / 1y fast)
  - pct_peer: percentile rank within cluster peers at same date (cross-section)

Both return 0..100. Higher = "hotter" relative to comparison set.
For signals where high values are NOT "hot" (e.g. pct_from_52w_high which is
always <=0), the percentile transform itself encodes "hot" as "extreme vs
own history" — caller decides interpretation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_percentile_rank(series: pd.Series, window: int) -> pd.Series:
    """Rolling percentile rank (0..100) of latest value within trailing window."""
    def _rank(x):
        if pd.isna(x[-1]):
            return np.nan
        valid = x[~np.isnan(x)]
        if len(valid) < 2:
            return np.nan
        # Rank of last value among the window
        rank = (valid <= x[-1]).sum() / len(valid)
        return rank * 100.0

    return series.rolling(window=window, min_periods=max(20, window // 5)).apply(_rank, raw=True)


def pct_self_panel(values: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Apply rolling percentile rank to each ticker (column) independently."""
    if values.empty:
        return values
    return values.apply(lambda s: rolling_percentile_rank(s, window_days))


def pct_peer_panel(values: pd.DataFrame, ticker_to_cluster: dict[str, str]) -> pd.DataFrame:
    """Cross-sectional percentile rank within cluster peers at each date.

    ticker_to_cluster: dict mapping each column ticker to its cluster id.
    Columns with no cluster mapping get NaN.
    """
    if values.empty:
        return values

    cluster_groups: dict[str, list[str]] = {}
    for t, cid in ticker_to_cluster.items():
        if cid and t in values.columns:
            cluster_groups.setdefault(cid, []).append(t)

    out = pd.DataFrame(np.nan, index=values.index, columns=values.columns, dtype=float)
    for cid, tickers in cluster_groups.items():
        if len(tickers) < 3:
            continue  # too small to rank meaningfully
        sub = values[tickers]
        # Per-row rank, scaled to 0..100 (NaN-safe)
        ranked = sub.rank(axis=1, pct=True, na_option="keep") * 100.0
        out.loc[:, tickers] = ranked
    return out
