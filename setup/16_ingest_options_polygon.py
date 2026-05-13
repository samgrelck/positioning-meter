"""Polygon historical options backfill — REQUIRES Polygon Options Advanced.

10y of daily options signals (IV30, skew, term slope, P/C) per ticker.

Strategy per (ticker, asof_date):
  1. List contracts active as of asof_date (~50-200 typical)
  2. For each contract, fetch the day's aggregate (OHLCV + Polygon-computed IV)
  3. Group by expiration, build chain, compute signals via options_compute
  4. Upsert into options_daily

Wall clock estimate: 366 names × ~2500 trading days × ~50 contracts each =
~45M API calls. At Polygon Advanced rate limits (~100 req/sec) = ~125 hours
nonstop. Too slow.

OPTIMIZATION: We sample DAILY through the universe but instead of full chain
reconstruction per day, we use Polygon's flat-files (S3 bucket) for bulk
historical access. Flat files are included in Options Advanced and dump
the full day's options data per file. Much faster than REST.

This script defaults to flat-file mode. REST mode available as fallback.

Usage (when subscribed):
  python setup/16_ingest_options_polygon.py --start 2016-05-08 --end today
  python setup/16_ingest_options_polygon.py --resume   # restart-safe
  python setup/16_ingest_options_polygon.py --mode rest --start 2024-01-01
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load, project_path, require_env
from lib.db import connect
from lib.signals.options_compute import compute_chain_signals
from providers.polygon_options import PolygonOptionsProvider

STATUS = project_path("logs/16_ingest_options_polygon_status.json")
LOG = project_path("logs/16_ingest_options_polygon.log")


def load_universe() -> list[str]:
    cfg = load()
    out = project_path(cfg["universe"]["output_csv"])
    return [r["ticker"] for r in csv.DictReader(open(out))]


def load_spot_prices() -> dict[tuple[str, str], float]:
    """Map (ticker, date) -> adj_close for spot price at each historical date."""
    conn = connect()
    rows = conn.execute(
        "SELECT ticker, date, adj_close FROM prices WHERE adj_close IS NOT NULL"
    ).fetchall()
    conn.close()
    return {(r["ticker"], r["date"]): r["adj_close"] for r in rows}


def business_days(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def upsert(conn, row: dict) -> int:
    conn.execute("""
        INSERT OR REPLACE INTO options_daily
            (ticker, date, iv_30d, iv_3m, iv_term_slope, skew_25d,
             pc_volume_ratio, pc_oi_ratio, options_volume, avg_options_volume_20d)
        VALUES
            (:ticker, :date, :iv_30d, :iv_3m, :iv_term_slope, :skew_25d,
             :pc_volume_ratio, :pc_oi_ratio, :options_volume, :avg_options_volume_20d)
    """, row)
    return 1


# ============================================================
# Flat-file mode (PREFERRED — fastest)
# ============================================================
def ingest_via_flatfiles(start: date, end: date, universe: set[str], spots: dict):
    """Polygon flat-files: daily gzip CSV per day with ALL options bars.
    s3://flatfiles/us_options_opra/day_aggs_v1/{YYYY}/{MM}/{YYYY-MM-DD}.csv.gz

    Requires Options Advanced (flat-file access included). Use the s3
    bucket access keys from Polygon dashboard. Falls back to REST for
    missing days.
    """
    print("Flat-file mode requires Polygon Advanced + S3 credentials.")
    print("Set env vars: POLYGON_S3_KEY, POLYGON_S3_SECRET")
    print("Or use --mode rest for slower REST-only ingestion.")
    print()
    print("Flat-file implementation: pulls one daily flat-file at a time,")
    print("filters to universe tickers, groups by expiration, computes")
    print("signals via lib.signals.options_compute. ~5-10 min per trading")
    print("day for full universe. ~2500 days × 7 min = ~12 days total.")
    print()
    print("NOTE: this stub is intentionally not running. Implementation lands")
    print("when subscription is active and S3 credentials are configured.")
    raise NotImplementedError(
        "Flat-file ingestion requires Polygon Options Advanced + S3 credentials. "
        "Subscribe first, set POLYGON_S3_KEY/POLYGON_S3_SECRET env vars, then "
        "fill in the boto3 S3 client logic here (or run --mode rest as fallback)."
    )


# ============================================================
# REST mode (FALLBACK — much slower)
# ============================================================
def ingest_via_rest(start: date, end: date, universe: list[str], spots: dict, resume: bool = True):
    """Per-day, per-ticker contract reconstruction. Slow (~125 hours nonstop)
    but doesn't require S3. Used as fallback when flat-files unavailable.
    """
    provider = PolygonOptionsProvider(rate_limit_sleep=0.05)
    conn = connect()

    # Resume from latest in DB
    if resume:
        max_existing = conn.execute(
            "SELECT MAX(date) FROM options_daily WHERE ticker IN ({})".format(
                ",".join("?" * len(universe))
            ),
            list(universe),
        ).fetchone()[0]
        if max_existing:
            resume_from = date.fromisoformat(max_existing) + timedelta(days=1)
            if resume_from > start:
                print(f"Resuming from {resume_from} (skipping already-ingested days)")
                start = resume_from

    days = list(business_days(start, end))
    started = time.time()
    n_written = 0
    universe_set = set(universe)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as logf:
        logf.write(f"\n=== REST mode {start} -> {end} ({len(days)} days, {len(universe)} tickers) ===\n")
        for day_i, asof in enumerate(days, 1):
            for t_i, ticker in enumerate(universe, 1):
                spot = spots.get((ticker, asof.isoformat()))
                if not spot:
                    continue
                contracts = provider.list_contracts_as_of(ticker, asof, limit=300)
                if not contracts:
                    continue
                # Group by expiration; for each expiration build chain from
                # per-contract aggs at this asof.
                # NOTE: full implementation would batch contract aggs API
                # calls. This stub leaves the heavy lifting commented out
                # since we'd burn API quota even in dry-run mode.
                pass  # TODO: implement when subscribed
            if day_i % 10 == 0:
                STATUS.write_text(json.dumps({
                    "mode": "rest", "completed_days": day_i, "total_days": len(days),
                    "rows_written": n_written, "elapsed_sec": round(time.time() - started, 1),
                    "status": "running",
                }, indent=2))

    conn.close()
    print("REST stub complete (no rows written — fill in contract aggs loop).")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2016-05-08", help="ISO date")
    parser.add_argument("--end", default=None, help="ISO date or 'today'")
    parser.add_argument("--mode", choices=["flatfiles", "rest"], default="flatfiles")
    parser.add_argument("--resume", action="store_true", default=True)
    args = parser.parse_args()

    require_env("POLYGON_API_KEY")
    start = date.fromisoformat(args.start)
    end = date.today() if (args.end in (None, "today")) else date.fromisoformat(args.end)

    universe = load_universe()
    spots = load_spot_prices()
    print(f"Universe: {len(universe)} tickers")
    print(f"Date range: {start} -> {end}")
    print(f"Spot prices loaded: {len(spots):,}")
    print(f"Mode: {args.mode}")

    if args.mode == "flatfiles":
        ingest_via_flatfiles(start, end, set(universe), spots)
    else:
        ingest_via_rest(start, end, universe, spots, resume=args.resume)


if __name__ == "__main__":
    main()
