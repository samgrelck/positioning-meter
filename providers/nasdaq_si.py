"""NASDAQ short interest API provider.

Endpoint: https://api.nasdaq.com/api/quote/{ticker}/short-interest
Returns ~23 bi-monthly settlement dates (≈ 1 year of history).

Provides TRUE short interest level + days-to-cover. Complements the FINRA
daily Reg SHO short-volume proxy (which has 6.5y history but measures flow,
not level).
"""
from __future__ import annotations

import logging
import subprocess
import time
import json
from datetime import datetime

logger = logging.getLogger(__name__)

_URL = "https://api.nasdaq.com/api/quote/{ticker}/short-interest?assetclass=stocks"
# NASDAQ's API is finicky with python `requests` (HTTP/1.1) — times out
# repeatedly. curl works reliably with HTTP/2. We shell out for robustness.
_CURL_HEADERS = [
    "-H", "User-Agent: Mozilla/5.0",
    "-H", "Accept: application/json, text/plain, */*",
    "-H", "Origin: https://www.nasdaq.com",
    "-H", "Referer: https://www.nasdaq.com/",
]


def _parse_int(s: str | None) -> int | None:
    if not s or s in ("N/A", "--", ""):
        return None
    try:
        return int(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _parse_date(s: str) -> str | None:
    """'04/15/2026' -> '2026-04-15'"""
    try:
        return datetime.strptime(s, "%m/%d/%Y").date().isoformat()
    except (ValueError, TypeError):
        return None


class NasdaqShortInterestProvider:
    def __init__(self, rate_limit_sleep: float = 0.5):
        self._sleep = rate_limit_sleep

    def fetch(self, ticker: str) -> list[dict]:
        url = _URL.format(ticker=ticker)
        data = None
        for attempt in range(3):
            try:
                proc = subprocess.run(
                    ["curl", "-s", "--max-time", "30", url, *_CURL_HEADERS],
                    capture_output=True, text=True, timeout=40,
                )
                if proc.returncode != 0 or not proc.stdout:
                    logger.warning(f"NASDAQ SI {ticker} attempt {attempt+1}: curl rc={proc.returncode}")
                    time.sleep(2 ** attempt)
                    continue
                data = json.loads(proc.stdout)
                break
            except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
                logger.warning(f"NASDAQ SI {ticker} attempt {attempt+1}: {e}")
                time.sleep(2 ** attempt)
        time.sleep(self._sleep)
        if data is None:
            return []

        rows = []
        try:
            table_rows = data["data"]["shortInterestTable"]["rows"]
        except (KeyError, TypeError):
            return []

        for r in table_rows:
            d = _parse_date(r.get("settlementDate", ""))
            if not d:
                continue
            si = _parse_int(r.get("interest"))
            adv = _parse_int(r.get("avgDailyShareVolume"))
            dtc = r.get("daysToCover")
            try:
                dtc_f = float(dtc) if dtc is not None else None
            except (ValueError, TypeError):
                dtc_f = None
            rows.append({
                "ticker": ticker,
                "settlement_date": d,
                "short_interest": si,
                "avg_daily_share_volume": adv,
                "days_to_cover": dtc_f,
            })
        return rows
