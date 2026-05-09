"""Abstract provider interfaces.

Every external data source implements one of these. Concrete implementations
(yfinance, Polygon, EDGAR, FINRA, openinsider, ETF holdings) live in sibling
modules. Backtest and daily pipeline both go through the same interfaces, so
swapping providers (e.g. flipping options from yfinance snapshots to Polygon
historical) is a config change.

Each method returns either:
  - a list of dicts ready for sqlite executemany() against the corresponding
    raw-data table, or
  - None / [] if no data is available

Providers are responsible for:
  - rate limiting (per provider's own limits)
  - retry / backoff
  - caching raw responses to data/cache/ for replay/debug
  - logging
Providers are NOT responsible for:
  - upserting to the DB (caller does that)
  - computing derived signals (that's lib/signals)
"""
from abc import ABC, abstractmethod
from datetime import date
from typing import Iterable


class PricesProvider(ABC):
    @abstractmethod
    def fetch_prices(
        self, ticker: str, start: date, end: date
    ) -> list[dict]:
        """Return rows shaped like the `prices` table."""


class OptionsProvider(ABC):
    @abstractmethod
    def fetch_snapshot(self, ticker: str, asof: date) -> dict | None:
        """Return one row shaped like `options_daily` for the given date,
        or None if data unavailable.

        Snapshot providers (yfinance) only support asof=today.
        Historical providers (Polygon) support arbitrary asof.
        """

    @abstractmethod
    def supports_history(self) -> bool:
        """True if fetch_snapshot accepts past dates."""


class OwnershipProvider(ABC):
    @abstractmethod
    def fetch_13f_filings(self, period_end: date) -> list[dict]:
        """Return rows shaped like `holdings_13f` for the quarter ending at
        period_end."""

    @abstractmethod
    def fetch_form4(
        self, ticker: str, start: date, end: date
    ) -> list[dict]:
        """Return rows shaped like `insider_form4` for the ticker over the
        date range."""


class ShortInterestProvider(ABC):
    @abstractmethod
    def fetch_settlement(self, settlement_date: date) -> list[dict]:
        """Return rows shaped like `short_interest` for the biweekly
        settlement date."""


class FlowsProvider(ABC):
    @abstractmethod
    def fetch_etf_aum(
        self, etf_ticker: str, start: date, end: date
    ) -> list[dict]:
        """Return rows shaped like `etf_aum`."""

    @abstractmethod
    def fetch_etf_holdings(
        self, etf_ticker: str, asof: date
    ) -> list[dict]:
        """Return rows shaped like `etf_holdings`."""


class EstimatesProvider(ABC):
    """Overlay only — never feeds composite. Snapshot scrape from free
    sources, or future FactSet manual export."""

    @abstractmethod
    def fetch_consensus(self, ticker: str) -> dict | None:
        """Return current consensus snapshot — NTM EPS, # analysts,
        revisions counts where available. No history."""
