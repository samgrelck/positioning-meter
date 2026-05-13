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

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import project_path
from lib.db import connect


HTML_OUT = project_path("data/dashboard.html")
SECTOR_GROUPS_PATH = project_path("data/sector_groups.json")


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
        "SELECT ticker, date, temperature FROM composite_daily WHERE date >= date(?, '-200 days')",
        conn, params=(latest,), parse_dates=["date"],
    )
    sparkline_data = {}
    chart_data = {}
    if not spark_df.empty:
        for t, grp in spark_df.groupby("ticker"):
            srt = grp.sort_values("date")[["date", "temperature"]].dropna()
            if len(srt) > 0:
                vals = srt["temperature"].tolist()
                sparkline_data[t] = vals[-30:]
                chart_data[t] = [(d.strftime("%Y-%m-%d"), v) for d, v in zip(srt["date"], vals)][-180:]

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
        "09_ingest_nasdaq_si_status.json": "Short interest (NASDAQ)",
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
    "short_volume_ratio_14d": ("Short volume 14d ratio", "FINRA Reg SHO short-vol/total-vol, 14d avg."),
    "si_true_dtc": ("Short interest days-to-cover", "NASDAQ true SI ÷ avg daily share volume."),
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
                <td class="num {chg_class}">{chg_str}</td>
                <td class=num>{fmt(r.get('score_positioning'))}</td>
                <td class=num>{fmt(r.get('score_technical'))}</td>
                <td class=num>{fmt(r.get('score_options'))}</td>
                <td class="num conv">{fmt(r.get('conviction'))}</td>
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
                    <th class=num title="Composite 0-100. High=hot/late (contrarian-bearish). Low=cold/washed (contrarian-bullish)">Temp</th>
                    <th class=num title="7-day change in temperature">7d Δ</th>
                    <th class=num title="Positioning bucket">Pos</th>
                    <th class=num title="Technical / price-revealed sentiment">Tech</th>
                    <th class=num title="Options sentiment bucket (IV rank, skew, term slope, P/C)">Opt</th>
                    <th class=num title="Conviction (bucket agreement)">Conv</th>
                    <th class=num title="# signals at 90th+ %ile vs cluster peers">Anom</th>
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


def render_drilldown(snap_row, sig_long, est_row, earnings_row, actions,
                     sparkline, chart_series, notes_row, sector_groups, cluster_mates, sector_mates,
                     bucket_weights=None, signal_weights=None, signal_to_bucket=None) -> str:
    t = snap_row["ticker"]
    name = snap_row.get("name") or t

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
            label, _ = SIGNAL_DESCRIPTIONS.get(sn, (sn, ""))
            ps = sr.get("pct_self")
            pp = sr.get("pct_peer")
            ps_cls = temp_class(ps) if ps is not None else ""
            pp_cls = temp_class(pp) if pp is not None else ""
            sig_rows.append(f"""
                <tr>
                    <td>{label}</td>
                    <td class=mono>{sr['bucket']}</td>
                    <td class="num mono">{fmt(sr['raw_value'], 4)}</td>
                    <td class="num {ps_cls}">{fmt(ps)}</td>
                    <td class="num {pp_cls}">{fmt(pp)}</td>
                </tr>
            """)
    sig_table = f"""
        <h4>📊 Signal-by-signal breakdown</h4>
        <p class=hint>Each signal is ranked vs (a) its own 5y history and (b) cluster peers. The two are blended 50/50 to form a per-signal score, which is then weighted by the signal-weight column to form the bucket score.</p>
        <table class=signals>
            <thead><tr><th>Signal</th><th>Bucket</th><th class=num>Raw value</th>
                <th class=num title="Percentile vs own 5-year history">%ile (self)</th>
                <th class=num title="Percentile vs cluster peers">%ile (peer)</th></tr></thead>
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
                # Each signal's contribution to its bucket = signal_weight × dual_pct
                rows = []
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
                    total_sw += sw
                    weighted_total += sw * dual
                    label = SIGNAL_DESCRIPTIONS.get(sn, (sn, ""))[0]
                    rows.append(f"""
                        <tr>
                            <td>{label}</td>
                            <td class="num mono">{dual:.1f}</td>
                            <td class="num mono">{sw:.3f}</td>
                            <td class="num mono">{(sw * dual):.2f}</td>
                        </tr>
                    """)
                if rows and total_sw > 0:
                    final_bkt = weighted_total / total_sw
                    rows.append(f"""
                        <tr style="border-top:2px solid var(--border); font-weight:600">
                            <td>Σ (bucket score)</td>
                            <td class="num mono">{final_bkt:.1f}</td>
                            <td class="num mono">{total_sw:.3f}</td>
                            <td class="num mono">{weighted_total:.2f}</td>
                        </tr>
                    """)
                    per_signal_html += f"""
                        <details>
                        <summary><b>{bkt.capitalize()} bucket — signal weights from IC</b></summary>
                        <table class=signals>
                            <thead><tr>
                                <th>Signal</th>
                                <th class=num>Dual %ile</th>
                                <th class=num title="Weight from |IC| at 3m fwd, normalized within bucket">Sig weight</th>
                                <th class=num>Contribution</th>
                            </tr></thead>
                            <tbody>{''.join(rows)}</tbody>
                        </table>
                        </details>
                    """

        breakdown_html = f"""
        <div class=card>
            <h4>🧮 How {t}'s Temperature = {fmt(temp)} was calculated</h4>
            <p class=hint><b>Step 1:</b> Each underlying signal is scored vs own history and cluster peers (50/50 blend) → percentile 0–100. <b>Step 2:</b> Within each bucket, signals are averaged using IC-based weights (stronger contrarian signals dominate). <b>Step 3:</b> Buckets are combined using configured bucket weights, renormalized for any missing buckets.</p>
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
            <div class=stat><span class=stat-label>Conv</span><span class=stat-val>{fmt(snap_row.get('conviction'))}</span></div>
            <div class=stat><span class=stat-label>Anom</span><span class=stat-val>{fmt(snap_row.get('anomaly_count'), 0)}</span></div>
            <div class=stat-spark>{spark_svg}</div>
        </div>
        <div class=chart-card>
            <div class=chart-card-label>📈 Temperature, last 6 months (red zone ≥70 = hot, green zone ≤30 = cold)</div>
            {_render_6m_chart(chart_series)}
        </div>
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


