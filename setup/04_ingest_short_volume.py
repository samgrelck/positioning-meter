"""Ingest 10y of FINRA Reg SHO daily short sale volume.

Iterates business days in the backtest window, downloads each day's CNMS file,
filters to universe tickers, upserts to short_interest table.

10y of trading days ~= 2520 files. At 0.2s rate-limit + ~1s/file fetch,
this takes ~50 minutes wall-clock.
"""
import csv
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load, project_path
from lib.db import connect
from providers.finra_short import FinraShortVolumeProvider

STATUS = project_path("logs/04_ingest_short_volume_status.json")
LOG = project_path("logs/04_ingest_short_volume.log")


def load_universe_set() -> set[str]:
    cfg = load()
    out = project_path(cfg["universe"]["output_csv"])
    return {r["ticker"] for r in csv.DictReader(open(out))}


def business_days(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon..Fri
            yield d
        d += timedelta(days=1)


def upsert(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO short_interest
            (ticker, settlement_date, short_interest, avg_daily_volume,
             days_to_cover, pct_float)
        VALUES
            (:ticker, :settlement_date, :short_interest, :avg_daily_volume,
             :days_to_cover, :pct_float)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def main():
    cfg = load()
    start = date.fromisoformat(cfg["backtest"]["start_date"])
    end = date.today()

    universe = load_universe_set()
    p = FinraShortVolumeProvider(rate_limit_sleep=0.1)
    conn = connect()
    LOG.parent.mkdir(parents=True, exist_ok=True)

    days = list(business_days(start, end))
    started = time.time()
    total_rows = 0
    missing_days = 0

    with open(LOG, "a") as logf:
        for i, d in enumerate(days, 1):
            all_rows = p.fetch_settlement(d)
            if not all_rows:
                missing_days += 1
                continue
            filtered = [r for r in all_rows if r["ticker"] in universe]
            n = upsert(conn, filtered)
            total_rows += n
            if i % 20 == 0 or i == len(days):
                logf.write(f"[{i:>4}/{len(days)}] {d}  +{n} rows  total={total_rows}  missing={missing_days}\n")
                logf.flush()
                STATUS.write_text(json.dumps({
                    "completed": i, "total": len(days),
                    "rows_written": total_rows,
                    "missing_files": missing_days,
                    "elapsed_sec": round(time.time() - started, 1),
                    "status": "running" if i < len(days) else "done",
                }, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
