"""Technical bucket signals.

All functions accept a wide DataFrame of adjusted closes (date x ticker) and
return a dict of {signal_name: DataFrame[date x ticker]} of raw values.

NOTE on directionality: the whole "temperature" framework treats high
percentile = "hot/extreme/late." For symmetric measures like RSI and 12m
return, the percentile transform handles directionality automatically.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Trading days, approximations
_DAYS_1M = 21
_DAYS_3M = 63
_DAYS_6M = 126
_DAYS_12M = 252


def _trailing_return(closes: pd.DataFrame, n: int) -> pd.DataFrame:
    return closes / closes.shift(n) - 1


def _rsi(closes: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta = closes.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    # Wilder smoothing via EMA approximation
    avg_up = up.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_down = down.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_up / avg_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _dist_from_ma(closes: pd.DataFrame, n: int = 200) -> pd.DataFrame:
    ma = closes.rolling(n, min_periods=n).mean()
    return (closes - ma) / ma


def _pct_from_52w_high(closes: pd.DataFrame) -> pd.DataFrame:
    high = closes.rolling(_DAYS_12M, min_periods=20).max()
    return closes / high - 1  # 0 at the high, negative below


def _relative_strength(closes: pd.DataFrame, benchmark_ticker: str, n: int) -> pd.DataFrame:
    """Trailing-n return of each name minus the benchmark's trailing-n return."""
    if benchmark_ticker not in closes.columns:
        return pd.DataFrame(index=closes.index, columns=closes.columns, dtype=float)
    name_ret = _trailing_return(closes, n)
    bench_ret = _trailing_return(closes[[benchmark_ticker]], n).iloc[:, 0]
    return name_ret.sub(bench_ret, axis=0)


def compute_all(
    closes: pd.DataFrame,
    qqq_ticker: str = "QQQ",
    sector_etf: str = "XLK",
) -> dict[str, pd.DataFrame]:
    """Return all technical signals as a dict of wide DataFrames."""
    return {
        "ret_1m":               _trailing_return(closes, _DAYS_1M),
        "ret_3m":               _trailing_return(closes, _DAYS_3M),
        "ret_6m":               _trailing_return(closes, _DAYS_6M),
        "ret_12m":              _trailing_return(closes, _DAYS_12M),
        "dist_200ma":           _dist_from_ma(closes, 200),
        "rsi_14":               _rsi(closes, 14),
        "pct_from_52w_high":    _pct_from_52w_high(closes),
        "rs_vs_qqq_3m":         _relative_strength(closes, qqq_ticker, _DAYS_3M),
        "rs_vs_xlk_3m":         _relative_strength(closes, sector_etf, _DAYS_3M),
    }
