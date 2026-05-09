"""Ingest daily Yahoo estimates snapshot, analyst actions, and earnings dates."""
import csv
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load, project_path
from lib.db import connect
from providers.yahoo_estimates import (
    fetch_estimates_snapshot,
    fetch_analyst_actions,
    fetch_earnings_date,
)

STATUS = project_path("logs/13_ingest_estimates_status.json")
LOG = project_path("logs/13_ingest_estimates.log")


def load_universe() -> list[str]:
    cfg = load()
    out = project_path(cfg["universe"]["output_csv"])
    return [r["ticker"] for r in csv.DictReader(open(out))]


def main():
    tickers = load_universe()
    conn = connect()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    snap_count = 0
    actions_count = 0
    cal_count = 0
    failures = []
    today = date.today().isoformat()

    with open(LOG, "a") as logf:
        for i, t in enumerate(tickers, 1):
            # Estimates snapshot
            s = fetch_estimates_snapshot(t, sleep=0.3)
            if s:
                conn.execute("""
                    INSERT OR REPLACE INTO estimates_daily
                        (ticker, date, forward_eps, trailing_eps,
                         target_mean_price, target_high_price, target_low_price,
                         target_dispersion, num_analyst_opinions,
                         recommendation_key, recommendation_mean)
                    VALUES (:ticker, :date, :forward_eps, :trailing_eps,
                            :target_mean_price, :target_high_price, :target_low_price,
                            :target_dispersion, :num_analyst_opinions,
                            :recommendation_key, :recommendation_mean)
                """, s)
                snap_count += 1

            # Analyst actions
            actions = fetch_analyst_actions(t, sleep=0.3)
            if actions:
                conn.executemany("""
                    INSERT OR REPLACE INTO analyst_actions
                        (ticker, action_date, firm, from_grade, to_grade, action)
                    VALUES (:ticker, :action_date, :firm, :from_grade, :to_grade, :action)
                """, actions)
                actions_count += len(actions)

            # Earnings date
            ed = fetch_earnings_date(t, sleep=0.3)
            if ed:
                conn.execute("""
                    INSERT OR REPLACE INTO earnings_calendar
                        (ticker, next_earnings_date, last_updated)
                    VALUES (?, ?, ?)
                """, (t, ed, today))
                cal_count += 1

            conn.commit()
            if not s and not actions and not ed:
                failures.append(t)

            if i % 25 == 0 or i == len(tickers):
                STATUS.write_text(json.dumps({
                    "completed": i, "total": len(tickers),
                    "snap_rows": snap_count,
                    "actions_rows": actions_count,
                    "calendar_rows": cal_count,
                    "failures": len(failures),
                    "elapsed_sec": round(time.time() - started, 1),
                    "status": "running" if i < len(tickers) else "done",
                }, indent=2))
                logf.write(f"[{i:>3}/{len(tickers)}] snaps={snap_count} actions={actions_count} cal={cal_count}\n")
                logf.flush()
    conn.close()


if __name__ == "__main__":
    main()
