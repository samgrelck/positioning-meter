"""Filter theme_detector universe to $1.5B+ market cap and write to data/universe.csv.

Adds cluster_id from theme_detector clusters.json so peer-group lookups are
materialized at universe-build time.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load, project_path
from lib.peers import ticker_to_cluster


def main():
    cfg = load()
    src = project_path(cfg["universe"]["source_csv"])
    out = project_path(cfg["universe"]["output_csv"])
    min_mcap = cfg["universe"]["min_market_cap"]

    cluster_map = ticker_to_cluster()
    rows_in = 0
    rows_out = 0
    unmapped = []

    written = set()
    fieldnames = ["ticker", "name", "sic_code", "market_cap", "exchange", "cluster_id"]
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(src) as f, open(out, "w", newline="") as g:
        reader = csv.DictReader(f)
        writer = csv.DictWriter(g, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            rows_in += 1
            try:
                mcap = float(row["market_cap"])
            except (ValueError, TypeError):
                continue
            if mcap < min_mcap:
                continue
            ticker = row["ticker"]
            cid = cluster_map.get(ticker)
            if not cid:
                unmapped.append(ticker)
            writer.writerow({**row, "cluster_id": cid or ""})
            written.add(ticker)
            rows_out += 1

        # Manual additions: curated names NOT in the theme_detector source (e.g.
        # recent IPOs like SPCX/SpaceX, listed 2026-06-12) that we still want
        # scored. Merged here so a universe rebuild never silently drops them.
        # Bypasses the min_market_cap filter (these are hand-picked). cluster_id
        # falls back to the theme_detector cluster map, else stays blank (blank =
        # universe-wide peer ranking, which is what pct_peer uses anyway).
        manual = project_path("data/universe_manual_additions.csv")
        n_manual = 0
        if manual.exists():
            with open(manual) as mf:
                for row in csv.DictReader(mf):
                    t = (row.get("ticker") or "").strip()
                    if not t or t in written:
                        continue
                    cid = (row.get("cluster_id") or "").strip() or cluster_map.get(t) or ""
                    writer.writerow({k: row.get(k, "") for k in fieldnames} | {"cluster_id": cid})
                    written.add(t)
                    rows_out += 1
                    n_manual += 1

    print(f"Read {rows_in} from {src}")
    print(f"Wrote {rows_out} to {out} (min_market_cap=${min_mcap:,}; +{n_manual} manual additions)")
    print(f"Unmapped to a cluster (will use pct_self only): {len(unmapped)}")
    if unmapped:
        print(f"  examples: {unmapped[:10]}")


if __name__ == "__main__":
    main()
