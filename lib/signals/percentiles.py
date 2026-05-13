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


def pct_peer_panel(values: pd.DataFrame, ticker_to_cluster: dict[str, str],
                    min_cluster_size: int = 3) -> pd.DataFrame:
    """Cross-sectional percentile rank within cluster peers at each date.

    For tickers in clusters with fewer than `min_cluster_size` members
    (including orphans with no cluster mapping), falls back to ranking
    against the FULL universe present at that date. This ensures every
    ticker with a raw value gets a peer percentile.
    """
    if values.empty:
        return values

    cluster_groups: dict[str, list[str]] = {}
    for t, cid in ticker_to_cluster.items():
        if cid and t in values.columns:
            cluster_groups.setdefault(cid, []).append(t)

    out = pd.DataFrame(np.nan, index=values.index, columns=values.columns, dtype=float)

    # Track which tickers got a cluster-based rank
    cluster_ranked = set()
    for cid, tickers in cluster_groups.items():
        if len(tickers) < min_cluster_size:
            continue
        sub = values[tickers]
        ranked = sub.rank(axis=1, pct=True, na_option="keep") * 100.0
        out.loc[:, tickers] = ranked
        cluster_ranked.update(tickers)

    # Fallback: rank everyone NOT yet ranked against the full universe panel
    fallback_tickers = [c for c in values.columns if c not in cluster_ranked]
    if fallback_tickers:
        # Rank within full panel — gives each fallback ticker its rank vs all
        # other names with a value on that date
        full_rank = values.rank(axis=1, pct=True, na_option="keep") * 100.0
        out.loc[:, fallback_tickers] = full_rank.loc[:, fallback_tickers]

    return out
