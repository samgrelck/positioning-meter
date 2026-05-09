"""Render the Positioning Meter HTML dashboard.

Single self-contained HTML file with:
  - Glossary explaining every metric
  - Methodology section (collapsed)
  - Top 25 hot / cold tables, 7d movers, compound flags, earnings soon, watchlist
  - Per-ticker drill-down with sparkline + signal-by-signal breakdown +
    estimates overlay + analyst actions + notes
  - JS-powered search/filter, sector-group filter, CSV export
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

    # Newly-triggered late_signal/washout flags in last 7 days
    recent_flags = pd.read_sql_query(
        """
        SELECT ticker, date, flag_late_signal, flag_washout
        FROM composite_daily
        WHERE date >= date(?, '-14 days')
        """,
        conn, params=(latest,), parse_dates=["date"],
    )
    new_late = []
    new_wash = []
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

    # Per-ticker temperature sparkline data (last ~30 days)
    spark_df = pd.read_sql_query(
        "SELECT ticker, date, temperature FROM composite_daily WHERE date >= date(?, '-45 days')",
        conn, params=(latest,), parse_dates=["date"],
    )
    sparkline_data: dict[str, list[float]] = {}
    if not spark_df.empty:
        for t, grp in spark_df.groupby("ticker"):
            vals = grp.sort_values("date")["temperature"].dropna().tolist()
            if vals:
                sparkline_data[t] = vals[-30:]

    # Per-ticker per-signal data (latest day only, for drill-down)
    sig_long = pd.read_sql_query(
        """SELECT ticker, signal_name, bucket, raw_value, pct_self, pct_peer
           FROM signals_daily WHERE date = ?""",
        conn, params=(latest,),
    )

    # Estimates / earnings calendar / analyst actions
    estimates = pd.read_sql_query(
        "SELECT * FROM estimates_daily WHERE date = (SELECT MAX(date) FROM estimates_daily)",
        conn,
    )
    earnings = pd.read_sql_query("SELECT * FROM earnings_calendar", conn)
    actions = pd.read_sql_query(
        """SELECT ticker, action_date, firm, from_grade, to_grade, action
           FROM analyst_actions
           WHERE action_date >= date('now', '-90 days')
           ORDER BY action_date DESC""",
        conn,
    )

    # Notes + watchlist
    notes = pd.read_sql_query("SELECT ticker, note, updated_at FROM ticker_notes", conn)
    watchlist = pd.read_sql_query("SELECT ticker, label FROM watchlist", conn)

    # Provenance — ingestion timestamps from each ingestion's status file
    provenance = compute_provenance()

    # Backtest summary
    backtest_path = project_path("data/backtest_results.json")
    backtest_results = []
    if backtest_path.exists():
        backtest_results = json.loads(backtest_path.read_text())

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
        "new_late": new_late,
        "new_wash": new_wash,
        "provenance": provenance,
        "backtest_results": backtest_results,
    }


def compute_provenance() -> dict[str, str]:
    """Last-modified time per status JSON in logs/."""
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
    "dist_200ma": ("Distance from 200d MA", "(price − 200-day moving average) / 200d MA."),
    "rsi_14": ("RSI(14)", "14-period Wilder RSI. >70 overbought, <30 oversold."),
    "pct_from_52w_high": ("% from 52w high", "Price relative to trailing 52-week high (0 = at high, negative = below)."),
    "rs_vs_qqq_3m": ("RS vs QQQ (overlay)", "3-month return − QQQ 3-month return. Trend signal — overlay only."),
    "rs_vs_xlk_3m": ("RS vs XLK (overlay)", "3-month return − XLK 3-month return. Trend signal — overlay only."),
    "ttm_pe": ("TTM P/E", "Price ÷ trailing-12-month diluted EPS."),
    "ev_sales": ("EV/Sales (TTM)", "(Mkt cap + debt − cash) ÷ trailing-12m revenue."),
    "insider_net_90d_signed": ("Insider net 90d (signed)", "Σ Form 4 net $ (purchases − sales) over trailing 90 days."),
    "insider_net_90d_abs": ("Insider |net 90d| (overlay)", "Magnitude of insider activity. Overlay — high absolute activity is trend, not contrarian."),
    "short_volume_ratio_14d": ("Short volume 14d ratio", "FINRA Reg SHO daily short-vol ÷ total-vol, 14d rolling avg. Proxy for shorting pressure (level differs from true SI)."),
    "si_true_dtc": ("Short interest days-to-cover", "NASDAQ true SI ÷ avg daily share volume. Bi-monthly settlement, NASDAQ-listed only. STRONGEST contrarian signal in panel."),
    "hf_count_13f": ("HF count 13F (overlay)", "Number of curated HFs holding the name (40-fund universe). Trend signal — high count tends to persist."),
    "hf_top_concentration": ("HF top-5 concentration (overlay)", "Top-5 HFs' $ as % of total HF $ in name."),
    "hf_count_change_4q": ("HF count Δ4q (overlay)", "Quarter-over-quarter change in HF holders (lagged ~90d)."),
}


GLOSSARY = """
<details open class="glossary">
<summary><h2 style="display:inline">📘 Glossary — what every number means</h2></summary>