def render_backtest_card(results: list) -> str:
    if not results:
        return ""
    composite = [r for r in results if r["signal"] == "COMPOSITE_TEMPERATURE"]
    sig_results = [r for r in results if r["signal"] != "COMPOSITE_TEMPERATURE"]

    # Best row per signal
    by_sig = {}
    for r in sig_results:
        s = r["signal"]
        if s not in by_sig or (r.get("ic") is not None and abs(r["ic"]) > abs(by_sig[s].get("ic") or 0)):
            by_sig[s] = r

    sig_rows = []
    for s in sorted(by_sig.keys(), key=lambda x: abs(by_sig[x].get("ic") or 0), reverse=True)[:14]:
        r = by_sig[s]
        ic = r.get("ic")
        ic_str = f"{ic:+.4f}" if ic is not None else "—"
        ic_cls = "chg-down" if (ic is not None and ic < 0) else ("chg-up" if ic is not None and ic > 0 else "")
        bars = _render_decile_bars(r.get("decile_means", {}))
        sig_rows.append(f"""
            <tr>
                <td class=mono>{s}</td>
                <td class=mono>{r['kind']} @ {r['horizon']}</td>
                <td class='num mono {ic_cls}'>{ic_str}</td>
                <td class=num>{r.get('top_hit_rate', 0):.1%}</td>
                <td class=num>{r.get('bot_hit_rate', 0):.1%}</td>
                <td>{bars}</td>
            </tr>
        """)

    comp_rows = []
    for r in composite:
        ic = r.get("ic")
        ic_cls = "chg-down" if ic and ic < 0 else "chg-up"
        bars = _render_decile_bars(r.get("decile_means", {}))
        comp_rows.append(f"""
            <tr>
                <td><b>Composite (V1.8)</b></td>
                <td>{r['horizon']}</td>
                <td class='num mono {ic_cls}'>{ic:+.4f}</td>
                <td class=num>{r['top_hit_rate']:.1%}</td>
                <td class=num>{r['bot_hit_rate']:.1%}</td>
                <td>{bars}</td>
            </tr>
        """)

    return f"""
    <div class="panel" id="backtest-panel">
        <h3>📈 Backtest validation (V1.8)</h3>
        <p class=hint>Information Coefficient (Spearman) per signal vs forward returns. <b class=chg-down>Negative IC</b> = contrarian (high signal → negative forward return). Bars show decile-mean forward returns: 10 bars left-to-right = bottom-decile (cold) → top-decile (hot). For a working contrarian signal you want bars sloping <span class=chg-down>green-down on the left</span> and <span class=chg-up>red-up on the right</span>.</p>
        <div class=table-wrap>
        <table class=signals>
            <thead><tr><th>Signal</th><th>Best</th><th class=num>IC</th><th class=num>Top hit</th><th class=num>Bot hit</th><th>Decile spread (cold → hot)</th></tr></thead>
            <tbody>{''.join(comp_rows)}{''.join(sig_rows)}</tbody>
        </table>
        </div>
    </div>
    """


