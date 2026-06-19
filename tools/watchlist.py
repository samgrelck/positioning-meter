#!/usr/bin/env python3
"""Manage the Positioning Meter watchlist (the 👁️ Watchlist tab on the dashboard).

The watchlist is just a small DB table; this is the easy way to edit it without
hand-writing SQL. Tickers must be in the universe (data/universe.csv) to have
scores — a warning prints if not, but the add still goes through.

Usage:
  python3 tools/watchlist.py list                      # show current watchlist
  python3 tools/watchlist.py add MU NVDA               # add one or more tickers
  python3 tools/watchlist.py add CRWD --label "core"   # add with a label
  python3 tools/watchlist.py remove MU                 # remove one or more
  python3 tools/watchlist.py clear                     # empty the watchlist

Changes appear on the dashboard after the next render (tomorrow's 5am refresh,
or run ./tools/deploy.sh now to rebuild immediately).
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.config import project_path  # noqa: E402
from lib.db import connect  # noqa: E402


def _universe_tickers():
    try:
        import csv
        with open(project_path("data/universe.csv")) as f:
            return {row["ticker"].upper() for row in csv.DictReader(f)}
    except Exception:
        return set()


def cmd_list(conn, _args):
    rows = conn.execute(
        "SELECT ticker, label, added_at FROM watchlist ORDER BY ticker"
    ).fetchall()
    if not rows:
        print("Watchlist is empty.")
        return
    print(f"Watchlist ({len(rows)} ticker{'s' if len(rows) != 1 else ''}):")
    for tk, label, added in rows:
        print(f"  {tk:8s} {('['+label+']') if label else '':16s} added {added or '?'}")


def cmd_add(conn, args):
    uni = _universe_tickers()
    today = date.today().isoformat()
    added, skipped = [], []
    for tk in args.tickers:
        tk = tk.upper()
        if uni and tk not in uni:
            print(f"  ⚠️  {tk} is not in the universe (data/universe.csv) — "
                  "it won't have scores until added there. Adding to watchlist anyway.")
        conn.execute(
            "INSERT INTO watchlist (ticker, added_at, label) VALUES (?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET label=COALESCE(excluded.label, watchlist.label)",
            (tk, today, args.label),
        )
        added.append(tk)
    conn.commit()
    print(f"Added/updated: {', '.join(added)}")
    cmd_list(conn, args)


def cmd_remove(conn, args):
    removed = []
    for tk in args.tickers:
        tk = tk.upper()
        cur = conn.execute("DELETE FROM watchlist WHERE ticker=?", (tk,))
        if cur.rowcount:
            removed.append(tk)
    conn.commit()
    print(f"Removed: {', '.join(removed) if removed else '(none matched)'}")
    cmd_list(conn, args)


def cmd_clear(conn, args):
    n = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    conn.execute("DELETE FROM watchlist")
    conn.commit()
    print(f"Cleared {n} ticker(s) from the watchlist.")


def main():
    p = argparse.ArgumentParser(description="Manage the Positioning Meter watchlist.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the current watchlist")
    pa = sub.add_parser("add", help="add ticker(s)")
    pa.add_argument("tickers", nargs="+")
    pa.add_argument("--label", default=None, help="optional label, e.g. 'core'")
    pr = sub.add_parser("remove", help="remove ticker(s)")
    pr.add_argument("tickers", nargs="+")
    sub.add_parser("clear", help="empty the watchlist")
    args = p.parse_args()

    conn = connect()
    try:
        {"list": cmd_list, "add": cmd_add, "remove": cmd_remove, "clear": cmd_clear}[args.cmd](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
