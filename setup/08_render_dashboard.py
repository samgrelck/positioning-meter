"""Render the Positioning Meter HTML dashboard.

Single self-contained HTML file with:
  - Modern card-based UI (Inter font, semantic color palette, KPI tiles)
  - Tabs: Overview, All Names (full 366), Movers, Flags, Watchlist
  - Glossary explaining every metric
  - Full sortable/searchable all-names table (all 366)
  - Per-ticker drill-down with sparkline + signals + estimates overlay + actions
  - JS-powered search/filter across tables AND drill-down sections
  - Cluster + sector group filters
  - CSV export
  - Backtest summary card
  - Provenance footer
"""
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import project_path
from lib.db import connect


HTML_OUT = project_path("data/dashboard.html")
SECTOR_GROUPS_PATH = project_path("data/sector_groups.json")


def html_escape(s) -> str:
    """Escape text for safe inclusion in an HTML attribute (e.g. title="...")."""
    return (str(s).replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def fmt(v, places=1, suffix="", default="—"):
    if v is None or pd.isna(v):
        return default
    try:
        return f"{float(v):.{places}f}{suffix}"
    except (TypeError, ValueError):
        return default


def fmt_money(v):
    if v is None or pd.isna(v):
        return "—"
    try:
        v = float(v)
        if abs(v) >= 1e9:
            return f"${v/1e9:.1f}B"
        if abs(v) >= 1e6:
            return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return "—"


def fmt_int(v):
    if v is None or pd.isna(v):
        return "—"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "—"


def temp_class(v):
    if v is None or pd.isna(v):
        return ""
    v = float(v)
    if v >= 85:
        return "ext-hot"
    if v >= 70:
        return "hot"
    if v <= 15:
        return "ext-cold"
    if v <= 30:
        return "cold"
    return "neutral"


# ---- V1.18: self-vs-own-history helpers ----
# A self-history percentile is 0..100 with the same "high = hot" orientation as
# temperature, so temp_class() colors it correctly (78 -> hot-for-itself = red).

def selfpct_word(pct):
    """Plain-language read of a self-history percentile."""
    if pct is None or pd.isna(pct):
        return None
    p = float(pct)
    if p >= 90:
        return "near its own 1y high"
    if p >= 70:
        return "hot for itself"
    if p >= 55:
        return "a touch warm for itself"
    if p > 45:
        return "middling for itself"
    if p > 30:
        return "a touch cool for itself"
    if p > 10:
        return "washed-out for itself"
    return "near its own 1y low"


def selfpct_cell(pct, z=None, pct_6m=None, label="Temp", note=""):
    """Render a self-history percentile as a colored numeric <td> with a
    tooltip carrying the z-score and the 6-month read.

    `note` appends a basis clarification (used by the ex-technical column)."""
    if pct is None or pd.isna(pct):
        return '<td class="num self" title="No self-history yet (insufficient own-history window).">—</td>'
    cls = temp_class(pct)
    z_str = f", {float(z):+.1f}σ" if (z is not None and not pd.isna(z)) else ""
    sixm = f" · 6mo: {float(pct_6m):.0f}th" if (pct_6m is not None and not pd.isna(pct_6m)) else ""
    title = (f"{label} sits at its {_ord(pct)} percentile vs this name's own "
             f"trailing 1y{z_str}{sixm}. High = hot for itself; low = washed-out for "
             f"itself — reframes a structurally cool/hot name vs its own norm.{note}")
    return f'<td class="num temp {cls}" title="{title}">{float(pct):.0f}</td>'


# V1.20 — the ex-technical ("Positioning + Options") self-history column.
# One source of copy for the header tooltip, the cell tooltip and the glossary
# so the three can never drift apart. Plain text only (goes inside title="...").
EXTECH_COL = "Self 1y P+O"
EXTECH_HDR_TITLE = (
    "Same read as Self 1y, but scored off the POSITIONING + OPTIONS pillars only — "
    "technicals excluded. Where today's positioning+options blend sits within this name's "
    "own trailing 1-year range (percentile 0-100). Use it when you want the crowding / "
    "hedging picture uncontaminated by how the stock has actually traded; compare it against "
    "Self 1y to see how much of the self-history read is just price action. "
    "Weights: the config 0.50 Pos / 0.30 Opt renormalized to 0.625 / 0.375. "
    "Caveat: options data starts 2026-05-12, so the earlier part of the 1-year window is "
    "positioning-only."
)
EXTECH_CELL_NOTE = (
    " Positioning + options pillars only (technicals excluded; 0.625 Pos / 0.375 Opt). "
    "Options history starts 2026-05-12 — earlier window is positioning-only."
)


# V1.21 — the cross-sectional percentile of Temperature. Temperature is an
# average of ~15 percentile signals, so it is compressed toward 50 by the central
# limit (std ~13; only ~6% of names clear 70 and ~6% fall under 30). That makes a
# 0-100 scale READ like a percentile while not being one. This column is the
# actual percentile. It is a monotone per-date transform of Temp, so it cannot
# change any ranking, IC or backtest result — it only changes what you see.
UNIVPCT_COL = "Univ %ile"
UNIVPCT_HDR_TITLE = (
    "Where this name's Temperature ranks against the whole TMT universe TODAY "
    "(percentile 0-100). Prefer this over the raw Temp when judging how extreme a "
    "reading is: the composite averages ~15 percentile signals, which compresses it "
    "toward the middle (std ~13, effective range ~20-89), so Temp 38 is really a "
    "bottom-quintile name and Temp 62 is already top-quartile. Purely a re-scaling "
    "of Temp — same ordering, same model."
)

QUAD_HDR_TITLE = (
    "Setup quadrant: how crowded the name is (positioning tercile) crossed with "
    "which way price is going (technical tercile), ranked across the universe today. "
    "Word = positioning, arrow = price. Only the four corners are tagged; middle "
    "terciles show a dot because the middle of the grid carries no measurable edge. "
    "Hover any tag for its historical 1-month factor-neutral cell return. "
    "See the 📖 How to read it tab."
)


# V1.21 — the "Setup" quadrant: positioning tercile x technical tercile, ranked
# across the universe on the current date. Only the four CORNERS get a tag; the
# middle terciles are deliberately unlabeled because they carry no measurable
# edge. Word = how crowded the name is, arrow = which way price is going.
#
# The annualized figures in the tooltips are the mean 1-month factor-neutral
# (sector + beta residualized) forward return of that cell over 121
# non-overlapping periods, 2016-2026. They are a DESCRIPTION of the historical
# cell, not a forecast: t-stats are 0.7-1.9 and the cells were read off a 3x3
# grid, so treat them as orientation, not as expected returns.
QUAD_DEFS = {
    ("cold", "weak"): (
        "Under-owned ↓", "quad-cool",
        "Light positioning + weak price action — the classic washed-out setup. "
        "Best-performing cell historically: +3.7%/yr residual (t 1.68)."),
    ("cold", "strong"): (
        "Under-owned ↑", "quad-cool",
        "Light positioning + strong price action — strength that nobody is "
        "positioned for. +2.6%/yr residual (t 1.04)."),
    ("hot", "weak"): (
        "Crowded ↓", "quad-warm",
        "Heavy positioning + weak price action — crowded and rolling over. "
        "−1.5%/yr residual (t −0.70)."),
    ("hot", "strong"): (
        "Crowded ↑", "quad-hot",
        "Heavy positioning + strong price action — crowded strength, the most "
        "expensive place to be adding. Worst cell historically: −3.5%/yr "
        "residual (t −1.86)."),
}
# Sort order for the Setup column: most-crowded first descending.
QUAD_SORT_RANK = {"Crowded ↑": 2, "Crowded ↓": 1, "·": 0,
                  "Under-owned ↑": -1, "Under-owned ↓": -2}

QUAD_NONE = ("·", "quad-none",
             "Middle tercile on positioning or on technicals — no corner tag. "
             "The middle of this grid showed no measurable edge, so it is left "
             "deliberately blank rather than given a label it hasn't earned.")


def _tercile(s: pd.Series, labels) -> pd.Series:
    """Rank a score cross-sectionally into 3 equal buckets. NaN stays NaN."""
    valid = s.notna()
    out = pd.Series(pd.NA, index=s.index, dtype="object")
    if valid.sum() < 6:
        return out
    out.loc[valid] = pd.qcut(s[valid].rank(method="first"), 3, labels=list(labels)).astype(object)
    return out


def assign_quadrants(snap: pd.DataFrame) -> pd.DataFrame:
    """Add `quad_label` / `quad_cls` / `quad_title` from the pos x tech corners."""
    pos_t = _tercile(snap.get("score_positioning", pd.Series(dtype=float)),
                     ("cold", "mid", "hot"))
    tech_t = _tercile(snap.get("score_technical", pd.Series(dtype=float)),
                      ("weak", "mid", "strong"))
    labels, classes, titles = [], [], []
    for p, t in zip(pos_t, tech_t):
        lbl, cls, title = QUAD_DEFS.get((p, t), QUAD_NONE)
        labels.append(lbl)
        classes.append(cls)
        titles.append(title)
    snap["quad_label"] = labels
    snap["quad_cls"] = classes
    snap["quad_title"] = titles
    return snap


def quad_cell(row) -> str:
    """Render the Setup quadrant as a <td> badge."""
    lbl = row.get("quad_label") or "·"
    cls = row.get("quad_cls") or "quad-none"
    title = html_escape(row.get("quad_title") or "")
    return f'<td class=num><span class="quad {cls}" title="{title}">{lbl}</span></td>'


def univpct_cell(pct) -> str:
    """Render the cross-sectional (vs TMT universe today) percentile of Temp."""
    if pct is None or pd.isna(pct):
        return '<td class="num univ" title="No composite temperature today.">—</td>'
    title = (f"Temperature ranks at the {_ord(pct)} percentile of the TMT universe "
             f"today. Read THIS, not the raw Temp: the composite averages ~15 "
             f"percentile signals, which compresses it toward 50 (std ~13, and only "
             f"~6% of names ever clear 70), so a Temp of 38 is really a bottom-quintile "
             f"reading. This column undoes that compression.")
    return f'<td class="num temp {temp_class(pct)}" title="{title}">{float(pct):.0f}</td>'


def load_data():
    conn = connect()
    latest = conn.execute("SELECT MAX(date) FROM composite_daily").fetchone()[0]

    snap = pd.read_sql_query(
        "SELECT * FROM composite_daily WHERE date = ? AND temperature IS NOT NULL",
        conn, params=(latest,),
    )
    universe = pd.read_csv(project_path("data/universe.csv"))
    snap = snap.merge(universe, on="ticker", how="left")
    snap["name"] = snap["name"].fillna(snap["ticker"])
    snap["mcap_b"] = snap["market_cap"] / 1e9 if "market_cap" in snap.columns else None

    # Cross-sectional standing: percentile rank of the composite temp + each
    # pillar score vs the whole TMT universe on this date. Surfaced per-pillar in
    # the drilldown "In a nutshell" so each pillar shows BOTH its rank vs TMT
    # today and its rank vs the name's own trailing history (the *_selfpct_* cols).
    for src, dst in [("temperature", "temp_univpct"),
                     ("score_positioning", "pos_univpct"),
                     ("score_technical", "tech_univpct"),
                     ("score_options", "opt_univpct")]:
        if src in snap.columns:
            snap[dst] = snap[src].rank(pct=True) * 100.0

    # V1.21: Setup quadrant (positioning x technical corners). Display-only —
    # never feeds the composite, the flags or the backtest.
    snap = assign_quadrants(snap)

    # New-listing guard. A name with too little PRICE HISTORY (e.g. a recent IPO
    # like SPCX/SpaceX, which posts a ~99 temp off just IPO float-churn + RSI)
    # can top the board on 1-2 artifact signals. Flag such names so they still
    # show in the drilldown + All Names, but are HELD OUT of the hottest/movers/
    # flag rankings until they mature. Keyed on trading-day count only: an
    # established name that merely lacks the options group (e.g. an illiquid
    # share class with 3 signals) is NOT a new listing and must not be flagged.
    MIN_HIST_DAYS = 40
    pdays = pd.read_sql_query(
        "SELECT ticker, COUNT(*) AS price_days FROM prices GROUP BY ticker", conn)
    snap = snap.merge(pdays, on="ticker", how="left")
    snap["price_days"] = snap["price_days"].fillna(0).astype(int)
    # present composite signals today — for the drilldown banner text only.
    nsig = pd.read_sql_query(
        "SELECT ticker, COUNT(*) AS n_signals FROM signals_daily "
        "WHERE date = ? AND bucket IN ('positioning','technical','options') "
        "AND (pct_self IS NOT NULL OR pct_peer IS NOT NULL) GROUP BY ticker",
        conn, params=(latest,))
    snap = snap.merge(nsig, on="ticker", how="left")
    snap["n_signals"] = snap["n_signals"].fillna(0).astype(int)
    snap["thin_history"] = snap["price_days"] < MIN_HIST_DAYS

    # 7-day prior snapshot for change
    recent = pd.read_sql_query(
        "SELECT ticker, date, temperature FROM composite_daily WHERE date >= date(?, '-15 days')",
        conn, params=(latest,), parse_dates=["date"],
    )
    if not recent.empty:
        pivot = recent.pivot(index="date", columns="ticker", values="temperature").sort_index()
        if len(pivot) >= 6:
            chg7 = (pivot.iloc[-1] - pivot.iloc[-6]).rename("temp_7d_chg").reset_index()
            snap = snap.merge(chg7, on="ticker", how="left")
        else:
            snap["temp_7d_chg"] = None
    else:
        snap["temp_7d_chg"] = None

    # Newly-triggered flags in last 7 days
    recent_flags = pd.read_sql_query(
        """
        SELECT ticker, date, flag_late_signal, flag_washout
        FROM composite_daily WHERE date >= date(?, '-14 days')
        """,
        conn, params=(latest,), parse_dates=["date"],
    )
    new_late, new_wash = [], []
    if not recent_flags.empty:
        for t, grp in recent_flags.groupby("ticker"):
            grp = grp.sort_values("date")
            late_today = bool(grp.iloc[-1]["flag_late_signal"]) if len(grp) > 0 else False
            late_week_ago = bool(grp.iloc[0]["flag_late_signal"]) if len(grp) > 1 else False
            wash_today = bool(grp.iloc[-1]["flag_washout"]) if len(grp) > 0 else False
            wash_week_ago = bool(grp.iloc[0]["flag_washout"]) if len(grp) > 1 else False
            if late_today and not late_week_ago:
                new_late.append(t)
            if wash_today and not wash_week_ago:
                new_wash.append(t)

    # Per-ticker temperature: 30d sparkline (header) + 180d larger chart (drill-down)
    spark_df = pd.read_sql_query(
        "SELECT ticker, date, temperature, score_positioning, score_technical, score_options "
        "FROM composite_daily WHERE date >= date(?, '-200 days')",
        conn, params=(latest,), parse_dates=["date"],
    )
    sparkline_data = {}
    chart_data = {}
    bucket_chart_data = {}  # last 180d of (date, positioning, technical, options) per ticker
    if not spark_df.empty:
        for t, grp in spark_df.groupby("ticker"):
            srt = grp.sort_values("date")
            tvals = srt[["date", "temperature"]].dropna()
            if len(tvals) > 0:
                vals = tvals["temperature"].tolist()
                sparkline_data[t] = vals[-30:]
                chart_data[t] = [(d.strftime("%Y-%m-%d"), v) for d, v in zip(tvals["date"], vals)][-180:]
            # Bucket-score history: keep days where at least one bucket score is present
            b = srt[["date", "score_positioning", "score_technical", "score_options"]].dropna(
                how="all", subset=["score_positioning", "score_technical", "score_options"]
            )
            if len(b) > 0:
                bucket_chart_data[t] = [
                    (d.strftime("%Y-%m-%d"),
                     None if pd.isna(p) else float(p),
                     None if pd.isna(tc) else float(tc),
                     None if pd.isna(o) else float(o))
                    for d, p, tc, o in zip(b["date"], b["score_positioning"],
                                           b["score_technical"], b["score_options"])
                ][-180:]

    # Per-ticker per-signal data (latest day)
    sig_long = pd.read_sql_query(
        "SELECT ticker, signal_name, bucket, raw_value, pct_self, pct_peer FROM signals_daily WHERE date = ?",
        conn, params=(latest,),
    )

    estimates = pd.read_sql_query(
        "SELECT * FROM estimates_daily WHERE date = (SELECT MAX(date) FROM estimates_daily)",
        conn,
    )
    # V1.5: compute NTM P/E from forward EPS × latest price.
    # No TTM multiples — user explicitly excluded them.
    if not estimates.empty:
        latest_prices = pd.read_sql_query(
            "SELECT ticker, adj_close FROM prices WHERE date = (SELECT MAX(date) FROM prices)",
            conn,
        )
        estimates = estimates.merge(latest_prices, on="ticker", how="left")
        estimates["ntm_pe"] = estimates.apply(
            lambda r: (r["adj_close"] / r["forward_eps"])
            if pd.notna(r.get("forward_eps")) and pd.notna(r.get("adj_close"))
            and r["forward_eps"] > 0 else None,
            axis=1,
        )
    earnings = pd.read_sql_query("SELECT * FROM earnings_calendar", conn)
    actions = pd.read_sql_query(
        """SELECT ticker, action_date, firm, from_grade, to_grade, action
           FROM analyst_actions WHERE action_date >= date('now', '-90 days')
           ORDER BY action_date DESC""",
        conn,
    )

    notes = pd.read_sql_query("SELECT ticker, note, updated_at FROM ticker_notes", conn)
    watchlist = pd.read_sql_query("SELECT ticker, label FROM watchlist", conn)

    backtest_path = project_path("data/backtest_results.json")
    backtest_results = json.loads(backtest_path.read_text()) if backtest_path.exists() else []

    conn.close()
    return {
        "latest": latest,
        "snap": snap,
        "sig_long": sig_long,
        "estimates": estimates,
        "earnings": earnings,
        "actions": actions,
        "notes": notes,
        "watchlist": watchlist,
        "sparklines": sparkline_data,
        "chart_data": chart_data,
        "bucket_chart_data": bucket_chart_data,
        "new_late": new_late,
        "new_wash": new_wash,
        "provenance": compute_provenance(),
        "backtest_results": backtest_results,
    }


def compute_provenance() -> dict[str, str]:
    logs = project_path("logs")
    out = {}
    if not logs.exists():
        return out
    name_map = {
        "02_ingest_prices_status.json": "Prices (Polygon)",
        "03_ingest_financials_status.json": "Financials (Polygon)",
        "04_ingest_short_volume_status.json": "Short volume (FINRA)",
        "05_ingest_insider_status.json": "Insider Form 4 (openinsider)",
        "18_ingest_finra_si_status.json": "Short interest (FINRA biweekly)",
        "12_ingest_13f_status.json": "13F holdings (EDGAR)",
        "13_ingest_estimates_status.json": "Estimates (Yahoo)",
        "14_ingest_etf_flows_status.json": "ETF AUM (Yahoo)",
        "06_compute_signals_status.json": "Signal compute",
    }
    for fn, label in name_map.items():
        p = logs / fn
        if p.exists():
            mt = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            out[label] = mt
    return out


def load_sector_groups() -> dict:
    if SECTOR_GROUPS_PATH.exists():
        return json.loads(SECTOR_GROUPS_PATH.read_text())
    return {}


SIGNAL_DESCRIPTIONS = {
    "ret_1m": ("1-month return", "Trailing 21-trading-day return."),
    "ret_3m": ("3-month return", "Trailing 63-day return."),
    "ret_6m": ("6-month return", "Trailing 126-day return."),
    "ret_12m": ("12-month return (overlay)", "Trailing 252-day return. Trend signal — overlay only."),
    "dist_200ma": ("Distance from 200d MA", "(price − 200d MA) / 200d MA."),
    "rsi_14": ("RSI(14)", "14-period Wilder RSI. >70 overbought, <30 oversold."),
    "pct_from_52w_high": ("% from 52w high", "Price relative to trailing 52-week high."),
    "rs_vs_qqq_3m": ("RS vs QQQ (overlay)", "3m return − QQQ 3m return. Trend."),
    "rs_vs_xlk_3m": ("RS vs XLK (overlay)", "3m return − XLK 3m return. Trend."),
    # ttm_pe and ev_sales removed in V1.5 — TTM multiples not used.
    # NTM P/E is shown on drill-down's live-overlay card.
    "insider_net_90d_signed": ("Insider net 90d (signed)", "Σ Form 4 net $ over trailing 90d."),
    "insider_net_90d_abs": ("Insider |net 90d| (overlay)", "Magnitude of insider activity."),
    "short_volume_ratio_14d": ("Short volume 14d ratio", "FINRA Reg SHO short-marked share of daily volume, 14d avg. A FLOW measure of intraday shorting activity — NOT the standing short position. Most short-marked prints are market-maker/liquidity-provider hedging and intraday arb that is flat by the close, so a high reading reflects heavy two-sided trading more than directional bearish bets. Read alongside Short interest days-to-cover (the actual open short position): high short volume + low days-to-cover = churned/heavily-traded, not pressed short."),
    "si_true_dtc": ("Short interest days-to-cover", "Actual reported short interest (open shares held short, bi-weekly FINRA snapshot) ÷ avg daily volume = days of volume needed to cover. A STOCK/position measure of real crowding, and the more reliable read of bearish positioning. Low when the open short book is small AND/OR the stock is very liquid (high turnover deflates days-to-cover). Contrast with Short volume 14d ratio, a same-day flow dominated by non-directional market-making."),
    "float_turnover_20d": ("Float turnover (20d)", "20-day avg daily share volume ÷ free float. High = heavy churn relative to tradable shares — a long/retail-crowding proxy (the dimension short interest + insider flow miss). High = HOT/crowded."),
    "inst_own_pct": ("Institutional ownership % (overlay)", "Sum of latest-quarter 13F shares ÷ shares outstanding. LOW = retail-heavy ownership. Overlay only — 13F is quarterly and 45d lagged."),
    "eps_revision_4w": ("EPS revision % 4w (overlay)", "% change in NTM forward EPS over trailing 20 trading days. Forward-only — accumulating since estimates ingestion started; null for early dates."),
    # Options signals (in composite once data accumulates)
    "iv_rank_1y": ("IV rank 1y", "30-day ATM IV as percentile within own trailing 252d range. High = vol expectations elevated (often marks crowded positioning / event risk)."),
    "iv_term_slope": ("IV term slope", "Front-month IV − 3m IV. Positive (backwardation) = near-term stress > structural; negative (contango) = calm. Backwardation often marks contrarian buy zones."),
    "skew_25d": ("25Δ skew", "IV(25Δ put) − IV(25Δ call). Positive = puts more expensive (fear/hedging demand); negative = calls more expensive (complacency/euphoria)."),
    "pc_volume_ratio": ("Put/call vol ratio", "Total put volume / total call volume. High = bearish positioning (often contrarian-bullish at extremes)."),
    "iv_30d": ("IV30 (overlay)", "30-day ATM implied vol. Raw level for context."),
    "iv_3m": ("IV3m (overlay)", "3-month ATM implied vol. Raw level for context."),
    "options_vol_vs_20d": ("Options vol vs 20d (overlay)", "Today's total options volume / 20d rolling avg. >2x is unusual activity."),
    "hf_count_13f": ("HF count 13F (overlay)", "# of curated HFs holding the name."),
    "hf_top_concentration": ("HF top-5 concentration (overlay)", "Top-5 HFs' $ as % of total HF $ in name."),
    "hf_count_change_4q": ("HF count Δ4q (overlay)", "Q/Q change in HF holders."),
}


def render_summary_table(df: pd.DataFrame, title: str, subtitle: str = "",
                          empty_msg: str = "(none)", panel_id: str = "") -> str:
    if df.empty:
        return f'<div class="panel" id="{panel_id}"><h3>{title}</h3>{f"<p class=hint>{subtitle}</p>" if subtitle else ""}<p class=empty>{empty_msg}</p></div>'

    rows = []
    for _, r in df.iterrows():
        late = "🔥" if r.get("flag_late_signal") == 1 else ""
        wash = "❄️" if r.get("flag_washout") == 1 else ""
        ern = "📅" if r.get("flag_earnings_soon") == 1 else ""
        chg = r.get("temp_7d_chg")
        chg_str = f"{chg:+.1f}" if pd.notna(chg) else "—"
        chg_class = "chg-up" if (pd.notna(chg) and chg > 0) else ("chg-down" if pd.notna(chg) and chg < 0 else "")
        ticker = r["ticker"]
        name = (r.get("name") or "")[:38]
        tcls = temp_class(r.get("temperature"))
        rows.append(f"""
            <tr data-ticker="{ticker}">
                <td><a href="#t-{ticker}" class=ticker-pill>{ticker}</a></td>
                <td class=name>{name}</td>
                <td class="num temp {tcls}">{fmt(r.get('temperature'))}</td>
                {univpct_cell(r.get('temp_univpct'))}
                <td class="num {chg_class}">{chg_str}</td>
                {quad_cell(r)}
                {selfpct_cell(r.get('temp_selfpct_1y'), r.get('temp_selfz_1y'), r.get('temp_selfpct_6m'), label='Temp')}
                {selfpct_cell(r.get('extech_selfpct_1y'), r.get('extech_selfz_1y'), r.get('extech_selfpct_6m'), label='Pos+Opt', note=EXTECH_CELL_NOTE)}
                <td class=num>{fmt(r.get('score_positioning'))}</td>
                <td class=num>{fmt(r.get('score_technical'))}</td>
                <td class=num>{fmt(r.get('score_options'))}</td>
                <td class="num anom">{fmt(r.get('anomaly_count'), places=0)}</td>
                <td class=flagcol>{late}{wash}{ern}</td>
            </tr>
        """)
    return f"""
    <div class="panel" id="{panel_id}">
        <h3>{title}</h3>
        {f'<p class=hint>{subtitle}</p>' if subtitle else ''}
        <div class="table-wrap">
        <table class=rank>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Name</th>
                    <th class=num title="Composite 0-100. High=hot/late (contrarian-bearish). Low=cold/washed (contrarian-bullish). NOTE: this scale is compressed — read Univ %ile beside it.">Temp</th>
                    <th class=num title="{UNIVPCT_HDR_TITLE}">{UNIVPCT_COL}</th>
                    <th class=num title="7-day change in temperature">7d Δ</th>
                    <th class=num title="{QUAD_HDR_TITLE}">Setup</th>
                    <th class=num title="Temperature vs this name's OWN trailing 1-year range (percentile, 0-100). High = hot for itself; low = washed-out for itself — surfaces structurally cool/hot names that never stand out cross-sectionally. Hover a cell for the z-score and 6-month read.">Self 1y</th>
                    <th class=num title="{EXTECH_HDR_TITLE}">{EXTECH_COL}</th>
                    <th class=num title="Positioning & crowding: short interest, insider flow, and float turnover (long/retail crowding). Best-validated pillar — see the 📖 How to read it tab.">Pos</th>
                    <th class=num title="Technical / price-revealed sentiment">Tech</th>
                    <th class=num title="Options sentiment bucket (IV rank, skew, term slope, P/C). Small sample — see the 📖 How to read it tab.">Opt</th>
                    <th class=num title="# signals at 90th+ %ile vs the full TMT universe">Anom</th>
                    <th title="🔥 late · ❄️ wash · 📅 earnings within 14d">Flags</th>
                </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
        </div>
    </div>
    """


def _render_6m_chart(series: list) -> str:
    """Larger SVG line chart of temperature over the last ~6 months.
    series = list of (date_str, value) tuples."""
    if not series or len(series) < 5:
        return ""
    w, h = 700, 140
    pad_l, pad_r, pad_t, pad_b = 30, 8, 12, 24
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    n = len(series)
    vals = [v for _, v in series]
    mn, mx = 0, 100  # fixed scale 0-100 for temperature
    # Bands at 30/70
    y30 = pad_t + (1 - 30 / 100) * plot_h
    y70 = pad_t + (1 - 70 / 100) * plot_h
    y50 = pad_t + (1 - 50 / 100) * plot_h
    pts = []
    for i, (_, v) in enumerate(series):
        x = pad_l + i * plot_w / (n - 1)
        y = pad_t + (1 - v / 100) * plot_h
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(pts)
    last_v = vals[-1]
    last_color = "#dc2626" if last_v >= 70 else ("#10b981" if last_v <= 30 else "#6366f1")
    # X-axis labels: first / midpoint / last date
    first_d, mid_d, last_d = series[0][0], series[n // 2][0], series[-1][0]
    return f"""
    <svg class=spark-6m width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-label="6-month temperature chart">
      <!-- Reference bands -->
      <rect x="{pad_l}" y="{pad_t}" width="{plot_w}" height="{y70 - pad_t:.1f}" fill="#fef2f2"/>
      <rect x="{pad_l}" y="{y30:.1f}" width="{plot_w}" height="{plot_h - (y30 - pad_t):.1f}" fill="#f0fdf4"/>
      <line x1="{pad_l}" y1="{y50:.1f}" x2="{w - pad_r}" y2="{y50:.1f}" stroke="#cbd5e1" stroke-dasharray="3,3" stroke-width="0.5"/>
      <line x1="{pad_l}" y1="{y30:.1f}" x2="{w - pad_r}" y2="{y30:.1f}" stroke="#10b981" stroke-dasharray="2,2" stroke-width="0.5" opacity="0.6"/>
      <line x1="{pad_l}" y1="{y70:.1f}" x2="{w - pad_r}" y2="{y70:.1f}" stroke="#dc2626" stroke-dasharray="2,2" stroke-width="0.5" opacity="0.6"/>
      <!-- Y-axis labels -->
      <text x="2" y="{pad_t + 4}" font-size="10" fill="#94a3b8">100</text>
      <text x="2" y="{y70 + 3:.1f}" font-size="10" fill="#dc2626">70</text>
      <text x="2" y="{y50 + 3:.1f}" font-size="10" fill="#94a3b8">50</text>
      <text x="2" y="{y30 + 3:.1f}" font-size="10" fill="#10b981">30</text>
      <text x="2" y="{h - pad_b + 4}" font-size="10" fill="#94a3b8">0</text>
      <!-- Line -->
      <polyline fill="none" stroke="{last_color}" stroke-width="1.5" points="{polyline}" />
      <circle cx="{pts[-1].split(',')[0]}" cy="{pts[-1].split(',')[1]}" r="3" fill="{last_color}"/>
      <!-- X-axis labels -->
      <text x="{pad_l}" y="{h - 6}" font-size="10" fill="#94a3b8">{first_d}</text>
      <text x="{pad_l + plot_w / 2 - 35}" y="{h - 6}" font-size="10" fill="#94a3b8">{mid_d}</text>
      <text x="{w - pad_r - 60}" y="{h - 6}" font-size="10" fill="#94a3b8">{last_d}</text>
    </svg>
    """


def _render_bucket_chart(series: list) -> str:
    """Multi-line SVG of the three composite bucket scores over the last ~6 months.
    series = list of (date_str, positioning, technical, options); any score may be None."""
    if not series or len(series) < 5:
        return ""
    w, h = 700, 140
    pad_l, pad_r, pad_t, pad_b = 30, 78, 12, 24
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    n = len(series)
    y50 = pad_t + 0.5 * plot_h

    def line_for(idx, color):
        pts = []
        for i, row in enumerate(series):
            v = row[idx]
            if v is None:
                continue
            x = pad_l + i * plot_w / (n - 1)
            y = pad_t + (1 - v / 100) * plot_h
            pts.append(f"{x:.1f},{y:.1f}")
        if len(pts) < 2:
            return ""
        return f'<polyline fill="none" stroke="{color}" stroke-width="1.4" points="{" ".join(pts)}" />'

    series_defs = [(1, "#6366f1", "Positioning"), (2, "#0891b2", "Technical"), (3, "#d97706", "Options")]
    lines = "".join(line_for(idx, c) for idx, c, _ in series_defs)
    legend = "".join(
        f'<g transform="translate({w - pad_r + 6},{pad_t + 8 + k * 16})">'
        f'<line x1="0" y1="0" x2="14" y2="0" stroke="{c}" stroke-width="2"/>'
        f'<text x="18" y="3" font-size="9" fill="#475569">{label}</text></g>'
        for k, (_, c, label) in enumerate(series_defs)
    )
    first_d, mid_d, last_d = series[0][0], series[n // 2][0], series[-1][0]
    return f"""
    <svg class=spark-6m width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-label="6-month bucket-score chart">
      <line x1="{pad_l}" y1="{y50:.1f}" x2="{pad_l + plot_w}" y2="{y50:.1f}" stroke="#cbd5e1" stroke-dasharray="3,3" stroke-width="0.5"/>
      <text x="2" y="{pad_t + 4}" font-size="10" fill="#94a3b8">100</text>
      <text x="2" y="{y50 + 3:.1f}" font-size="10" fill="#94a3b8">50</text>
      <text x="2" y="{h - pad_b + 4}" font-size="10" fill="#94a3b8">0</text>
      {lines}
      {legend}
      <text x="{pad_l}" y="{h - 6}" font-size="10" fill="#94a3b8">{first_d}</text>
      <text x="{pad_l + plot_w / 2 - 35}" y="{h - 6}" font-size="10" fill="#94a3b8">{mid_d}</text>
      <text x="{pad_l + plot_w - 60}" y="{h - 6}" font-size="10" fill="#94a3b8">{last_d}</text>
    </svg>
    """


def render_live_performance() -> str:
    """Forward-only (genuine out-of-sample) performance of the logged decile book,
    headlined; in-sample backfill shown separately as context only. Realized 21-day
    market-neutral long/short on non-overlapping matured cohorts."""
    H = 21
    conn = connect()
    bl = pd.read_sql_query("SELECT date,ticker,side,source FROM book_log", conn, parse_dates=["date"])
    px = pd.read_sql_query("SELECT ticker,date,adj_close FROM prices", conn, parse_dates=["date"]).pivot(
        index="date", columns="ticker", values="adj_close").sort_index()
    conn.close()
    fwd = px.shift(-H) / px - 1.0
    pos = {d: i for i, d in enumerate(px.index)}

    def stats(sub):
        cohort_dates = sorted(d for d in sub["date"].unique() if d in pos)
        picked, last_i, ls = [], -10 ** 9, []
        for d in cohort_dates:
            i = pos[d]
            if i - last_i >= H and i + H < len(px.index):  # non-overlapping + matured
                longs = sub[(sub.date == d) & (sub.side == "long")]["ticker"]
                shorts = sub[(sub.date == d) & (sub.side == "short")]["ticker"]
                lr = fwd.loc[d, fwd.columns.intersection(longs)].mean()
                sr = fwd.loc[d, fwd.columns.intersection(shorts)].mean()
                if pd.notna(lr) and pd.notna(sr):
                    ls.append(lr - sr)
                    picked.append(d)
                    last_i = i
        if len(ls) < 2:
            return None
        a = np.array(ls, float)
        m, n = np.nanmean(a), int(np.isfinite(a).sum())
        return {"mean": m, "ann": m * 12, "hit": float(np.mean(a > 0)),
                "t": m / np.nanstd(a) * np.sqrt(n) if n > 1 else float("nan"), "n": n,
                "first": min(picked).strftime("%Y-%m-%d"), "last": max(picked).strftime("%Y-%m-%d")}

    live = stats(bl[bl.source == "live"]) if not bl.empty else None
    n_live_days = bl[bl.source == "live"]["date"].nunique() if not bl.empty else 0

    # Headline: forward-only (genuine OOS)
    if live:
        s, cls = live, ("chg-up" if live["mean"] > 0 else "chg-down")
        head = f"""
      <p class=hint>Realized 21-day <b>market-neutral long/short</b> of the logged decile book (bottom-decile longs minus top-decile shorts) on <b>{s['n']} non-overlapping forward cohorts</b>, {s['first']} to {s['last']} — weights frozen, never fit on these returns. This is the genuine test.</p>
      <table class=signals style="max-width:520px"><tbody>
        <tr><td>Avg L/S per cohort (21d)</td><td class="num mono {cls}">{s['mean']:+.2%}</td></tr>
        <tr><td>Annualized</td><td class="num mono {cls}">{s['ann']:+.1%}</td></tr>
        <tr><td>Hit rate</td><td class="num mono">{s['hit']:.0%}</td></tr>
        <tr><td>t-stat</td><td class="num mono">{s['t']:+.2f}</td></tr>
        <tr><td>Forward cohorts</td><td class="num mono">{s['n']}</td></tr>
      </tbody></table>"""
    else:
        head = (f'<p class=hint><b>Accumulating live, no results yet.</b> {n_live_days} forward day(s) logged; '
                f'each cohort needs ~{H} trading days to mature, so genuine out-of-sample numbers start appearing '
                f'about a month after launch and build from there. (This panel deliberately shows <em>only</em> '
                f'forward-logged data — the in-sample history below is context, not validation.)</p>')

    # Context only: in-sample backfill, clearly demoted
    back = stats(bl[bl.source == "backfill"]) if not bl.empty else None
    ctx = ""
    if back:
        ctx = (f'<p class=hint style="margin-top:0.5rem;border-top:1px solid var(--border);padding-top:0.5rem;">'
               f'<b>In-sample context (not a track record):</b> applied to history ({back["n"]} cohorts, '
               f'{back["first"]}–{back["last"]}) the current model\'s book returned {back["ann"]:+.1%}/yr '
               f'market-neutral — but the weights were tuned on this period, so it\'s <em>optimistic and not '
               f'out-of-sample</em>. The walk-forward (Methodology card) is the honest backtest; this live panel '
               f'is the honest forward test.</p>')

    return f"""
    <div class=panel>
      <h3>🔬 Live forward performance (out-of-sample only)</h3>
      {head}
      {ctx}
    </div>
    """


def _ord(n) -> str:
    """Ordinal string: 1->1st, 22->22nd, 13->13th."""
    n = int(round(n))
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def render_model_book(snap: pd.DataFrame) -> str:
    """Candidate contrarian book: the temperature decile extremes — where the
    factor-neutral long/short spread is measured (modest in-sample, unreliable out-of-sample). Bottom
    decile (washed-out) = candidate LONGS; top decile (crowded) = candidate
    SHORTS/avoids. Meant to be traded market/sector-neutral; a screen, not advice."""
    d = snap.dropna(subset=["temperature"]).copy()
    if d.empty:
        return "<div class=panel><p class=empty>No composite data.</p></div>"
    n = len(d)
    lo_cut, hi_cut = d["temperature"].quantile(0.10), d["temperature"].quantile(0.90)
    longs = d[d["temperature"] <= lo_cut].sort_values("temperature").head(25)
    shorts = d[d["temperature"] >= hi_cut].sort_values("temperature", ascending=False).head(25)

    def rows(df):
        out = []
        for _, r in df.iterrows():
            chg = r.get("temp_7d_chg")
            chg_str = f"{chg:+.1f}" if pd.notna(chg) else "—"
            out.append(
                f"<tr data-ticker='{r['ticker']}'>"
                f"<td><a href='#t-{r['ticker']}' class=ticker-pill onclick=\"showTab('detail')\">{r['ticker']}</a></td>"
                f"<td class=name>{(r.get('name') or '')[:34]}</td>"
                f"<td class=mono>{r.get('cluster_id') or '—'}</td>"
                f"<td class='num temp {temp_class(r['temperature'])}'>{fmt(r['temperature'])}</td>"
                f"<td class=num>{fmt(r.get('score_positioning'))}</td>"
                f"<td class=num>{fmt(r.get('score_technical'))}</td>"
                f"<td class=num>{fmt(r.get('score_options'))}</td>"
                f"<td class=num>{chg_str}</td></tr>")
        return "".join(out)

    head = ("<tr><th>Ticker</th><th>Name</th><th>Cluster</th><th class=num>Temp</th>"
            "<th class=num>Pos</th><th class=num>Tech</th><th class=num>Opt</th><th class=num>7d Δ</th></tr>")
    return f"""
    <div class=panel>
      <h3>📕 Model book — candidate contrarian basket</h3>
      <p class=hint>The temperature decile extremes: <b>bottom-decile</b> (most washed-out) = candidate <b>longs</b>; <b>top-decile</b> (most crowded) = candidate <b>shorts / avoids</b>, meant to be viewed market/sector-neutral (balance $ and clusters across the two sides). <b>Important caveat:</b> the decile long/short was modestly positive <em>in-sample</em> (~+4%/yr) but is <b>unreliable out-of-sample</b> in walk-forward testing (noisy, ~flat, swings widely with the sample) — so this is an <b>idea-generation screen, not a strategy and not advice</b>. The underlying rank signal is weak; pair with fundamentals and don't trade these lists standalone.</p>
      <div class=book-grid>
        <div>
          <h4 class=chg-up>🟢 Candidate longs — washed-out (bottom decile, temp ≤ {lo_cut:.0f})</h4>
          <div class=table-wrap><table class=rank><thead>{head}</thead><tbody>{rows(longs)}</tbody></table></div>
        </div>
        <div>
          <h4 class=chg-down>🔴 Candidate shorts / avoids — crowded (top decile, temp ≥ {hi_cut:.0f})</h4>
          <div class=table-wrap><table class=rank><thead>{head}</thead><tbody>{rows(shorts)}</tbody></table></div>
        </div>
      </div>
      <p class=hint>Showing the {len(longs)} coldest and {len(shorts)} hottest of {n} names (decile ≈ {n // 10} each).</p>
    </div>
    """


def render_score_narrative(snap_row, sig_long) -> str:
    """Plain-language, rule-based summary of a ticker's score — what it reads and
    what's driving it. Deterministic (no LLM): composed from the temperature,
    bucket scores, the most extreme signals, and the flags."""
    t = snap_row.get("temperature")
    if t is None or pd.isna(t):
        return ""
    if t >= 85:
        head = "screening <b>extremely hot</b> — crowded and late-stage (contrarian-bearish)"
    elif t >= 70:
        head = "screening <b>hot</b> — crowded positioning (contrarian-bearish)"
    elif t >= 55:
        head = "leaning <b>warm</b>"
    elif t > 45:
        head = "roughly <b>neutral</b>"
    elif t > 30:
        head = "leaning <b>cool</b>"
    elif t > 15:
        head = "screening <b>cold</b> — washed-out (contrarian-bullish)"
    else:
        head = "screening <b>extremely cold</b> — deeply washed-out (contrarian-bullish)"

    label = {"positioning": "positioning/crowding", "technical": "technicals", "options": "options sentiment"}
    present = [(n, snap_row.get(c)) for n, c in
              [("positioning", "score_positioning"), ("technical", "score_technical"), ("options", "score_options")]
              if snap_row.get(c) is not None and not pd.isna(snap_row.get(c))]
    present.sort(key=lambda x: x[1], reverse=True)

    def desc(v):
        return "hot" if v >= 70 else "elevated" if v >= 55 else "neutral" if v > 45 else "soft" if v > 30 else "cold"

    drivers = ""
    if present:
        hi, lo = present[0], present[-1]
        if len(present) >= 2 and (hi[1] - lo[1]) >= 25:
            drivers = (f"It's a tug-of-war: {label[hi[0]]} {desc(hi[1])} ({hi[1]:.0f}) "
                       f"vs {label[lo[0]]} {desc(lo[1])} ({lo[1]:.0f}).")
        else:
            drivers = f"Driven mostly by {label[hi[0]]} at {hi[1]:.0f}."

    comp = pd.DataFrame()
    if sig_long is not None and not sig_long.empty:
        df = sig_long.copy()
        df["dual"] = df[["pct_self", "pct_peer"]].mean(axis=1)
        comp = df[df["bucket"].isin(["positioning", "technical", "options"])].dropna(subset=["dual"])

    def lbl(sn):
        return SIGNAL_DESCRIPTIONS.get(sn, (sn, ""))[0]

    sig_bits = []
    if not comp.empty:
        hot = comp.nlargest(1, "dual").iloc[0]
        cold = comp.nsmallest(1, "dual").iloc[0]
        if hot["dual"] >= 70:
            sig_bits.append(f"hottest is {lbl(hot['signal_name'])} ({_ord(hot['dual'])} %ile)")
        if cold["dual"] <= 30:
            sig_bits.append(f"coldest is {lbl(cold['signal_name'])} ({_ord(cold['dual'])} %ile)")

    flag_bits = []
    if snap_row.get("flag_divergence") == 1:
        flag_bits.append("price strength not confirmed by options (divergence)")
    if snap_row.get("flag_late_signal") == 1:
        flag_bits.append("late-signal (temp ≥ 85)")
    if snap_row.get("flag_washout") == 1:
        flag_bits.append("washout (temp ≤ 15)")
    if snap_row.get("flag_earnings_soon") == 1:
        flag_bits.append("earnings within ~2 weeks")

    # V1.21: lead with the cross-sectional standing, because the raw 0-100 is
    # compressed toward 50 and reads far milder than it is.
    up = snap_row.get("temp_univpct")
    up_txt = ""
    if up is not None and not pd.isna(up):
        up_txt = f" That is the <b>{_ord(up)} percentile</b> of the TMT universe today."

    quad_txt = ""
    if (snap_row.get("quad_label") or "·") != "·":
        quad_txt = (f"Setup: <b>{snap_row['quad_label']}</b> — "
                    f"{snap_row.get('quad_title', '').split(' Best')[0].split(' Worst')[0].strip()}")

    parts = [f"<b>{t:.0f}/100</b> — {head}.{up_txt}", drivers]
    if quad_txt:
        parts.append(quad_txt)
    if sig_bits:
        parts.append("Key signals: " + "; ".join(sig_bits) + ".")
    if flag_bits:
        parts.append("Flags: " + ", ".join(flag_bits) + ".")

    # V1.18: reframe the absolute read against the name's OWN trailing 1y range.
    sp1 = snap_row.get("temp_selfpct_1y")
    sz1 = snap_row.get("temp_selfz_1y")
    sp6 = snap_row.get("temp_selfpct_6m")
    if sp1 is not None and not pd.isna(sp1):
        z_bit = f" ({float(sz1):+.1f}σ)" if (sz1 is not None and not pd.isna(sz1)) else ""
        sixm_bit = f"; 6mo at the {_ord(sp6)}" if (sp6 is not None and not pd.isna(sp6)) else ""
        opt_caveat = ""
        if snap_row.get("score_options") is not None and not pd.isna(snap_row.get("score_options")):
            opt_caveat = (" <span class=basis>(options data began 2026, so the 1y temp baseline is "
                          "partly pre-options — lean on the clean positioning/technical reads below.)</span>")
        tup = snap_row.get("temp_univpct")
        univ_bit = (f" It sits at the {_ord(tup)} %ile <b>across TMT today</b>."
                    if (tup is not None and not pd.isna(tup)) else "")
        parts.append(
            f"<b>Vs its own past year</b>, Temp is at the {_ord(sp1)} %ile{z_bit} — "
            f"{selfpct_word(sp1)}{sixm_bit}.{univ_bit}{opt_caveat}"
        )

    # V1.20: the same own-history lens with TECHNICALS STRIPPED OUT (positioning +
    # options only). Separates "extreme for itself because it has rallied" from
    # "extreme for itself on crowding / options hedging" — the gap vs the headline
    # Self 1y is the interesting part, so state it explicitly.
    xp1 = snap_row.get("extech_selfpct_1y")
    if xp1 is not None and not pd.isna(xp1):
        xz1 = snap_row.get("extech_selfz_1y")
        xz_bit = f" ({float(xz1):+.1f}σ)" if (xz1 is not None and not pd.isna(xz1)) else ""
        gap_bit = ""
        if sp1 is not None and not pd.isna(sp1):
            gap = float(xp1) - float(sp1)
            if gap <= -15:
                gap_bit = (" — well below the headline read, so much of the Temperature's "
                           "own-history extremity is <b>price action, not positioning</b>")
            elif gap >= 15:
                gap_bit = (" — well above the headline read: <b>positioning/options are more "
                           "stretched than price</b> suggests")
            else:
                gap_bit = " — broadly in line with the headline read, so the two agree"
        parts.append(
            f"<b>Ex-technicals</b> (positioning + options only), it sits at the {_ord(xp1)} %ile"
            f"{xz_bit} vs its own year{gap_bit}. "
            f"<span class=basis>(0.625 Pos / 0.375 Opt; options history starts 2026-05-12, so the "
            f"earlier part of the window is positioning-only.)</span>"
        )
    body = " ".join(p for p in parts if p)

    # Per-pillar color: one line each for positioning / technical / options
    interp = {
        # Cold phrases describe the SHORT/insider side only — float-turnover (churn)
        # is a separate sub-signal that can diverge, so it's surfaced explicitly below
        # rather than asserted here (avoids "low churn" when churn is actually high).
        "positioning": ("crowded — heavy short- or long-side positioning", "light short-side positioning (few shorts / low insider selling)"),
        "technical": ("extended / strong momentum", "weak / washed-out price action"),
        "options": ("rich — fear/skew or call euphoria", "calm / complacent"),
    }
    col_name = {"positioning": "score_positioning", "technical": "score_technical", "options": "score_options"}
    pillar_rows = []
    for bname in ["positioning", "technical", "options"]:
        score = snap_row.get(col_name[bname])
        if score is None or pd.isna(score):
            if bname == "options":
                pillar_rows.append('<li class=muted><b>Options sentiment</b> — no options data for this name yet.</li>')
            continue
        lead = interp[bname][0] if score >= 55 else interp[bname][1] if score <= 45 else "middling"
        bits = ""
        if not comp.empty:
            bdf = comp[comp["bucket"] == bname].copy()
            if not bdf.empty:
                hot_one = bdf[bdf["dual"] >= 70].nlargest(1, "dual")
                cold_one = bdf[bdf["dual"] <= 30].nsmallest(1, "dual")
                diverges = not hot_one.empty and not cold_one.empty
                if diverges:
                    # Bucket has both a hot and a cold signal — always show one of each
                    # so a divergent signal (e.g. high churn inside a cold bucket) is visible.
                    picks = pd.concat([hot_one, cold_one])
                else:
                    bdf["dist"] = (bdf["dual"] - 50).abs()
                    picks = bdf.sort_values("dist", ascending=False).head(2)
                sb = []
                for _, r in picks.iterrows():
                    dd = r["dual"]
                    word = "high" if dd >= 60 else "low" if dd <= 40 else "mid"
                    sb.append(f"{lbl(r['signal_name'])} {word} ({_ord(dd)})")
                if sb:
                    bits = " — " + ", ".join(sb)
                if diverges:
                    bits += ' <b class=chg-down>(signals diverge)</b>'
        basis = "score = 50/50 own-5yr + TMT-universe blend of the pillar's signals"
        # V1.18/V1.19: show each pillar's standing on THREE lenses — its rank vs
        # the TMT universe today (*_univpct), and vs the name's OWN trailing 1y/6m
        # history (*_selfpct_*; clean ~10y history for positioning/technical,
        # shorter for options).
        prefix = {"positioning": "pos", "technical": "tech", "options": "opt"}[bname]
        up = snap_row.get(f"{prefix}_univpct")
        bp1 = snap_row.get(f"{prefix}_selfpct_1y")
        bp6 = snap_row.get(f"{prefix}_selfpct_6m")
        bz1 = snap_row.get(f"{prefix}_selfz_1y")
        pctile_parts = []
        if up is not None and not pd.isna(up):
            pctile_parts.append(f"vs TMT {_ord(up)}")
        bword = selfpct_word(bp1)
        if bword:
            zb = f" {float(bz1):+.1f}σ" if (bz1 is not None and not pd.isna(bz1)) else ""
            six = f" / 6m {_ord(bp6)}" if (bp6 is not None and not pd.isna(bp6)) else ""
            pctile_parts.append(f"vs own 1y {_ord(bp1)}{zb}{six} ({bword})")
        pctile_bit = (' <b class=basis>· ' + ' · '.join(pctile_parts) + '</b>') if pctile_parts else ''
        pillar_rows.append(
            f'<li><b>{label[bname].capitalize()} {score:.0f} ({desc(score)})</b>{pctile_bit} — {lead}{bits} '
            f'<span class=basis>({basis})</span>.</li>')
    pillars_html = f'<ul class=pillars>{"".join(pillar_rows)}</ul>' if pillar_rows else ""

    thin_banner = ""
    if snap_row.get("thin_history"):
        nd = int(snap_row.get("price_days") or 0)
        ns = int(snap_row.get("n_signals") or 0)
        thin_banner = (
            f'<p class="thin-banner">🆕 <b>New listing — insufficient history.</b> '
            f'Scored on only {ns} live signal{"" if ns == 1 else "s"} over {nd} trading '
            f'day{"" if nd == 1 else "s"}, so the composite is <b>provisional</b> and this '
            f'name is held out of the hottest / movers / flag rankings until it matures '
            f'(no short-interest, insider, options, or long-horizon technical history yet).</p>')

    return (f'<div class="score-narrative"><h4>📝 In a nutshell</h4>'
            f'{thin_banner}<p>{body}</p>{pillars_html}</div>')


def render_drilldown(snap_row, sig_long, est_row, earnings_row, actions,
                     sparkline, chart_series, notes_row, sector_groups, cluster_mates, sector_mates,
                     bucket_series=None,
                     bucket_weights=None, signal_weights=None, signal_to_bucket=None) -> str:
    t = snap_row["ticker"]
    name = snap_row.get("name") or t

    bucket_chart_svg = _render_bucket_chart(bucket_series) if bucket_series else ""
    bucket_chart_html = (
        '<div class=chart-card><div class=chart-card-label>📊 Bucket scores, last 6 months '
        f'(Positioning / Technical / Options, 0–100)</div>{bucket_chart_svg}</div>'
        if bucket_chart_svg else ""
    )
    narrative_html = render_score_narrative(snap_row, sig_long)

    spark_svg = ""
    if sparkline and len(sparkline) > 1:
        w, h, pad = 280, 60, 4
        mn = min(sparkline)
        mx = max(sparkline)
        rng = (mx - mn) or 1
        pts = []
        for i, v in enumerate(sparkline):
            x = pad + i * (w - 2 * pad) / (len(sparkline) - 1)
            y = h - pad - (v - mn) / rng * (h - 2 * pad)
            pts.append(f"{x:.1f},{y:.1f}")
        polyline = " ".join(pts)
        last_v = sparkline[-1]
        last_color = "#dc2626" if last_v >= 70 else ("#10b981" if last_v <= 30 else "#6366f1")
        # Reference line at temperature 50
        y50 = h - pad - (50 - mn) / rng * (h - 2 * pad) if mn <= 50 <= mx else None
        ref_line = f'<line x1="{pad}" y1="{y50:.1f}" x2="{w - pad}" y2="{y50:.1f}" stroke="#e2e8f0" stroke-dasharray="3,3"/>' if y50 else ""
        spark_svg = f"""
        <svg class=spark width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-label="30-day temperature sparkline">
            {ref_line}
            <polyline fill="none" stroke="{last_color}" stroke-width="2" points="{polyline}" />
            <circle cx="{pts[-1].split(',')[0]}" cy="{pts[-1].split(',')[1]}" r="3" fill="{last_color}"/>
        </svg>
        <div class=spark-meta>last {len(sparkline)} days · range {mn:.0f}–{mx:.0f}</div>
        """

    sig_rows = []
    if not sig_long.empty:
        for _, sr in sig_long.iterrows():
            sn = sr["signal_name"]
            label, sdesc = SIGNAL_DESCRIPTIONS.get(sn, (sn, ""))
            ps = sr.get("pct_self")
            pp = sr.get("pct_peer")
            ps_cls = temp_class(ps) if ps is not None else ""
            pp_cls = temp_class(pp) if pp is not None else ""
            label_cell = (f'<td class=sig-label title="{html_escape(sdesc)}">{label} <span class=info-dot>ⓘ</span></td>'
                          if sdesc else f'<td>{label}</td>')
            sig_rows.append(f"""
                <tr>
                    {label_cell}
                    <td class=mono>{sr['bucket']}</td>
                    <td class="num mono">{fmt(sr['raw_value'], 4)}</td>
                    <td class="num {ps_cls}">{fmt(ps)}</td>
                    <td class="num {pp_cls}">{fmt(pp)}</td>
                </tr>
            """)
    sig_table = f"""
        <h4>📊 Signal-by-signal breakdown</h4>
        <p class=hint>Each signal is ranked vs (a) its own 5y history and (b) the full TMT universe today. The two are blended 50/50 to form a per-signal score, which is then weighted by the signal-weight column to form the bucket score.</p>
        <table class=signals>
            <thead><tr><th>Signal</th><th>Bucket</th><th class=num>Raw value</th>
                <th class=num title="Percentile of this signal vs THIS stock's own 5-year history (is it extended vs its own norm?)">%ile vs own 5y</th>
                <th class=num title="Percentile of this signal vs ALL TMT names today (is it extended vs peers right now?)">%ile vs TMT peers</th></tr></thead>
            <tbody>{''.join(sig_rows) if sig_rows else '<tr><td colspan=5 class=empty>(no signals)</td></tr>'}</tbody>
        </table>
    """

    # === Score-breakdown card: explicit formula + contributions ===
    breakdown_html = ""
    if bucket_weights and signal_to_bucket:
        pos = snap_row.get("score_positioning")
        tech = snap_row.get("score_technical")
        opt = snap_row.get("score_options")
        temp = snap_row.get("temperature")

        # Active buckets (those present today)
        buckets_present = []
        if pd.notna(pos):
            buckets_present.append(("positioning", pos, bucket_weights.get("positioning", 0)))
        if pd.notna(tech):
            buckets_present.append(("technical", tech, bucket_weights.get("technical", 0)))
        if pd.notna(opt):
            buckets_present.append(("options", opt, bucket_weights.get("options", 0)))

        # Effective weights after renormalization for missing buckets
        total_w = sum(w for _, _, w in buckets_present) or 1.0
        bucket_raw_w = {b: w for b, _, w in buckets_present}
        bucket_rows = []
        for bkt, score, raw_w in buckets_present:
            eff_w = raw_w / total_w
            contribution = score * eff_w
            bucket_rows.append(f"""
                <tr>
                    <td><b>{bkt.capitalize()}</b></td>
                    <td class="num mono">{score:.1f}</td>
                    <td class="num mono">{raw_w:.2f}</td>
                    <td class="num mono">{eff_w:.3f}</td>
                    <td class="num mono">{contribution:.2f}</td>
                </tr>
            """)

        # Per-signal breakdown within each bucket
        per_signal_html = ""
        if signal_weights and not sig_long.empty:
            for bkt in [b for b, _, _ in buckets_present]:
                bkt_sigs = sig_long[sig_long["bucket"] == bkt].copy()
                if bkt_sigs.empty:
                    continue
                # Pass 1: collect the signals actually present today + total weight,
                # so we can show each signal's NORMALIZED share of the bucket and its
                # effective share of the whole composite (within-bucket × bucket weight).
                present = []  # (sn, dual, sw)
                total_sw = 0
                weighted_total = 0
                for _, sr in bkt_sigs.iterrows():
                    sn = sr["signal_name"]
                    ps = sr.get("pct_self")
                    pp = sr.get("pct_peer")
                    # Recreate dual percentile (50/50 by default) — use whichever is present
                    if pd.notna(ps) and pd.notna(pp):
                        dual = 0.5 * ps + 0.5 * pp
                    elif pd.notna(ps):
                        dual = ps
                    elif pd.notna(pp):
                        dual = pp
                    else:
                        dual = None
                    sw = signal_weights.get(sn, 1.0)
                    if dual is None:
                        continue
                    present.append((sn, dual, sw))
                    total_sw += sw
                    weighted_total += sw * dual

                if present and total_sw > 0:
                    final_bkt = weighted_total / total_sw
                    eff_bw = bucket_raw_w.get(bkt, 0.0) / total_w  # bucket's share of composite

                    def _read(d):
                        # dual percentiles are temperature-oriented (high = pushes HOT),
                        # so HOT/COLD here is direction-safe for every signal.
                        if d >= 70:
                            return ('<span class=chg-down><b>HOT</b></span>', 'hot')
                        if d <= 30:
                            return ('<span class=chg-up><b>COLD</b></span>', 'cold')
                        return ('<span class=muted>neutral</span>', 'neutral')

                    # Pass 2: build rows now that total_sw / eff_bw are known
                    rows = []
                    hot_n = cold_n = 0
                    for sn, dual, sw in present:
                        in_bucket = sw / total_sw            # share of THIS bucket (sums to 1)
                        comp_wt = in_bucket * eff_bw          # share of the whole Temperature
                        label = SIGNAL_DESCRIPTIONS.get(sn, (sn, ""))[0]
                        read_html, read_kind = _read(dual)
                        hot_n += read_kind == "hot"
                        cold_n += read_kind == "cold"
                        rows.append(f"""
                        <tr>
                            <td>{label}</td>
                            <td class="num mono">{dual:.1f}</td>
                            <td>{read_html}</td>
                            <td class="num mono">{in_bucket * 100:.1f}%</td>
                            <td class="num mono">{comp_wt * 100:.1f}%</td>
                            <td class="num mono">{(sw * dual):.2f}</td>
                        </tr>
                        """)
                    net_word = ("hot" if final_bkt >= 70 else "warm" if final_bkt >= 55
                                else "neutral" if final_bkt > 45 else "cool" if final_bkt > 30 else "cold")
                    rows.append(f"""
                        <tr style="border-top:2px solid var(--border); font-weight:600">
                            <td>Σ ({bkt} bucket)</td>
                            <td class="num mono">{final_bkt:.1f}</td>
                            <td>{net_word}</td>
                            <td class="num mono">100%</td>
                            <td class="num mono">{eff_bw * 100:.1f}%</td>
                            <td class="num mono">{weighted_total:.2f}</td>
                        </tr>
                    """)
                    nsig = len(present)
                    # Plain-language read of the bucket, incl. internal divergence
                    summary = f"Nets <b>{final_bkt:.0f} ({net_word})</b> — {hot_n} hot, {cold_n} cold"
                    if nsig - hot_n - cold_n:
                        summary += f", {nsig - hot_n - cold_n} neutral"
                    summary += f" of {nsig} signal{'s' if nsig != 1 else ''}."
                    if hot_n and cold_n:
                        summary += (" <b class=chg-down>⚠ Signals diverge</b> — the net score "
                                    "averages out genuine disagreement; check the HOT vs COLD rows below.")
                    per_signal_html += f"""
                        <details>
                        <summary><b>{bkt.capitalize()} bucket — {eff_bw * 100:.0f}% of composite — {nsig} signal{'s' if nsig != 1 else ''}</b></summary>
                        <p class=hint style="margin:.3em 0 .5em">{summary}</p>
                        <p class=hint style="margin:.3em 0 .5em"><b>Read</b> = HOT (≥70th, pushes temperature up / crowded-late) vs COLD (≤30th, washed-out). <b>Wt in bucket</b> = share of the {bkt} bucket (from 1-month factor-neutral IC; sums to 100%). <b>Composite wt</b> = Wt in bucket × {eff_bw * 100:.0f}% = share of the whole Temperature.</p>
                        <table class=signals>
                            <thead><tr>
                                <th>Signal</th>
                                <th class=num>Dual %ile</th>
                                <th title="HOT ≥70th pushes temperature up; COLD ≤30th pulls it down. Hover the signal name for what it measures.">Read</th>
                                <th class=num title="This signal's share within its bucket (sums to 100% across the bucket)">Wt in bucket</th>
                                <th class=num title="Wt in bucket × bucket's weight in composite = share of the whole Temperature">Composite wt</th>
                                <th class=num>Contribution</th>
                            </tr></thead>
                            <tbody>{''.join(rows)}</tbody>
                        </table>
                        </details>
                    """

        breakdown_html = f"""
        <div class=card>
            <h4>🧮 How {t}'s Temperature = {fmt(temp)} was calculated</h4>
            <p class=hint><b>Step 1:</b> Each underlying signal is scored vs own history and the full TMT universe today (50/50 blend) → percentile 0–100. <b>Step 2:</b> Within each bucket, signals are averaged using IC-based weights (stronger contrarian signals dominate). <b>Step 3:</b> Buckets are combined using configured bucket weights, renormalized for any missing buckets.</p>
            <table class=signals>
                <thead><tr>
                    <th>Bucket</th>
                    <th class=num title="Bucket score 0-100">Score</th>
                    <th class=num title="Raw weight from config.yaml">Raw weight</th>
                    <th class=num title="Effective weight after renormalizing for missing buckets">Eff. weight</th>
                    <th class=num title="Score × eff. weight">Contribution</th>
                </tr></thead>
                <tbody>{''.join(bucket_rows)}
                    <tr style="border-top:2px solid var(--border); font-weight:600">
                        <td><b>Temperature</b></td>
                        <td class="num mono"><b>{fmt(temp)}</b></td>
                        <td class=num>—</td>
                        <td class="num mono">1.000</td>
                        <td class="num mono"><b>{fmt(temp)}</b></td>
                    </tr>
                </tbody>
            </table>
            {per_signal_html}
        </div>
        """

    est_html = ""
    if est_row is not None and isinstance(est_row, pd.Series):
        rec_key = est_row.get('recommendation_key', '—') or '—'
        rec_class = "rec-buy" if rec_key in ("strong_buy", "buy") else ("rec-sell" if rec_key in ("sell", "strong_sell") else "")
        ntm_pe = est_row.get('ntm_pe')
        ntm_pe_str = f"{ntm_pe:.1f}x" if pd.notna(ntm_pe) and ntm_pe is not None else "—"
        est_html = f"""
        <div class=card>
            <h4>📊 Live overlay (Yahoo / consensus snapshot — context only, NOT in composite)</h4>
            <div class=overlay-grid>
                <div><span class=overlay-label>NTM P/E</span><span class=overlay-val>{ntm_pe_str}</span></div>
                <div><span class=overlay-label>Forward EPS (NTM)</span><span class=overlay-val>{fmt(est_row.get('forward_eps'), 2)}</span></div>
                <div><span class=overlay-label>Target mean</span><span class=overlay-val>${fmt(est_row.get('target_mean_price'), 2)}</span></div>
                <div><span class=overlay-label>Target dispersion</span><span class=overlay-val>{fmt(est_row.get('target_dispersion'), 2)}</span></div>
                <div><span class=overlay-label># analysts</span><span class=overlay-val>{fmt_int(est_row.get('num_analyst_opinions'))}</span></div>
                <div><span class=overlay-label>Recommendation</span><span class="overlay-val {rec_class}">{rec_key} ({fmt(est_row.get('recommendation_mean'), 2)})</span></div>
            </div>
        </div>
        """

    erng_html = ""
    if earnings_row is not None:
        nd = earnings_row.get("next_earnings_date") if hasattr(earnings_row, "get") else None
        if nd:
            erng_html = f'<div class=tag-earnings>📅 Next earnings: <b>{nd}</b></div>'

    act_html = ""
    if not actions.empty:
        act_rows = []
        for _, ar in actions.head(10).iterrows():
            act_rows.append(f"<tr><td class=mono>{ar['action_date']}</td><td>{ar['firm']}</td><td>{ar['from_grade'] or '—'} → {ar['to_grade'] or '—'}</td><td class=mono>{ar['action']}</td></tr>")
        act_html = f"""
        <div class=card>
            <h4>🎯 Analyst actions (last 90d)</h4>
            <table class=actions><thead><tr><th>Date</th><th>Firm</th><th>Action</th><th>Type</th></tr></thead>
            <tbody>{''.join(act_rows)}</tbody></table>
        </div>
        """

    mates_html = ""
    if cluster_mates:
        mates_html += f'<div class=peer-row><span class=peer-label>🧬 Cluster:</span> {", ".join(f"<a href=#t-{m} class=peer-link>{m}</a>" for m in cluster_mates[:12])}</div>'
    if sector_mates:
        for sg, members in sector_mates.items():
            sg_label = sector_groups.get(sg, {}).get("label", sg)
            mates_html += f'<div class=peer-row><span class=peer-label>🏷️ {sg_label}:</span> {", ".join(f"<a href=#t-{m} class=peer-link>{m}</a>" for m in members[:10] if m != t)}</div>'

    notes_text = ""
    if notes_row is not None and isinstance(notes_row, pd.Series):
        notes_text = notes_row.get("note", "") or ""
    # Editable textarea — JS hooks up localStorage save
    notes_html = f"""
    <div class=card>
        <h4>📝 Notes <span class=hint style="font-weight:normal">(saved to your browser's localStorage — use Export Notes button at top to persist to SQL)</span></h4>
        <textarea class=notes-edit data-ticker="{t}" rows=3 placeholder="Write a thesis note, observation, follow-up...">{notes_text}</textarea>
        <div class=notes-meta><span class=notes-status data-ticker="{t}"></span></div>
    </div>
    """

    temp_v = snap_row.get('temperature')
    temp_cls = temp_class(temp_v)
    chg7 = snap_row.get('temp_7d_chg')

    return f"""
    <section class=drilldown id="t-{t}" data-ticker="{t}">
        <div class=drilldown-header>
            <div class=drilldown-title>
                <h3><a href="#top" class=back title="back to top">↑</a> {t}<span class=ticker-name>{name}</span>
                <button class=watch-toggle data-ticker="{t}" onclick="toggleWatch('{t}')" title="Add/remove from watchlist">☆</button>
                </h3>
                {erng_html}
            </div>
            <div class=drilldown-temp>
                <div class="temp-big {temp_cls}">{fmt(temp_v)}</div>
                <div class=temp-sub>Temperature {f"<span class={('chg-up' if chg7>0 else 'chg-down') if pd.notna(chg7) else ''}>{chg7:+.1f}</span> 7d" if pd.notna(chg7) else ''}</div>
            </div>
        </div>
        <div class=drilldown-stats>
            <div class=stat><span class=stat-label>Pos</span><span class="stat-val {temp_class(snap_row.get('score_positioning'))}">{fmt(snap_row.get('score_positioning'))}</span></div>
            <div class=stat><span class=stat-label>Tech</span><span class="stat-val {temp_class(snap_row.get('score_technical'))}">{fmt(snap_row.get('score_technical'))}</span></div>
            <div class=stat><span class=stat-label>Opt</span><span class="stat-val {temp_class(snap_row.get('score_options'))}">{fmt(snap_row.get('score_options'))}</span></div>
            <div class=stat title="{html_escape(UNIVPCT_HDR_TITLE)}"><span class=stat-label>Univ %ile</span><span class="stat-val {temp_class(snap_row.get('temp_univpct'))}">{fmt(snap_row.get('temp_univpct'), 0)}</span></div>
            <div class=stat title="{html_escape(snap_row.get('quad_title') or '')}"><span class=stat-label>Setup</span><span class="stat-val"><span class="quad {snap_row.get('quad_cls') or 'quad-none'}">{snap_row.get('quad_label') or '·'}</span></span></div>
            <div class=stat><span class=stat-label>Anom</span><span class=stat-val>{fmt(snap_row.get('anomaly_count'), 0)}</span></div>
            <div class=stat-spark>{spark_svg}</div>
        </div>
        {narrative_html}
        <div class=chart-card>
            <div class=chart-card-label>📈 Temperature, last 6 months (red zone ≥70 = hot, green zone ≤30 = cold)</div>
            {_render_6m_chart(chart_series)}
        </div>
        {bucket_chart_html}
        {breakdown_html}
        {sig_table}
        {est_html}
        {act_html}
        {mates_html}
        {notes_html}
    </section>
    """


def render_provenance(prov: dict) -> str:
    rows = []
    for k, v in prov.items():
        rows.append(f"<tr><td>{k}</td><td class=mono>{v}</td></tr>")
    if not rows:
        return ""
    return f"""
    <details class=footer-card>
    <summary>🕒 Data provenance — last refresh per provider</summary>
    <table class=actions><thead><tr><th>Provider</th><th>Last refresh</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table>
    </details>
    """


def _render_decile_bars(decile_means: dict, label: str = "") -> str:
    """Render a small SVG bar chart of decile mean forward returns."""
    if not decile_means:
        return ""
    vals = [decile_means.get(d) or decile_means.get(str(d)) or 0 for d in range(10)]
    w, h, pad_l, pad_r, pad_t, pad_b = 240, 60, 4, 4, 4, 12
    bar_w = (w - pad_l - pad_r) / 10
    mn = min(vals)
    mx = max(vals)
    rng = max(abs(mn), abs(mx)) or 0.01
    mid_y = pad_t + (h - pad_t - pad_b) / 2
    bars = []
    for i, v in enumerate(vals):
        x = pad_l + i * bar_w + 1
        bw = max(bar_w - 2, 1)
        bh = abs(v) / rng * (h - pad_t - pad_b) / 2
        if v >= 0:
            y = mid_y - bh
            color = "#dc2626"  # red — top decile pos return is "bad" for high-temp = late
        else:
            y = mid_y
            color = "#10b981"  # green — bot decile neg return is contrarian-good
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{color}" opacity="0.85"/>')
    return f"""
    <svg class=spark width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-label="decile mean forward return bars">
        <line x1="{pad_l}" y1="{mid_y:.1f}" x2="{w - pad_r}" y2="{mid_y:.1f}" stroke="#cbd5e1" stroke-width="0.5"/>
        {''.join(bars)}
        <text x="{pad_l}" y="{h - 2}" font-size="9" fill="#94a3b8">cold</text>
        <text x="{w - pad_r - 18}" y="{h - 2}" font-size="9" fill="#94a3b8">hot</text>
    </svg>
    """


def load_validation_stats() -> dict:
    """Read auto-computed validation numbers (tools/compute_validation_stats.py)
    as pre-formatted strings, so dashboard text is never hand-typed / stale.
    Returns em-dashes if the file is missing."""
    def f3(x):
        return f"{x:+.3f}".replace("-", "−") if isinstance(x, (int, float)) else "—"
    def f1(x):
        return f"{x:+.1f}".replace("-", "−") if isinstance(x, (int, float)) else "—"
    def fp(x):
        return f"{x:+.1%}".replace("-", "−") if isinstance(x, (int, float)) else "—"
    try:
        d = json.loads(project_path("data/validation_stats.json").read_text())
    except Exception:
        d = {}
    isd, oo = d.get("in_sample", {}), d.get("oos", {})
    return {
        "asof": d.get("as_of", "—"),
        "is_ic": f3(isd.get("ic")), "is_t": f1(isd.get("t")), "is_ls": fp(isd.get("ls_ann")),
        "is_n": isd.get("n", "—"),
        "oos_ic": f3(oo.get("ic")), "oos_t": f1(oo.get("t")), "oos_ls": fp(oo.get("ls_ann")),
        "oos_n": oo.get("n", "—"),
    }


def render_methodology_card(vs: dict) -> str:
    """Plain-language explanation of how Temperature is computed and how it was
    validated. Validation numbers come from load_validation_stats() (auto-computed)."""
    return f"""
    <div class="panel" id="methodology">
      <h3>🧮 How the score is built &amp; validated (V1.17)</h3>
      <p class=hint>This is a contrarian <b>sentiment/positioning</b> score, not a price target — it pairs with fundamental work, it doesn't replace it.</p>

      <h4>How Temperature (0–100) is computed</h4>
      <ol class=method>
        <li>Every signal is converted to a <b>percentile</b>, blended <b>50/50</b> between "vs the stock's own 5-year history" and "vs all TMT peers today" — the same basis for all three buckets (technicals previously used own-history only; walk-forward testing showed the 50/50 blend generalizes better once returns are factor-neutralized).</li>
        <li>Signals are grouped into three <b>buckets</b>, each a weighted average of its signals:
          <ul>
            <li><b>Positioning &amp; crowding (50%)</b> — short interest (days-to-cover, short-volume), insider flow, and <b>float turnover</b> (20d volume ÷ free float — a long/retail-crowding proxy that earns ~28% of the bucket on its own 1-month merit).</li>
            <li><b>Technical (20%)</b> — 1/3/6m returns, RSI, distance from 200d MA, % from 52-week high.</li>
            <li><b>Options (30%)</b> — IV rank, 25Δ skew, put/call ratio, term-structure slope.</li>
          </ul>
        </li>
        <li>Temperature = weighted average of the buckets (re-normalized if a bucket has no data). High = crowded/stretched/late (contrarian-bearish); low = washed-out (contrarian-bullish).</li>
        <li>Within-bucket weights come from each signal's <b>1-month factor-neutral IC</b>; trend-following (wrong-signed) signals get zero. Across-bucket weights tilt to positioning — the strongest-validated bucket (~2× technical) — with technical kept at a smaller (still-additive) weight and options held as a forward-looking prior (its history is too short to backtest).</li>
      </ol>

      <h4>How it was validated — and why 1-month is the reference horizon</h4>
      <p>We score the signal by <b>Information Coefficient</b> (rank correlation of Temperature with forward returns; for a contrarian signal, <b>negative is good</b>). Raw IC <em>understates</em> the edge because market/sector/beta moves dominate returns, so we measure against <b>factor-neutral residuals</b> (sector- and beta-stripped), using <b>non-overlapping periods</b> so the statistics aren't inflated by overlapping return windows. <span class=basis>(Numbers below auto-computed by <code>tools/compute_validation_stats.py</code>, as of {vs['asof']}.)</span></p>
      <table class=signals style="max-width:640px">
        <thead><tr><th>1-month, factor-neutral</th><th class=num>IC</th><th class=num>t-stat</th><th class=num>Decile L/S (ann.)</th></tr></thead>
        <tbody>
          <tr><td><b>In-sample</b> ({vs['is_n']} mo; weights tuned on same data)</td><td class="num mono chg-down">{vs['is_ic']}</td><td class="num mono">{vs['is_t']}</td><td class="num mono chg-up">{vs['is_ls']}</td></tr>
          <tr><td><b>Out-of-sample</b> ({vs['oos_n']} mo; walk-forward)</td><td class="num mono chg-down">{vs['oos_ic']}</td><td class="num mono">{vs['oos_t']}</td><td class="num mono">{vs['oos_ls']}</td></tr>
        </tbody>
      </table>
      <p>1 month beats 3 months (3m IC is weak/insignificant), so it's the reference horizon. Weights were tuned to this 1-month factor-neutral target (<code>tools/tune_weights_1m.py</code>, <code>tools/bucket_weight_scan.py</code>). <b>But the in-sample numbers are optimistic.</b> A proper <b>walk-forward test</b> (tune on past, measure on held-out future; <code>tools/walk_forward.py</code>) shows the rank IC <b>partially survives</b> out-of-sample ({vs['oos_ic']}, t {vs['oos_t']}, borderline-significant) but weakens — and the <b>decile long/short is noisy and unreliable</b> out of sample (it swings widely with the sample, so it's not tradeable). The rank IC is the more stable read.</p>
      <p class=hint><b>Honest read:</b> a <b>weak</b> rank signal that partially generalizes, not a tradeable standalone strategy. Use it for breadth and as <b>one input alongside fundamentals / idea-generation</b> — do not trade the decile spread on its own. (Earlier headline t-stats ≈ −11 were inflated by overlapping windows; corrected and out-of-sample, the edge is modest.)</p>
    </div>
    """


def render_backtest_card(results: list, signal_weights=None, signal_to_bucket=None,
                         bucket_weights=None) -> str:
    if not results:
        return ""
    signal_weights = signal_weights or {}
    signal_to_bucket = signal_to_bucket or {}
    bucket_weights = bucket_weights or {}

    # Each signal's MODEL weight = its share of Temperature = (within-bucket weight,
    # normalized) × (the bucket's weight in the composite). This is the actual basis
    # the model is built on (within-bucket weights come from 1-month factor-neutral IC).
    bucket_sum = {}
    for sig, w in signal_weights.items():
        b = signal_to_bucket.get(sig)
        if b:
            bucket_sum[b] = bucket_sum.get(b, 0.0) + w

    def model_wt(sig):
        w = signal_weights.get(sig, 0.0)
        b = signal_to_bucket.get(sig)
        if not b or not bucket_sum.get(b):
            return 0.0
        return (w / bucket_sum[b]) * bucket_weights.get(b, 0.0)

    composite = [r for r in results if r["signal"] == "COMPOSITE_TEMPERATURE"]
    sig_results = [r for r in results if r["signal"] != "COMPOSITE_TEMPERATURE"]

    # Pin to the 1-MONTH horizon (the model horizon), picking the stronger of the
    # two percentile bases (pct_self / pct_peer) for the raw-shape visualization.
    by_sig = {}
    for r in sig_results:
        if r.get("horizon") != "1m":
            continue
        s = r["signal"]
        if s not in by_sig or abs(r.get("ic") or 0) > abs(by_sig[s].get("ic") or 0):
            by_sig[s] = r

    # Sort by model weight (most important signals first), then |IC|.
    ordered = sorted(by_sig.keys(),
                     key=lambda x: (model_wt(x), abs(by_sig[x].get("ic") or 0)), reverse=True)
    sig_rows = []
    for s in ordered:
        r = by_sig[s]
        ic = r.get("ic")
        ic_str = f"{ic:+.4f}" if ic is not None else "—"
        ic_cls = "chg-down" if (ic is not None and ic < 0) else ("chg-up" if ic is not None and ic > 0 else "")
        mw = model_wt(s)
        mw_str = f"{mw * 100:.1f}%" if mw > 0 else '<span class=muted>not used</span>'
        bkt = (signal_to_bucket.get(s) or "—").capitalize()
        bars = _render_decile_bars(r.get("decile_means", {}))
        sig_rows.append(f"""
            <tr>
                <td class=mono>{s}</td>
                <td>{bkt}</td>
                <td class='num mono'>{mw_str}</td>
                <td class='num mono {ic_cls}'>{ic_str}</td>
                <td class=num>{r.get('top_hit_rate', 0):.1%}</td>
                <td class=num>{r.get('bot_hit_rate', 0):.1%}</td>
                <td>{bars}</td>
            </tr>
        """)

    comp_rows = []
    for r in [c for c in composite if c.get("horizon") == "1m"] or composite:
        ic = r.get("ic")
        ic_cls = "chg-down" if ic and ic < 0 else "chg-up"
        bars = _render_decile_bars(r.get("decile_means", {}))
        comp_rows.append(f"""
            <tr style="font-weight:600; border-bottom:2px solid var(--border)">
                <td><b>Composite Temperature</b></td>
                <td>all (1.00)</td>
                <td class=num>100%</td>
                <td class='num mono {ic_cls}'>{ic:+.4f}</td>
                <td class=num>{r['top_hit_rate']:.1%}</td>
                <td class=num>{r['bot_hit_rate']:.1%}</td>
                <td>{bars}</td>
            </tr>
        """)

    return f"""
    <div class="panel" id="backtest-panel">
        <h3>📈 Per-signal model basis — 1-month horizon, ordered by model weight</h3>
        <p class=hint><b>What the model is built on, signal by signal.</b> <b>Model weight</b> = each signal's share of the composite Temperature = (its weight within its bucket) × (the bucket's weight: Pos 0.50 / Tech 0.20 / Opt 0.30). Those within-bucket weights are set by each signal's <b>1-month, factor-neutral</b> IC (the validated horizon — composite in-sample/out-of-sample numbers are in the 🧮 Methodology card above). The <b>IC</b> and <b>decile bars</b> here are <b>raw 1-month</b> (not factor-neutral) — shown for the <em>shape</em> of each signal, so they won't line up exactly with the weights. <b class=chg-down>Negative IC</b> = contrarian (high reading → negative forward return). Bars: 10 left→right = bottom-decile (cold) → top-decile (hot); a working contrarian signal slopes <span class=chg-down>down-left</span> / <span class=chg-up>up-right</span>. Options signals show <span class=muted>not used</span> weight context where their history is too short to tune (equal-weighted prior). </p>
        <div class=table-wrap>
        <table class=signals>
            <thead><tr><th>Signal</th><th>Bucket</th><th class=num title="Share of the whole Temperature score">Model wt</th><th class=num title="Raw 1-month IC (Spearman), for shape">1m IC (raw)</th><th class=num>Top hit</th><th class=num>Bot hit</th><th>Decile spread (cold → hot)</th></tr></thead>
            <tbody>{''.join(comp_rows)}{''.join(sig_rows)}</tbody>
        </table>
        </div>
    </div>
    """


def _pick_teaching_example(snap: pd.DataFrame):
    """Pick the name whose headline Temp hides the most — i.e. the widest gap
    between what positioning says and what technicals say. Deterministic, so the
    example only changes when the underlying divergence leader changes.

    Restricted to names with all three pillars and enough price history, so the
    walkthrough never leans on a half-scored or brand-new listing."""
    d = snap.copy()
    need = ["pos_univpct", "tech_univpct", "temp_univpct", "score_options"]
    for c in need:
        if c not in d.columns:
            return None
    d = d[d[need].notna().all(axis=1)]
    if "thin_history" in d.columns:
        d = d[~d["thin_history"].astype(bool)]
    if d.empty:
        return None
    d = d.assign(_gap=(d["pos_univpct"] - d["tech_univpct"]).abs())
    return d.sort_values(["_gap", "ticker"], ascending=[False, True]).iloc[0]


def render_reading_guide(snap: pd.DataFrame, sig_long: pd.DataFrame, vs: dict) -> str:
    """The '📖 How to read it' tab: what to look at, in what order, and why.

    Everything quantitative here is computed from the live snapshot, so the
    scale table and the worked example cannot go stale. The evidence figures
    (IC / cell returns) are fixed properties of the V1.17 model's validation and
    are quoted as constants."""
    t = snap["temperature"].dropna()
    n = len(t)

    # --- §1: the live Temp -> percentile mapping -------------------------------
    map_rows = "".join(
        f"<tr><td class=num>{v}</td><td class=num><b>{(t < v).mean() * 100:.0f}th</b></td>"
        f"<td class=num>{(t >= v).sum()}</td></tr>"
        for v in (30, 35, 40, 45, 50, 55, 60, 65, 70)
    )
    scale_stats = (f"mean {t.mean():.1f} · median {t.median():.1f} · "
                   f"std {t.std():.1f} · range {t.min():.1f}–{t.max():.1f}")
    pct_hot = (t >= 70).mean() * 100
    pct_cold = (t <= 30).mean() * 100

    # --- §3: live census of the Setup grid ------------------------------------
    counts = snap["quad_label"].value_counts().to_dict() if "quad_label" in snap.columns else {}

    def _cnt(lbl):
        return counts.get(lbl, 0)

    # --- §4: the worked example ----------------------------------------------
    ex = _pick_teaching_example(snap)
    if ex is None:
        example_html = "<p class=hint>Not enough scored names today to build a worked example.</p>"
    else:
        tk = ex["ticker"]
        sigs = sig_long[(sig_long["ticker"] == tk)
                        & (sig_long["bucket"].isin(["positioning", "technical", "options"]))].copy()
        sigs["dual"] = sigs[["pct_self", "pct_peer"]].mean(axis=1)
        sigs = sigs.dropna(subset=["dual"])
        hot3 = sigs.nlargest(3, "dual")
        cold3 = sigs.nsmallest(3, "dual")
        _sl = lambda df: ", ".join(  # noqa: E731
            f"<code>{r['signal_name']}</code> {_ord(r['dual'])}" for _, r in df.iterrows())

        pos_p, tech_p = ex["pos_univpct"], ex["tech_univpct"]
        crowded = pos_p >= 50
        strong = tech_p >= 50
        # Plain-English statement of what the two pillars disagree about.
        story = (
            f"price action in the {_ord(tech_p)} percentile of the universe while "
            f"positioning sits in the {_ord(pos_p)}"
        )
        if strong and not crowded:
            reading = ("the market is moving this name <b>without</b> anyone being "
                       "positioned for it — strength that is not yet owned")
        elif crowded and not strong:
            reading = ("everybody is already positioned in a name that is <b>not</b> "
                       "working — crowding without the price to support it")
        elif crowded and strong:
            reading = ("both the price and the positioning are extended — the crowd "
                       "is right and fully aboard, which is where the model is most cautious")
        else:
            reading = ("neither the price nor the positioning is extended — a quiet, "
                       "genuinely washed-out name")

        self1y = ex.get("temp_selfpct_1y")
        self_txt = (f"{self1y:.0f}th vs its own year" if pd.notna(self1y) else "no self-history yet")
        agree = (pd.notna(self1y)
                 and ((ex["temp_univpct"] >= 70 and self1y >= 70)
                      or (ex["temp_univpct"] <= 30 and self1y <= 30)))
        confirm_txt = (
            "Both lenses agree, which is the case that historically mattered: names extreme "
            "cross-sectionally <b>and</b> against their own year were the only tail cut that "
            "cleared statistical significance (−7.0%/yr residual for the hot-on-both group, "
            "t −2.59)."
            if agree else
            "The two lenses <b>disagree</b> here, so treat the reading as unconfirmed. A name "
            "that is extreme on only one of the two showed no reliable edge — the cross-sectional "
            "reading alone was −2.0%/yr (t −0.62)."
        )

        example_html = f"""
<div class=guide-example>
<h4>4 · Worked example — {tk} ({html_escape(str(ex.get('name') or ''))})</h4>
<p class=hint>Auto-selected as today's widest positioning-vs-technicals divergence — the case
where the single headline number hides the most. It will change as the data changes.</p>

<div class=table-wrap>
<table class=rank>
<thead><tr><th class=num>Temp</th><th class=num>Univ %ile</th><th class=num>Setup</th>
<th class=num>Self 1y</th><th class=num>{EXTECH_COL}</th>
<th class=num>Pos</th><th class=num>Tech</th><th class=num>Opt</th></tr></thead>
<tbody><tr>
<td class="num temp {temp_class(ex['temperature'])}">{fmt(ex['temperature'])}</td>
<td class="num temp {temp_class(ex['temp_univpct'])}">{fmt(ex['temp_univpct'], 0)}</td>
<td class=num><span class="quad {ex.get('quad_cls', 'quad-none')}">{ex.get('quad_label', '·')}</span></td>
<td class="num temp {temp_class(self1y)}">{fmt(self1y, 0)}</td>
<td class="num temp {temp_class(ex.get('extech_selfpct_1y'))}">{fmt(ex.get('extech_selfpct_1y'), 0)}</td>
<td class=num>{fmt(ex.get('score_positioning'))}</td>
<td class=num>{fmt(ex.get('score_technical'))}</td>
<td class=num>{fmt(ex.get('score_options'))}</td>
</tr></tbody>
</table>
</div>

<ol class=guide-steps>
<li><b>Start with Univ %ile, not Temp.</b> {tk} shows a Temperature of
{fmt(ex['temperature'])}, which on a 0–100 scale reads unremarkable. It is actually the
<b>{_ord(ex['temp_univpct'])} percentile</b> of the {n} TMT names scored today. That is the
single most common misreading of this dashboard.</li>

<li><b>Then split the headline into its pillars.</b> The composite is averaging
{story} — so {reading}. Averaging two opposite readings into one number is exactly what
buries the information; the pillar columns are where it lives.</li>

<li><b>Read the Setup tag as the shorthand for that split.</b> {tk} is tagged
<span class="quad {ex.get('quad_cls', 'quad-none')}">{ex.get('quad_label', '·')}</span>.
{html_escape(ex.get('quad_title', ''))}</li>

<li><b>Look at which signals are driving it.</b> Hottest: {_sl(hot3) or '—'}. Coldest:
{_sl(cold3) or '—'}. If one or two signals are carrying the whole pillar, the reading is
thinner than the score implies — open the drill-down and check.</li>

<li><b>Use self-history only to confirm, never to rank.</b> {tk} sits at {self_txt}.
{confirm_txt}</li>
</ol>
</div>
"""

    return f"""
<div class=panel>
<h3>📖 How to read this dashboard</h3>
<p class=hint>Written to answer one question: given ~{n} names and a wall of numbers, what
should you actually look at, and in what order?</p>
</div>

<div class=panel>
<h3>1 · Read the percentile, not the score</h3>
<p>This is the single biggest source of confusion, and it is a property of the scale rather
than of any particular name. Temperature is the weighted average of ~15 percentile signals.
Averaging percentiles pulls the result toward the middle (the central limit at work), so the
composite <b>never uses most of the 0–100 range</b>. Today's cross-section: {scale_stats}.
Only <b>{pct_hot:.0f}%</b> of names sit at 70 or above and <b>{pct_cold:.0f}%</b> at 30 or
below — and that has been true every year since 2016, so it is structural, not a quirk of
today's tape.</p>
<p>The practical consequence: a 0–100 number <i>looks</i> like a percentile and isn't one.
The <b>Univ %ile</b> column, now next to Temp everywhere, is the real percentile. Today's
translation:</p>
<div class=table-wrap style="max-width:420px">
<table class=rank>
<thead><tr><th class=num>Temp of…</th><th class=num>…is really</th><th class=num>names at or above</th></tr></thead>
<tbody>{map_rows}</tbody>
</table>
</div>
<p class=hint>Univ %ile is a monotone re-scaling of Temp within each date, so it cannot change
any ordering, IC or backtest result. Nothing about the model changed — only what is displayed.</p>
</div>

<div class=panel>
<h3>2 · Not all three pillars are equal</h3>
<p>The three bucket scores look symmetric on screen. They are not, and knowing which to lean on
is most of the skill in using this tool.</p>
<ul class=guide-list>
<li><b>Positioning — lean on this one.</b> It is the only pillar that is strongly validated
standalone: 1-month factor-neutral IC −0.022 (t −3.9), and its own decile long/short spread
(+8.2%/yr, t 2.74) is <i>wider</i> than the full composite's (+4.8%/yr, t 1.47). When
positioning and the headline disagree, positioning has the better track record. It carries
0.50 of the composite.</li>
<li><b>Technical — real but weak.</b> Standalone IC −0.011 (t −1.3); its own decile spread is
+1.9%/yr (t 0.41), i.e. indistinguishable from noise on its own. It earns its 0.20 weight by
combining with positioning, not by standing alone. Most of the time it is the pillar dragging
a headline toward the middle.</li>
<li><b>Options — genuinely provisional.</b> Yahoo options history only begins 2026-05-12, which
leaves <b>one</b> measurable non-overlapping 1-month period in the entire backtest. Its 0.30
weight is a forward-looking prior, not a fitted result, and no claim on this dashboard about
options is backed by out-of-sample evidence. Read it as color. That caveat also applies to the
<b>{EXTECH_COL}</b> column, which is 37.5% options by construction.</li>
</ul>
<p class=hint>The model is frozen at V1.17 — none of this changes any weight. It changes where
you should place your confidence when the pillars disagree.</p>
</div>

<div class=panel>
<h3>3 · The Setup grid</h3>
<p>Crowding and price direction interact, and the interaction is more informative than either
alone. The <b>Setup</b> column crosses the positioning tercile with the technical tercile and
tags only the four corners. Cell figures are the mean 1-month factor-neutral forward return
over 121 non-overlapping periods, 2016–2026, with today's name count in brackets.</p>
<div class=table-wrap style="max-width:640px">
<table class=rank>
<thead><tr><th></th><th class=num>Price weak</th><th class=num>Price strong</th></tr></thead>
<tbody>
<tr><th style="text-align:left">Positioning light</th>
<td class=num><span class="quad quad-cool">Under-owned ↓</span><br><b>+3.7%/yr</b> (t 1.68) · [{_cnt('Under-owned ↓')}]</td>
<td class=num><span class="quad quad-cool">Under-owned ↑</span><br><b>+2.6%/yr</b> (t 1.04) · [{_cnt('Under-owned ↑')}]</td></tr>
<tr><th style="text-align:left">Positioning heavy</th>
<td class=num><span class="quad quad-warm">Crowded ↓</span><br><b>−1.5%/yr</b> (t −0.70) · [{_cnt('Crowded ↓')}]</td>
<td class=num><span class="quad quad-hot">Crowded ↑</span><br><b>−3.5%/yr</b> (t −1.86) · [{_cnt('Crowded ↑')}]</td></tr>
</tbody>
</table>
</div>
<p>The useful comparison is along the top-to-bottom axis: <b>within strong price action</b>,
light-positioning names beat heavy-positioning names by <b>+6.1%/yr</b> (t 2.00). Strength
itself is not the problem; strength that everyone already owns is.</p>
<p class=hint><b>Honest caveat:</b> that cell was chosen after looking at a 3×3 grid on 121
periods, so it carries a multiple-comparison discount, and the project's own walk-forward
showed decile long/short spreads do not survive out-of-sample. Use the grid to orient and to
generate ideas; do not treat these as expected returns. Middle terciles are left untagged
because the middle of the grid showed nothing measurable.</p>
</div>

{example_html}

<div class=panel>
<h3>5 · What not to lean on</h3>
<ul class=guide-list>
<li><b>Self-history as a ranking.</b> <b>Self 1y</b> is uniform by construction — every name
spends 10% of its days above its own 90th percentile whether or not it is genuinely crowded,
so a chronically quiet name reads "extreme" just for being ordinary. In a regression with both,
the cross-sectional score keeps its predictive sign and self-history goes to zero. Sort on Univ
%ile; use Self 1y as a second opinion on names the sort already surfaced.</li>
<li><b>The {EXTECH_COL} column as evidence.</b> Useful for separating crowding from price
action, but 37.5% of it is the unvalidated options bucket, and before 2026-05-12 its trailing
window is positioning-only — so a name can jump sharply the day options first enters its window.
Directional color, not proof.</li>
<li><b>Conviction.</b> Removed from the tables in V1.21. It was tested as a filter and did not
work: composite IC was flat from no filter through conviction ≥70, then degraded at ≥80
(t −1.65). Screening on bucket agreement threw away signal instead of sharpening it. The field
is still computed and still in the CSV export; it is simply no longer given screen space.</li>
<li><b>The tool as a standalone strategy.</b> In-sample IC {vs['is_ic']} (t {vs['is_t']}),
walk-forward out-of-sample {vs['oos_ic']} (t {vs['oos_t']}). The rank signal partially survives
out-of-sample; the decile long/short does not. This is an idea-generation and
confirmation overlay for fundamental work — that is the honest ceiling on it.</li>
</ul>
</div>
"""


def render_glossary() -> str:
    return """
<details open class=glossary>
<summary><h2>📘 Glossary — what every number means</h2></summary>
<div class=gloss-grid>

<div class=gloss-card>
<h4>Temperature (0–100)</h4>
<p>The composite "how hot/late" score (0–100). Each signal is scored as a percentile, then within each bucket signals are weighted by their backtest IC. Composite = <b>weighted average of buckets</b>: <b>positioning 0.50 + technical 0.20 + options 0.30</b>, renormalized when a bucket is missing.</p><p><b>How percentiles are computed:</b> every composite signal (all three buckets) is a 50/50 blend of <code>pct_self</code> (vs own 5y history) and <code>pct_peer</code> (vs the full TMT universe). <b>Validated at the 1-month, factor-neutral horizon — the current (auto-computed) in-sample / out-of-sample IC numbers and full method are in the 🧮 Methodology card on the Backtest tab.</b></p>
</div>

<div class=gloss-card>
<h4>Bucket scores (Pos / Tech / Opt)</h4>
<p>Each 0–100, IC-weighted average of underlying signals. Each signal is scored as a percentile vs own history AND vs the full TMT universe (50/50 blend). Stronger contrarian signals (lower IC) get more weight within the bucket.</p>
<ul>
<li><b>Pos</b> — Positioning: insider Form 4, FINRA short volume, NASDAQ true SI days-to-cover</li>
<li><b>Tech</b> — Sentiment via price action: returns, RSI, distance from 200d MA, % from 52w high</li>
<li><b>Opt</b> — Options sentiment: IV rank, 25Δ skew, term structure slope, P/C ratio (live institutional positioning via options markets)</li>
</ul>
<p><b>NTM P/E</b> (price ÷ forward consensus EPS) is shown on per-ticker drill-downs as overlay context only — <b>NOT</b> in the composite. Tool measures sentiment / positioning only; valuation is fundamental analysis done separately. <b>No TTM multiples are used</b> — only NTM (forward) per design choice.</p>
</div>

<div class=gloss-card>
<h4>Short volume vs. days-to-cover (why they can disagree)</h4>
<p>Two positioning signals that measure <b>different things</b> and often diverge:</p>
<ul>
<li><b>Short volume 14d ratio</b> — a <b>flow</b>: the short-marked share of each day's tape (FINRA Reg SHO), 14d avg. Mostly <b>market-maker hedging and intraday arb</b> that is flat by the close, so a high reading means heavy two-sided trading, not necessarily bearish bets.</li>
<li><b>Short interest days-to-cover</b> — a <b>stock</b>: actual reported short interest (open shares held short) ÷ average daily volume. This is the real, accumulated short position and the more reliable crowding read. It falls when the open short book is small <i>or</i> the stock trades a lot (high turnover deflates days-to-cover).</li>
</ul>
<p><b>High short volume + low days-to-cover</b> (a heavily-churned name) = lots of short-marked prints crossing an active tape, but little settling into a crowded overnight short — <b>churned, not pressed short</b>. Lean on days-to-cover for actual positioning. Windows differ too: short volume is a fresh 14-day flow; days-to-cover uses the last bi-weekly short-interest settlement (~2–3 weeks lagged).</p>
</div>

<div class=gloss-card>
<h4>Univ %ile (0–100)</h4>
<p>Where the Temperature ranks against the <b>whole TMT universe today</b>. <b>Judge extremity on this column, not on raw Temp.</b> Temperature is an average of ~15 percentile signals, so the central limit compresses it toward 50 — std is only ~13 and the effective range is ~20–89, with just ~6% of names above 70 and ~6% below 30. That makes a 0–100 number <i>look</i> like a percentile without being one: a Temp of 38 is really a bottom-quintile reading, and 62 is already top-quartile.</p>
<p>This is a monotone re-scaling of Temp on each date, so it cannot change any ranking, IC or backtest result — it changes only what you see.</p>
</div>

<div class=gloss-card>
<h4>Setup (quadrant)</h4>
<p>Positioning tercile × technical tercile, ranked across the universe today. The <b>word</b> says how crowded the name is; the <b>arrow</b> says which way price is going.</p>
<ul>
<li><span class="quad quad-hot">Crowded ↑</span> — heavy positioning, strong price. The most expensive place to add. Historically the worst cell: −3.5%/yr residual (t −1.86).</li>
<li><span class="quad quad-warm">Crowded ↓</span> — heavy positioning, weak price. Crowded and rolling over: −1.5%/yr (t −0.70).</li>
<li><span class="quad quad-cool">Under-owned ↑</span> — light positioning, strong price. Strength nobody is positioned for: +2.6%/yr (t 1.04).</li>
<li><span class="quad quad-cool">Under-owned ↓</span> — light positioning, weak price. The classic washed-out setup, and the best cell: +3.7%/yr (t 1.68).</li>
<li><span class="quad quad-none">·</span> — middle tercile on one or both axes. Deliberately unlabeled: the middle of the grid showed no measurable edge.</li>
</ul>
<p>Figures are mean 1-month factor-neutral forward returns over 121 non-overlapping periods, 2016–2026 — a description of the historical cell, not a forecast. Display-only; never feeds the composite, flags or backtest. Full walkthrough on the <b>📖 How to read it</b> tab.</p>
</div>

<div class=gloss-card>
<h4>Anomaly count</h4>
<p>Number of signals where this name is at the 90th+ percentile vs the full TMT universe <i>today</i>. High = stands out across many measures.</p>
</div>

<div class=gloss-card>
<h4>7d Δ (temperature change)</h4>
<p>Today's temperature minus 5 trading days ago. <span class=chg-up>Red/positive</span> = heating up. <span class=chg-down>Green/negative</span> = cooling off (contrarian-favorable).</p>
</div>

<div class=gloss-card>
<h4>Self 1y (vs own history)</h4>
<p>Where today's Temperature sits within <b>this same name's</b> trailing <b>1-year</b> range — a percentile (0–100), colored like Temp (high = hot for itself, low = washed-out for itself). This is the fix for <b>structurally cool/hot names</b>: a large-cap semi can read a cool 40 vs the universe yet be at its own 1-year high (Self 1y ≈ 90) because positioning/options keep it quiet cross-sectionally. Cross-sectional Temp answers "hot vs other TMT names?"; Self 1y answers "hot <i>for itself</i>?" Hover a cell for the <b>z-score</b> (how many σ from its own norm — a 90th %ile on a near-flat name may still be only +0.5σ) and the <b>6-month</b> read. Per-bucket self-history (positioning / technical / options vs own 1y) appears in each name's drill-down. <b>Caveat:</b> options data starts 2026, so the 1-year <i>Temperature</i> baseline is partly pre-options and biased slightly cool; the positioning &amp; technical bucket self-histories (clean ~10y) are the robust reads until options accrues a full year.</p>
</div>

<div class=gloss-card>
<h4>Self 1y P+O (ex-technicals)</h4>
<p>The same self-vs-own-history percentile as <b>Self 1y</b>, but computed on a composite built from the <b>Positioning and Options pillars only</b> — every price/momentum-derived signal removed. Weights are the model's own (Pos 0.50, Opt 0.30) renormalized over the two kept pillars, i.e. <b>0.625 Pos / 0.375 Opt</b>.</p>
<p><b>Why it's separate from Self 1y.</b> Temperature is 20% technicals, and technicals are the fastest-moving, most price-reflexive bucket — so a name can print a hot Self 1y mostly because it has rallied. This column answers the narrower question: <i>is the crowding and options-hedging setup extreme for this name, independent of how the stock has traded?</i> Read the two side by side — a <b>high Self 1y with a middling P+O</b> is a momentum-driven reading, while <b>both high</b> means positioning and price agree, which is the more complete late-cycle setup. The reverse (P+O hot, Self 1y cool) flags crowding that price hasn't confirmed yet.</p>
<p><b>Caveat — composition break.</b> Options history only begins <b>2026-05-12</b>. To keep a genuine 252-day window, dates before that are scored on <b>positioning alone</b>, so today's blended value is ranked against a partly positioning-only past. Treat the level as directional rather than precise until options accrues a full year; the positioning pillar (clean ~10y) dominates the blend either way. Names with no options coverage at all show the positioning-only read.</p>
</div>

<div class=gloss-card>
<h4>Compound flags</h4>
<ul>
<li><b>🔥 Late</b> — Temperature ≥ 85 (composite is already a weighted aggregate — no double-filter needed).</li>
<li><b>❄️ Washout</b> — Temperature ≤ 15.</li>
<li><b>⚠️ Divergence</b> — Technical ≥ 80 AND Options ≤ 30 (price hot but options cold — disagreement between buckets).</li>
<li><b>📅 Earnings</b> — earnings reporting within next 14 days.</li>
</ul>
</div>

<div class=gloss-card>
<h4>Color coding (contrarian)</h4>
<p><span class=chg-up>Red</span> = hot/extended/dangerous. <span class=chg-down>Green</span> = cold/washed-out/opportunity. Inverted from typical price-momentum coloring because this tool is contrarian.</p>
</div>

<div class=gloss-card>
<h4>Backtest validation (V1.17)</h4>
<p><b>1-month, factor-neutral</b>: the rank signal partially survives out-of-sample but is weak/borderline, and the decile long/short is unreliable out-of-sample. Treat as idea-generation, not a standalone strategy. 3-month is insignificant. Options is live but unvalidated (yfinance history too short) — its weight is a prior. <b>Current auto-computed IC / t-stat numbers are in the 🧮 Methodology card</b> on the Backtest tab.</p>
</div>

</div>
</details>
"""


def main(asof: str | None = None):
    print("Loading data...")
    data = load_data()
    snap = data["snap"]
    asof = data["latest"]

    # Freshness badge — make staleness obvious at a glance (no mental date math)
    try:
        _age = (date.today() - datetime.strptime(str(asof)[:10], "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        _age = None
    if _age is None:
        freshness_html = ""
    elif _age <= 1:
        freshness_html = f'<span class="freshness fresh">✓ updated {"today" if _age == 0 else "yesterday"}</span>'
    elif _age <= 4:
        freshness_html = f'<span class="freshness ok">{_age} days old</span>'
    else:
        freshness_html = f'<span class="freshness stale">⚠️ {_age} days old — may be out of date</span>'
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    vs = load_validation_stats()

    sector_groups = load_sector_groups()

    wl_tickers = set(data["watchlist"]["ticker"]) if not data["watchlist"].empty else set()

    cluster_to_tickers = snap.groupby("cluster_id")["ticker"].apply(list).to_dict() if "cluster_id" in snap.columns else {}
    ticker_to_sectors = {}
    for sg, info in sector_groups.items():
        for t in info["tickers"]:
            ticker_to_sectors.setdefault(t, []).append(sg)

    # Panels. Ranking/flag panels draw from `rankable` (excludes new-listing /
    # insufficient-history names so a fresh IPO can't top the board on artifact
    # signals); All Names + drilldowns still use the full `snap`.
    rankable = snap[~snap["thin_history"]] if "thin_history" in snap.columns else snap
    hottest = rankable.dropna(subset=["temperature"]).nlargest(25, "temperature")
    coldest = rankable.dropna(subset=["temperature"]).nsmallest(25, "temperature")
    movers_up = rankable.dropna(subset=["temp_7d_chg"]).nlargest(20, "temp_7d_chg")
    movers_down = rankable.dropna(subset=["temp_7d_chg"]).nsmallest(20, "temp_7d_chg")
    late_flagged = rankable[rankable["flag_late_signal"] == 1].sort_values("temperature", ascending=False)
    wash_flagged = rankable[rankable["flag_washout"] == 1].sort_values("temperature")
    earnings_soon = rankable[rankable["flag_earnings_soon"] == 1].sort_values("temperature", ascending=False)
    new_late_df = rankable[rankable["ticker"].isin(data["new_late"])].sort_values("temperature", ascending=False)
    new_wash_df = rankable[rankable["ticker"].isin(data["new_wash"])].sort_values("temperature")
    watchlist_df = snap[snap["ticker"].isin(wl_tickers)].sort_values("temperature", ascending=False)

    # KPI tile values (flag counts from rankable so they match the panels)
    kpi_total = len(snap)
    kpi_late = int((rankable["flag_late_signal"] == 1).sum())
    kpi_wash = int((rankable["flag_washout"] == 1).sum())
    kpi_earnings = int((snap["flag_earnings_soon"] == 1).sum())
    kpi_new_late = len(new_late_df)
    kpi_new_wash = len(new_wash_df)
    kpi_avg_temp = snap["temperature"].mean()
    kpi_pct_hot = (snap["temperature"] >= 70).mean() * 100
    kpi_pct_cold = (snap["temperature"] <= 30).mean() * 100

    # Pre-build drilldowns for ALL tickers
    sig_long_by_ticker = {t: g for t, g in data["sig_long"].groupby("ticker")}
    est_by_ticker = data["estimates"].set_index("ticker") if not data["estimates"].empty else pd.DataFrame()
    earn_by_ticker = data["earnings"].set_index("ticker") if not data["earnings"].empty else pd.DataFrame()
    notes_by_ticker = data["notes"].set_index("ticker") if not data["notes"].empty else pd.DataFrame()

    # Load weights once for the breakdown card
    from lib.config import load as load_cfg
    cfg_for_weights = load_cfg()
    bucket_weights_for_dash = cfg_for_weights["composite"]["bucket_weights"]
    sw_path = project_path("data/signal_weights.json")
    signal_weights_for_dash = {}
    if sw_path.exists():
        try:
            signal_weights_for_dash = json.loads(sw_path.read_text()).get("weights", {})
        except Exception:
            pass
    # Re-import SIGNAL_TO_BUCKET from compute_signals
    import importlib.util as _imp
    _spec = _imp.spec_from_file_location("_cs", project_path("setup/06_compute_signals.py"))
    _mod = _imp.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    signal_to_bucket_for_dash = _mod.SIGNAL_TO_BUCKET

    drilldowns = []
    for _, row in snap.iterrows():
        t = row["ticker"]
        sig_t = sig_long_by_ticker.get(t, pd.DataFrame())
        est_t = est_by_ticker.loc[t] if (not est_by_ticker.empty and t in est_by_ticker.index) else None
        earn_t = earn_by_ticker.loc[t] if (not earn_by_ticker.empty and t in earn_by_ticker.index) else None
        actions_t = data["actions"][data["actions"]["ticker"] == t]
        notes_t = notes_by_ticker.loc[t] if (not notes_by_ticker.empty and t in notes_by_ticker.index) else None
        spark = data["sparklines"].get(t, [])
        chart_series = data["chart_data"].get(t, [])
        cluster_id = row.get("cluster_id")
        cluster_mates = [x for x in cluster_to_tickers.get(cluster_id, []) if x != t][:12] if cluster_id else []
        sector_mates = {sg: sector_groups[sg]["tickers"] for sg in ticker_to_sectors.get(t, [])}
        drilldowns.append(render_drilldown(
            row, sig_t, est_t, earn_t, actions_t, spark, chart_series, notes_t, sector_groups, cluster_mates, sector_mates,
            bucket_series=data["bucket_chart_data"].get(t, []),
            bucket_weights=bucket_weights_for_dash,
            signal_weights=signal_weights_for_dash,
            signal_to_bucket=signal_to_bucket_for_dash,
        ))

    # All-names data for JS-rendered table
    all_names_data = []
    for _, r in snap.iterrows():
        all_names_data.append({
            "ticker": r["ticker"],
            "name": (r.get("name") or "")[:40],
            "temp": float(r["temperature"]) if pd.notna(r["temperature"]) else None,
            "univpct": float(r["temp_univpct"]) if pd.notna(r.get("temp_univpct")) else None,
            "chg7d": float(r["temp_7d_chg"]) if pd.notna(r.get("temp_7d_chg")) else None,
            "pos": float(r["score_positioning"]) if pd.notna(r.get("score_positioning")) else None,
            "tech": float(r["score_technical"]) if pd.notna(r.get("score_technical")) else None,
            "opt": float(r["score_options"]) if pd.notna(r.get("score_options")) else None,
            "anom": int(r["anomaly_count"]) if pd.notna(r.get("anomaly_count")) else None,
            # V1.21 Setup quadrant. `quadrank` orders the column most-crowded to
            # least so a sort walks Crowded ↑ -> Crowded ↓ -> untagged -> Under-owned.
            "quad": r.get("quad_label") or "·",
            "quadcls": r.get("quad_cls") or "quad-none",
            "quadtitle": r.get("quad_title") or "",
            "quadrank": QUAD_SORT_RANK.get(r.get("quad_label"), 0),
            "self1y": float(r["temp_selfpct_1y"]) if pd.notna(r.get("temp_selfpct_1y")) else None,
            "self6m": float(r["temp_selfpct_6m"]) if pd.notna(r.get("temp_selfpct_6m")) else None,
            "selfz": float(r["temp_selfz_1y"]) if pd.notna(r.get("temp_selfz_1y")) else None,
            # V1.20: ex-technical (positioning + options only) self-history
            "xself1y": float(r["extech_selfpct_1y"]) if pd.notna(r.get("extech_selfpct_1y")) else None,
            "xself6m": float(r["extech_selfpct_6m"]) if pd.notna(r.get("extech_selfpct_6m")) else None,
            "xselfz": float(r["extech_selfz_1y"]) if pd.notna(r.get("extech_selfz_1y")) else None,
            "late": bool(r.get("flag_late_signal") == 1),
            "wash": bool(r.get("flag_washout") == 1),
            "earn": bool(r.get("flag_earnings_soon") == 1),
            "cluster": r.get("cluster_id") or "",
            "mcap_b": float(r["market_cap"]) / 1e9 if pd.notna(r.get("market_cap")) else None,
            "watched": r["ticker"] in wl_tickers,
        })

    # CSV
    csv_cols = ["ticker", "name", "temperature", "score_positioning",
                "score_valuation", "score_technical", "conviction",
                "anomaly_count", "temp_7d_chg",
                "temp_selfpct_1y", "temp_selfpct_6m", "temp_selfz_1y",
                "extech_selfpct_1y", "extech_selfpct_6m", "extech_selfz_1y",
                "pos_selfpct_1y", "tech_selfpct_1y", "opt_selfpct_1y",
                "flag_late_signal", "flag_washout", "flag_earnings_soon"]
    csv_data = snap[[c for c in csv_cols if c in snap.columns]].fillna("")
    csv_text = csv_data.to_csv(index=False)

    sg_options = "<option value=''>All sectors</option>" + "".join(
        f"<option value='{sg}'>{info['label']}</option>" for sg, info in sector_groups.items()
    )
    cluster_options_set = sorted(set(snap.dropna(subset=["cluster_id"])["cluster_id"]))
    cluster_options = "<option value=''>All clusters</option>" + "".join(
        f"<option value='{c}'>{c}</option>" for c in cluster_options_set
    )

    sg_ticker_map = {sg: info["tickers"] for sg, info in sector_groups.items()}

    # === HTML ===
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Positioning Meter — {asof}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #f1f5f9;
  --panel: #ffffff;
  --border: #e2e8f0;
  --text: #0f172a;
  --text-muted: #64748b;
  --text-dim: #94a3b8;
  --primary: #2563eb;
  --primary-dark: #1d4ed8;
  --hot-ext: #b91c1c;
  --hot: #ef4444;
  --neutral: #64748b;
  --cold: #10b981;
  --cold-ext: #047857;
  --warning: #f59e0b;
  --shadow-sm: 0 1px 2px rgba(15,23,42,0.04);
  --shadow: 0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04);
  --shadow-lg: 0 4px 12px rgba(15,23,42,0.08);
  --radius: 10px;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  font-size: 14px;
  font-feature-settings: 'cv02', 'cv03', 'cv04', 'cv11';
}}
.container {{ max-width: 1400px; margin: 0 auto; padding: 1.5rem; }}

/* Header */
.app-header {{
  background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
  color: white;
  padding: 1.5rem 0;
  margin-bottom: 1.5rem;
  box-shadow: var(--shadow-lg);
}}
.app-header .container {{ padding-top: 0; padding-bottom: 0; }}
.app-header h1 {{ margin: 0 0 0.25rem 0; font-size: 1.75rem; font-weight: 700; }}
.app-header .subtitle {{ opacity: 0.85; font-size: 0.875rem; }}
.app-header .subtitle b {{ font-weight: 600; }}
.freshness {{ display: inline-block; padding: 0.05rem 0.45rem; border-radius: 0.6rem; font-size: 0.78rem; font-weight: 600; vertical-align: middle; }}
.freshness.fresh {{ background: #dcfce7; color: #166534; }}
.freshness.ok {{ background: #fef9c3; color: #854d0e; }}
.freshness.stale {{ background: #fee2e2; color: #991b1b; }}

/* KPI tiles */
.kpis {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}}
.kpi {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.875rem 1rem;
  box-shadow: var(--shadow-sm);
}}
.kpi-label {{ font-size: 0.7rem; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.04em; font-weight: 500; }}
.kpi-value {{ font-size: 1.5rem; font-weight: 700; margin-top: 0.25rem; line-height: 1.2; }}
.kpi-sub {{ font-size: 0.75rem; color: var(--text-dim); margin-top: 0.1rem; }}
.kpi.hot .kpi-value {{ color: var(--hot); }}
.kpi.cold .kpi-value {{ color: var(--cold); }}

/* Tabs */
.tabs {{
  display: flex;
  gap: 0.25rem;
  border-bottom: 2px solid var(--border);
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
}}
.tab {{
  padding: 0.625rem 1rem;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  cursor: pointer;
  color: var(--text-muted);
  font-weight: 500;
  font-family: inherit;
  font-size: 0.875rem;
  transition: all 0.15s;
}}
.tab:hover {{ color: var(--text); background: rgba(37,99,235,0.04); }}
.tab.active {{ color: var(--primary); border-bottom-color: var(--primary); font-weight: 600; }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}

/* Controls */
.controls {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.875rem 1rem;
  margin-bottom: 1.5rem;
  display: flex;
  gap: 0.625rem;
  flex-wrap: wrap;
  align-items: center;
  box-shadow: var(--shadow-sm);
  position: sticky;
  top: 0;
  z-index: 100;
}}
.controls input, .controls select {{
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 0.875rem;
  font-family: inherit;
  background: white;
  color: var(--text);
}}
.controls input {{ min-width: 200px; }}
.controls input:focus, .controls select:focus {{ outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(37,99,235,0.15); }}
.controls button {{
  padding: 0.5rem 1rem;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.875rem;
  font-weight: 500;
  font-family: inherit;
  transition: background 0.15s;
}}
.controls button:hover {{ background: var(--primary-dark); }}
.controls button.secondary {{ background: white; color: var(--text); border: 1px solid var(--border); }}
.controls button.secondary:hover {{ background: var(--bg); }}
#count {{ color: var(--text-muted); font-size: 0.8125rem; margin-left: auto; }}

/* Panels */
.panel {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem;
  margin-bottom: 1.25rem;
  box-shadow: var(--shadow-sm);
}}
.panel h3 {{ margin: 0 0 0.5rem 0; font-size: 1.0625rem; font-weight: 600; color: var(--text); }}
.panel .hint {{ color: var(--text-muted); font-size: 0.8125rem; margin: 0 0 0.875rem 0; }}
.panel .empty {{ color: var(--text-dim); font-style: italic; padding: 1rem 0; }}

.panels-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; margin-bottom: 1.25rem; }}
@media (max-width: 980px) {{ .panels-grid {{ grid-template-columns: 1fr; }} }}
.panels-grid .panel {{ margin-bottom: 0; }}

/* Tables */
.table-wrap {{ overflow-x: auto; max-width: 100%; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.8125rem; }}
th, td {{ padding: 0.5rem 0.625rem; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }}
th {{ background: #f8fafc; font-weight: 600; color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.03em; cursor: help; position: sticky; top: 0; }}
table.sortable th {{ cursor: pointer; user-select: none; }}
table.sortable th:hover {{ color: var(--primary); }}
table.sortable th.sorted-asc::after {{ content: " ▲"; color: var(--primary); }}
table.sortable th.sorted-desc::after {{ content: " ▼"; color: var(--primary); }}
tr:hover td {{ background: #f8fafc; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 0.8125rem; }}
.mono {{ font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 0.8125rem; }}
.name {{ color: var(--text-muted); font-size: 0.8125rem; }}
.flagcol {{ font-size: 1rem; }}

/* Ticker pill */
.ticker-pill {{
  display: inline-block;
  padding: 2px 8px;
  background: rgba(37,99,235,0.08);
  color: var(--primary);
  border-radius: 4px;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8125rem;
  text-decoration: none;
}}
.ticker-pill:hover {{ background: rgba(37,99,235,0.15); }}

/* Temperature classes */
.temp.ext-hot, .stat-val.ext-hot {{ color: var(--hot-ext); font-weight: 700; }}
.temp.hot, .stat-val.hot {{ color: var(--hot); font-weight: 600; }}
.temp.ext-cold, .stat-val.ext-cold {{ color: var(--cold-ext); font-weight: 700; }}
.temp.cold, .stat-val.cold {{ color: var(--cold); font-weight: 600; }}
.temp.neutral, .stat-val.neutral {{ color: var(--text); }}

/* Change indicators */
.chg-up {{ color: var(--hot); }}
.chg-down {{ color: var(--cold); }}

/* Anom muted */
.anom {{ color: var(--text-muted); }}

/* 📖 How to read it tab */
.guide-list {{ line-height:1.7; padding-left:1.1rem; margin:0.5rem 0; }}
.guide-list li {{ margin-bottom:0.6rem; }}
.guide-steps {{ line-height:1.7; padding-left:1.3rem; margin:0.75rem 0 0; }}
.guide-steps li {{ margin-bottom:0.75rem; }}
.guide-example {{ background:var(--panel); border:1px solid var(--border);
                 border-left:3px solid var(--primary); border-radius:8px;
                 padding:1rem 1.25rem; margin-bottom:1rem; }}
.guide-example h4 {{ margin:0 0 0.25rem; font-size:1rem; }}
#tab-guide .panel p {{ line-height:1.7; }}

/* Setup quadrant badges. Only the four corners are colored; the middle is a
   deliberately faint dot so the eye skips it. */
.quad {{ display:inline-block; padding:0.1rem 0.4rem; border-radius:4px;
        font-size:0.6875rem; font-weight:600; white-space:nowrap; letter-spacing:0.01em; }}
.quad-hot  {{ background:rgba(239,68,68,0.16);  color:#dc2626; }}
.quad-warm {{ background:rgba(249,115,22,0.14); color:#ea580c; }}
.quad-cool {{ background:rgba(34,197,94,0.14);  color:#16a34a; }}
.quad-none {{ background:transparent; color:var(--text-muted); opacity:0.45; font-weight:400; }}
@media (prefers-color-scheme: dark) {{
  .quad-hot  {{ background:rgba(239,68,68,0.22);  color:#f87171; }}
  .quad-warm {{ background:rgba(249,115,22,0.20); color:#fb923c; }}
  .quad-cool {{ background:rgba(34,197,94,0.20);  color:#4ade80; }}
}}

/* Glossary */
.glossary {{
  background: linear-gradient(to bottom right, #fffbeb, #fef3c7);
  border: 1px solid #fde68a;
  border-radius: var(--radius);
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
}}
.glossary > summary {{ cursor: pointer; font-weight: 600; color: #92400e; }}
.glossary summary h2 {{ display: inline; margin: 0; font-size: 1.125rem; color: #78350f; }}
.gloss-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 0.875rem;
  margin-top: 1rem;
}}
.gloss-card {{
  background: white;
  border: 1px solid #fde68a;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  font-size: 0.8125rem;
}}
.gloss-card h4 {{ margin: 0 0 0.4rem 0; color: var(--text); font-size: 0.875rem; font-weight: 600; }}
.gloss-card p, .gloss-card ul {{ margin: 0.3rem 0; line-height: 1.5; color: var(--text-muted); }}
.gloss-card ul {{ padding-left: 1.1rem; }}
.gloss-card code {{ background: #f1f5f9; padding: 1px 5px; border-radius: 3px; font-size: 0.75rem; font-family: 'JetBrains Mono', monospace; color: var(--text); }}

/* Drill-down */
.drilldown {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem;
  margin-bottom: 0.875rem;
  scroll-margin-top: 5rem;
  box-shadow: var(--shadow-sm);
}}
.drilldown:target {{ border-color: var(--primary); box-shadow: 0 0 0 3px rgba(37,99,235,0.15), var(--shadow); }}
.drilldown-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 1.5rem; margin-bottom: 1rem; }}
.drilldown-title h3 {{ margin: 0 0 0.25rem 0; font-size: 1.25rem; font-weight: 700; }}
.drilldown-title .ticker-name {{ display: block; font-size: 0.875rem; font-weight: 400; color: var(--text-muted); margin-top: 0.2rem; }}
.drilldown-title .back {{ color: var(--text-dim); text-decoration: none; margin-right: 0.5rem; font-size: 1rem; }}
.drilldown-title .back:hover {{ color: var(--primary); }}
.drilldown-temp {{ text-align: right; }}
.drilldown-temp .temp-big {{ font-size: 2.75rem; font-weight: 700; line-height: 1; font-family: 'JetBrains Mono', monospace; }}
.drilldown-temp .temp-sub {{ font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem; }}
.tag-earnings {{ display: inline-block; background: #fef3c7; color: #92400e; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem; margin-top: 0.4rem; }}
.drilldown-stats {{ display: grid; grid-template-columns: repeat(5, 1fr) auto; gap: 0.625rem; margin-bottom: 1rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border); align-items: center; }}
.chart-card {{ background: #f8fafc; border-radius: 6px; padding: 0.75rem 1rem; margin-bottom: 1rem; }}
.score-narrative {{ background: #eff6ff; border-left: 3px solid var(--primary); border-radius: 6px; padding: 0.6rem 0.9rem; margin-bottom: 1rem; }}
.score-narrative h4 {{ margin: 0 0 0.3rem 0; font-size: 0.8rem; color: var(--text-muted); }}
.score-narrative p {{ margin: 0; font-size: 0.9rem; line-height: 1.45; }}
.score-narrative ul.pillars {{ margin: 0.55rem 0 0 0; padding-left: 1.1rem; }}
.score-narrative ul.pillars li {{ font-size: 0.85rem; line-height: 1.5; margin-bottom: 0.2rem; }}
.score-narrative ul.pillars li.muted {{ color: var(--text-muted); }}
.score-narrative .basis {{ color: var(--text-muted); font-size: 0.78rem; font-style: italic; }}
.book-grid {{ display: grid; grid-template-columns: 1fr; gap: 1.5rem; }}
.book-grid h4 {{ margin: 0 0 0.4rem 0; font-size: 0.9rem; }}
.book-grid table {{ width: 100%; }}
.chart-card-label {{ font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.5rem; font-weight: 500; }}
.spark-6m {{ display: block; width: 100%; max-width: 700px; height: auto; }}
.stat {{ background: #f8fafc; padding: 0.625rem; border-radius: 6px; text-align: center; }}
.stat-label {{ display: block; font-size: 0.7rem; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.03em; font-weight: 500; }}
.stat-val {{ display: block; font-size: 1.125rem; font-weight: 600; margin-top: 0.2rem; font-family: 'JetBrains Mono', monospace; }}
.stat-spark {{ background: #f8fafc; border-radius: 6px; padding: 0.5rem; text-align: center; }}
.spark {{ display: block; margin: 0 auto; }}
.spark-meta {{ font-size: 0.7rem; color: var(--text-muted); margin-top: 0.2rem; }}
.drilldown h4 {{ font-size: 0.875rem; font-weight: 600; color: var(--text); margin: 1rem 0 0.5rem 0; }}
.drilldown table.signals th, .drilldown table.actions th {{ background: #f1f5f9; }}
.thin-banner {{ background: #fef3c7; border: 1px solid #f6cf6b; border-radius: 6px; padding: 0.5rem 0.7rem; margin: 0 0 0.6rem 0; font-size: 0.85rem; line-height: 1.5; color: #7a5b00; }}
.drilldown td.sig-label {{ cursor: help; }}
.info-dot {{ color: var(--text-muted); font-size: 0.7rem; opacity: 0.55; }}
td.sig-label:hover .info-dot {{ opacity: 1; }}
.card {{ margin: 0.875rem 0; padding: 0.875rem 1rem; background: #f8fafc; border-radius: 6px; }}
.overlay-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.625rem; margin-top: 0.5rem; }}
.overlay-grid > div {{ display: flex; flex-direction: column; gap: 0.15rem; }}
.overlay-label {{ font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }}
.overlay-val {{ font-size: 0.875rem; font-weight: 600; font-family: 'JetBrains Mono', monospace; }}
.overlay-val.rec-buy {{ color: var(--cold); }}
.overlay-val.rec-sell {{ color: var(--hot); }}
.peer-row {{ font-size: 0.8125rem; margin: 0.4rem 0; color: var(--text-muted); }}
.peer-label {{ color: var(--text); font-weight: 500; }}
.peer-link {{ color: var(--primary); text-decoration: none; padding: 0 2px; font-family: 'JetBrains Mono', monospace; }}
.peer-link:hover {{ text-decoration: underline; }}
.notes {{ background: white; border: 1px solid var(--border); padding: 0.625rem 0.875rem; font-family: inherit; font-size: 0.8125rem; min-height: 30px; margin: 0; white-space: pre-wrap; border-radius: 6px; }}
.notes-edit {{ width: 100%; background: white; border: 1px solid var(--border); padding: 0.625rem 0.875rem; font-family: inherit; font-size: 0.8125rem; border-radius: 6px; resize: vertical; min-height: 60px; box-sizing: border-box; }}
.notes-edit:focus {{ outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(37,99,235,0.15); }}
.notes-meta {{ font-size: 0.7rem; color: var(--text-muted); margin-top: 0.3rem; min-height: 14px; }}
.notes-status.saved {{ color: var(--cold); }}
.watch-toggle {{ background: none; border: none; font-size: 1.4rem; cursor: pointer; color: #cbd5e1; vertical-align: middle; padding: 0 0.3rem; transition: transform 0.1s, color 0.15s; }}
.watch-toggle:hover {{ transform: scale(1.15); }}
.watch-toggle.watched {{ color: #f59e0b; }}
.watched-row {{ background: #fffbeb !important; }}
.ticker-pill.watched::before {{ content: "★ "; color: #f59e0b; font-size: 0.7em; }}

/* Footer cards */
.footer-card {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.625rem 1rem;
  margin-top: 1.5rem;
  font-size: 0.8125rem;
}}
.footer-card summary {{ cursor: pointer; font-weight: 500; color: var(--text-muted); }}
.footer-card summary:hover {{ color: var(--text); }}

/* Responsive */
@media (max-width: 700px) {{
  .container {{ padding: 0.75rem; }}
  .app-header {{ padding: 1rem 0; }}
  .app-header h1 {{ font-size: 1.25rem; }}
  .kpis {{ grid-template-columns: repeat(2, 1fr); }}
  .drilldown-header {{ flex-direction: column; gap: 0.5rem; }}
  .drilldown-temp {{ text-align: left; }}
  .drilldown-stats {{ grid-template-columns: repeat(3, 1fr); }}
  .drilldown-stats .stat-spark {{ grid-column: span 3; }}
  table {{ font-size: 0.75rem; }}
  th, td {{ padding: 0.4rem 0.5rem; }}
}}
</style>
</head>
<body>
<a id=top></a>

<header class=app-header>
<div class=container>
<h1>Positioning Meter</h1>
<div class=subtitle>Data as of <b>{asof}</b> {freshness_html} · rendered {generated_at} · {kpi_total} TMT names · <b>V1.17</b> (Pos 0.50 / Tech 0.20 / Opt 0.30; positioning = short interest + insider flow + float-turnover crowding) · <b>1-month factor-neutral</b> IC <b>{vs['is_ic']}</b> in-sample / <b>{vs['oos_ic']}</b> out-of-sample (t {vs['oos_t']}) · weak signal, see Backtest tab</div>
</div>
</header>

<div class=container>

<div class=kpis>
<div class=kpi><div class=kpi-label>Universe</div><div class=kpi-value>{kpi_total}</div><div class=kpi-sub>names with composite</div></div>
<div class=kpi><div class=kpi-label>Avg temp</div><div class=kpi-value>{kpi_avg_temp:.1f}</div><div class=kpi-sub>0=cold · 100=hot</div></div>
<div class="kpi hot"><div class=kpi-label>% hot (≥70)</div><div class=kpi-value>{kpi_pct_hot:.0f}%</div><div class=kpi-sub>{int(kpi_pct_hot/100*kpi_total)} names</div></div>
<div class="kpi cold"><div class=kpi-label>% cold (≤30)</div><div class=kpi-value>{kpi_pct_cold:.0f}%</div><div class=kpi-sub>{int(kpi_pct_cold/100*kpi_total)} names</div></div>
<div class="kpi hot"><div class=kpi-label>🔥 Late flag</div><div class=kpi-value>{kpi_late}</div><div class=kpi-sub>{kpi_new_late} new this week</div></div>
<div class="kpi cold"><div class=kpi-label>❄️ Washout flag</div><div class=kpi-value>{kpi_wash}</div><div class=kpi-sub>{kpi_new_wash} new this week</div></div>
<div class=kpi><div class=kpi-label>📅 Earnings ≤14d</div><div class=kpi-value>{kpi_earnings}</div><div class=kpi-sub>names reporting soon</div></div>
</div>

{render_glossary()}

<div class=controls>
<input type=text id=search placeholder="🔍 Search ticker or name…" oninput=filterAll()>
<select id=cluster onchange=filterAll()>{cluster_options}</select>
<select id=sector onchange=filterAll()>{sg_options}</select>
<button onclick=exportCSV() title="Download current snapshot as CSV">📥 CSV</button>
<button onclick=exportNotes() title="Download SQL file to persist your notes + watchlist back to the DB" class=secondary>💾 Export Notes/Watchlist SQL</button>
<button onclick=clearFilters() class=secondary>↻ Clear filters</button>
<span id=count></span>
</div>

<div class=tabs>
<button class="tab active" data-tab=overview onclick=showTab('overview')>📊 Overview</button>
<button class=tab data-tab=allnames onclick=showTab('allnames')>📋 All Names ({kpi_total})</button>
<button class=tab data-tab=movers onclick=showTab('movers')>📈 Movers</button>
<button class=tab data-tab=flags onclick=showTab('flags')>🚩 Flags</button>
<button class=tab data-tab=watchlist onclick=showTab('watchlist')>👁️ Watchlist (<span id=watchCount>{len(watchlist_df)}</span>)</button>
<button class=tab data-tab=book onclick=showTab('book')>📕 Book</button>
<button class=tab data-tab=guide onclick=showTab('guide')>📖 How to read it</button>
<button class=tab data-tab=backtest onclick=showTab('backtest')>📈 Backtest</button>
<button class=tab data-tab=detail onclick=showTab('detail')>🔍 Detail (per-ticker)</button>
</div>

<div class="tab-content active" id=tab-overview>
<div class=panels-grid>
{render_summary_table(hottest, "🔥 Hottest 25", "Highest composite temperature — most extreme positioning + price-revealed sentiment + options sentiment.")}
{render_summary_table(coldest, "❄️ Coldest 25", "Lowest composite temperature — most washed out names.")}
</div>
</div>

<div class="tab-content" id=tab-allnames>
<div class=panel>
<h3>📋 All names ({kpi_total})</h3>
<p class=hint>Sortable by clicking any column header. Use the search/filter at top to narrow down. Click any ticker to jump to its detail card.</p>
<div class=table-wrap>
<table id=allNamesTable class="rank sortable">
<thead><tr>
<th title="Star to add/remove from watchlist">★</th>
<th data-sort=ticker>Ticker</th>
<th data-sort=name>Name</th>
<th class=num data-sort=temp title="Composite 0-100. Compressed by construction — sort/judge on Univ %ile beside it.">Temp</th>
<th class=num data-sort=univpct title="{UNIVPCT_HDR_TITLE}">{UNIVPCT_COL}</th>
<th class=num data-sort=chg7d>7d Δ</th>
<th class=num data-sort=quadrank title="{QUAD_HDR_TITLE}">Setup</th>
<th class=num data-sort=self1y title="Temperature vs this name's OWN trailing 1-year range (percentile 0-100). High = hot for itself, low = washed-out for itself. Sort this to find structurally cool/hot names that are extreme relative to their own norm. Hover a cell for z-score + 6-month read.">Self 1y</th>
<th class=num data-sort=xself1y title="{EXTECH_HDR_TITLE}">{EXTECH_COL}</th>
<th class=num data-sort=pos title="Positioning &amp; crowding. Best-validated pillar — see the 📖 How to read it tab.">Pos</th>
<th class=num data-sort=tech>Tech</th>
<th class=num data-sort=opt title="Options sentiment. Small sample — see the 📖 How to read it tab.">Opt</th>
<th class=num data-sort=anom>Anom</th>
<th class=num data-sort=mcap_b title="Market cap ($B)">$B</th>
<th>Flags</th>
</tr></thead>
<tbody></tbody>
</table>
</div>
</div>
</div>

<div class="tab-content" id=tab-movers>
<div class=panels-grid>
{render_summary_table(movers_up, "📈 Heating up (top 20 by 7d temp Δ)", "Names whose temperature rose most.")}
{render_summary_table(movers_down, "📉 Cooling off (top 20 by 7d temp Δ)", "Names whose temperature dropped most.")}
</div>
</div>

<div class="tab-content" id=tab-flags>
{render_summary_table(late_flagged, f"🔥 Compound LATE flag ({len(late_flagged)} names)", "Pos ≥ 85, Val ≥ 80, Tech ≥ 85.", "No names triggered today.")}
{render_summary_table(wash_flagged, f"❄️ Compound WASHOUT flag ({len(wash_flagged)} names)", "Pos ≤ 15, Val ≤ 25, Tech ≤ 15.", "No names triggered today.")}
{render_summary_table(new_late_df, f"🆕 NEW Late flags (last 7d, {len(new_late_df)})", "Newly entered LATE in past 7 days.", "(none)")}
{render_summary_table(new_wash_df, f"🆕 NEW Washout flags (last 7d, {len(new_wash_df)})", "Newly entered WASHOUT in past 7 days.", "(none)")}
{render_summary_table(earnings_soon, f"📅 Earnings within 14d ({len(earnings_soon)})", "Reporting in next 2 weeks.", "(none)")}
</div>

<div class="tab-content" id=tab-watchlist>
<div class=panel>
<h3>👁️ Watchlist (<span id=watchCountPanel>0</span>)</h3>
<p class=hint>Click the <b>☆</b> star on any ticker — in the table below, the <b>All Names</b> list, or a ticker's <b>Detail</b> card — to add or remove it here. Saved in this browser instantly; no code or SQL needed. Use <b>💾 Export Notes/Watchlist SQL</b> if you want it persisted to the database across devices.</p>
<div id=watchEmpty class=hint style="padding:1rem 0">Nothing here yet — star a ticker (☆) anywhere to add it to your watchlist.</div>
<div class=table-wrap>
<table id=watchTable class=rank>
<thead><tr>
<th title="Star to add/remove">★</th>
<th>Ticker</th>
<th>Name</th>
<th class=num>Temp</th>
<th class=num title="{UNIVPCT_HDR_TITLE}">{UNIVPCT_COL}</th>
<th class=num>7d Δ</th>
<th class=num title="{QUAD_HDR_TITLE}">Setup</th>
<th class=num title="Temperature vs this name's own trailing 1-year range (percentile). High = hot for itself.">Self 1y</th>
<th class=num title="{EXTECH_HDR_TITLE}">{EXTECH_COL}</th>
<th class=num title="Positioning &amp; crowding. Best-validated pillar — see the 📖 How to read it tab.">Pos</th>
<th class=num>Tech</th>
<th class=num title="Options sentiment. Small sample — see the 📖 How to read it tab.">Opt</th>
<th class=num>Anom</th>
<th class=num title="Market cap ($B)">$B</th>
<th>Flags</th>
</tr></thead>
<tbody></tbody>
</table>
</div>
</div>
</div>

<div class="tab-content" id=tab-book>
{render_live_performance()}
{render_model_book(snap)}
</div>

<div class="tab-content" id=tab-guide>
{render_reading_guide(snap, data["sig_long"], vs)}
</div>

<div class="tab-content" id=tab-backtest>
{render_methodology_card(vs)}
{render_backtest_card(data["backtest_results"], signal_weights_for_dash, signal_to_bucket_for_dash, bucket_weights_for_dash)}
</div>

<div class="tab-content" id=tab-detail>
<div class=panel>
<h3>🔍 Per-ticker drill-down ({len(drilldowns)} cards)</h3>
<p class=hint>Click any ticker in any table to jump here. Use the search filter above to narrow this view.</p>
</div>
{''.join(drilldowns)}
</div>

{render_provenance(data["provenance"])}

<details class=footer-card>
<summary><b>Methodology</b></summary>
<div style="max-width:850px;line-height:1.6;color:var(--text-muted);font-size:0.8125rem;padding-top:0.5rem;">
<p><b>Universe</b>: {kpi_total} TMT names (mcap ≥ $1.5B) drawn from theme_detector, plus hand-curated additions in <code>data/universe_manual_additions.csv</code>.</p>
<p><b>Signals</b>: ~27 daily signals — 15 in the composite, the rest overlay-only. Inclusion driven by backtest IC sign (positive IC = trend-following, excluded from the contrarian composite).</p>
<p><b>Percentile basis</b>: every composite signal (all three buckets) is a <b>50/50 blend</b> of the stock's own-5yr-history rank and its rank vs the full TMT universe today — so each percentile blends "extended vs its own norm?" with "extended vs peers right now?". Bucket scores are the (IC-weighted) average of their signals' percentiles.</p>
<p><b>Composite</b>: weighted average of bucket scores (Pos 0.50 / Tech 0.20 / Opt 0.30), reweighted when a bucket is missing.</p>
<p><b>Self-history columns</b>: <b>Self 1y</b> ranks today's Temperature against the same name's own trailing 252 trading days. <b>Self 1y P+O</b> does the same on a positioning+options-only composite (0.625 / 0.375 — technicals excluded), so the own-history read can be separated from price action. Options data begins 2026-05-12; earlier dates in that window are scored on positioning alone. Neither column feeds the composite or the backtest — they are read-outs, not model inputs.</p>
<p><b>Backtest (V1.17)</b>: <b>1-month, factor-neutral, non-overlapping</b>. In-sample IC <b>{vs['is_ic']}</b> (t {vs['is_t']}). Walk-forward <b>out-of-sample IC {vs['oos_ic']}</b> (t {vs['oos_t']}): the rank signal partially survives but is weak/borderline; the decile long/short is unreliable out-of-sample. 3-month is insignificant. Numbers auto-computed by <code>tools/compute_validation_stats.py</code> (as of {vs['asof']}); weights tuned via <code>tools/tune_weights_1m.py</code> + <code>tools/bucket_weight_scan.py</code>. Options has no backtest history — its weight is a prior. See the 🧮 Methodology card.</p>
<p><b>Limitations</b>: options bucket is live but unvalidated (no historical options data). Float uses a current snapshot across history (mild look-ahead). ETF flows + EPS revisions are forward-only. 13F has a 45-day lag and is long-only.</p>
</div>
</details>

</div>

<script>
// On a genuine reload, always land at the top with the Overview tab — never
// restore the prior scroll or jump to a #t- ticker anchor. Deep links (a fresh
// visit to a #t-XXX URL) still honor the anchor.
const NAV_TYPE = (performance.getEntriesByType('navigation')[0] || {{}}).type;
if ('scrollRestoration' in history) {{ history.scrollRestoration = 'manual'; }}
window.addEventListener('load', () => {{
  if (NAV_TYPE === 'reload' || !window.location.hash.startsWith('#t-')) {{
    if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
    showTab('overview');
    window.scrollTo(0, 0);
  }}
}});

const CSV = {json.dumps(csv_text)};
const SECTOR_TICKERS = {json.dumps(sg_ticker_map)};
const ALL_NAMES = {json.dumps(all_names_data)};
const TOTAL_NAMES = {len(snap)};
const DB_WATCHLIST = {json.dumps(sorted(watchlist_df["ticker"].tolist()) if not watchlist_df.empty else [])};

// Shared row renderer for the All Names + Watchlist tables (leading ☆ star cell).
function rowHtml(r) {{
  const fmt = (v, p) => v == null ? '—' : v.toFixed(p);
  const tempCls = v => v == null ? '' : v >= 85 ? 'ext-hot' : v >= 70 ? 'hot' : v <= 15 ? 'ext-cold' : v <= 30 ? 'cold' : 'neutral';
  return `
    <tr data-ticker="${{r.ticker}}">
      <td><button class=watch-toggle data-ticker="${{r.ticker}}" onclick="event.stopPropagation();toggleWatch('${{r.ticker}}')" title="Add/remove from watchlist">☆</button></td>
      <td><a href="#t-${{r.ticker}}" class=ticker-pill onclick="showTab('detail')">${{r.ticker}}</a></td>
      <td class=name>${{r.name}}</td>
      <td class="num temp ${{tempCls(r.temp)}}">${{fmt(r.temp, 1)}}</td>
      <td class="num temp ${{tempCls(r.univpct)}}" title="${{r.univpct == null ? 'No composite temperature today.' : 'Temperature ranks at the ' + r.univpct.toFixed(0) + 'th percentile of the TMT universe today. Read this rather than the raw Temp — the composite is compressed toward 50 by averaging ~15 percentile signals.'}}">${{r.univpct == null ? '—' : r.univpct.toFixed(0)}}</td>
      <td class="num ${{r.chg7d > 0 ? 'chg-up' : r.chg7d < 0 ? 'chg-down' : ''}}">${{r.chg7d == null ? '—' : (r.chg7d >= 0 ? '+' : '') + r.chg7d.toFixed(1)}}</td>
      <td class=num><span class="quad ${{r.quadcls}}" title="${{r.quadtitle}}">${{r.quad}}</span></td>
      <td class="num temp ${{tempCls(r.self1y)}}" title="${{r.self1y == null ? 'No self-history yet' : 'Temp at its ' + r.self1y.toFixed(0) + 'th %ile vs own 1y' + (r.selfz == null ? '' : ' (' + (r.selfz>=0?'+':'') + r.selfz.toFixed(1) + 'σ)') + (r.self6m == null ? '' : ' · 6mo: ' + r.self6m.toFixed(0) + 'th') + '. High = hot for itself.'}}">${{r.self1y == null ? '—' : r.self1y.toFixed(0)}}</td>
      <td class="num temp ${{tempCls(r.xself1y)}}" title="${{r.xself1y == null ? 'No self-history yet' : 'Positioning+Options blend at its ' + r.xself1y.toFixed(0) + 'th %ile vs own 1y' + (r.xselfz == null ? '' : ' (' + (r.xselfz>=0?'+':'') + r.xselfz.toFixed(1) + 'σ)') + (r.xself6m == null ? '' : ' · 6mo: ' + r.xself6m.toFixed(0) + 'th') + '. Technicals excluded (0.625 Pos / 0.375 Opt). Options history starts 2026-05-12 — earlier window is positioning-only.'}}">${{r.xself1y == null ? '—' : r.xself1y.toFixed(0)}}</td>
      <td class=num>${{fmt(r.pos, 1)}}</td>
      <td class=num>${{fmt(r.tech, 1)}}</td>
      <td class=num>${{fmt(r.opt, 1)}}</td>
      <td class="num anom">${{r.anom == null ? '—' : r.anom}}</td>
      <td class=num>${{r.mcap_b == null ? '—' : '$' + r.mcap_b.toFixed(1)}}</td>
      <td class=flagcol>${{r.late ? '🔥' : ''}}${{r.wash ? '❄️' : ''}}${{r.earn ? '📅' : ''}}</td>
    </tr>`;
}}

// Watchlist tab is driven live by the browser watchlist (localStorage), seeded
// once from the DB table so CLI/exported entries show up too.
function seedWatchlistFromDB() {{
  if (getWatchlist().length === 0 && DB_WATCHLIST.length) setWatchlist(DB_WATCHLIST.slice());
}}
function renderWatchlist() {{
  const wl = new Set(getWatchlist());
  const rows = ALL_NAMES.filter(r => wl.has(r.ticker))
    .sort((a, b) => (b.temp == null ? -Infinity : b.temp) - (a.temp == null ? -Infinity : a.temp));
  const tbody = document.querySelector('#watchTable tbody');
  if (tbody) tbody.innerHTML = rows.map(rowHtml).join('');
  const empty = document.getElementById('watchEmpty');
  const tbl = document.getElementById('watchTable');
  if (empty) empty.style.display = rows.length ? 'none' : 'block';
  if (tbl) tbl.style.display = rows.length ? '' : 'none';
  const n = String(rows.length);
  ['watchCount', 'watchCountPanel'].forEach(id => {{ const e = document.getElementById(id); if (e) e.textContent = n; }});
  applyWatchedStyling();
}}

// === Tabs ===
function showTab(id) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === id));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + id));
}}

// === All-names table render ===
let allNamesSortKey = 'temp';
let allNamesSortDir = 'desc';
function renderAllNames() {{
  const tbody = document.querySelector('#allNamesTable tbody');
  const data = [...ALL_NAMES].sort((a, b) => {{
    let av = a[allNamesSortKey], bv = b[allNamesSortKey];
    if (av == null) av = allNamesSortDir === 'desc' ? -Infinity : Infinity;
    if (bv == null) bv = allNamesSortDir === 'desc' ? -Infinity : Infinity;
    if (typeof av === 'string') return allNamesSortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    return allNamesSortDir === 'asc' ? av - bv : bv - av;
  }});
  tbody.innerHTML = data.map(rowHtml).join('');
  // Update sort indicators
  document.querySelectorAll('#allNamesTable th').forEach(th => {{
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.dataset.sort === allNamesSortKey) th.classList.add(allNamesSortDir === 'asc' ? 'sorted-asc' : 'sorted-desc');
  }});
  filterAll();
}}

// === Sort headers ===
document.addEventListener('DOMContentLoaded', () => {{
  document.querySelectorAll('#allNamesTable th[data-sort]').forEach(th => {{
    th.addEventListener('click', () => {{
      const key = th.dataset.sort;
      if (allNamesSortKey === key) {{
        allNamesSortDir = allNamesSortDir === 'asc' ? 'desc' : 'asc';
      }} else {{
        allNamesSortKey = key;
        allNamesSortDir = ['ticker','name','cluster'].includes(key) ? 'asc' : 'desc';
      }}
      renderAllNames();
    }});
  }});
}});

// === Search/filter (works across all tables AND drilldowns AND all-names) ===
function filterAll() {{
  const q = document.getElementById('search').value.toLowerCase();
  const cluster = document.getElementById('cluster').value;
  const sector = document.getElementById('sector').value;
  const sectorTickers = sector ? new Set(SECTOR_TICKERS[sector] || []) : null;
  let visible = 0;

  const matchTicker = (ticker, name) => {{
    if (q && !ticker.toLowerCase().includes(q) && !(name||'').toLowerCase().includes(q)) return false;
    if (cluster) {{
      const r = ALL_NAMES.find(x => x.ticker === ticker);
      if (!r || r.cluster !== cluster) return false;
    }}
    if (sectorTickers && !sectorTickers.has(ticker)) return false;
    return true;
  }};

  document.querySelectorAll('table.rank tbody tr').forEach(tr => {{
    const ticker = tr.dataset.ticker || '';
    const name = (tr.querySelector('.name')?.textContent || '');
    const ok = matchTicker(ticker, name);
    tr.style.display = ok ? '' : 'none';
    if (ok) visible++;
  }});

  document.querySelectorAll('section.drilldown').forEach(sec => {{
    const ticker = sec.dataset.ticker || '';
    const name = sec.querySelector('h3')?.textContent || '';
    sec.style.display = matchTicker(ticker, name) ? '' : 'none';
  }});

  const cnt = document.getElementById('count');
  if (q || cluster || sector) {{
    cnt.textContent = `${{visible}} matching rows`;
  }} else {{
    cnt.textContent = '';
  }}
}}

function clearFilters() {{
  document.getElementById('search').value = '';
  document.getElementById('cluster').value = '';
  document.getElementById('sector').value = '';
  filterAll();
}}

function exportCSV() {{
  const blob = new Blob([CSV], {{type: 'text/csv'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `positioning_meter_${{new Date().toISOString().slice(0,10)}}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}}

// Auto-show 'detail' tab when navigating to a #t-XXX anchor
window.addEventListener('hashchange', () => {{
  if (window.location.hash.startsWith('#t-')) {{
    showTab('detail');
    setTimeout(() => {{
      const el = document.querySelector(window.location.hash);
      if (el) el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }}, 50);
  }}
}});
if (NAV_TYPE !== 'reload' && window.location.hash.startsWith('#t-')) {{
  showTab('detail');
}}

// === Notes (localStorage) ===
function loadNotes() {{
  document.querySelectorAll('textarea.notes-edit').forEach(ta => {{
    const t = ta.dataset.ticker;
    const stored = localStorage.getItem('note_' + t);
    if (stored !== null && stored !== '') ta.value = stored;
    ta.addEventListener('input', () => saveNote(t, ta));
  }});
}}
function saveNote(ticker, ta) {{
  const v = ta.value;
  if (v.trim() === '') {{
    localStorage.removeItem('note_' + ticker);
  }} else {{
    localStorage.setItem('note_' + ticker, v);
  }}
  const status = document.querySelector(`.notes-status[data-ticker="${{ticker}}"]`);
  if (status) {{
    status.textContent = '✓ saved to browser';
    status.classList.add('saved');
    clearTimeout(status._t);
    status._t = setTimeout(() => {{ status.textContent = ''; status.classList.remove('saved'); }}, 1500);
  }}
}}

// === Watchlist (localStorage) ===
function getWatchlist() {{
  try {{ return JSON.parse(localStorage.getItem('watchlist') || '[]'); }} catch (e) {{ return []; }}
}}
function setWatchlist(list) {{
  localStorage.setItem('watchlist', JSON.stringify(list));
}}
function isWatched(t) {{ return getWatchlist().includes(t); }}
function toggleWatch(t) {{
  let list = getWatchlist();
  if (list.includes(t)) {{
    list = list.filter(x => x !== t);
  }} else {{
    list.push(t);
  }}
  setWatchlist(list);
  applyWatchedStyling();
  renderWatchlist();
}}
function applyWatchedStyling() {{
  const watched = new Set(getWatchlist());
  document.querySelectorAll('.watch-toggle').forEach(btn => {{
    const t = btn.dataset.ticker;
    if (watched.has(t)) {{
      btn.classList.add('watched');
      btn.textContent = '★';
    }} else {{
      btn.classList.remove('watched');
      btn.textContent = '☆';
    }}
  }});
  document.querySelectorAll('.ticker-pill').forEach(a => {{
    const t = a.textContent.trim();
    a.classList.toggle('watched', watched.has(t));
  }});
  document.querySelectorAll('table.rank tbody tr').forEach(tr => {{
    const t = tr.dataset.ticker;
    tr.classList.toggle('watched-row', watched.has(t));
  }});
}}

// === Export notes + watchlist as SQL ===
function exportNotes() {{
  const lines = [
    "-- Positioning Meter — notes + watchlist export",
    "-- Generated: " + new Date().toISOString(),
    "-- Run: sqlite3 data/positioning.db < this_file.sql",
    ""
  ];
  // Notes
  const noteEntries = [];
  for (let i = 0; i < localStorage.length; i++) {{
    const k = localStorage.key(i);
    if (k.startsWith('note_')) {{
      const t = k.slice(5);
      const v = localStorage.getItem(k).replaceAll("'", "''");
      noteEntries.push(`INSERT OR REPLACE INTO ticker_notes (ticker, note, updated_at) VALUES ('${{t}}', '${{v}}', date('now'));`);
    }}
  }}
  if (noteEntries.length > 0) {{
    lines.push("-- Notes (" + noteEntries.length + ")");
    lines.push(...noteEntries, "");
  }}
  // Watchlist
  const wl = getWatchlist();
  if (wl.length > 0) {{
    lines.push("-- Watchlist (" + wl.length + ")");
    lines.push("DELETE FROM watchlist;  -- replace existing");
    wl.forEach(t => lines.push(`INSERT INTO watchlist (ticker, label, added_at) VALUES ('${{t}}', '', date('now'));`));
  }}
  if (noteEntries.length === 0 && wl.length === 0) {{
    alert('No notes or watchlist entries to export. Add some first by writing in a notes box or starring a ticker.');
    return;
  }}
  const blob = new Blob([lines.join('\\n')], {{type: 'text/plain'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `positioning_notes_${{new Date().toISOString().slice(0,10)}}.sql`;
  a.click();
  URL.revokeObjectURL(url);
}}

// Init notes + watchlist + render All Names table after DOM is ready.
// Render All Names eagerly so search works from any tab.
document.addEventListener('DOMContentLoaded', () => {{
  seedWatchlistFromDB();
  renderAllNames();
  renderWatchlist();
  loadNotes();
  applyWatchedStyling();
}});
</script>
</body></html>
"""
    HTML_OUT.write_text(html)
    print(f"Wrote {HTML_OUT} ({len(html):,} bytes, {len(drilldowns)} drilldowns)")


if __name__ == "__main__":
    asof = sys.argv[1] if len(sys.argv) > 1 else None
    main(asof)
