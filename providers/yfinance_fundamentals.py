"""yfinance fundamentals provider for valuation bucket.

Pulls quarterly income statement + balance sheet for each ticker. yfinance
typically returns ~4-5y of quarterly data. We compute TTM EPS and TTM Sales
at signal-computation time by summing the trailing 4 quarters as of any
historical date — no peek-ahead.

Filing date isn't reported by yfinance — we assume filing happens
period_end + 35 days (conservative, ~10-Q deadline).

Returns one row per ticker per fiscal quarter to a separate `fundamentals_q`
table (added below as a schema extension).
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

ASSUMED_FILING_LAG_DAYS = 35

# Map yfinance row labels (which vary by version) to our canonical names.
# yfinance has changed these labels several times; we try multiple aliases.
_INCOME_FIELDS = {
    "diluted_eps": ["Diluted EPS", "DilutedEPS"],
    "basic_eps": ["Basic EPS", "BasicEPS"],
    "total_revenue": ["Total Revenue", "TotalRevenue"],
}
_BALANCE_FIELDS = {
    "total_debt": ["Total Debt", "TotalDebt"],
    "cash_and_short_term": ["Cash And Cash Equivalents", "CashAndCashEquivalents",
                             "Cash Cash Equivalents And Short Term Investments",
                             "CashCashEquivalentsAndShortTermInvestments"],
    "shares_out": ["Share Issued", "ShareIssued", "Ordinary Shares Number",
                    "OrdinaryShares Number"],
}


def _first(d: dict | pd.Series, keys: list[str]):
    for k in keys:
        if isinstance(d, pd.Series):
            if k in d.index:
                v = d.get(k)
                if pd.notna(v):
                    return float(v)
        else:
            if k in d:
                v = d[k]
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    return float(v)
    return None


def fetch_quarterly(ticker: str, sleep: float = 0.5) -> list[dict]:
    """Return a list of per-quarter fundamentals rows for `ticker`.

    Schema:
      ticker, period_end, filing_date_est, diluted_eps_q, total_revenue_q,
      total_debt, cash_and_short_term, shares_out
    """
    try:
        t = yf.Ticker(ticker)
        income = t.quarterly_income_stmt
        balance = t.quarterly_balance_sheet
    except Exception as e:
        logger.warning(f"yfinance fundamentals fetch failed for {ticker}: {e}")
        time.sleep(sleep)
        return []
    finally:
        time.sleep(sleep)

    if income is None or income.empty:
        return []

    rows: list[dict] = []
    for period in income.columns:
        period_end = pd.Timestamp(period).date()
        income_col = income[period]
        balance_col = balance[period] if (balance is not None
                                          and period in balance.columns) else None

        eps = _first(income_col, _INCOME_FIELDS["diluted_eps"]) or \
              _first(income_col, _INCOME_FIELDS["basic_eps"])
        rev = _first(income_col, _INCOME_FIELDS["total_revenue"])
        debt = _first(balance_col, _BALANCE_FIELDS["total_debt"]) if balance_col is not None else None
        cash = _first(balance_col, _BALANCE_FIELDS["cash_and_short_term"]) if balance_col is not None else None
        shares = _first(balance_col, _BALANCE_FIELDS["shares_out"]) if balance_col is not None else None

        rows.append({
            "ticker": ticker,
            "period_end": period_end.isoformat(),
            "filing_date_est": (period_end + timedelta(days=ASSUMED_FILING_LAG_DAYS)).isoformat(),
            "diluted_eps_q": eps,
            "total_revenue_q": rev,
            "total_debt": debt,
            "cash_and_short_term": cash,
            "shares_out": shares,
        })
    return rows
