"""Load raw provider data from SQLite into pandas DataFrames for signal compute.

All loaders return pandas frames indexed appropriately for vectorized math.
"""
from __future__ import annotations

import pandas as pd

from ..db import connect


def load_prices() -> pd.DataFrame:
    """Wide DataFrame of adjusted close prices: index=date, columns=tickers."""
    conn = connect()
    df = pd.read_sql_query(
        "SELECT ticker, date, adj_close, volume FROM prices ORDER BY date",
        conn,
        parse_dates=["date"],
    )
    conn.close()
    closes = df.pivot(index="date", columns="ticker", values="adj_close")
    volumes = df.pivot(index="date", columns="ticker", values="volume")
    return closes, volumes


def load_short_volume() -> pd.DataFrame:
    """Wide DF of short-volume ratio (0..1): index=date, columns=tickers."""
    conn = connect()
    df = pd.read_sql_query(
        """
        SELECT ticker, settlement_date as date,
               short_interest / 1000000.0 AS sv_ratio
        FROM short_interest
        """,
        conn,
        parse_dates=["date"],
    )
    conn.close()
    if df.empty:
        return pd.DataFrame()
    return df.pivot(index="date", columns="ticker", values="sv_ratio")


def load_insider_flows(window_days: int = 90) -> pd.DataFrame:
    """Per-(ticker, date) rolling-window net insider $ over `window_days`.

    Returns DF indexed by date, columns by ticker, values = net $ over the
    trailing window (positive = net buying, negative = net selling).
    """
    conn = connect()
    df = pd.read_sql_query(
        """
        SELECT ticker, transaction_date as date, value_usd
        FROM insider_form4
        WHERE value_usd IS NOT NULL
        """,
        conn,
        parse_dates=["date"],
    )
    conn.close()
    if df.empty:
        return pd.DataFrame()
    # daily sum per ticker
    daily = df.groupby(["date", "ticker"])["value_usd"].sum().unstack(fill_value=0)
    # reindex to all calendar days then rolling window
    full_idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_idx, fill_value=0)
    rolling = daily.rolling(window=window_days, min_periods=1).sum()
    return rolling


def load_fundamentals_q() -> pd.DataFrame:
    """All quarterly + TTM + FY rows. Caller filters by fiscal_period."""
    conn = connect()
    df = pd.read_sql_query(
        """
        SELECT ticker, period_end, fiscal_period, fiscal_year, filing_date_est,
               diluted_eps_q, total_revenue_q, total_debt, cash_and_short_term, shares_out
        FROM fundamentals_q
        """,
        conn,
        parse_dates=["period_end", "filing_date_est"],
    )
    conn.close()
    return df


def load_universe() -> pd.DataFrame:
    """Universe table with cluster_id."""
    from ..config import load, project_path
    cfg = load()
    return pd.read_csv(project_path(cfg["universe"]["output_csv"]))


def load_eps_revisions_panel(prices_index: pd.DatetimeIndex, lookback_days: int = 20) -> pd.DataFrame:
    """Per-ticker rolling change in forward EPS over `lookback_days`.

    Reads estimates_daily.forward_eps history (forward-only — accumulates from
    when we started snapshotting). Returns empty if we have <2 snapshots per
    ticker yet.
    """
    conn = connect()
    df = pd.read_sql_query(
        "SELECT ticker, date, forward_eps FROM estimates_daily WHERE forward_eps IS NOT NULL",
        conn, parse_dates=["date"],
    )
    conn.close()
    if df.empty:
        return pd.DataFrame(index=prices_index)
    wide = df.pivot_table(index="date", columns="ticker", values="forward_eps", aggfunc="last").sort_index()
    if len(wide) < 2:
        return pd.DataFrame(index=prices_index)
    # Forward-fill across calendar days, then compute % change over lookback
    full_idx = pd.date_range(wide.index.min(), max(wide.index.max(), prices_index.max()), freq="D")
    wide = wide.reindex(full_idx).ffill()
    revision = (wide / wide.shift(lookback_days) - 1) * 100  # % change in NTM EPS
    return revision.reindex(prices_index, method="ffill")


def load_si_true(prices_index: pd.DatetimeIndex) -> pd.DataFrame:
    """True SI as days-to-cover, NASDAQ API, forward-filled to daily."""
    conn = connect()
    df = pd.read_sql_query(
        "SELECT ticker, settlement_date, days_to_cover FROM short_interest_true WHERE days_to_cover IS NOT NULL",
        conn, parse_dates=["settlement_date"],
    )
    conn.close()
    if df.empty:
        return pd.DataFrame(index=prices_index)
    wide = df.pivot_table(index="settlement_date", columns="ticker",
                          values="days_to_cover", aggfunc="last").sort_index()
    wide = wide.reindex(wide.index.union(prices_index)).ffill().loc[prices_index]
    return wide


def load_hf_holdings_panels(prices_index: pd.DatetimeIndex, lag_days: int = 45) -> dict[str, pd.DataFrame]:
    """Aggregate 13F holdings to per-(quarter, ticker) and forward-fill to daily.

    Returns dict of DataFrames (date x ticker), each forward-filled with the
    most recent quarterly value as of `period_end + lag_days`:
      - hf_count_13f: # of HF filers holding the name
      - hf_total_value: total $ held by HFs in this name
      - hf_top_concentration: % of total HF $ from top 5 filers

    The lag captures the assumption that holdings as of period_end are not
    publicly knowable until ~45 days later (max 13F filing deadline).
    """
    conn = connect()
    df = pd.read_sql_query(
        """
        SELECT period_end, ticker, filer_cik, value_usd, shares
        FROM holdings_13f
        WHERE value_usd IS NOT NULL
        """,
        conn,
        parse_dates=["period_end"],
    )
    conn.close()
    if df.empty:
        empty = pd.DataFrame(index=prices_index)
        return {"hf_count_13f": empty, "hf_total_value": empty, "hf_top_concentration": empty}

    # Aggregate per (period_end, ticker)
    agg = df.groupby(["period_end", "ticker"]).agg(
        hf_count_13f=("filer_cik", "nunique"),
        hf_total_value=("value_usd", "sum"),
    ).reset_index()

    # Top-filer concentration: top 5 filers' $ as % of total per (period_end, ticker)
    top = (
        df.groupby(["period_end", "ticker", "filer_cik"])["value_usd"].sum().reset_index()
        .sort_values(["period_end", "ticker", "value_usd"], ascending=[True, True, False])
    )
    top["rank"] = top.groupby(["period_end", "ticker"]).cumcount()
    top5_sum = top[top["rank"] < 5].groupby(["period_end", "ticker"])["value_usd"].sum().rename("top5_value")
    agg = agg.merge(top5_sum, on=["period_end", "ticker"], how="left")
    agg["hf_top_concentration"] = agg["top5_value"] / agg["hf_total_value"]

    # Effective date = period_end + lag_days
    agg["eff_date"] = agg["period_end"] + pd.Timedelta(days=lag_days)
    agg = agg.sort_values("eff_date")

    # Pivot to wide DataFrames and forward-fill on prices_index
    out = {}
    for col in ["hf_count_13f", "hf_total_value", "hf_top_concentration"]:
        wide = agg.pivot_table(index="eff_date", columns="ticker", values=col, aggfunc="last")
        # Reindex to prices' trading days, forward-fill
        wide = wide.sort_index()
        wide = wide.reindex(wide.index.union(prices_index)).ffill()
        wide = wide.loc[prices_index]
        out[col] = wide
    return out
