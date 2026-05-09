"""Valuation bucket signals — TTM P/E and EV/Sales, point-in-time aware.

We use Polygon's TTM rows (fiscal_period='TTM') for trailing ratios. For each
business day we look up the most recent TTM row whose `filing_date_est` is
<= that day — no peek-ahead.

Returns wide DataFrames (date x ticker) of raw ratio values.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _build_ttm_panel(fundamentals: pd.DataFrame) -> pd.DataFrame:
    """Construct historical TTM by summing trailing 4 quarterly reports per ticker.

    Polygon's `fiscal_period='TTM'` only contains a current snapshot. For backtest
    we must roll our own TTM from Q1/Q2/Q3/Q4 reports. Each TTM row inherits the
    filing_date of the most recent of the four constituent quarters.
    """
    q = fundamentals[fundamentals["fiscal_period"].isin(["Q1", "Q2", "Q3", "Q4"])].copy()
    q = q.dropna(subset=["filing_date_est"])
    q = q.sort_values(["ticker", "period_end"]).reset_index(drop=True)

    rows = []
    for ticker, grp in q.groupby("ticker"):
        if len(grp) < 4:
            continue
        eps = grp["diluted_eps_q"].astype(float)
        rev = grp["total_revenue_q"].astype(float)
        ttm_eps = eps.rolling(4, min_periods=4).sum()
        ttm_rev = rev.rolling(4, min_periods=4).sum()
        for i in range(3, len(grp)):
            row = grp.iloc[i]
            rows.append({
                "ticker": ticker,
                "period_end": row["period_end"],
                "filing_date_est": row["filing_date_est"],
                "ttm_eps": float(ttm_eps.iloc[i]) if pd.notna(ttm_eps.iloc[i]) else None,
                "ttm_revenue": float(ttm_rev.iloc[i]) if pd.notna(ttm_rev.iloc[i]) else None,
                "total_debt": row["total_debt"],
                "cash_and_short_term": row["cash_and_short_term"],
                "shares_out": row["shares_out"],
            })
    return pd.DataFrame(rows)


def _asof_join(prices: pd.DataFrame, fundamentals_ttm: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """For one ticker, return a DataFrame indexed by trading date with the most
    recent fundamentals row whose filing_date_est <= that date."""
    if ticker not in prices.columns:
        return pd.DataFrame()
    px = prices[ticker].dropna().to_frame("price").reset_index()
    px = px.rename(columns={"date": "trade_date"})

    f = fundamentals_ttm[fundamentals_ttm["ticker"] == ticker].copy()
    f = f.dropna(subset=["filing_date_est"])
    if f.empty:
        return pd.DataFrame()
    f = f.sort_values("filing_date_est")
    px = px.sort_values("trade_date")
    merged = pd.merge_asof(
        px, f, left_on="trade_date", right_on="filing_date_est",
        direction="backward",
    )
    return merged


def compute_all(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Return wide DataFrames for ttm_pe and ev_sales."""
    ttm = _build_ttm_panel(fundamentals)
    if ttm.empty:
        empty = pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
        return {"ttm_pe": empty, "ev_sales": empty}

    pe_dict = {}
    evs_dict = {}
    for ticker in prices.columns:
        merged = _asof_join(prices, ttm, ticker)
        if merged.empty:
            continue
        merged = merged.set_index("trade_date")
        # Numeric coercion — Polygon returns clean floats but be defensive
        eps = pd.to_numeric(merged["ttm_eps"], errors="coerce")
        rev = pd.to_numeric(merged["ttm_revenue"], errors="coerce")
        debt = pd.to_numeric(merged["total_debt"], errors="coerce").fillna(0)
        cash = pd.to_numeric(merged["cash_and_short_term"], errors="coerce").fillna(0)
        shares = pd.to_numeric(merged["shares_out"], errors="coerce")

        pe = merged["price"] / eps.replace(0, np.nan)
        # mask negative EPS (NM)
        pe = pe.where(eps > 0)

        market_cap = merged["price"] * shares
        ev = market_cap + debt - cash
        evs = ev / rev.replace(0, np.nan)
        evs = evs.where(rev > 0)

        pe_dict[ticker] = pe
        evs_dict[ticker] = evs

    return {
        "ttm_pe": pd.DataFrame(pe_dict).reindex(prices.index),
        "ev_sales": pd.DataFrame(evs_dict).reindex(prices.index),
    }