def render_glossary() -> str:
    return """
<details open class=glossary>
<summary><h2>📘 Glossary — what every number means</h2></summary>
<div class=gloss-grid>

<div class=gloss-card>
<h4>Temperature (0–100)</h4>
<p>The composite "how hot/late" score. Each signal is ranked vs (a) its own trailing 5y history (<code>pct_self</code>) and (b) the full TMT universe at the same date (<code>pct_peer</code>), then blended 50/50. Bucket scores are weighted by IC (stronger contrarian signals get more weight). Composite = <b>weighted average</b> of buckets (positioning 0.60, technical 0.25, options 0.15 — weights renormalize when a bucket is missing). <b>High temperature ⇒ stretched positioning + price-revealed sentiment + options sentiment, historically associated with negative forward returns at extremes (V1.8 backtest IC −0.034 at 3m fwd, bot decile hit 58%; options bucket added in V1.7 but not yet backtested).</b></p>
</div>

<div class=gloss-card>
<h4>Bucket scores (Pos / Tech / Opt)</h4>
<p>Each 0–100, average of underlying signals (each signal a percentile vs own history & cluster peers).</p>
<ul>
<li><b>Pos</b> — Positioning: insider Form 4, FINRA short volume, NASDAQ true SI days-to-cover</li>
<li><b>Tech</b> — Sentiment via price action: returns, RSI, distance from 200d MA, % from 52w high</li>
<li><b>Opt</b> — Options sentiment: IV rank, 25Δ skew, term structure slope, P/C ratio (live institutional positioning via options markets)</li>
</ul>
<p><b>NTM P/E</b> (price ÷ forward consensus EPS) is shown on per-ticker drill-downs as overlay context only — <b>NOT</b> in the composite. Tool measures sentiment / positioning only; valuation is fundamental analysis done separately. <b>No TTM multiples are used</b> — only NTM (forward) per design choice.</p>
</div>

<div class=gloss-card>
<h4>Conviction (0–100)</h4>
<p>How much the buckets <i>agree</i>. High conviction = all buckets pointing same way (all hot, or all cold). Low = mixed signals (e.g., extreme positioning but cold technicals, or hot options sentiment with washed-out positioning).</p>
</div>

<div class=gloss-card>
<h4>Anomaly count</h4>
<p>Number of signals where this name is at the 90th+ percentile vs its cluster peers <i>today</i>. High = stands out from peers across many measures.</p>
</div>

<div class=gloss-card>
<h4>7d Δ (temperature change)</h4>
<p>Today's temperature minus 5 trading days ago. <span class=chg-up>Red/positive</span> = heating up. <span class=chg-down>Green/negative</span> = cooling off (contrarian-favorable).</p>
</div>

<div class=gloss-card>
<h4>Compound flags</h4>
<ul>
<li><b>🔥 Late</b> — Positioning ≥ 85 AND Technical ≥ 85. Both buckets triple-extreme.</li>
<li><b>❄️ Washout</b> — Positioning ≤ 15 AND Technical ≤ 15. Both buckets triple-extreme washed.</li>
<li><b>📅 Earnings</b> — earnings reporting within next 14 days.</li>
</ul>
</div>

<div class=gloss-card>
<h4>Color coding (contrarian)</h4>
<p><span class=chg-up>Red</span> = hot/extended/dangerous. <span class=chg-down>Green</span> = cold/washed-out/opportunity. Inverted from typical price-momentum coloring because this tool is contrarian.</p>
</div>

<div class=gloss-card>
<h4>Backtest validation (V1.8 positioning+technical only)</h4>
<p>Composite IC <b>−0.034</b> at 3-month forward (Spearman). Bottom-decile temperature → 58% positive forward return; top-decile → 54% negative. Strongest individual signal: <code>si_true_dtc</code> (NASDAQ days-to-cover) IC <b>−0.080</b> at 3m. <b>Options bucket added V1.7 (yfinance forward-only) — not yet backtested due to no historical options data; live cross-sectional ranking working today.</b> Pct_peer now uses universe-wide ranking (cluster-relative was suppressing cluster-wide moves like a hot CPU cluster).</p>
</div>

</div>
</details>
"""


