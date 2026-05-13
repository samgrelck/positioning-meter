"""Options math: compute IV30, 25-delta skew, term structure slope, P/C
ratios from a chain snapshot.

Provider-agnostic. Takes pandas DataFrames of calls/puts and a spot price,
returns the computed signals. Used by both yfinance (snapshot) and Polygon
(historical) ingestion paths.

Chain DataFrame schema expected:
  - strike (float)
  - impliedVolatility (float, 0..N where 1.0 = 100% IV)
  - volume (int, optional)
  - openInterest (int, optional)
  - delta (float, optional — Black-Scholes delta. If absent we approximate.)
  - expiration (datetime, optional — if not on DF, passed separately)
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm


def _bs_delta_approx(spot: float, strike: float, iv: float, t_years: float, is_call: bool) -> float:
    """Black-Scholes delta. Assumes r=0, q=0 (close enough for our purposes)."""
    if iv <= 0 or t_years <= 0 or spot <= 0 or strike <= 0:
        return float("nan")
    d1 = (math.log(spot / strike) + (iv ** 2 / 2) * t_years) / (iv * math.sqrt(t_years))
    if is_call:
        return norm.cdf(d1)
    return norm.cdf(d1) - 1.0


def _days_to_expiry(exp: datetime | date | str, asof: datetime | date | None = None) -> int:
    """Return days from asof to exp."""
    asof = asof or date.today()
    if isinstance(asof, datetime):
        asof = asof.date()
    if isinstance(exp, datetime):
        exp = exp.date()
    elif isinstance(exp, str):
        exp = datetime.fromisoformat(exp).date()
    return (exp - asof).days


def atm_iv(chain: pd.DataFrame, spot: float) -> float | None:
    """Average call/put IV at the two strikes nearest spot."""
    if chain is None or chain.empty or "strike" not in chain.columns or "impliedVolatility" not in chain.columns:
        return None
    df = chain.dropna(subset=["strike", "impliedVolatility"]).copy()
    df = df[df["impliedVolatility"] > 0]
    if df.empty:
        return None
    df["dist"] = (df["strike"] - spot).abs()
    nearest = df.nsmallest(4, "dist")
    if nearest.empty:
        return None
    # Weight by inverse distance
    w = 1.0 / (nearest["dist"] + 0.01)
    return float(np.average(nearest["impliedVolatility"], weights=w))


def iv_at_target_delta(chain: pd.DataFrame, spot: float, days: int,
                        target_delta: float, is_call: bool) -> float | None:
    """Find the strike whose Black-Scholes delta is closest to target_delta,
    return its implied volatility.

    target_delta should be positive for calls (e.g. 0.25) and the function
    will use negative target for puts internally.
    """
    if chain is None or chain.empty:
        return None
    df = chain.dropna(subset=["strike", "impliedVolatility"]).copy()
    df = df[df["impliedVolatility"] > 0]
    if df.empty:
        return None
    t_years = max(days, 1) / 365.0
    target = target_delta if is_call else -target_delta
    df["_delta"] = df.apply(
        lambda r: _bs_delta_approx(spot, r["strike"], r["impliedVolatility"], t_years, is_call),
        axis=1,
    )
    df = df.dropna(subset=["_delta"])
    if df.empty:
        return None
    df["dist"] = (df["_delta"] - target).abs()
    nearest = df.nsmallest(1, "dist").iloc[0]
    return float(nearest["impliedVolatility"])


def skew_25d(calls: pd.DataFrame, puts: pd.DataFrame, spot: float, days: int) -> float | None:
    """25-delta risk reversal: IV(25Δ put) − IV(25Δ call).

    Positive skew = puts more expensive than calls = fear/downside hedge demand.
    """
    iv_put = iv_at_target_delta(puts, spot, days, 0.25, is_call=False)
    iv_call = iv_at_target_delta(calls, spot, days, 0.25, is_call=True)
    if iv_put is None or iv_call is None:
        return None
    return iv_put - iv_call


def total_pc_volume_ratio(calls: pd.DataFrame, puts: pd.DataFrame) -> float | None:
    """Total put volume / total call volume across all strikes/expirations."""
    if calls is None or puts is None:
        return None
    cv = calls["volume"].fillna(0).sum() if "volume" in calls.columns else 0
    pv = puts["volume"].fillna(0).sum() if "volume" in puts.columns else 0
    if cv <= 0:
        return None
    return float(pv / cv)


def total_pc_oi_ratio(calls: pd.DataFrame, puts: pd.DataFrame) -> float | None:
    """Total put OI / total call OI."""
    if calls is None or puts is None:
        return None
    co = calls["openInterest"].fillna(0).sum() if "openInterest" in calls.columns else 0
    po = puts["openInterest"].fillna(0).sum() if "openInterest" in puts.columns else 0
    if co <= 0:
        return None
    return float(po / co)


def compute_chain_signals(
    chains_by_expiry: dict[datetime, dict],
    spot: float,
    asof: date | None = None,
) -> dict:
    """Top-level driver: takes a dict of {expiration_date: {'calls': df, 'puts': df}},
    returns the full computed signal set for one (ticker, date).

    Returned dict has keys:
      iv_30d, iv_3m, iv_term_slope, skew_25d, pc_volume_ratio, pc_oi_ratio,
      options_volume
    Values are None when uncomputable (e.g. insufficient chain depth).
    """
    asof = asof or date.today()
    out = {
        "iv_30d": None, "iv_3m": None, "iv_term_slope": None,
        "skew_25d": None, "pc_volume_ratio": None, "pc_oi_ratio": None,
        "options_volume": None,
    }
    if not chains_by_expiry or spot is None or spot <= 0:
        return out

    # Find the expirations closest to 30d and 90d
    exp_to_days = {exp: _days_to_expiry(exp, asof) for exp in chains_by_expiry.keys()}
    exp_to_days = {e: d for e, d in exp_to_days.items() if d > 0}
    if not exp_to_days:
        return out

    def closest_to(target):
        return min(exp_to_days.items(), key=lambda kv: abs(kv[1] - target))

    front_exp, front_days = closest_to(30)
    three_m_exp, three_m_days = closest_to(90)

    front_chain = chains_by_expiry[front_exp]
    three_m_chain = chains_by_expiry[three_m_exp]

    # ATM IV at front and 3m
    front_calls = front_chain.get("calls", pd.DataFrame())
    front_puts = front_chain.get("puts", pd.DataFrame())
    if not front_calls.empty:
        out["iv_30d"] = atm_iv(pd.concat([front_calls, front_puts], ignore_index=True), spot)

    three_calls = three_m_chain.get("calls", pd.DataFrame())
    three_puts = three_m_chain.get("puts", pd.DataFrame())
    if not three_calls.empty:
        out["iv_3m"] = atm_iv(pd.concat([three_calls, three_puts], ignore_index=True), spot)

    if out["iv_30d"] is not None and out["iv_3m"] is not None:
        out["iv_term_slope"] = out["iv_30d"] - out["iv_3m"]

    # 25-delta skew at front expiration
    out["skew_25d"] = skew_25d(front_calls, front_puts, spot, front_days)

    # P/C across ALL expirations (aggregate volume + OI)
    all_calls = pd.concat(
        [chains_by_expiry[e].get("calls", pd.DataFrame()) for e in chains_by_expiry],
        ignore_index=True,
    )
    all_puts = pd.concat(
        [chains_by_expiry[e].get("puts", pd.DataFrame()) for e in chains_by_expiry],
        ignore_index=True,
    )
    out["pc_volume_ratio"] = total_pc_volume_ratio(all_calls, all_puts)
    out["pc_oi_ratio"] = total_pc_oi_ratio(all_calls, all_puts)

    # Total options volume across everything
    total_vol = 0
    if "volume" in all_calls.columns:
        total_vol += int(all_calls["volume"].fillna(0).sum())
    if "volume" in all_puts.columns:
        total_vol += int(all_puts["volume"].fillna(0).sum())
    out["options_volume"] = total_vol if total_vol > 0 else None

    return out
