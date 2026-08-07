"""Load raw provider data from SQLite into pandas DataFrames for signal compute.

All loaders return pandas frames indexed appropriately for vectorized math.
"""
from __future__ import annotations

import numpy as np
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


def load_float() -> pd.Series:
    """Latest free-float per ticker (Series, index=ticker). Falls back to
    shares_out when floatShares is unavailable. Used as the divisor for the
    float-turnover crowding signal."""
    conn = connect()
    df = pd.read_sql_query(
        "SELECT ticker, float_shares, shares_out FROM share_float "
        "WHERE asof_date = (SELECT MAX(asof_date) FROM share_float)",
        conn,
    )
    conn.close()
    if df.empty:
        return pd.Series(dtype=float)
    fl = df["float_shares"].fillna(df["shares_out"])
    return pd.Series(fl.values, index=df["ticker"]).dropna()


def load_inst_own_pct() -> pd.Series:
    """Institutional ownership fraction per ticker (Series, index=ticker):
    sum of latest-COMPLETE-quarter 13F shares / shares_out. LOW = retail-heavy.
    Overlay only (13F is quarterly + 45d lagged).

    We anchor to the latest quarter with a full filer set (>=10 distinct filers),
    NOT MAX(period_end): a single early filer creates a sparse current quarter
    weeks before the 45-day deadline, and using it would silently compute this
    overlay from one filer instead of the complete prior quarter."""
    conn = connect()
    hf = pd.read_sql_query(
        "SELECT ticker, SUM(shares) AS inst_shares FROM holdings_13f "
        "WHERE period_end = ("
        "  SELECT period_end FROM holdings_13f GROUP BY period_end "
        "  HAVING COUNT(DISTINCT filer_cik) >= 10 ORDER BY period_end DESC LIMIT 1"
        ") GROUP BY ticker",
        conn,
    )
    so = pd.read_sql_query(
        "SELECT ticker, shares_out FROM share_float "
        "WHERE asof_date = (SELECT MAX(asof_date) FROM share_float)",
        conn,
    )
    conn.close()
    if hf.empty or so.empty:
        return pd.Series(dtype=float)
    m = hf.merge(so, on="ticker", how="inner")
    m = m[m["shares_out"] > 0]
    return pd.Series((m["inst_shares"] / m["shares_out"]).values, index=m["ticker"]).dropna()


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


