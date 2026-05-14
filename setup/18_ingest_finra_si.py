"""Parse FINRA biweekly Short Interest files and load into short_interest_true.

Reads all files in data/FINRA/shrt*.csv (pipe-delimited despite .csv extension),
filters to universe tickers, upserts into short_interest_true table.

Replaces the existing NASDAQ-API data (which was only 1y of NASDAQ-listed names).
FINRA data covers full universe (NYSE + NASDAQ + everything) with ~7.5y history.
"""
import csv
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load, project_path
from lib.db import connect

FINRA_DIR = project_path("data/FINRA")
STATUS = project_path("logs/18_ingest_finra_si_status.json")
LOG = project_path("logs/18_ingest_finra_si.log")


def load_universe() -> set[str]:
    cfg = load()
    out = project_path(cfg["universe"]["output_csv"])
    return {r["ticker"] for r in csv.DictReader(open(out))}


def parse_file(path: Path, universe: set[str]) -> list[dict]:
    """Parse one biweekly file, return rows for tickers in universe."""
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            ticker = row.get("symbolCode", "").strip()
            if ticker not in universe:
                continue
            try:
                si = int(row.get("currentShortPositionQuantity") or 0)
                adv = int(row.get("averageDailyVolumeQuantity") or 0)
                dtc_raw = row.get("daysToCoverQuantity") or ""
                dtc = float(dtc_raw) if dtc_raw else None
                settle = row.get("settlementDate") or ""
            except (ValueError, TypeError):
                continue
            if not settle:
                continue
            rows.append({
                "ticker": ticker,
                "settlement_date": settle,
                "short_interest": si,
                "avg_daily_share_volume": adv,
                "days_to_cover": dtc,
            })
    return rows


def upsert(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO short_interest_true
            (ticker, settlement_date, short_interest, avg_daily_share_volume, days_to_cover)
        VALUES
            (:ticker, :settlement_date, :short_interest, :avg_daily_share_volume, :days_to_cover)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def main():
    universe = load_universe()
    print(f"Universe: {len(universe)} tickers")
    files = sorted(FINRA_DIR.glob("shrt*.csv"))
    print(f"FINRA files to parse: {len(files)}")
    if not files:
        print("No files found. Run setup/17_download_finra_si.py first.")
        return

    conn = connect()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    total_rows = 0

    with open(LOG, "a") as logf:
        logf.write(f"\n=== {date.today().isoformat()} FINRA SI ingest ===\n")
        for i, path in enumerate(files, 1):
            try:
                rows = parse_file(path, universe)
                n = upsert(conn, rows)
                total_rows += n
                logf.write(f"[{i:>3}/{len(files)}] {path.name}  {n:>4} rows\n")
            except Exception as e:
                logf.write(f"[{i:>3}/{len(files)}] {path.name}  FAILED: {e}\n")
            if i % 20 == 0 or i == len(files):
                logf.flush()
                STATUS.write_text(json.dumps({
                    "completed": i, "total": len(files),
                    "rows_written": total_rows,
                    "elapsed_sec": round(time.time() - started, 1),
                    "status": "running" if i < len(files) else "done",
                }, indent=2))

    # Coverage report
    print(f"\nDONE.")
    print(f"  Rows ingested: {total_rows:,}")
    print(f"  Universe coverage:")
    cov = conn.execute("""
        SELECT COUNT(DISTINCT ticker), MIN(settlement_date), MAX(settlement_date)
        FROM short_interest_true
    """).fetchone()
    print(f"    Distinct tickers with SI: {cov[0]}")
    print(f"    Date range: {cov[1]} -> {cov[2]}")
    conn.close()


if __name__ == "__main__":
    main()
