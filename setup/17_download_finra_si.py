"""Download FINRA biweekly Short Interest historical files.

Source: https://cdn.finra.org/equity/otcmarket/biweekly/shrt{YYYYMMDD}.csv
Coverage: ~May 2018 to present (~7.5y, universe-wide NYSE + NASDAQ + everything)
Format: pipe-delimited despite .csv extension
Files: biweekly settlement dates (~15th and end-of-month of each month)

Saves files to data/FINRA/shrt{YYYYMMDD}.csv. Idempotent — skips already-downloaded.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import project_path

FINRA_DIR = project_path("data/FINRA")
URL_TEMPLATE = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{date}.csv"
STATUS = project_path("logs/17_download_finra_si_status.json")
LOG = project_path("logs/17_download_finra_si.log")


def candidate_dates(start: date, end: date):
    """Generate plausible biweekly settlement dates: 15th and last-day of each month."""
    d = date(start.year, start.month, 1)
    while d <= end:
        # ~15th of month
        mid = date(d.year, d.month, 15)
        if start <= mid <= end:
            yield mid
        # Last day of month
        if d.month == 12:
            eom = date(d.year, 12, 31)
        else:
            eom = date(d.year, d.month + 1, 1) - timedelta(days=1)
        if start <= eom <= end:
            yield eom
        # Advance to next month
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)


def download_one(asof: date, sleep: float = 0.3) -> str:
    """Download one file. Returns 'ok' / 'skip' / 'missing' / 'fail'."""
    fname = f"shrt{asof.strftime('%Y%m%d')}.csv"
    out_path = FINRA_DIR / fname
    if out_path.exists() and out_path.stat().st_size > 1000:
        return "skip"
    url = URL_TEMPLATE.format(date=asof.strftime("%Y%m%d"))
    try:
        r = requests.get(url, timeout=30)
        time.sleep(sleep)
        if r.status_code == 200 and len(r.content) > 1000:
            out_path.write_bytes(r.content)
            return "ok"
        return "missing"  # 403/404 — date doesn't have a file
    except Exception:
        return "fail"


def main(start_str: str = "2018-05-01", end_str: str | None = None):
    FINRA_DIR.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)

    start = date.fromisoformat(start_str)
    end = date.today() if end_str in (None, "today") else date.fromisoformat(end_str)

    dates = list(candidate_dates(start, end))
    print(f"Trying {len(dates)} candidate settlement dates from {start} to {end}")
    started = time.time()
    counts = {"ok": 0, "skip": 0, "missing": 0, "fail": 0}

    with open(LOG, "a") as logf:
        for i, d in enumerate(dates, 1):
            result = download_one(d)
            counts[result] += 1
            logf.write(f"[{i:>3}/{len(dates)}] {d}  {result}\n")
            if i % 20 == 0 or i == len(dates):
                logf.flush()
                STATUS.write_text(json.dumps({
                    "completed": i, "total": len(dates),
                    **counts,
                    "elapsed_sec": round(time.time() - started, 1),
                    "status": "running" if i < len(dates) else "done",
                }, indent=2))

    print(f"\nDONE.")
    print(f"  Downloaded (new):  {counts['ok']}")
    print(f"  Skipped (cached):  {counts['skip']}")
    print(f"  Missing (404/403): {counts['missing']}")
    print(f"  Failed (network):  {counts['fail']}")
    print(f"  Files in {FINRA_DIR}: {len(list(FINRA_DIR.glob('shrt*.csv')))}")


if __name__ == "__main__":
    start = sys.argv[1] if len(sys.argv) > 1 else "2018-05-01"
    end = sys.argv[2] if len(sys.argv) > 2 else None
    main(start, end)
