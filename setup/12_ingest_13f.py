"""Ingest 10y of 13F-HR holdings for curated HF filer list.

For each filer in data/hf_filers.csv:
  - List 13F-HR filings within backtest window
  - For each filing, fetch InfoTable, parse holdings, filter to universe
    CUSIPs (via data/cusip_to_ticker.csv mapping)
  - Insert into holdings_13f table
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
from providers.edgar_13f import Edgar13FProvider

STATUS = project_path("logs/12_ingest_13f_status.json")
LOG = project_path("logs/12_ingest_13f.log")


def load_filers() -> list[dict]:
    return list(csv.DictReader(open(project_path("data/hf_filers.csv"))))


def load_cusip_to_ticker() -> dict[str, str]:
    m = {}
    with open(project_path("data/cusip_to_ticker.csv")) as f:
        for r in csv.DictReader(f):
            m[r["cusip"].strip()] = r["ticker"]
            # Also try the 6-char CUSIP issuer prefix (some 13Fs report short)
            m.setdefault(r["cusip"][:8], r["ticker"])
    return m


def upsert_holdings(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO holdings_13f
            (accession, filer_cik, filer_name, period_end, ticker, shares, value_usd)
        VALUES
            (:accession, :filer_cik, :filer_name, :period_end, :ticker, :shares, :value_usd)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def main():
    cfg = load()
    start = date.fromisoformat(cfg["backtest"]["start_date"])
    end = date.today()

    filers = load_filers()
    cusip_to_ticker = load_cusip_to_ticker()
    print(f"Loaded {len(filers)} filers, {len(cusip_to_ticker)} CUSIP mappings")

    p = Edgar13FProvider(rate_limit_sleep=0.15)
    conn = connect()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    total = 0
    filing_count = 0
    failures = []
    with open(LOG, "a") as logf:
        for fi, filer in enumerate(filers, 1):
            cik = filer["cik"]
            name = filer["name"]
            try:
                filings = p.list_filings(cik)
                in_window = [
                    f for f in filings
                    if f["filing_date"]
                    and start.isoformat() <= f["filing_date"] <= end.isoformat()
                ]
            except Exception as e:
                logf.write(f"[{fi:>3}/{len(filers)}] {name[:35]}  list FAILED: {e}\n")
                failures.append(cik)
                continue

            filer_rows = 0
            for f in in_window:
                try:
                    holdings = p.fetch_holdings(cik, f["accession"], f["filing_date"])
                except Exception as e:
                    logf.write(f"  ! {f['accession']} parse FAILED: {e}\n")
                    continue
                # Map CUSIPs to universe tickers
                rows = []
                for h in holdings:
                    cusip = h["cusip"].strip()
                    ticker = cusip_to_ticker.get(cusip) or cusip_to_ticker.get(cusip[:8])
                    if not ticker:
                        continue
                    rows.append({
                        "accession": f["accession"],
                        "filer_cik": cik,
                        "filer_name": name,
                        "period_end": f["period_end"],
                        "ticker": ticker,
                        "shares": h["shares"],
                        "value_usd": h["value_usd"],
                    })
                n = upsert_holdings(conn, rows)
                total += n
                filer_rows += n
                filing_count += 1

            logf.write(f"[{fi:>3}/{len(filers)}] {name[:40]:40s}  filings={len(in_window):>3}  rows={filer_rows:>5}\n")
            logf.flush()
            STATUS.write_text(json.dumps({
                "completed": fi, "total": len(filers),
                "filings_processed": filing_count,
                "rows_written": total, "failures": failures,
                "elapsed_sec": round(time.time() - started, 1),
                "status": "running" if fi < len(filers) else "done",
            }, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
