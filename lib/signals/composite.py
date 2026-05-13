"""Composite assembly + flag computation.

Inputs:
  - per_signal_pct_self: dict[signal_name -> DF[date x ticker]] of pct_self
  - per_signal_pct_peer: dict[signal_name -> DF[date x ticker]] of pct_peer
  - signal_to_bucket: dict[signal_name -> bucket_name]
  - bucket_weights: dict[bucket_name -> float]
  - dual_pct_weights: dict (pct_self -> w, pct_peer -> w), default 0.5/0.5

Output:
  composite_panel: DF[date x ticker] of temperature 0..100
  bucket_panels: dict[bucket_name -> DF[date x ticker]] of subscore 0..100
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _dual_pct(pct_self: pd.DataFrame, pct_peer: pd.DataFrame, w_self: float, w_peer: float) -> pd.DataFrame:
    """Blend pct_self and pct_peer. Fall back to whichever is available when
    one is missing (NaN). Common cases:
      - mature signal with cluster peers: both present -> blended
      - signal with no cluster mapping: pct_self only
      - young signal (few days of history): pct_peer only (cross-section works)
    """
    if (pct_self is None or pct_self.empty) and (pct_peer is None or pct_peer.empty):
        return pct_self or pd.DataFrame()
    if pct_self is None or pct_self.empty:
        return pct_peer
    if pct_peer is None or pct_peer.empty:
        return pct_self
    pct_peer = pct_peer.reindex_like(pct_self)
    has_self = pct_self.notna()
    has_peer = pct_peer.notna()
    both = has_self & has_peer
    blended = pct_self * w_self + pct_peer * w_peer
    # Where both present: blended. Where only one: that one. Where neither: NaN.
    return blended.where(both, pct_self.where(has_self, pct_peer))


def assemble_buckets(
    per_signal_pct_self: dict[str, pd.DataFrame],
    per_signal_pct_peer: dict[str, pd.DataFrame],
    signal_to_bucket: dict[str, str],
    dual_pct_weights: dict[str, float],
    signal_weights: dict[str, float] | None = None,
) -> dict[str, pd.DataFrame]:
    """Weighted average of dual-percentile signals within each bucket.

    `signal_weights`: optional dict of {signal_name: weight}. If provided,
    signals are weighted by the given values (typically computed from IC).
    If None, signals are equal-weighted within each bucket.
    """
    w_self = dual_pct_weights.get("pct_self", 0.5)
    w_peer = dual_pct_weights.get("pct_peer", 0.5)
    signal_weights = signal_weights or {}

    bucket_to_signals: dict[str, list[str]] = {}
    for sig, bkt in signal_to_bucket.items():
        bucket_to_signals.setdefault(bkt, []).append(sig)

    bucket_panels: dict[str, pd.DataFrame] = {}
    for bkt, sigs in bucket_to_signals.items():
        # Compute per-signal dual percentile + collect weights
        sig_panels = []
        weights = []
        for s in sigs:
            ps = per_signal_pct_self.get(s)
            if ps is None or ps.empty:
                continue
            pp = per_signal_pct_peer.get(s)
            sig_panels.append(_dual_pct(ps, pp, w_self, w_peer))
            weights.append(signal_weights.get(s, 1.0))
        if not sig_panels:
            continue
        # Weighted average across signals, handling NaN per-cell
        w_arr = pd.Series(weights, index=range(len(sig_panels)))
        stack = pd.concat([p.stack(future_stack=True) for p in sig_panels], axis=1)
        # weighted mean: sum(w_i × x_i where x_i present) / sum(w_i where x_i present)
        present = stack.notna()
        weighted = (stack.fillna(0).values * w_arr.values).sum(axis=1)
        weight_sum = (present.values * w_arr.values).sum(axis=1)
        bucket_score_long = pd.Series(weighted / pd.Series(weight_sum).replace(0, float('nan')).values, index=stack.index)
        bucket_panels[bkt] = bucket_score_long.unstack()
    return bucket_panels


def assemble_composite(
    bucket_panels: dict[str, pd.DataFrame],
    bucket_weights: dict[str, float],
    min_buckets_present: int = 2,
) -> pd.DataFrame:
    """Weighted average of bucket scores. Missing buckets get their weight
    redistributed proportionally. Cells with fewer than `min_buckets_present`
    non-null buckets get NaN — single-bucket "temperatures" are misleading."""
    if not bucket_panels:
        return pd.DataFrame()

    all_dates = sorted(set().union(*[bp.index for bp in bucket_panels.values()]))
    all_tickers = sorted(set().union(*[bp.columns for bp in bucket_panels.values()]))
    aligned = {b: bp.reindex(index=all_dates, columns=all_tickers) for b, bp in bucket_panels.items()}

    weight_sum_panel = pd.DataFrame(0.0, index=all_dates, columns=all_tickers)
    weighted_sum = pd.DataFrame(0.0, index=all_dates, columns=all_tickers)
    bucket_count_panel = pd.DataFrame(0, index=all_dates, columns=all_tickers, dtype=int)
    for b, panel in aligned.items():
        w = bucket_weights.get(b, 0.0)
        if w == 0.0:
            continue
        present = panel.notna()
        weighted_sum = weighted_sum.add(panel.fillna(0) * w, fill_value=0)
        weight_sum_panel = weight_sum_panel.add(present.astype(float) * w, fill_value=0)
        bucket_count_panel = bucket_count_panel.add(present.astype(int), fill_value=0)
    composite = weighted_sum.where(weight_sum_panel > 0) / weight_sum_panel
    # Require at least N buckets present
    composite = composite.where(bucket_count_panel >= min_buckets_present)
    return composite


def compute_conviction(bucket_panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Conviction = 100 − (std-dev of bucket scores at each (date,ticker) × 2).

    Higher conviction = buckets agree (all hot or all cold). Lower = mixed.
    Caps at 0..100. NaN if fewer than 2 buckets present at that cell.
    """
    if not bucket_panels:
        return pd.DataFrame()

    all_dates = sorted(set().union(*[bp.index for bp in bucket_panels.values()]))
    all_tickers = sorted(set().union(*[bp.columns for bp in bucket_panels.values()]))
    stack = pd.concat(
        [bp.reindex(index=all_dates, columns=all_tickers).stack(future_stack=True) for bp in bucket_panels.values()],
        axis=1,
    )
    # std across buckets per (date, ticker)
    std = stack.std(axis=1, ddof=0).unstack()
    # Convert: 0 std → conviction 100; std 50 → conviction 0
    conviction = (100 - std * 2).clip(lower=0, upper=100)
    # Mask cells with <2 buckets present
    nonnull_count = stack.notna().sum(axis=1).unstack()
    return conviction.where(nonnull_count >= 2)


