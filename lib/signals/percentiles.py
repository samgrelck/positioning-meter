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
        last = x[-1]
        # No dispersion (constant / all-zero window) => percentile is undefined.
        # Return NaN so the signal falls back to pct_peer (or drops from the
        # bucket blend) instead of being spuriously ranked at the top by a tie
        # rule. This is the source of the "raw 0 -> 100th %ile" artifact on
        # sparse signals like insider_buying_90d (~88% of names are 0).
        if valid.max() == valid.min():
            return np.nan
        # Midpoint tie rank: tied values sit at the mean of their positions
        # rather than all being pushed to 100 by a `<=` rule. Matches the
        # 'mean' convention used by scipy.percentileofscore / pandas rank.
        below = (valid < last).sum()
        equal = (valid == last).sum()
        rank = (below + 0.5 * equal) / len(valid)
        return rank * 100.0

    return series.rolling(window=window, min_periods=max(20, window // 5)).apply(_rank, raw=True)


def pct_self_panel(values: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Apply rolling percentile rank to each ticker (column) independently."""
    if values.empty:
        return values
    return values.apply(lambda s: rolling_percentile_rank(s, window_days))


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Rolling z-score (in std-devs) of the latest value vs its trailing window.

    Companion to rolling_percentile_rank: the percentile says *where in the range*
    today sits, the z-score says *how far from typical* in std-devs (so a 95th-%ile
    reading on a near-flat series is correctly seen as a small move, z~0.5, not a
    big one). Window includes today, matching the percentile convention. Returns
    NaN where the trailing window has zero dispersion (constant series)."""
    roll = series.rolling(window=window, min_periods=max(20, window // 5))
    mu = roll.mean()
    sigma = roll.std(ddof=0)
    return (series - mu) / sigma.replace(0, np.nan)


def zscore_self_panel(values: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Apply rolling z-score to each ticker (column) independently."""
    if values.empty:
        return values
    return values.apply(lambda s: rolling_zscore(s, window_days))


def size_neutral_rank(values: pd.DataFrame, size_panel: pd.DataFrame,
                      min_names: int = 40) -> pd.DataFrame:
    """Cross-sectional percentile rank (0..100) with the size effect removed.

    V1.22. A plain universe rank is contaminated for any signal whose
    construction scales with liquidity. Both `si_true_dtc` (short interest /
    ADV) and `float_turnover_20d` (ADV / float) read structurally low for mega
    caps, so ranking them across the whole universe tags the largest names as
    lightly-positioned on size alone: score_positioning was -0.37 rank-correlated
    with log market cap, and 76% of the top market-cap decile fell in the
    "under-owned" tercile vs 14% of the bottom decile.

    Method, per date: rank the signal cross-sectionally, regress that rank on
    log(market cap), then re-rank the residual back to 0..100.
      - Rank space, not raw space: raw values are heavily skewed (insider
        dollars run to -$1.5bn) and an OLS on raw would chase the outliers.
      - Regression, not within-quintile ranking: a name drifting across a
        bucket boundary would flip its dashboard tag day to day.

    Names with a signal value but no market cap keep their plain universe rank.
    Dates with fewer than `min_names` usable observations are left unneutralized.
    """
    universe_rank = values.rank(axis=1, pct=True, na_option="keep") * 100.0
    if size_panel is None or size_panel.empty:
        return universe_rank

    log_mcap = np.log(size_panel.reindex(index=values.index, columns=values.columns))
    log_mcap = log_mcap.replace([np.inf, -np.inf], np.nan)

    out = universe_rank.copy()
    rank_vals = universe_rank.values
    mcap_vals = log_mcap.values
    for i in range(len(values.index)):
        r = rank_vals[i].astype(float)
        m = mcap_vals[i].astype(float)
        ok = np.isfinite(r) & np.isfinite(m)
        if ok.sum() < min_names:
            continue
        X = np.column_stack([np.ones(ok.sum()), m[ok]])
        coef, *_ = np.linalg.lstsq(X, r[ok], rcond=None)
        resid = r[ok] - X @ coef
        # Re-rank the residual so the output stays a 0..100 percentile.
        out.values[i, np.where(ok)[0]] = (
            pd.Series(resid).rank(pct=True).values * 100.0
        )
    return out


def pct_peer_panel(values: pd.DataFrame, ticker_to_cluster: dict[str, str],
                    min_cluster_size: int = 3, blend_universe: float = 0.5,
                    ticker_to_clusters: dict[str, list[str]] | None = None,
                    cluster_members: dict[str, list[str]] | None = None,
                    size_panel: pd.DataFrame | None = None) -> pd.DataFrame:
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
      size_panel: optional (date x ticker) market cap. When given, the universe
        rank is size-neutralized (see size_neutral_rank). Applied to the
        positioning composite signals only — their construction scales with
        liquidity, so the plain rank encodes market cap.
    """
    if values.empty:
        return values

    # Universe rank baseline — every ticker against everyone with a value
    if size_panel is not None and not size_panel.empty:
        universe_rank = size_neutral_rank(values, size_panel)
    else:
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
