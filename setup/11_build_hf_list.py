"""Curate a list of hedge fund / L-S manager CIKs by querying SEC EDGAR
full-text search for each known fund name.

Output: data/hf_filers.csv (cik, name, classification, search_term)

V1 list focuses on:
  - Tiger Cubs / L-S TMT specialists
  - Multi-strats (pod shops)
  - Quant (typically large 13F books, fast turnover)
  - Concentrated active managers
  - Activists
Excludes: passive index funds (Vanguard, BlackRock iShares), mutual fund
complexes (Fidelity AUM is mostly passive/blend, not L-S).
"""
import csv
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import project_path, require_env


# Curated list — (search_term, classification)
# search_term is what we send to SEC; we'll take the first 13F-HR filer match.
# classification: tiger_cub | pod_shop | quant | concentrated | activist | crossover
KNOWN_FUNDS = [
    # Tiger Cubs / L-S TMT
    ("Tiger Global Management", "tiger_cub"),
    ("Coatue Management", "tiger_cub"),
    ("Lone Pine Capital", "tiger_cub"),
    ("Whale Rock Capital Management", "tiger_cub"),
    ("Light Street Capital Management", "tiger_cub"),
    ("D1 Capital Partners", "tiger_cub"),
    ("Hound Partners", "tiger_cub"),
    ("Maverick Capital", "tiger_cub"),
    ("Viking Global Investors", "tiger_cub"),
    ("Discovery Capital Management", "tiger_cub"),
    ("Steadfast Capital Management", "tiger_cub"),

    # Pod shops / multi-strats
    ("Citadel Advisors", "pod_shop"),
    ("Millennium Management", "pod_shop"),
    ("Point72 Asset Management", "pod_shop"),
    ("Balyasny Asset Management", "pod_shop"),
    ("ExodusPoint Capital Management", "pod_shop"),
    ("Hudson Bay Capital Management", "pod_shop"),
    ("Schonfeld Strategic Advisors", "pod_shop"),
    ("Verition Fund Management", "pod_shop"),
    ("Squarepoint Capital", "pod_shop"),
    ("Walleye Capital", "pod_shop"),

    # Quant
    ("Renaissance Technologies", "quant"),
    ("Two Sigma Investments", "quant"),
    ("D. E. Shaw", "quant"),
    ("AQR Capital Management", "quant"),
    ("Marshall Wace", "quant"),
    ("Acadian Asset Management", "quant"),
    ("Numeric Investors", "quant"),

    # Concentrated active
    ("Sands Capital Management", "concentrated"),
    ("Baillie Gifford", "concentrated"),
    ("Capital Research Global Investors", "concentrated"),
    ("ARK Investment Management", "concentrated"),
    ("Polen Capital Management", "concentrated"),
    ("Magnetar Capital", "concentrated"),
    ("Generation Investment Management", "concentrated"),
    ("Brave Warrior Advisors", "concentrated"),
    ("Akre Capital Management", "concentrated"),
    ("Soroban Capital Partners", "concentrated"),
    ("Glenview Capital Management", "concentrated"),
    ("Egerton Capital", "concentrated"),
    ("Senator Investment Group", "concentrated"),
    ("Holocene Advisors", "concentrated"),

    # Activists / event-driven
    ("Pershing Square Capital Management", "activist"),
    ("Third Point", "activist"),
    ("Trian Fund Management", "activist"),
    ("Elliott Investment Management", "activist"),
    ("ValueAct Holdings", "activist"),
    ("Starboard Value", "activist"),
    ("Engine No 1", "activist"),
    ("Politan Capital Management", "activist"),
    ("Jana Partners", "activist"),

    # Crossover / late stage / mutual-fund-like with TMT skew
    ("T. Rowe Price Associates", "crossover"),
    ("Wellington Management", "crossover"),
    ("Capital World Investors", "crossover"),
    ("Morgan Stanley Investment Management", "crossover"),
    ("BlackRock", "crossover"),  # huge but file-by-file ownership matters

    # Miscellaneous L/S
    ("Greenlight Capital", "concentrated"),
    ("Pentwater Capital Management", "pod_shop"),
    ("ANSON FUNDS", "concentrated"),
]


SEC_FTS = "https://efts.sec.gov/LATEST/search-index"
HEADERS = {"User-Agent": require_env("SEC_EDGAR_USER_AGENT")}


def lookup_cik(name: str) -> tuple[str | None, str | None]:
    """Return (cik, official_name) for the first 13F-HR filer matching `name`."""
    params = {
        "q": f'"{name}"',
        "forms": "13F-HR",
        "dateRange": "custom",
        "startdt": "2025-01-01",
        "enddt": "2026-05-01",
    }
    try:
        r = requests.get(SEC_FTS, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        print(f"  SEC search failed for '{name}': {e}")
        return (None, None)
    finally:
        time.sleep(0.3)

    hits = d.get("hits", {}).get("hits", [])
    if not hits:
        return (None, None)

    # Prefer the hit whose display_name most closely matches our search
    name_l = name.lower()
    for h in hits:
        src = h.get("_source", {})
        names = src.get("display_names", [])
        ciks = src.get("ciks", [])
        if not names or not ciks:
            continue
        if any(name_l in nm.lower() for nm in names):
            return (str(int(ciks[0])).zfill(10), names[0])
    # Fall back to first hit
    src = hits[0].get("_source", {})
    return (str(int(src.get("ciks", ["0"])[0])).zfill(10),
            src.get("display_names", [""])[0])


def main():
    out = project_path("data/hf_filers.csv")
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    found = 0
    for name, cls in KNOWN_FUNDS:
        cik, official = lookup_cik(name)
        if cik:
            found += 1
            print(f"  OK   {name:<45s}  CIK={cik}  ({official[:50]})")
            rows.append({
                "cik": cik,
                "name": official or name,
                "classification": cls,
                "search_term": name,
            })
        else:
            print(f"  MISS {name}")
    print(f"\nResolved {found}/{len(KNOWN_FUNDS)} CIKs")

    with open(out, "w", newline="") as g:
        w = csv.DictWriter(g, fieldnames=["cik", "name", "classification", "search_term"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
