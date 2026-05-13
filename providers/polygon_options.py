"""Polygon.io options provider.

Requires Polygon Options Starter+ subscription. Will fail with a clear
error message until subscription is active.

Endpoints used:
  - v3/snapshot/options/{underlying} — current chain w/ Greeks + IV (live use)
  - v3/reference/options/contracts — list contracts as-of historical date
  - v2/aggs/ticker/O:{contract}/range/1/day/{from}/{to} — per-contract daily aggs
  - v3/snapshot/options/{underlying}/{contract} — per-contract snapshot w/ IV
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from lib.config import require_env
from lib.signals.options_compute import compute_chain_signals

logger = logging.getLogger(__name__)


BASE_URL = "https://api.polygon.io"


class PolygonOptionsProvider:
    """Subscription-gated options provider. Tries each endpoint and surfaces
    a clear error message if the user is on a tier that doesn't include it.
    """

    def __init__(self, rate_limit_sleep: float = 0.1):
        self._key = require_env("POLYGON_API_KEY")
        self._sleep = rate_limit_sleep
        self._session = requests.Session()

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        params = (params or {}).copy()
        params["apiKey"] = self._key
        try:
            r = self._session.get(f"{BASE_URL}{path}", params=params, timeout=30)
            if r.status_code == 403:
                logger.warning(
                    f"Polygon 403 for {path}: subscription tier doesn't include this endpoint. "
                    f"Upgrade to Options Starter or Advanced."
                )
                return None
            if r.status_code != 200:
                logger.warning(f"Polygon {path}: HTTP {r.status_code} — {r.text[:200]}")
                return None
            return r.json()
        except Exception as e:
            logger.warning(f"Polygon {path} request failed: {e}")
            return None
        finally:
            time.sleep(self._sleep)

    # === Live (snapshot) ===
    def fetch_chain_snapshot(self, underlying: str) -> dict | None:
        """Current full chain w/ Greeks + IV. Used for daily refresh after
        subscription is active.

        Returns dict shaped like the yfinance provider's output.
        """
        data = self._get(f"/v3/snapshot/options/{underlying}", params={"limit": 250})
        if data is None or "results" not in data:
            return None
        results = data["results"]
        if not results:
            return None

        spot = None
        chains_by_expiry: dict[datetime, dict] = {}

        for c in results:
            details = c.get("details", {})
            greeks = c.get("greeks", {})
            ua = c.get("underlying_asset", {})
            if spot is None and ua.get("price"):
                spot = float(ua["price"])
            try:
                exp = datetime.fromisoformat(details["expiration_date"])
            except (KeyError, ValueError):
                continue
            strike = details.get("strike_price")
            contract_type = details.get("contract_type")  # 'call' or 'put'
            iv = c.get("implied_volatility")
            day = c.get("day", {})
            vol = day.get("volume")
            oi = c.get("open_interest")
            if iv is None or strike is None:
                continue
            row = {
                "strike": strike,
                "impliedVolatility": iv,
                "volume": vol,
                "openInterest": oi,
                "delta": greeks.get("delta"),
            }
            bucket = chains_by_expiry.setdefault(exp, {"calls": [], "puts": []})
            if contract_type == "call":
                bucket["calls"].append(row)
            elif contract_type == "put":
                bucket["puts"].append(row)

        if not chains_by_expiry or spot is None:
            return None

        # Lists -> DataFrames
        for exp in list(chains_by_expiry.keys()):
            chains_by_expiry[exp]["calls"] = pd.DataFrame(chains_by_expiry[exp]["calls"])
            chains_by_expiry[exp]["puts"] = pd.DataFrame(chains_by_expiry[exp]["puts"])

        return {
            "ticker": underlying,
            "asof": date.today().isoformat(),
            "spot": spot,
            "chains_by_expiry": chains_by_expiry,
        }

    # === Historical ===
    def list_contracts_as_of(self, underlying: str, asof: date, limit: int = 1000) -> list[dict]:
        """List options contracts that existed (had aggs activity) as of a date.
        Returns contract metadata with expiration, strike, type.
        """
        all_contracts = []
        params = {
            "underlying_ticker": underlying,
            "as_of": asof.isoformat(),
            "limit": 250,
            "expired": "true",
        }
        url = "/v3/reference/options/contracts"
        while url and len(all_contracts) < limit:
            data = self._get(url, params=params if url == "/v3/reference/options/contracts" else None)
            if data is None:
                break
            for r in data.get("results", []):
                all_contracts.append(r)
            next_url = data.get("next_url")
            if not next_url:
                break
            # next_url is full URL — strip base
            url = next_url.replace(BASE_URL, "")
            params = None  # already encoded in next_url
        return all_contracts

    def fetch_contract_aggs(
        self, contract_ticker: str, start: date, end: date
    ) -> list[dict]:
        """Daily OHLCV for one contract over date range.
        contract_ticker like 'O:AAPL230120C00150000'.
        """
        path = f"/v2/aggs/ticker/{contract_ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}"
        data = self._get(path, params={"adjusted": "true", "limit": 5000})
        if data is None:
            return []
        return data.get("results", []) or []

    def fetch_historical_iv(self, underlying: str, asof: date) -> dict | None:
        """Reconstruct chain at asof from contracts list + per-contract aggs.

        This is the heavy path used for backfill. For each asof:
          1. List contracts that were active
          2. For each contract, fetch the day's aggregate (OHLCV)
          3. Polygon doesn't include IV in aggs — would need separate snapshot

        Returns the same shape as fetch_chain_snapshot but for asof.

        NOTE: this is expensive (many API calls per date). For the historical
        backfill we use a more efficient batched approach in setup/16.
        """
        # Single-date implementation is here for completeness. Backfill script
        # uses bulk endpoints where available.
        raise NotImplementedError(
            "Use setup/16_ingest_options_polygon.py for historical backfill — "
            "it batches efficiently. Single-date reconstruction is too slow per call."
        )
