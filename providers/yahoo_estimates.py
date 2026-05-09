"""Yahoo Finance estimates + analyst actions provider (forward-only).

Daily snapshot of consensus EPS, target prices, recommendation distribution,
and recent analyst rating actions. No historical depth — we accumulate
forward from today.
"""
from __future__ import annotations

import logging
import time
from datetime import date

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_estimates_snapshot(ticker: str, sleep: float = 0.4) -> dict | None:
    """Return one row of consensus / target / rating snapshot data, or None."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
    except Exception as e:
        logger.warning(f"yfinance estimates fetch failed for {ticker}: {e}")
        time.sleep(sleep)
        return None
    finally:
        time.sleep(sleep)

    if not info:
        return None

    target_mean = info.get("targetMeanPrice")
    target_high = info.get("targetHighPrice")
    target_low = info.get("targetLowPrice")
    target_disp = None
    if target_mean and target_high and target_low and target_mean > 0:
        target_disp = (target_high - target_low) / target_mean

    return {
        "ticker": ticker,
        "date": date.today().isoformat(),
        "forward_eps": _f(info.get("forwardEps")),
        "trailing_eps": _f(info.get("trailingEps")),
        "target_mean_price": _f(target_mean),
        "target_high_price": _f(target_high),
        "target_low_price": _f(target_low),
        "target_dispersion": _f(target_disp),
        "num_analyst_opinions": _i(info.get("numberOfAnalystOpinions")),
        "recommendation_key": info.get("recommendationKey"),
        "recommendation_mean": _f(info.get("recommendationMean")),
    }


def fetch_analyst_actions(ticker: str, sleep: float = 0.4) -> list[dict]:
    """Return rating change actions over yfinance's rolling window (~12 mo)."""
    try:
        t = yf.Ticker(ticker)
        df = t.upgrades_downgrades
    except Exception as e:
        logger.warning(f"yfinance actions fetch failed for {ticker}: {e}")
        time.sleep(sleep)
        return []
    finally:
        time.sleep(sleep)

    if df is None or df.empty:
        return []

    rows = []
    for idx, r in df.iterrows():
        try:
            d = pd.Timestamp(idx).date().isoformat()
        except (ValueError, TypeError):
            continue
        rows.append({
            "ticker": ticker,
            "action_date": d,
            "firm": r.get("Firm") or "",
            "from_grade": r.get("FromGrade") or "",
            "to_grade": r.get("ToGrade") or "",
            "action": r.get("Action") or "",
        })
    return rows


def fetch_earnings_date(ticker: str, sleep: float = 0.4) -> str | None:
    """Return next earnings date as ISO string, or None."""
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
    except Exception as e:
        logger.warning(f"yfinance earnings date fetch failed for {ticker}: {e}")
        time.sleep(sleep)
        return None
    finally:
        time.sleep(sleep)

    if cal is None:
        return None
    if isinstance(cal, dict):
        d = cal.get("Earnings Date")
        if isinstance(d, list) and d:
            d = d[0]
        if d:
            try:
                return pd.Timestamp(d).date().isoformat()
            except (ValueError, TypeError):
                return None
    return None


def _f(v):
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