<div class="gloss-grid">
<div class="gloss-card">
<h4>Temperature (0–100)</h4>
<p>The composite "how hot/late" score. Each name is ranked vs its own trailing 5y history (0 = coldest ever, 100 = hottest ever) AND vs cluster peers, then those two are blended. The composite averages bucket scores. <b>High temperature = positioning + momentum + valuation are all stretched ⇒ historically associated with negative forward returns at extremes (V1.4 backtest IC −0.022 at 3m).</b></p>
</div>

<div class="gloss-card">
<h4>Bucket scores (Pos / Val / Tech)</h4>
<p>Each is 0–100, average of the underlying signals (each signal scored as percentile vs own history & cluster peers). Click any ticker to see the signal-by-signal breakdown.</p>
<ul>
<li><b>Pos</b> — Positioning (insider Form 4, short volume, true SI)</li>
<li><b>Val</b> — Valuation (TTM P/E, EV/Sales)</li>
<li><b>Tech</b> — Technical/momentum (returns, RSI, distance from 200d MA, % from 52w high)</li>
</ul>
</div>

<div class="gloss-card">
<h4>Conviction (0–100)</h4>
<p>How much the buckets <i>agree</i>. High conviction = all buckets pointing the same way (all hot, or all cold). Low conviction = buckets disagree (e.g., expensive valuation but cold technicals — value-trap risk). 100 = perfect agreement; 0 = wide spread.</p>
</div>

<div class="gloss-card">
<h4>Anomaly count</h4>
<p>Number of individual signals where this ticker is at the 90th+ percentile vs its cluster peers <i>today</i>. High = name stands out from peers across many measures. Low = blends in.</p>
</div>

<div class="gloss-card">
<h4>7d Δ (temperature change)</h4>
<p>Today's temperature minus temperature 5 trading days ago. Catches names heating up or cooling off recently. Positive (red) = heating up. Negative (green, contrarian-favorable) = cooling.</p>
</div>

<div class="gloss-card">
<h4>Compound flags</h4>
<ul>
<li><b>Late</b> — Pos ≥ 85, Val ≥ 80, Tech ≥ 85. Triple-extreme stretched.</li>
<li><b>Wash</b> — Pos ≤ 15, Val ≤ 25, Tech ≤ 15. Triple-extreme washed-out.</li>
<li><b>Earnings</b> — earnings within next 14 days.</li>
</ul>
</div>

<div class="gloss-card">
<h4>Why colors are inverted</h4>
<p>This tool is contrarian-oriented: high temperature = "overheated, expect mean reversion" = <b>red/danger</b>. Low temperature = "washed out, expect bounce" = <b>green/opportunity</b>. Opposite of typical price-momentum coloring.</p>
</div>

<div class="gloss-card">
<h4>Backtest validation</h4>
<p>V1.4 composite IC −0.022 at 3-month forward horizon (Spearman). Bottom decile → 56% positive forward return; top decile → 56% negative forward return. Strongest individual signal: <code>si_true_dtc</code> (NASDAQ days-to-cover) IC −0.064 at 3m. See backtest_report.md for full per-signal metrics.</p>
</div>