def load_insider_flows(window_days: int = 90, buying_only: bool = False) -> pd.DataFrame:
    """Per-(ticker, date) rolling-window net insider $ over `window_days`.

    Returns DF indexed by date, columns by ticker, values = net $ over the
    trailing window (positive = net buying, negative = net selling).

    If `buying_only=True`, sets all negative (net-selling) daily values to 0
    before rolling. Result: only counts dollar-amount of net buying days.
    Used for insider_buying_90d signal where selling is treated as noise
    (Seyhun, Lakonishok-Lee literature).
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
    if buying_only:
        # Keep only positive (net buying) days; selling days → 0
        daily = daily.clip(lower=0)
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


def load_market_cap_panel(closes: pd.DataFrame) -> pd.DataFrame:
    """Size panel (date x ticker) for the V1.22 size-neutral rank.

    mcap_t = current market cap x (adj_close_t / latest adj_close)

    i.e. today's market cap walked backwards along the split- and dividend-
    adjusted price path. Used only to ORDER names by size when neutralizing the
    cross-sectional rank (see percentiles.size_neutral_rank), so it has to get
    relative size right, not absolute dollars.

    Why not close x shares_out from fundamentals_q, which would be the textbook
    construction: `prices.close` is already split-adjusted (Polygon returns
    adjusted bars — close == adj_close), while `fundamentals_q.shares_out` is
    as-reported at the time. Multiplying the two mixes bases and breaks badly on
    any split — NVDA's 2021 count of 628m against a post-40:1-adjusted price
    read as a $4bn company. That table also carries duplicate period_end rows
    with conflicting counts and outright junk (CRWD 2026-01-31 = 671,000).

    The cost of this construction is that share-count drift (buybacks, issuance)
    is ignored, and today's count is used for the whole history. That is a mild
    look-ahead in the share count only — the price path, which dominates size
    ordering over a decade, stays strictly point-in-time, so a name that grew
    into a mega cap still reads small in its early years. Names are NaN before
    their first traded date and simply keep the plain universe rank there.
    """
    from ..config import project_path

    px = closes.sort_index()
    last_px = px.ffill().iloc[-1]

    # Anchor share count: prefer share_float.shares_out (refreshed weekly by
    # setup/19_ingest_float.py, and already trusted as the float-turnover
    # divisor). universe.csv market_cap is the fallback — it is Polygon-sourced
    # and runs ~2x light on names that have split or re-rated (PANW, CRWD, FTNT,
    # DDOG all read half their traded value there), which would under-neutralize
    # exactly the large caps this correction exists to handle.
    conn = connect()
    so = pd.read_sql_query(
        "SELECT ticker, shares_out FROM share_float "
        "WHERE asof_date = (SELECT MAX(asof_date) FROM share_float) AND shares_out > 0",
        conn,
    )
    conn.close()
    shares = pd.Series(dtype=float)
    if not so.empty:
        shares = pd.Series(so["shares_out"].values, index=so["ticker"]).dropna()

    anchor = (last_px.reindex(shares.index) * shares).dropna()
    try:
        uni = pd.read_csv(project_path("data/universe.csv")).set_index("ticker")["market_cap"]
        uni = uni[uni > 0]
        anchor = anchor.reindex(anchor.index.union(uni.index))
        anchor = anchor.fillna(uni)
    except Exception:
        pass
    anchor = anchor.dropna()

    cols = [c for c in px.columns if c in anchor.index]
    if not cols:
        return pd.DataFrame()

    scale = (anchor.reindex(cols) / last_px.reindex(cols)).replace([np.inf, -np.inf], np.nan)
    mcap = px[cols].mul(scale, axis=1)
    return mcap.where(mcap > 0)


def load_options_panels(prices_index: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """Load all options signals from options_daily, reindex to prices_index.

    Computed signals (per ticker per date):
      - iv_30d, iv_3m, iv_term_slope, skew_25d, pc_volume_ratio, options_volume
    Also derives:
      - iv_rank_1y: percentile of today's IV30 within own trailing 252d range
      - options_vol_vs_20d: today's vol / 20d rolling avg
    """
    conn = connect()
    df = pd.read_sql_query(
        """SELECT ticker, date, iv_30d, iv_3m, iv_term_slope, skew_25d,
                  pc_volume_ratio, pc_oi_ratio, options_volume
           FROM options_daily""",
        conn, parse_dates=["date"],
    )
    conn.close()
    if df.empty:
        empty = pd.DataFrame(index=prices_index)
        return {k: empty for k in [
            "iv_30d", "iv_3m", "iv_term_slope", "skew_25d",
            "pc_volume_ratio", "iv_rank_1y", "options_vol_vs_20d",
        ]}

    out = {}
    for col in ["iv_30d", "iv_3m", "iv_term_slope", "skew_25d", "pc_volume_ratio"]:
        out[col] = df.pivot_table(index="date", columns="ticker", values=col, aggfunc="last").reindex(prices_index, method="ffill")

    # IV rank vs own 1y history
    iv30 = out["iv_30d"]
    rolling_min = iv30.rolling(252, min_periods=20).min()
    rolling_max = iv30.rolling(252, min_periods=20).max()
    rng = rolling_max - rolling_min
    out["iv_rank_1y"] = ((iv30 - rolling_min) / rng).where(rng > 0) * 100.0

    # Options volume vs 20d avg
    vol = df.pivot_table(index="date", columns="ticker", values="options_volume", aggfunc="last").reindex(prices_index, method="ffill")
    rolling_avg = vol.rolling(20, min_periods=5).mean()
    out["options_vol_vs_20d"] = (vol / rolling_avg.replace(0, np.nan))

    # === Direction inversion for contrarian framework ===
    # In the "hot=late=contrarian-bearish" framework:
    #   - HIGH P/C ratio = puts dominate = washout/fear = COLD (low temp)
    #   - HIGH skew (positive: put IV > call IV) = put premium = fear = COLD
    #   - HIGH term slope (backwardation: front > 3m) = near-term stress = COLD
    #   - HIGH IV rank = vol elevated = panic/washout = COLD
    # All four are naturally "fear" measures. Their HIGH readings mean
    # capitulation/contrarian-bullish, which in our framework should give
    # LOW temperature. We invert the raw values here so the downstream
    # percentile-rank machinery produces the right sign.
    invert_signals = ["pc_volume_ratio", "skew_25d", "iv_term_slope", "iv_rank_1y"]
    for sig in invert_signals:
        if sig in out and not out[sig].empty:
            out[sig] = -out[sig]
    return out


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
