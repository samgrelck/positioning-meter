"""OpenInsider Form 4 scraper.

OpenInsider pre-parses SEC Form 4 filings into a clean HTML screener at
http://openinsider.com/screener — much easier than parsing EDGAR XML directly.

We paginate per ticker. cnt=1000 per page is the practical max.

Returned rows match the `insider_form4` schema. `accession` is synthesized
since openinsider doesn't expose the SEC accession number — we use a hash
of (ticker, trade_date, insider_name, shares) which is unique enough for
our PK and lets us deduplicate on re-scrape.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

from .base import OwnershipProvider

logger = logging.getLogger(__name__)

_BASE = "http://openinsider.com/screener"
_HEADERS = {"User-Agent": "Mozilla/5.0 (PositioningMeter research bot)"}


def _parse_money(s: str) -> float | None:
    """'$1,234,567' -> 1234567.0; '-$38,502,524' -> -38502524.0"""
    if not s or s in ("", "-"):
        return None
    sign = -1 if s.startswith("-") else 1
    cleaned = re.sub(r"[^\d.]", "", s)
    try:
        return sign * float(cleaned)
    except ValueError:
        return None


def _parse_qty(s: str) -> float | None:
    if not s or s in ("", "-"):
        return None
    cleaned = s.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _synth_accession(ticker: str, trade_date: str, insider: str, shares: float) -> str:
    h = hashlib.sha1(f"{ticker}|{trade_date}|{insider}|{shares}".encode()).hexdigest()
    return f"oi_{h[:16]}"


class OpenInsiderProvider(OwnershipProvider):
    def __init__(self, rate_limit_sleep: float = 0.5):
        self._sleep = rate_limit_sleep
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def fetch_13f_filings(self, period_end: date) -> list[dict]:
        raise NotImplementedError("Use EdgarProvider for 13F.")

    def fetch_form4(
        self, ticker: str, start: date, end: date
    ) -> list[dict]:
        days = (end - start).days
        rows: list[dict] = []
        page = 1
        while True:
            params = {
                "s": ticker,
                "fd": days,        # within N days of today
                "cnt": 1000,
                "page": page,
            }
            try:
                r = self._session.get(_BASE, params=params, timeout=30)
                if r.status_code != 200:
                    logger.warning(f"openinsider {ticker} page {page}: HTTP {r.status_code}")
                    break
            except Exception as e:
                logger.warning(f"openinsider {ticker} fetch failed: {e}")
                break
            finally:
                time.sleep(self._sleep)

            page_rows = self._parse_page(r.text, ticker, start, end)
            if not page_rows:
                break
            rows.extend(page_rows)
            if len(page_rows) < 1000:
                break  # last page
            page += 1
            if page > 20:  # safety cap
                logger.warning(f"openinsider {ticker}: hit page cap, stopping")
                break
        return rows

    def _parse_page(
        self, html: str, ticker: str, start: date, end: date
    ) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table", class_="tinytable")
        if not tables:
            return []
        rows: list[dict] = []
        for tr in tables[0].find_all("tr")[1:]:  # skip header
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 12:
                continue
            try:
                filing_dt = cells[1].split(" ")[0]  # date portion
                trade_dt = cells[2]
                insider = cells[4]
                title = cells[5]
                trade_type = cells[6]  # 'P - Purchase', 'S - Sale', etc.
                price = _parse_money(cells[7])
                qty = _parse_qty(cells[8])
                value = _parse_money(cells[11])
            except IndexError:
                continue

            try:
                td_d = date.fromisoformat(trade_dt)
            except (ValueError, TypeError):
                continue
            if not (start <= td_d <= end):
                continue

            tx_code = trade_type.split(" ")[0] if trade_type else None
            shares = qty if qty is not None else 0.0
            rows.append({
                "accession": _synth_accession(ticker, trade_dt, insider, shares),
                "ticker": ticker,
                "filer_cik": None,
                "filer_name": insider,
                "relationship": title,
                "transaction_date": trade_dt,
                "transaction_code": tx_code,
                "shares": shares,
                "price_per_share": price,
                "value_usd": value,
                "direct_indirect": None,
            })
        return rows