</div>
</details>
"""


def render_table(df: pd.DataFrame, title: str, subtitle: str = "", extra_cols: list = None,
                  empty_msg: str = "(none)") -> str:
    if df.empty:
        return f"<section><h3>{title}</h3>{f'<p class=hint>{subtitle}</p>' if subtitle else ''}<p class=empty>{empty_msg}</p></section>"

    extra_cols = extra_cols or []
    rows = []
    for _, r in df.iterrows():
        late = "🔥" if r.get("flag_late_signal") == 1 else ""
        wash = "❄️" if r.get("flag_washout") == 1 else ""
        ern = "📅" if r.get("flag_earnings_soon") == 1 else ""
        chg = r.get("temp_7d_chg")
        chg_str = f"{chg:+.1f}" if pd.notna(chg) else "—"
        chg_class = "pos" if (pd.notna(chg) and chg > 0) else ("neg" if pd.notna(chg) and chg < 0 else "")
        ticker = r["ticker"]
        name = (r.get("name") or "")[:40]
        rows.append(f"""
            <tr data-ticker="{ticker}">
                <td><a href="#t-{ticker}" class=ticker-link>{ticker}</a></td>
                <td class=name>{name}</td>
                <td class=temp>{fmt(r.get('temperature'))}</td>
                <td class="chg {chg_class}">{chg_str}</td>
                <td class=bk>{fmt(r.get('score_positioning'))}</td>
                <td class=bk>{fmt(r.get('score_valuation'))}</td>
                <td class=bk>{fmt(r.get('score_technical'))}</td>
                <td class=bk title="Conviction (bucket agreement, 0=disagree, 100=agree)">{fmt(r.get('conviction'))}</td>
                <td class=bk title="Anomaly count (# signals at 90th+ %ile vs cluster peers)">{fmt(r.get('anomaly_count'), places=0)}</td>
                <td class=flag>{late}{wash}{ern}</td>
            </tr>
        """)
    return f"""
    <section>
        <h3>{title}</h3>
        {f'<p class=hint>{subtitle}</p>' if subtitle else ''}
        <table class=rank>
            <thead>
                <tr>
                    <th title="Click to drill down">Ticker</th>
                    <th>Name</th>
                    <th title="Composite score 0-100. Higher = hotter (more contrarian-bearish)">Temp</th>
                    <th title="7-day change in temperature">7d Δ</th>
                    <th title="Positioning bucket (insider, short interest)">Pos</th>
                    <th title="Valuation bucket (TTM P/E, EV/Sales)">Val</th>
                    <th title="Technical bucket (returns, RSI, distance from MA)">Tech</th>
                    <th title="Conviction (bucket agreement 0-100)">Conv</th>
                    <th title="# signals at 90th+ %ile vs cluster peers">Anom</th>
                    <th>Flags</th>
                </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </section>
    """


def render_drilldown(snap_row: pd.Series, sig_long: pd.DataFrame, est_row,
                      earnings_row, actions: pd.DataFrame,
                      sparkline: list, notes_row, sector_groups: dict,
                      cluster_mates: list, sector_mates: dict[str, list]) -> str:
    t = snap_row["ticker"]
    name = snap_row.get("name") or t

    # Sparkline SVG
    spark_svg = ""
    if sparkline and len(sparkline) > 1:
        w, h, pad = 220, 40, 2
        mn = min(sparkline)
        mx = max(sparkline)
        rng = (mx - mn) or 1
        pts = []
        for i, v in enumerate(sparkline):
            x = pad + i * (w - 2 * pad) / (len(sparkline) - 1)
            y = h - pad - (v - mn) / rng * (h - 2 * pad)
            pts.append(f"{x:.1f},{y:.1f}")
        polyline = " ".join(pts)
        last_color = "#c53030" if sparkline[-1] >= 70 else ("#2e7d32" if sparkline[-1] <= 30 else "#666")
        spark_svg = f"""
        <svg class=spark width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-label="30-day temperature sparkline">
            <polyline fill="none" stroke="{last_color}" stroke-width="1.5" points="{polyline}" />
            <line x1="{pad}" y1="{h - pad - (50 - mn) / rng * (h - 2 * pad):.1f}" x2="{w - pad}" y2="{h - pad - (50 - mn) / rng * (h - 2 * pad):.1f}" stroke="#ddd" stroke-dasharray="2,2"/>
        </svg>
        <span class=hint>last {len(sparkline)}d, range {mn:.0f}–{mx:.0f}</span>
        """

    # Per-signal table
    sig_rows = []
    if not sig_long.empty:
        for _, sr in sig_long.iterrows():
            sn = sr["signal_name"]
            label, _ = SIGNAL_DESCRIPTIONS.get(sn, (sn, ""))
            sig_rows.append(f"""
                <tr>
                    <td>{label}</td>
                    <td class=mono>{sr['bucket']}</td>
                    <td class=mono>{fmt(sr['raw_value'], 4)}</td>
                    <td class=bk>{fmt(sr['pct_self'])}</td>
                    <td class=bk>{fmt(sr['pct_peer'])}</td>
                </tr>
            """)
    sig_table = f"""
        <table class=signals>
            <thead><tr><th>Signal</th><th>Bucket</th><th>Raw</th><th>%ile self (5y)</th><th>%ile peer (cluster)</th></tr></thead>
            <tbody>{''.join(sig_rows) if sig_rows else '<tr><td colspan=5 class=empty>(no signals)</td></tr>'}</tbody>
        </table>
    """

    # Estimates / earnings overlay
    est_html = ""
    if est_row is not None and isinstance(est_row, pd.Series):
        est_html = f"""
        <div class=card>
            <h4>📊 Live overlay (Yahoo/FactSet — context, not in composite)</h4>
            <table class=overlay>
                <tr><td>Forward EPS</td><td>{fmt(est_row.get('forward_eps'), 2)}</td>
                    <td>Trailing EPS</td><td>{fmt(est_row.get('trailing_eps'), 2)}</td></tr>
                <tr><td>Target mean</td><td>${fmt(est_row.get('target_mean_price'), 2)}</td>
                    <td>Target dispersion</td><td>{fmt(est_row.get('target_dispersion'), 2)}</td></tr>
                <tr><td># analyst opinions</td><td>{fmt_int(est_row.get('num_analyst_opinions'))}</td>
                    <td>Recommendation</td><td>{est_row.get('recommendation_key', '—') or '—'} ({fmt(est_row.get('recommendation_mean'), 2)})</td></tr>
            </table>
        </div>
        """

    # Earnings date
    erng_html = ""
    if earnings_row is not None:
        nd = earnings_row.get("next_earnings_date") if hasattr(earnings_row, "get") else None
        if nd:
            erng_html = f"<p class=hint>📅 Next earnings: <b>{nd}</b></p>"

    # Recent actions
    act_html = ""
    if not actions.empty:
        act_rows = []
        for _, ar in actions.head(8).iterrows():
            act_rows.append(f"<tr><td>{ar['action_date']}</td><td>{ar['firm']}</td><td>{ar['from_grade'] or '—'} → {ar['to_grade'] or '—'}</td><td class=mono>{ar['action']}</td></tr>")
        act_html = f"""
        <div class=card>
            <h4>🎯 Recent analyst actions (last 90d)</h4>
            <table class=overlay><thead><tr><th>Date</th><th>Firm</th><th>Action</th><th>Type</th></tr></thead>
            <tbody>{''.join(act_rows)}</tbody></table>
        </div>
        """

    # Cluster + sector mates
    mates_html = ""
    if cluster_mates:
        mates_html += f"<p class=hint>🧬 Cluster peers: {', '.join(f'<a href=\"#t-{m}\">{m}</a>' for m in cluster_mates[:12])}</p>"
    if sector_mates:
        for sg, members in sector_mates.items():
            sg_label = sector_groups.get(sg, {}).get("label", sg)
            mates_html += f"<p class=hint>🏷️ {sg_label}: {', '.join(f'<a href=\"#t-{m}\">{m}</a>' for m in members[:10] if m != t)}</p>"

    # Notes
    notes_text = ""
    if notes_row is not None and isinstance(notes_row, pd.Series):
        notes_text = notes_row.get("note", "") or ""
    notes_html = f"""
    <div class=card>
        <h4>📝 Notes</h4>
        <pre class=notes>{notes_text or '(no notes — edit via SQLite)'}</pre>
    </div>
    """

    return f"""
    <section class=drilldown id="t-{t}">
        <h3>{t} — {name} <a class=back href="#top" title="Back to top">↑</a></h3>
        <div class=summary>
            <div>
                <p><b>Temperature:</b> <span class="big {('hot' if (snap_row.get('temperature') or 0) >= 70 else ('cold' if (snap_row.get('temperature') or 0) <= 30 else ''))}">{fmt(snap_row.get('temperature'))}</span>
                {f"  ({fmt(snap_row.get('temp_7d_chg'), 1)} 7d)" if pd.notna(snap_row.get('temp_7d_chg')) else ''}</p>
                <p>Pos {fmt(snap_row.get('score_positioning'))} · Val {fmt(snap_row.get('score_valuation'))} · Tech {fmt(snap_row.get('score_technical'))}</p>
                <p>Conviction: {fmt(snap_row.get('conviction'))} · Anomaly: {fmt(snap_row.get('anomaly_count'), 0)}</p>
                {erng_html}
            </div>
            <div>{spark_svg}</div>
        </div>
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
    <details class=prov>
    <summary>🕒 Data provenance — last refresh per provider</summary>
    <table class=overlay><thead><tr><th>Provider</th><th>Last refresh</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table>
    </details>
    """


def render_backtest_card(results: list) -> str:
    if not results:
        return ""
    composite = [r for r in results if r["signal"] == "COMPOSITE_TEMPERATURE"]
    sig_results = [r for r in results if r["signal"] != "COMPOSITE_TEMPERATURE"]

    # Per-signal best IC table
    by_sig = {}
    for r in sig_results:
        s = r["signal"]
        if s not in by_sig or (r.get("ic") is not None and abs(r["ic"]) > abs(by_sig[s].get("ic") or 0)):
            by_sig[s] = r
    rows = []
    for s in sorted(by_sig.keys(), key=lambda x: abs(by_sig[x].get("ic") or 0), reverse=True)[:10]:
        r = by_sig[s]
        ic = r.get("ic")
        ic_str = f"{ic:+.4f}" if ic is not None else "—"
        ic_class = "neg" if (ic is not None and ic < 0) else ("pos" if ic is not None and ic > 0 else "")
        rows.append(f"<tr><td class=mono>{s}</td><td>{r['kind']} @ {r['horizon']}</td><td class=mono><span class={ic_class}>{ic_str}</span></td><td class=bk>{r.get('top_hit_rate', 0):.1%}</td><td class=bk>{r.get('bot_hit_rate', 0):.1%}</td></tr>")

    comp_rows = []
    for r in composite:
        ic = r.get("ic")
        comp_rows.append(f"<tr><td>Composite (V1.4)</td><td>{r['horizon']}</td><td class=mono><span class={'neg' if ic and ic < 0 else 'pos'}>{ic:+.4f}</span></td><td class=bk>{r['top_hit_rate']:.1%}</td><td class=bk>{r['bot_hit_rate']:.1%}</td></tr>")

    return f"""
    <details class=backtest>
    <summary><h3 style=display:inline>📈 Backtest validation (V1.4)</h3></summary>
    <p class=hint>Information Coefficient (Spearman) per signal vs forward returns. Negative IC = contrarian (high signal predicts negative forward return). Top/bot hit rates measure decile reliability.</p>
    <table class=overlay><thead><tr><th>Signal</th><th>Best</th><th>IC</th><th>Top hit</th><th>Bot hit</th></tr></thead>
    <tbody>{''.join(comp_rows)}{''.join(rows)}</tbody></table>
    </details>
    """


def main(asof: str | None = None):
    print("Loading data...")
    data = load_data()
    snap = data["snap"]
    asof = data["latest"]
    sector_groups = load_sector_groups()

    # Watchlist tickers as set
    wl_tickers = set(data["watchlist"]["ticker"]) if not data["watchlist"].empty else set()
    snap["watched"] = snap["ticker"].isin(wl_tickers)

    # Cluster + sector mate maps
    cluster_to_tickers = snap.groupby("cluster_id")["ticker"].apply(list).to_dict() if "cluster_id" in snap.columns else {}
    ticker_to_sectors = {}
    for sg, info in sector_groups.items():
        for t in info["tickers"]:
            ticker_to_sectors.setdefault(t, []).append(sg)

    # Sort/select panels
    hottest = snap.dropna(subset=["temperature"]).nlargest(25, "temperature")
    coldest = snap.dropna(subset=["temperature"]).nsmallest(25, "temperature")
    movers_up = snap.dropna(subset=["temp_7d_chg"]).nlargest(15, "temp_7d_chg") if "temp_7d_chg" in snap.columns else pd.DataFrame()
    movers_down = snap.dropna(subset=["temp_7d_chg"]).nsmallest(15, "temp_7d_chg") if "temp_7d_chg" in snap.columns else pd.DataFrame()
    late_flagged = snap[snap["flag_late_signal"] == 1].sort_values("temperature", ascending=False)
    wash_flagged = snap[snap["flag_washout"] == 1].sort_values("temperature")
    earnings_soon = snap[snap["flag_earnings_soon"] == 1].sort_values("temperature", ascending=False)
    new_late_df = snap[snap["ticker"].isin(data["new_late"])].sort_values("temperature", ascending=False)
    new_wash_df = snap[snap["ticker"].isin(data["new_wash"])].sort_values("temperature")
    watchlist_df = snap[snap["ticker"].isin(wl_tickers)].sort_values("temperature", ascending=False)

    # Pre-build drill-downs for ALL tickers in snap
    sig_long_by_ticker = {t: g for t, g in data["sig_long"].groupby("ticker")}
    est_by_ticker = data["estimates"].set_index("ticker") if not data["estimates"].empty else pd.DataFrame()
    earn_by_ticker = data["earnings"].set_index("ticker") if not data["earnings"].empty else pd.DataFrame()
    notes_by_ticker = data["notes"].set_index("ticker") if not data["notes"].empty else pd.DataFrame()

    drilldowns = []
    for _, row in snap.iterrows():
        t = row["ticker"]
        sig_t = sig_long_by_ticker.get(t, pd.DataFrame())
        est_t = est_by_ticker.loc[t] if (not est_by_ticker.empty and t in est_by_ticker.index) else None
        earn_t = earn_by_ticker.loc[t] if (not earn_by_ticker.empty and t in earn_by_ticker.index) else None
        actions_t = data["actions"][data["actions"]["ticker"] == t]
        notes_t = notes_by_ticker.loc[t] if (not notes_by_ticker.empty and t in notes_by_ticker.index) else None
        spark = data["sparklines"].get(t, [])
        cluster_id = row.get("cluster_id")
        cluster_mates = [x for x in cluster_to_tickers.get(cluster_id, []) if x != t][:12] if cluster_id else []
        sector_mates = {sg: sector_groups[sg]["tickers"] for sg in ticker_to_sectors.get(t, [])}
        drilldowns.append(render_drilldown(
            row, sig_t, est_t, earn_t, actions_t, spark, notes_t, sector_groups, cluster_mates, sector_mates
        ))

    # CSV data (snapshot for export)
    csv_data = snap[["ticker", "name", "temperature", "score_positioning",
                     "score_valuation", "score_technical", "conviction",
                     "anomaly_count", "temp_7d_chg",
                     "flag_late_signal", "flag_washout", "flag_earnings_soon"]].fillna("")
    csv_text = csv_data.to_csv(index=False)

    # Sector group filter options
    sg_options = "<option value=''>(all)</option>" + "".join(
        f"<option value='{sg}'>{info['label']}</option>" for sg, info in sector_groups.items()
    )
    cluster_options_set = sorted(set(snap.dropna(subset=["cluster_id"])["cluster_id"]))
    cluster_options = "<option value=''>(all)</option>" + "".join(
        f"<option value='{c}'>{c}</option>" for c in cluster_options_set
    )

    # Sector group → ticker map for JS filter
    sg_ticker_map = {sg: info["tickers"] for sg, info in sector_groups.items()}

    # === HTML ===
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Positioning Meter — {asof}</title>
<style>
:root {{
  --hot: #c53030;
  --cold: #2e7d32;
  --bg: #fafafa;
  --card-bg: #fff;
  --border: #e1e1e1;
}}
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: #222; max-width: 1300px; margin: 0 auto; padding: 1em; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3em; }}
h2 {{ color: #333; margin-top: 1.5em; }}
h3 {{ color: #444; margin-top: 1.2em; }}
h4 {{ margin: 0.5em 0; color: #555; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; background: var(--card-bg); }}
th, td {{ padding: 6px 8px; border-bottom: 1px solid #eee; text-align: left; vertical-align: top; }}
th {{ background: #f5f5f5; font-weight: 600; cursor: help; }}
tr:hover {{ background: #fcfcfc; }}
.ticker-link {{ font-weight: 600; font-family: ui-monospace, 'SF Mono', Menlo, monospace; color: #1d4ed8; text-decoration: none; }}
.ticker-link:hover {{ text-decoration: underline; }}
.name {{ color: #555; font-size: 12px; }}
.temp {{ font-weight: 700; text-align: right; font-family: ui-monospace, monospace; }}
.chg {{ text-align: right; font-family: ui-monospace, monospace; font-size: 12px; }}
.chg.pos {{ color: var(--hot); }}
.chg.neg {{ color: var(--cold); }}
.bk {{ text-align: right; color: #666; font-size: 12px; font-family: ui-monospace, monospace; }}
.flag {{ text-align: center; font-size: 14px; }}
.empty {{ color: #999; font-style: italic; }}
.hint {{ color: #777; font-size: 12px; }}
.mono {{ font-family: ui-monospace, monospace; font-size: 12px; }}
.subtitle {{ color: #777; font-size: 13px; }}
.gloss-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; margin: 1em 0; }}
.gloss-card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px; font-size: 13px; }}
.gloss-card h4 {{ color: #333; margin: 0 0 0.3em 0; }}
.gloss-card p {{ margin: 0.3em 0; line-height: 1.4; }}
.gloss-card ul {{ margin: 0.3em 0; padding-left: 1.2em; line-height: 1.4; }}
.gloss-card code {{ background: #f0f0f0; padding: 1px 4px; border-radius: 3px; font-size: 11px; }}
.glossary {{ background: #fffbe6; border: 1px solid #f0d090; padding: 0.6em 0.8em; border-radius: 4px; margin-bottom: 1.5em; }}
.glossary > summary {{ cursor: pointer; font-weight: 600; }}
.controls {{ background: var(--card-bg); border: 1px solid var(--border); padding: 10px; border-radius: 6px; margin-bottom: 1em; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
.controls input, .controls select {{ padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }}
.controls button {{ padding: 6px 12px; background: #1d4ed8; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }}
.controls button:hover {{ background: #1e40af; }}
section {{ margin-bottom: 1.5em; }}
section.drilldown {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; padding: 1em; margin-bottom: 0.8em; }}
section.drilldown .summary {{ display: flex; justify-content: space-between; gap: 1em; align-items: flex-start; }}
section.drilldown table.signals th {{ background: #f9f9f9; }}
section.drilldown .card {{ margin-top: 0.8em; padding: 0.6em 0.8em; background: #fafafa; border: 1px solid var(--border); border-radius: 4px; }}
section.drilldown .back {{ font-size: 14px; color: #1d4ed8; text-decoration: none; margin-left: 8px; }}
.big {{ font-size: 24px; font-weight: 700; }}
.big.hot {{ color: var(--hot); }}
.big.cold {{ color: var(--cold); }}
.spark {{ display: block; }}
.notes {{ background: #fff; border: 1px solid var(--border); padding: 6px 10px; font-family: -apple-system, system-ui, sans-serif; white-space: pre-wrap; font-size: 13px; min-height: 30px; }}
table.overlay td {{ padding: 4px 8px; }}
table.overlay td:nth-child(odd) {{ color: #666; font-size: 12px; }}
.prov {{ background: var(--card-bg); border: 1px solid var(--border); padding: 0.5em 0.8em; border-radius: 4px; margin-top: 1.5em; font-size: 12px; }}
.backtest {{ background: var(--card-bg); border: 1px solid var(--border); padding: 0.5em 0.8em; border-radius: 4px; margin-top: 1em; }}
.watched-row {{ background: #fff7ed; }}
neg {{ color: var(--cold); }}
pos {{ color: var(--hot); }}
@media (max-width: 700px) {{
  body {{ padding: 0.5em; font-size: 13px; }}
  table {{ font-size: 11px; }}
  th, td {{ padding: 3px 4px; }}
}}
</style>
</head>
<body>
<a id=top></a>
<h1>Positioning Meter</h1>
<div class=subtitle>As of <b>{asof}</b> · {len(snap)} names with composite temperature · V1.4 + min-buckets · Backtest IC −0.022 (3m fwd)</div>

{GLOSSARY}

<div class=controls>
<input type=text id=search placeholder="Search ticker or name…" oninput=filterAll()>
<select id=cluster onchange=filterAll()>
<option value=''>(all clusters)</option>
{cluster_options}
</select>
<select id=sector onchange=filterAll()>
{sg_options}
</select>
<button onclick=exportCSV()>📥 Export CSV</button>
<button onclick=clearFilters()>↻ Clear</button>
<span class=hint id=count></span>
</div>

<h2>📊 Summary panels</h2>

{render_table(hottest, "🔥 Hottest 25 (highest temperature)", "Largest extreme-positioning + extreme-momentum + extreme-valuation triple-stretches.")}
{render_table(coldest, "❄️ Coldest 25 (lowest temperature)", "Most washed-out names — historically associated with positive forward returns at extremes.")}
{render_table(movers_up, "📈 Heating up (top 15 by 7d temp Δ)", "Names whose temperature rose the most in the last 5 trading days.")}
{render_table(movers_down, "📉 Cooling off (top 15 by 7d temp Δ)", "Names whose temperature dropped the most in the last 5 trading days.")}
{render_table(late_flagged, f"🔥 Compound LATE flag ({len(late_flagged)} names)", "Pos ≥ 85, Val ≥ 80, Tech ≥ 85 — triple-extreme stretched.", empty_msg="No names triggered today.")}
{render_table(wash_flagged, f"❄️ Compound WASHOUT flag ({len(wash_flagged)} names)", "Pos ≤ 15, Val ≤ 25, Tech ≤ 15 — triple-extreme washed-out.", empty_msg="No names triggered today.")}
{render_table(new_late_df, f"🆕 NEW Late flags (last 7d, {len(new_late_df)} names)", "Names that newly entered the LATE flag in the past 7 days.", empty_msg="(none)")}
{render_table(new_wash_df, f"🆕 NEW Washout flags (last 7d, {len(new_wash_df)} names)", "Names that newly entered the WASHOUT flag in the past 7 days.", empty_msg="(none)")}
{render_table(earnings_soon, f"📅 Earnings within 14d ({len(earnings_soon)} names)", "Names reporting earnings in the next 2 weeks. Implied move + positioning often diverge here.", empty_msg="(none)")}
{render_table(watchlist_df, f"👁️ Watchlist ({len(watchlist_df)} names)", "Tickers you've added to the watchlist (via the watchlist DB table).", empty_msg="(empty — add via SQL: INSERT INTO watchlist (ticker, label) VALUES ('NVDA', 'core'))")}

{render_backtest_card(data["backtest_results"])}

<h2>🔍 Per-ticker drill-down</h2>
<p class=hint>Click any ticker in the tables above to jump to its detail card. {len(drilldowns)} cards below.</p>
{''.join(drilldowns)}

{render_provenance(data["provenance"])}

<details>
<summary class=hint><b>Methodology (click to expand)</b></summary>
<div class=hint style="max-width:800px;line-height:1.5;font-size:12px;">
<p><b>Universe</b>: 366 TMT names (mcap ≥ $1.5B) from theme_detector.</p>
<p><b>Signals</b>: 18 total computed daily — 13 in composite, 5 overlay-only. See QUESTIONS.md for backtest-driven inclusion decisions (e.g. trend signals like 12m return excluded because positive IC means they're not contrarian).</p>
<p><b>Dual percentile</b>: each signal is scored vs (a) own 5y rolling history and (b) cluster peers cross-section. Bucket scores average those.</p>
<p><b>Composite</b>: weighted average of bucket scores. Initial weights pos 0.25 / val 0.20 / tech 0.20 (flows + options not yet implemented). Reweighted when buckets are missing for a name. Min 2 buckets required.</p>
<p><b>Backtest</b>: 10y daily panel, IC = Spearman correlation between signal percentile and forward return. V1.4 composite IC −0.022 at 3m fwd, decile spread −2.30%, bot decile hit 56%. See data/backtest_report.md.</p>
<p><b>Limitations</b>: options bucket not implemented (would require Polygon $200/mo). ETF flows forward-only. EPS revision overlay shows current snapshot only. 13F has 45-day reporting lag and is long-only. NASDAQ true SI covers only NASDAQ-listed names (~65% of universe).</p>
</div>
</details>

<script>
const CSV = {json.dumps(csv_text)};
const SECTOR_TICKERS = {json.dumps(sg_ticker_map)};
const CLUSTER_OF = {json.dumps(dict(zip(snap["ticker"], snap["cluster_id"].fillna(""))))};
const TOTAL_NAMES = {len(snap)};

function filterAll() {{
  const q = document.getElementById('search').value.toLowerCase();
  const cluster = document.getElementById('cluster').value;
  const sector = document.getElementById('sector').value;
  const sectorTickers = sector ? new Set(SECTOR_TICKERS[sector] || []) : null;
  let visible = 0;

  document.querySelectorAll('table.rank tbody tr').forEach(tr => {{
    const ticker = tr.dataset.ticker || '';
    const name = (tr.querySelector('.name')?.textContent || '').toLowerCase();
    const tickerLower = ticker.toLowerCase();
    let match = !q || tickerLower.includes(q) || name.includes(q);
    if (cluster && CLUSTER_OF[ticker] !== cluster) match = false;
    if (sectorTickers && !sectorTickers.has(ticker)) match = false;
    tr.style.display = match ? '' : 'none';
    if (match) visible++;
  }});

  document.querySelectorAll('section.drilldown').forEach(sec => {{
    const ticker = sec.id.replace('t-', '');
    let match = !q || ticker.toLowerCase().includes(q) || (sec.querySelector('h3')?.textContent || '').toLowerCase().includes(q);
    if (cluster && CLUSTER_OF[ticker] !== cluster) match = false;
    if (sectorTickers && !sectorTickers.has(ticker)) match = false;
    sec.style.display = match ? '' : 'none';
  }});

  document.getElementById('count').textContent = q || cluster || sector ? `${{visible}} / ${{TOTAL_NAMES}} names match` : '';
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
</script>
</body></html>
"""
    HTML_OUT.write_text(html)
    print(f"Wrote {HTML_OUT} ({len(html):,} bytes, {len(drilldowns)} drilldowns)")


if __name__ == "__main__":
    asof = sys.argv[1] if len(sys.argv) > 1 else None
    main(asof)
