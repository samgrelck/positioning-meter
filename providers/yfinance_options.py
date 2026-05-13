"""yfinance options chain provider — current snapshot only.

Free. Used for:
  - Daily forward-only accumulation of options signals
  - Validation / sanity-check of the math while we build the pipeline
  - Fallback / overlay when Polygon historical not subscribed

Does NOT have historical chains. Each call returns today's snapshot.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime

import pandas as pd
import yfinance as yf

from lib.signals.options_compute import compute_chain_signals

logger = logging.getLogger(__name__)


def fetch_chain_snapshot(ticker: str, sleep: float = 0.3, max_expirations: int = 8) -> dict | None:
    """Return today's chain organized by expiration date + spot price.

    Returns dict:
      {
        "ticker": str,
        "asof": "YYYY-MM-DD",
        "spot": float,
        "chains_by_expiry": {datetime: {"calls": DF, "puts": DF}},
      }
    Or None if data unavailable.
    """
    try:
        t = yf.Ticker(ticker)
        expirations = t.options
    except Exception as e:
        logger.warning(f"yfinance options expirations failed for {ticker}: {e}")
        time.sleep(sleep)
        return None
    finally:
        time.sleep(sleep)

    if not expirations:
        return None

    try:
        fast = t.fast_info
        spot = float(fast.last_price)
    except Exception:
        try:
            spot = float(t.info.get("regularMarketPrice") or 0)
        except Exception:
            spot = None

    if not spot or spot <= 0:
        return None

    chains = {}
    # Limit to first N expirations to keep API calls bounded
    for exp_str in expirations[:max_expirations]:
        try:
            chain = t.option_chain(exp_str)
            exp_dt = datetime.fromisoformat(exp_str)
            chains[exp_dt] = {
                "calls": chain.calls,
                "puts": chain.puts,
            }
        except Exception as e:
            logger.debug(f"yfinance chain {ticker}@{exp_str} failed: {e}")
            continue
        time.sleep(sleep)

    if not chains:
        return None

    return {
        "ticker": ticker,
        "asof": date.today().isoformat(),
        "spot": spot,
        "chains_by_expiry": chains,
    }


def compute_signals_today(ticker: str, sleep: float = 0.3) -> dict | None:
    """Fetch chain + compute IV30/skew/term slope/PC in one call.

    Returns a dict shaped like options_daily row, or None.
    """
    snap = fetch_chain_snapshot(ticker, sleep=sleep)
    if snap is None:
        return None
    signals = compute_chain_signals(snap["chains_by_expiry"], snap["spot"], asof=date.today())
    return {
        "ticker": ticker,
        "date": snap["asof"],
        **signals,
        # 20d avg vol not derivable from single snapshot — filled at signal-compute time
        "avg_options_volume_20d": None,
    }
