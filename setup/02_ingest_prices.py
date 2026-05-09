"""Ingest 10y of split-adjusted daily prices for the full universe + ETFs.

Idempotent — uses INSERT OR REPLACE so re-runs only update missing/stale rows.
Writes a status JSON so the user can poll progress while running in background.
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
from providers.polygon_prices import PolygonPricesProvider

STATUS_PATH = project_path("logs/02_ingest_prices_status.json")
LOG_PATH = project_path("logs/02_ingest_prices.log")


def load_universe() -> list[str]:
    cfg = load()
    out = project_path(cfg["universe"]["output_csv"])
    tickers = []
    with open(out) as f:
        for row in csv.DictReader(f):
            tickers.append(row["ticker"])
    return tickers


def all_tickers_to_ingest() -> list[str]:
    cfg = load()
    universe = load_universe()
    etfs = cfg["etfs"]["sector"] + cfg["etfs"]["single_stock_leveraged"]
    seen = set()
    ordered = []
    for t in universe + etfs:
        if t not in seen:
            ordered.append(t)
            seen.add(t)
    return ordered


def upsert_prices(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO prices
            (ticker, date, open, high, low, close, adj_close, volume)
        VALUES
            (:ticker, :date, :open, :high, :low, :close, :adj_close, :volume)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def write_status(d: dict):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(d, indent=2))


def append_log(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(msg + "\n")


def main():
    cfg = load()
    end = date.today()
    start_str = cfg["backtest"]["start_date"]
    start = date.fromisoformat(start_str)

    tickers = all_tickers_to_ingest()
    provider = PolygonPricesProvider(rate_limit_sleep=0.1)
    conn = connect()

    started_at = time.time()
    total_rows = 0
    failures: list[str] = []

    for i, t in enumerate(tickers, 1):
        try:
            rows = provider.fetch_prices(t, start, end)
            n = upsert_prices(conn, rows)
            total_rows += n
            msg = f"[{i:>3}/{len(tickers)}] {t:8s}  {n:>5} rows"
        except Exception as e:
            failures.append(t)
            msg = f"[{i:>3}/{len(tickers)}] {t:8s}  FAILED — {e}"
        append_log(msg)
        if i % 10 == 0 or i == len(tickers):
            elapsed = time.time() - started_at
            rate = i / elapsed if elapsed > 0 else 0
            eta_sec = (len(tickers) - i) / rate if rate > 0 else 0
            write_status({
                "started_at": started_at,
                "elapsed_sec": round(elapsed, 1),
                "completed": i,
                "total": len(tickers),
                "rows_written": total_rows,
                "failures": failures,
                "eta_sec": round(eta_sec, 1),
                "status": "running" if i < len(tickers) else "done",
            })

    conn.close()
    write_status({
        "started_at": started_at,
        "elapsed_sec": round(time.time() - started_at, 1),
        "completed": len(tickers),
        "total": len(tickers),
        "rows_written": total_rows,
        "failures": failures,
        "status": "done",
    })
    append_log(f"DONE. {len(tickers)} tickers, {total_rows} rows, {len(failures)} failures.")


if __name__ == "__main__":
    main()
