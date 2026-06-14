"""Append the daily decile book to book_log for live forward-performance tracking.

Each run records the bottom-decile (candidate longs) and top-decile (candidate
shorts) by temperature for the latest composite date. Realized forward returns
are computed later (render_live_performance), so this accumulates genuine
out-of-sample evidence over time. Idempotent per date.

Usage:
  python3 tools/log_book.py             # log the latest composite date
  python3 tools/log_book.py --backfill  # seed from all historical dates (once)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from lib.db import connect, init_schema


def deciles_for_date(conn, d, source):
    df = pd.read_sql_query(
        "SELECT ticker, temperature FROM composite_daily WHERE date=? AND temperature IS NOT NULL",
        conn, params=(d,))
    if len(df) < 20:
        return []
    lo, hi = df["temperature"].quantile(0.10), df["temperature"].quantile(0.90)
    rows = []
    for _, r in df[df["temperature"] <= lo].iterrows():
        rows.append((d, r["ticker"], "long", float(r["temperature"]), source))
    for _, r in df[df["temperature"] >= hi].iterrows():
        rows.append((d, r["ticker"], "short", float(r["temperature"]), source))
    return rows


def main():
    init_schema()
    backfill = "--backfill" in sys.argv
    conn = connect()
    if backfill:
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM composite_daily ORDER BY date").fetchall()]
    else:
        dates = [conn.execute("SELECT MAX(date) FROM composite_daily").fetchone()[0]]
    total = 0
    source = "backfill" if backfill else "live"
    for d in dates:
        if not d:
            continue
        # never downgrade an existing 'live' row to 'backfill'
        rows = [r for r in deciles_for_date(conn, d, source)
                if source == "live" or not conn.execute(
                    "SELECT 1 FROM book_log WHERE date=? AND ticker=? AND source='live'", (d, r[1])).fetchone()]
        conn.executemany(
            "INSERT OR REPLACE INTO book_log (date, ticker, side, temperature, source) VALUES (?,?,?,?,?)", rows)
        total += len(rows)
    conn.commit()
    n_dates = conn.execute("SELECT COUNT(DISTINCT date) FROM book_log").fetchone()[0]
    conn.close()
    print(f"book_log: wrote {total} rows across {len(dates)} date(s); {n_dates} dates total in log.")


if __name__ == "__main__":
    main()
