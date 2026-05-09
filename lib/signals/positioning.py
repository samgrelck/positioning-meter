"""Positioning bucket signals (V1 — without 13F crowding).

V1 signals:
  - insider_net_90d_signed:   trailing 90d net insider $ (signed)
  - insider_net_90d_abs:      |trailing 90d net insider $| (magnitude)
  - short_volume_ratio_14d:   trailing 14-day mean of daily ShortVol/TotVol

The two insider variants are kept side-by-side so the backtest can pick the
one that maps better to "hot" (per QUESTIONS.md and DESIGN.md §3.1).
"""
from __future__ import annotations

import pandas as pd


def insider_signals(insider_rolling_90d: pd.DataFrame, prices_index: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """insider_rolling_90d is calendar-day indexed; reindex to trading days."""
    if insider_rolling_90d.empty:
        empty = pd.DataFrame(index=prices_index)
        return {
            "insider_net_90d_signed": empty,
            "insider_net_90d_abs": empty,
        }
    daily = insider_rolling_90d.reindex(prices_index, method="ffill")
    return {
        "insider_net_90d_signed": daily,
        "insider_net_90d_abs": daily.abs(),
    }


def short_volume_signal(short_volume: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """Rolling mean of daily short-volume ratio."""
    if short_volume.empty:
        return short_volume
    return short_volume.rolling(window, min_periods=max(3, window // 2)).mean()


def compute_all(
    insider_rolling_90d: pd.DataFrame,
    short_volume: pd.DataFrame,
    prices_index: pd.DatetimeIndex,
    hf_panels: dict[str, pd.DataFrame] | None = None,
    si_true: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    out = {}
    out.update(insider_signals(insider_rolling_90d, prices_index))
    sv = short_volume_signal(short_volume)
    if not sv.empty:
        out["short_volume_ratio_14d"] = sv.reindex(prices_index, method="ffill")
    else:
        out["short_volume_ratio_14d"] = pd.DataFrame(index=prices_index)
    if hf_panels:
        for k, panel in hf_panels.items():
            out[k] = panel
    if si_true is not None and not si_true.empty:
        out["si_true_pct_adv"] = si_true.reindex(prices_index, method="ffill")
    return out


def hf_change_signal(hf_count_panel: pd.DataFrame, periods: int = 1) -> pd.DataFrame:
    """Quarter-over-quarter change in HF count (forward-filled). Uses the
    daily forward-filled panel, so 'q-over-q' here means 90-day diff in
    practice. Captures whether crowding is increasing or decreasing.
    """
    if hf_count_panel.empty:
        return hf_count_panel
    days_per_q = 90
    return hf_count_panel - hf_count_panel.shift(days_per_q * periods)


def si_true_pct_adv_panel(si_df: pd.DataFrame, prices_index: pd.DatetimeIndex) -> pd.DataFrame:
    """For each (ticker, settlement_date) compute SI as % of avg daily volume.
    Forward-fill to daily index. Higher = more crowded short side.
    Uses days_to_cover from short_interest_true table directly as the metric.
    """
    if si_df.empty:
        return pd.DataFrame(index=prices_index)
    return si_df.reindex(prices_index, method="ffill")
