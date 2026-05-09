"""Ingest Polygon stock financials for the full universe."""
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load, project_path
from lib.db import connect
from providers.polygon_financials import PolygonFinancialsProvider

STATUS = project_path("logs/03_ingest_financials_status.json")
LOG = project_path("logs/03_ingest_financials.log")


def load_universe() -> list[str]:
    cfg = load()
    out = project_path(cfg["universe"]["output_csv"])
    return [r["ticker"] for r in csv.DictReader(open(out))]


def upsert(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO fundamentals_q
            (ticker, period_end, fiscal_period, fiscal_year, filing_date_est,
             diluted_eps_q, total_revenue_q, total_debt, cash_and_short_term, shares_out)
        VALUES
            (:ticker, :period_end, :fiscal_period, :fiscal_year, :filing_date_est,
             :diluted_eps_q, :total_revenue_q, :total_debt, :cash_and_short_term, :shares_out)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def main():
    tickers = load_universe()
    p = PolygonFinancialsProvider(rate_limit_sleep=0.15)
    conn = connect()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    total = 0
    failures = []
    with open(LOG, "a") as logf:
        for i, t in enumerate(tickers, 1):
            try:
                rows = p.fetch(t, limit=100)
                n = upsert(conn, rows)
                total += n
                logf.write(f"[{i:>3}/{len(tickers)}] {t:8s}  {n:>3} rows\n")
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
