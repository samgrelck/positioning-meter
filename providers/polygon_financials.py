"""Polygon stock financials provider.

Endpoint: vX/reference/financials. Returns up to ~20y of quarterly + annual +
TTM reports per ticker, each with a real `filing_date` (not estimated).

We store ALL reports (Q + FY + TTM) and let the signal-compute layer pick the
flavor it needs (typically TTM for trailing ratios).

`fiscal_period`: 'Q1' | 'Q2' | 'Q3' | 'Q4' | 'FY' | 'TTM'
"""
from __future__ import annotations

import logging
import time
from datetime import date

from polygon import RESTClient

from lib.config import require_env

logger = logging.getLogger(__name__)


def _get(dp) -> float | None:
    """Polygon DataPoint -> float or None."""
    if dp is None:
        return None
    v = getattr(dp, "value", None)
    return float(v) if v is not None else None


class PolygonFinancialsProvider:
    def __init__(self, rate_limit_sleep: float = 0.2):
        self._client = RESTClient(require_env("POLYGON_API_KEY"))
        self._sleep = rate_limit_sleep

    def fetch(self, ticker: str, limit: int = 100) -> list[dict]:
        """Return list of fundamentals rows for `ticker`. Most recent first."""
        try:
            reports = list(self._client.vx.list_stock_financials(
                ticker=ticker, limit=limit
            ))
        except Exception as e:
            logger.warning(f"Polygon financials fetch failed for {ticker}: {e}")
            return []
        finally:
            time.sleep(self._sleep)

        rows: list[dict] = []
        for r in reports:
            fin = r.financials
            inc = fin.income_statement if fin else None
            bal = fin.balance_sheet if fin else None
            if inc is None and bal is None:
                continue

            row = {
                "ticker": ticker,
                "period_end": r.end_date,
                "filing_date_est": r.filing_date,  # actual, not estimated
                "fiscal_period": r.fiscal_period,
                "fiscal_year": str(r.fiscal_year) if r.fiscal_year else None,
                "diluted_eps_q": _get(getattr(inc, "diluted_earnings_per_share", None)) if inc else None,
                "total_revenue_q": _get(getattr(inc, "revenues", None)) if inc else None,
                "total_debt": _get(getattr(bal, "long_term_debt", None)) if bal else None,
                "cash_and_short_term": _get(getattr(bal, "cash", None)) if bal else None,
                "shares_out": _get(getattr(inc, "diluted_average_shares", None)) if inc else None,
            }
            rows.append(row)
        return rows
