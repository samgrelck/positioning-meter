"""Ingest 10y of openinsider Form 4 transactions for the universe."""
import csv
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load, project_path
from lib.db import connect
from providers.openinsider import OpenInsiderProvider

STATUS = project_path("logs/05_ingest_insider_status.json")
LOG = project_path("logs/05_ingest_insider.log")


def load_universe() -> list[str]:
    cfg = load()
    out = project_path(cfg["universe"]["output_csv"])
    return [r["ticker"] for r in csv.DictReader(open(out))]


def upsert(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO insider_form4
            (accession, ticker, filer_cik, filer_name, relationship,
             transaction_date, transaction_code, shares, price_per_share,
             value_usd, direct_indirect)
        VALUES
            (:accession, :ticker, :filer_cik, :filer_name, :relationship,
             :transaction_date, :transaction_code, :shares, :price_per_share,
             :value_usd, :direct_indirect)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def main():
    cfg = load()
    start = date.fromisoformat(cfg["backtest"]["start_date"])
    end = date.today()
    tickers = load_universe()
    p = OpenInsiderProvider(rate_limit_sleep=0.4)
    conn = connect()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    total = 0
    failures = []
    with open(LOG, "a") as logf:
        for i, t in enumerate(tickers, 1):
            try:
                rows = p.fetch_form4(t, start, end)
                n = upsert(conn, rows)
                total += n
                logf.write(f"[{i:>3}/{len(tickers)}] {t:8s}  {n:>4} txs\n")
                logf.flush()
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
