"""Ingest true bi-monthly short interest from NASDAQ API.

NASDAQ-listed names only (~65% of universe). NYSE names get null and rely
on the FINRA short-volume proxy alone.
"""
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load, project_path
from lib.db import connect
from providers.nasdaq_si import NasdaqShortInterestProvider

STATUS = project_path("logs/09_ingest_nasdaq_si_status.json")
LOG = project_path("logs/09_ingest_nasdaq_si.log")


def load_universe_nasdaq() -> list[str]:
    cfg = load()
    out = project_path(cfg["universe"]["output_csv"])
    return [
        r["ticker"] for r in csv.DictReader(open(out))
        if r["exchange"] == "XNAS"
    ]


def upsert(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO short_interest_true
            (ticker, settlement_date, short_interest, avg_daily_share_volume, days_to_cover)
        VALUES (:ticker, :settlement_date, :short_interest, :avg_daily_share_volume, :days_to_cover)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def main():
    tickers = load_universe_nasdaq()
    p = NasdaqShortInterestProvider(rate_limit_sleep=0.4)
    conn = connect()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    total = 0
    failures = []
    with open(LOG, "a") as logf:
        for i, t in enumerate(tickers, 1):
            try:
                rows = p.fetch(t)
                n = upsert(conn, rows)
                total += n
                logf.write(f"[{i:>3}/{len(tickers)}] {t:8s}  {n:>3} dates\n")
                logf.flush()
                if n == 0:
                    failures.append(t)
            except Exception as e:
                failures.append(t)
                logf.write(f"[{i:>3}/{len(tickers)}] {t:8s}  FAILED — {e}\n")
            if i % 25 == 0 or i == len(tickers):
                STATUS.write_text(json.dumps({
                    "completed": i, "total": len(tickers),
                    "rows_written": total, "failures": failures,
                    "elapsed_sec": round(time.time() - started, 1),
                    "status": "running" if i < len(tickers) else "done",
                }, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