def main(asof: str | None = None):
    print("Loading data...")
    data = load_data()
    snap = data["snap"]
    asof = data["latest"]
    sector_groups = load_sector_groups()

    wl_tickers = set(data["watchlist"]["ticker"]) if not data["watchlist"].empty else set()

    cluster_to_tickers = snap.groupby("cluster_id")["ticker"].apply(list).to_dict() if "cluster_id" in snap.columns else {}
    ticker_to_sectors = {}
    for sg, info in sector_groups.items():
        for t in info["tickers"]:
            ticker_to_sectors.setdefault(t, []).append(sg)

    # Panels
    hottest = snap.dropna(subset=["temperature"]).nlargest(25, "temperature")
    coldest = snap.dropna(subset=["temperature"]).nsmallest(25, "temperature")
    movers_up = snap.dropna(subset=["temp_7d_chg"]).nlargest(20, "temp_7d_chg")
    movers_down = snap.dropna(subset=["temp_7d_chg"]).nsmallest(20, "temp_7d_chg")
    late_flagged = snap[snap["flag_late_signal"] == 1].sort_values("temperature", ascending=False)
    wash_flagged = snap[snap["flag_washout"] == 1].sort_values("temperature")
    earnings_soon = snap[snap["flag_earnings_soon"] == 1].sort_values("temperature", ascending=False)
    new_late_df = snap[snap["ticker"].isin(data["new_late"])].sort_values("temperature", ascending=False)
    new_wash_df = snap[snap["ticker"].isin(data["new_wash"])].sort_values("temperature")
    watchlist_df = snap[snap["ticker"].isin(wl_tickers)].sort_values("temperature", ascending=False)

    # KPI tile values
    kpi_total = len(snap)
    kpi_late = int((snap["flag_late_signal"] == 1).sum())
    kpi_wash = int((snap["flag_washout"] == 1).sum())
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
            "chg7d": float(r["temp_7d_chg"]) if pd.notna(r.get("temp_7d_chg")) else None,
            "pos": float(r["score_positioning"]) if pd.notna(r.get("score_positioning")) else None,
            "tech": float(r["score_technical"]) if pd.notna(r.get("score_technical")) else None,
            "opt": float(r["score_options"]) if pd.notna(r.get("score_options")) else None,
            "conv": float(r["conviction"]) if pd.notna(r.get("conviction")) else None,
            "anom": int(r["anomaly_count"]) if pd.notna(r.get("anomaly_count")) else None,
            "late": bool(r.get("flag_late_signal") == 1),
            "wash": bool(r.get("flag_washout") == 1),
            "earn": bool(r.get("flag_earnings_soon") == 1),
            "cluster": r.get("cluster_id") or "",
            "mcap_b": float(r["market_cap"]) / 1e9 if pd.notna(r.get("market_cap")) else None,
            "watched": r["ticker"] in wl_tickers,
        })

    # CSV
    csv_data = snap[["ticker", "name", "temperature", "score_positioning",
                     "score_valuation", "score_technical", "conviction",
                     "anomaly_count", "temp_7d_chg",
                     "flag_late_signal", "flag_washout", "flag_earnings_soon"]].fillna("")
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

/* Conv/anom muted */
.conv, .anom {{ color: var(--text-muted); }}

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
<div class=subtitle>As of <b>{asof}</b> · {kpi_total} TMT names · <b>V1.8</b> (Pos 0.60 / Tech 0.25 / Opt 0.15, IC-weighted signals, universe-rank pct_peer) · Backtest IC <b>−0.034</b> at 3m fwd · Bot decile hit <b>57%</b></div>
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
<button class=tab data-tab=watchlist onclick=showTab('watchlist')>👁️ Watchlist ({len(watchlist_df)})</button>
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
<th data-sort=ticker>Ticker</th>
<th data-sort=name>Name</th>
<th class=num data-sort=temp>Temp</th>
<th class=num data-sort=chg7d>7d Δ</th>
<th class=num data-sort=pos>Pos</th>
<th class=num data-sort=tech>Tech</th>
<th class=num data-sort=opt>Opt</th>
<th class=num data-sort=conv>Conv</th>
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
{render_summary_table(watchlist_df, f"👁️ Watchlist ({len(watchlist_df)})", "Tickers in your watchlist table.", "(empty — add via SQL: INSERT INTO watchlist (ticker, label, added_at) VALUES ('NVDA', 'core', date('now')))")}
</div>

