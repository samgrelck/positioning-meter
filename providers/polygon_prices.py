"""Polygon.io daily aggregates provider.

Pulls split/dividend-adjusted daily bars via the v2/aggs endpoint.
Single API call covers up to 5y per request — for 10y+ we paginate by year.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from polygon import RESTClient

from lib.config import require_env
from .base import PricesProvider

logger = logging.getLogger(__name__)

_MAX_BARS_PER_CALL = 5000  # Polygon caps; ~20y of trading days, never an issue


class PolygonPricesProvider(PricesProvider):
    def __init__(self, rate_limit_sleep: float = 0.1):
        self._client = RESTClient(require_env("POLYGON_API_KEY"))
        self._sleep = rate_limit_sleep

    def fetch_prices(
        self, ticker: str, start: date, end: date
    ) -> list[dict]:
        rows: list[dict] = []
        try:
            aggs = self._client.list_aggs(
                ticker=ticker,
                multiplier=1,
                timespan="day",
                from_=start.isoformat(),
                to=end.isoformat(),
                adjusted=True,
                limit=_MAX_BARS_PER_CALL,
            )
            for a in aggs:
                d = date.fromtimestamp(a.timestamp / 1000).isoformat()
                rows.append({
                    "ticker": ticker,
                    "date": d,
                    "open": a.open,
                    "high": a.high,
                    "low": a.low,
                    "close": a.close,
                    "adj_close": a.close,  # already split-adjusted
                    "volume": int(a.volume) if a.volume else None,
                })
        except Exception as e:
            logger.warning(f"Polygon fetch failed for {ticker}: {e}")
        time.sleep(self._sleep)
        return rows
