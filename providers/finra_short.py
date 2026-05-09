"""FINRA Reg SHO daily short sale volume provider.

Endpoint: https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt
Format:   Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market

This is daily SHORT VOLUME (flow), not biweekly SHORT INTEREST (level).
We use it as a backtestable positioning proxy. See QUESTIONS.md.

Stored in `short_interest` table for schema convenience — `short_interest`
column holds the day's short-volume-share-of-total (a ratio scaled to 1e6
to fit INTEGER), and `pct_float` holds the rolling 14d ratio (recomputed
at signal time).
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from io import StringIO

import requests

from .base import ShortInterestProvider

logger = logging.getLogger(__name__)

_BASE = "https://cdn.finra.org/equity/regsho/daily"


class FinraShortVolumeProvider(ShortInterestProvider):
    def __init__(self, rate_limit_sleep: float = 0.2):
        self._sleep = rate_limit_sleep
        self._session = requests.Session()

    def _url(self, d: date) -> str:
        return f"{_BASE}/CNMSshvol{d.strftime('%Y%m%d')}.txt"

    def fetch_settlement(self, settlement_date: date) -> list[dict]:
        """Fetch one day's file. Returns rows for *all* tickers in the file —
        caller is responsible for filtering to universe.

        Returns [] for weekends, holidays, missing files (HTTP 403/404).
        """
        url = self._url(settlement_date)
        try:
            r = self._session.get(url, timeout=30)
            if r.status_code != 200:
                logger.debug(f"FINRA {settlement_date}: HTTP {r.status_code}")
                return []
        except Exception as e:
            logger.warning(f"FINRA fetch failed for {settlement_date}: {e}")
            return []
        finally:
            time.sleep(self._sleep)

        rows = []
        text = r.text
        for line in text.splitlines()[1:]:  # skip header
            parts = line.split("|")
            if len(parts) < 5:
                continue
            try:
                short_vol = float(parts[2])
                total_vol = float(parts[4])
            except ValueError:
                continue
            if total_vol <= 0:
                continue
            ratio = short_vol / total_vol  # 0..1
            rows.append({
                "ticker": parts[1],
                "settlement_date": settlement_date.isoformat(),
                # Schema reuse: store ratio as int micro-units (0-1_000_000)
                "short_interest": int(round(ratio * 1_000_000)),
                "avg_daily_volume": int(total_vol),
                "days_to_cover": None,  # not meaningful daily
                "pct_float": None,      # filled at signal-compute time
            })
        return rows
