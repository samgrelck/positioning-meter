"""Free-float + shares-outstanding snapshot from yfinance.

Float moves slowly, so this is a periodic snapshot (not a daily-cadence pull).
The latest row per ticker becomes the divisor for the float-turnover signal
(a long/retail-crowding proxy added in V1.14). Falls back to shares_out when
floatShares is unavailable.

Usage:  python3 setup/19_ingest_float.py
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import yfinance as yf

from lib.config import project_path
from lib.db import connect, init_schema

STATUS = project_path("logs/19_ingest_float_status.json")
LOG = project_path("logs/19_ingest_float.log")


def fetch(ticker: str, sleep: float = 0.4):
    try:
        info = yf.Ticker(ticker).info
        time.sleep(sleep)
        fl = info.get("floatShares")
        so = info.get("sharesOutstanding")
        fl = float(fl) if fl else None
        so = float(so) if so else None
        if not fl and not so:
            return None
        return {"float_shares": fl, "shares_out": so}
    except Exception:
        return None


def main():
    init_schema()
    universe = pd.read_csv(project_path("data/universe.csv"))
    tickers = universe["ticker"].dropna().unique().tolist()
    conn = connect()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    started = time.time()
    written, failures = 0, []
    with open(LOG, "a") as logf:
        logf.write(f"\n=== float ingest {today} ===\n")
        for i, t in enumerate(tickers, 1):
            r = fetch(t)
            if r:
                conn.execute(
                    """INSERT OR REPLACE INTO share_float
                       (ticker, asof_date, float_shares, shares_out)
                       VALUES (?, ?, ?, ?)""",
                    (t, today, r["float_shares"], r["shares_out"]),
                )
                written += 1
                logf.write(f"  {t:8s} float={r['float_shares'] or 0:>16,.0f} so={r['shares_out'] or 0:>16,.0f}\n")
            else:
                failures.append(t)
            if i % 10 == 0 or i == len(tickers):
                conn.commit()
                STATUS.write_text(json.dumps({
                    "completed": i, "total": len(tickers),
                    "rows_written": written, "failures": len(failures),
                    "elapsed_sec": round(time.time() - started, 1),
                    "status": "running" if i < len(tickers) else "done",
                }, indent=2))
    conn.commit()
    conn.close()
    print(f"DONE. float for {written} of {len(tickers)} tickers ({len(failures)} failed).")


if __name__ == "__main__":
    main()
