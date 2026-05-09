"""Daily ETF AUM snapshot — forward-only history."""
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load, project_path
from lib.db import connect
from providers.etf_flows import fetch_aum_snapshot

STATUS = project_path("logs/14_ingest_etf_flows_status.json")
LOG = project_path("logs/14_ingest_etf_flows.log")


def main():
    cfg = load()
    etfs = cfg["etfs"]["sector"] + cfg["etfs"]["single_stock_leveraged"]
    conn = connect()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    today = date.today().isoformat()
    written = 0
    failures = []
    with open(LOG, "a") as logf:
        for i, t in enumerate(etfs, 1):
            r = fetch_aum_snapshot(t, sleep=0.3)
            if r:
                # Compute flow estimate from prior day's snapshot
                prev = conn.execute(
                    "SELECT shares_outstanding, nav FROM etf_aum WHERE etf_ticker=? AND date < ? ORDER BY date DESC LIMIT 1",
                    (t, today),
                ).fetchone()
                if prev and prev["shares_outstanding"] and r["shares_outstanding"] and r["nav"]:
                    delta_shares = r["shares_outstanding"] - prev["shares_outstanding"]
                    r["daily_flow_estimate"] = delta_shares * r["nav"]
                conn.execute("""
                    INSERT OR REPLACE INTO etf_aum
                        (etf_ticker, date, shares_outstanding, nav, aum_usd, daily_flow_estimate)
                    VALUES (:etf_ticker, :date, :shares_outstanding, :nav, :aum_usd, :daily_flow_estimate)
                """, r)
                written += 1
                logf.write(f"  {t:8s}  AUM=${r['aum_usd']:>12,.0f}  shares={r['shares_outstanding'] or 0:>14,.0f}  flow=${r['daily_flow_estimate'] or 0:>12,.0f}\n")
            else:
                failures.append(t)
            conn.commit()
            STATUS.write_text(json.dumps({
                "completed": i, "total": len(etfs),
                "rows_written": written, "failures": failures,
                "elapsed_sec": round(time.time() - started, 1),
                "status": "running" if i < len(etfs) else "done",
            }, indent=2))
    conn.close()
    print(f"DONE. {written} of {len(etfs)} ETFs ingested.")


if __name__ == "__main__":
    main()