def compute_anomaly(per_signal_pct_peer: dict[str, pd.DataFrame], threshold: float = 90.0) -> pd.DataFrame:
    """Anomaly count: # of signals where ticker is at threshold+ percentile vs
    its cluster peers. High anomaly = stands out from peers across many measures.
    """
    if not per_signal_pct_peer:
        return pd.DataFrame()
    panels = [p for p in per_signal_pct_peer.values() if p is not None and not p.empty]
    if not panels:
        return pd.DataFrame()
    all_dates = sorted(set().union(*[p.index for p in panels]))
    all_tickers = sorted(set().union(*[p.columns for p in panels]))
    count = pd.DataFrame(0, index=all_dates, columns=all_tickers, dtype=int)
    for p in panels:
        aligned = p.reindex(index=all_dates, columns=all_tickers)
        count = count.add((aligned >= threshold).astype(int), fill_value=0)
    return count


def compute_flags(
    composite: pd.DataFrame,
    bucket_panels: dict[str, pd.DataFrame],
    cfg_flags: dict,
) -> dict[str, pd.DataFrame]:
    late_thr = cfg_flags["late_signal_threshold"]
    wash_thr = cfg_flags["washout_threshold"]
    min_tech = cfg_flags["divergence_min_technical"]
    max_opt = cfg_flags["divergence_max_options"]

    pos = bucket_panels.get("positioning")
    val = bucket_panels.get("valuation")
    tech = bucket_panels.get("technical")
    opt = bucket_panels.get("options")

    def _to_int(panel: pd.DataFrame) -> pd.DataFrame:
        return panel.fillna(False).astype(int).where(panel.notna())

    flags = {}
    if pos is not None and tech is not None:
        # Align indexes
        idx = tech.index
        cols = tech.columns
        pos_a = pos.reindex(index=idx, columns=cols)
        late = (pos_a >= late_thr) & (tech >= late_thr)
        wash = (pos_a <= wash_thr) & (tech <= wash_thr)
        # If valuation IS present (overlay), use it as a tiebreaker confirmation
        if val is not None:
            val_a = val.reindex(index=idx, columns=cols)
            late = late & (val_a.isna() | (val_a >= max(0, late_thr - 10)))
            wash = wash & (val_a.isna() | (val_a <= wash_thr + 15))
        flags["flag_late_signal"] = _to_int(late)
        flags["flag_washout"] = _to_int(wash)
    if tech is not None and opt is not None:
        opt_a = opt.reindex(index=tech.index, columns=tech.columns)
        flags["flag_divergence"] = _to_int((tech >= min_tech) & (opt_a <= max_opt))
    return flags
