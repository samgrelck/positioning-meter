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
                    min_cluster_size: int = 3, blend_universe: float = 0.5,
                    ticker_to_clusters: dict[str, list[str]] | None = None,
                    cluster_members: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """Cross-sectional percentile rank — blend of cluster-rank + universe-rank.

    Two-stage methodology:
      1. Cluster rank: each ticker ranked vs the UNION of members across all
         clusters it belongs to (so AMD ranks vs CPU+GPU+AI-semi peers, not
         just one). If a ticker's peer set is < min_cluster_size, only the
         universe rank applies for that ticker.
      2. Universe rank: each ticker ranked vs the full panel.

    Final pct_peer = (1-blend_universe) × cluster_rank + blend_universe × universe_rank.

    blend_universe controls the mix. 0.0 = cluster only, 1.0 = universe only,
    0.5 = balanced. Universe rank provides statistical stability; cluster
    rank provides peer-specificity. Tunable per design choice.

    Falls back to universe rank only when cluster peer set is too small.

    Args (backward compatible):
      ticker_to_cluster: legacy single-cluster mapping (still accepted)
      ticker_to_clusters: optional multi-cluster mapping (preferred)
      cluster_members: optional dict cluster_id -> list of members
    """
    if values.empty:
        return values

    # Universe rank baseline — every ticker against everyone with a value
    universe_rank = values.rank(axis=1, pct=True, na_option="keep") * 100.0

    # Build per-ticker peer set
    if ticker_to_clusters is None:
        # Derive from single-cluster mapping (each ticker has 1 cluster)
        ticker_to_clusters = {t: [c] for t, c in ticker_to_cluster.items() if c}
    if cluster_members is None:
        # Derive from single-cluster mapping: each cluster's members
        cluster_members = {}
        for t, c in ticker_to_cluster.items():
            if c:
                cluster_members.setdefault(c, []).append(t)

    # Build cluster rank by union-of-clusters peer set
    cluster_rank = pd.DataFrame(np.nan, index=values.index, columns=values.columns, dtype=float)
    # Group tickers by their peer-set fingerprint to avoid redundant compute
    peer_sets: dict[frozenset, list[str]] = {}
    for ticker in values.columns:
        cids = ticker_to_clusters.get(ticker, [])
        peers: set = set()
        for cid in cids:
            peers.update(cluster_members.get(cid, []))
        if len(peers) < min_cluster_size:
            continue  # Will only get universe rank
        peer_sets.setdefault(frozenset(peers), []).append(ticker)

    for peer_set_frozen, tickers in peer_sets.items():
        peer_cols = [t for t in peer_set_frozen if t in values.columns]
        if len(peer_cols) < min_cluster_size:
            continue
        sub = values[peer_cols]
        ranked = sub.rank(axis=1, pct=True, na_option="keep") * 100.0
        for t in tickers:
            if t in ranked.columns:
                cluster_rank[t] = ranked[t]

    # Blend cluster + universe, falling back to universe only when cluster absent
    has_cluster = cluster_rank.notna()
    blended = (1 - blend_universe) * cluster_rank + blend_universe * universe_rank
    return blended.where(has_cluster, universe_rank)