<div class="tab-content" id=tab-backtest>
{render_backtest_card(data["backtest_results"])}
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
<p><b>Universe</b>: 366 TMT names (mcap ≥ $1.5B) drawn from theme_detector.</p>
<p><b>Signals</b>: 18 daily signals — 13 in composite, 5 overlay-only. Inclusion driven by backtest IC sign (positive IC = trend, excluded from contrarian composite).</p>
<p><b>Dual percentile</b>: each signal ranked vs (a) own 5y trailing history and (b) cluster peers cross-section. Bucket scores average those.</p>
<p><b>Composite</b>: weighted average of bucket scores. Reweighted when buckets are missing. Min 2 buckets required for a temperature reading.</p>
<p><b>Backtest</b>: 10y daily panel. IC = Spearman correlation between signal percentile and forward return. V1.8 composite (Pos+Tech, weighted 0.6/0.25 with options 0.15 placeholder) IC <b>−0.034</b> at 3m fwd, decile spread <b>−3.6%</b>, bot decile hit <b>58%</b>. V1.7 added options bucket but options have no backtest history (yfinance forward-only). Within-bucket signal weights computed empirically from IC (<code>tools/tune_signal_weights.py</code>). V1.8 changed pct_peer from cluster-relative to universe-wide ranking — cluster-relative was suppressing cluster-wide moves (e.g. when the entire CPU cluster is crowded, ranking within CPUs gave each name ~50th percentile, hiding the cluster-wide elevation). See data/backtest_report.md.</p>
<p><b>Limitations</b>: options bucket not implemented (Polygon $200/mo would unlock). ETF flows forward-only. EPS revisions live snapshot only. NASDAQ true SI covers only NASDAQ-listed names (~65% of universe). 13F has 45-day reporting lag and is long-only.</p>
</div>
</details>

</div>

<script>
const CSV = {json.dumps(csv_text)};
const SECTOR_TICKERS = {json.dumps(sg_ticker_map)};
const ALL_NAMES = {json.dumps(all_names_data)};
const TOTAL_NAMES = {len(snap)};

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
  const fmt = (v, p) => v == null ? '—' : v.toFixed(p);
  const tempCls = v => v == null ? '' : v >= 85 ? 'ext-hot' : v >= 70 ? 'hot' : v <= 15 ? 'ext-cold' : v <= 30 ? 'cold' : 'neutral';
  tbody.innerHTML = data.map(r => `
    <tr data-ticker="${{r.ticker}}">
      <td><a href="#t-${{r.ticker}}" class=ticker-pill onclick="showTab('detail')">${{r.ticker}}</a></td>
      <td class=name>${{r.name}}</td>
      <td class="num temp ${{tempCls(r.temp)}}">${{fmt(r.temp, 1)}}</td>
      <td class="num ${{r.chg7d > 0 ? 'chg-up' : r.chg7d < 0 ? 'chg-down' : ''}}">${{r.chg7d == null ? '—' : (r.chg7d >= 0 ? '+' : '') + r.chg7d.toFixed(1)}}</td>
      <td class=num>${{fmt(r.pos, 1)}}</td>
      <td class=num>${{fmt(r.tech, 1)}}</td>
      <td class=num>${{fmt(r.opt, 1)}}</td>
      <td class="num conv">${{fmt(r.conv, 1)}}</td>
      <td class="num anom">${{r.anom == null ? '—' : r.anom}}</td>
      <td class=num>${{r.mcap_b == null ? '—' : '$' + r.mcap_b.toFixed(1)}}</td>
      <td class=flagcol>${{r.late ? '🔥' : ''}}${{r.wash ? '❄️' : ''}}${{r.earn ? '📅' : ''}}</td>
    </tr>
  `).join('');
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
if (window.location.hash.startsWith('#t-')) {{
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
  renderAllNames();
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
