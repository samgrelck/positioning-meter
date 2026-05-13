"""Daily options snapshot via yfinance — forward-only accumulation.

Free. Pulls today's chain for each universe ticker, computes IV30, skew,
term slope, P/C ratios, persists to options_daily.

Idempotent: INSERT OR REPLACE on (ticker, date).
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
from providers.yfinance_options import compute_signals_today

STATUS = project_path("logs/15_ingest_options_yahoo_status.json")
LOG = project_path("logs/15_ingest_options_yahoo.log")


def load_universe() -> list[str]:
    cfg = load()
    out = project_path(cfg["universe"]["output_csv"])
    return [r["ticker"] for r in csv.DictReader(open(out))]


def upsert(conn, row: dict) -> int:
    if row is None:
        return 0
    conn.execute("""
        INSERT OR REPLACE INTO options_daily
            (ticker, date, iv_30d, iv_3m, iv_term_slope, skew_25d,
             pc_volume_ratio, pc_oi_ratio, options_volume, avg_options_volume_20d)
        VALUES
            (:ticker, :date, :iv_30d, :iv_3m, :iv_term_slope, :skew_25d,
             :pc_volume_ratio, :pc_oi_ratio, :options_volume, :avg_options_volume_20d)
    """, row)
    return 1


def main(limit: int | None = None):
    cfg = load()
    tickers = load_universe()
    if limit:
        tickers = tickers[:limit]

    conn = connect()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    n_written = 0
    n_failed = 0
    failures = []

    with open(LOG, "a") as logf:
        logf.write(f"\n=== {date.today().isoformat()} options yahoo run ===\n")
        for i, t in enumerate(tickers, 1):
            try:
                row = compute_signals_today(t, sleep=0.3)
                if row:
                    n = upsert(conn, row)
                    n_written += n
                    conn.commit()
                    iv30 = row.get("iv_30d")
                    skew = row.get("skew_25d")
                    iv30_s = f"{iv30:.3f}" if iv30 else "—"
                    skew_s = f"{skew:+.3f}" if skew else "—"
                    logf.write(f"[{i:>3}/{len(tickers)}] {t:8s} IV30={iv30_s} skew={skew_s}\n")
                else:
                    n_failed += 1
                    failures.append(t)
                    logf.write(f"[{i:>3}/{len(tickers)}] {t:8s} NO DATA\n")
            except Exception as e:
                n_failed += 1
                failures.append(t)
                logf.write(f"[{i:>3}/{len(tickers)}] {t:8s} FAILED: {e}\n")
            logf.flush()

            if i % 25 == 0 or i == len(tickers):
                STATUS.write_text(json.dumps({
                    "completed": i, "total": len(tickers),
                    "rows_written": n_written, "failures": n_failed,
                    "elapsed_sec": round(time.time() - started, 1),
                    "status": "running" if i < len(tickers) else "done",
                }, indent=2))
    conn.close()
    print(f"DONE. {n_written}/{len(tickers)} rows written, {n_failed} failures.")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=limit)
