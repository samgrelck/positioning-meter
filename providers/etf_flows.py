"""ETF AUM / flows provider (forward-only).

For each ETF in config, snapshot:
  - shares_outstanding (yfinance fast_info or info)
  - NAV (close price approximation)
  - AUM (totalAssets if available, else shares_out × close)
  - daily flow estimate = Δ(shares_outstanding) × NAV — only meaningful day-2+

Forward-only history: we accumulate daily snapshots starting today.
"""
from __future__ import annotations

import logging
import time
from datetime import date

import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_aum_snapshot(etf_ticker: str, sleep: float = 0.4) -> dict | None:
    try:
        t = yf.Ticker(etf_ticker)
        info = t.info
        fast = t.fast_info
    except Exception as e:
        logger.warning(f"yfinance ETF fetch failed for {etf_ticker}: {e}")
        time.sleep(sleep)
        return None
    finally:
        time.sleep(sleep)

    if not info:
        return None

    aum = info.get("totalAssets")
    nav = None
    try:
        nav = float(fast.last_price) if fast.last_price else None
    except (AttributeError, TypeError):
        pass
    if nav is None:
        nav = info.get("regularMarketPrice")

    shares_out = None
    try:
        shares_out = float(fast.shares) if fast.shares else None
    except (AttributeError, TypeError):
        pass
    if shares_out is None and aum and nav:
        shares_out = aum / nav

    if not aum and shares_out and nav:
        aum = shares_out * nav

    return {
        "etf_ticker": etf_ticker,
        "date": date.today().isoformat(),
        "shares_outstanding": shares_out,
        "nav": nav,
        "aum_usd": aum,
        "daily_flow_estimate": None,  # filled by post-processing using prior day
    }
