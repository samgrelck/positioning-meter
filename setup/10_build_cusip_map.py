"""Build CUSIP -> universe-ticker mapping from SEC's official 13F securities list.

Output: data/cusip_to_ticker.csv (cusip, ticker, source_name)

Strategy:
  - Download SEC's quarterly 13F securities list (CUSIP + issuer name)
  - Normalize both 13F issuer names and our universe names
  - Match by normalized name; record CUSIPs that map to universe tickers

Match coverage <100% is expected — some universe names won't have an exact
match in the 13F list (foreign-domiciled, non-13F-eligible classes, name
mismatches). Those names just don't get HF crowding signals.
"""
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

from lib.config import load, project_path, require_env


SEC_URL = "https://www.sec.gov/files/investment/13flist2026q1.txt"

OUT = project_path("data/cusip_to_ticker.csv")


_SUFFIXES = [
    "INCORPORATED", "INC", "CORPORATION", "CORP", "LIMITED", "LTD", "PLC",
    "HOLDINGS", "HLDGS", "HLDG", "GROUP", "GRP", "COMPANY", "CO",
    "PARTNERSHIP", "LP", "TECHNOLOGIES", "TECH", "TECHNOLOGY",
    "INTERNATIONAL", "INTL", "SYSTEMS", "SYS", "SOLUTIONS",
    "ORDINARY", "ORD", "SHARES", "SHS", "COMMON", "COM",
    "CAP", "CAPITAL", "STK", "STOCK",
]
# Common abbreviation pairs in SEC list
_ABBREV = {
    "MATLS": "MATERIALS",
    "INTL": "INTERNATIONAL",
    "MACHS": "MACHINES",
    "TECHN": "TECHNOLOGIES",
    "MFG": "MANUFACTURING",
    "INDS": "INDUSTRIES",
    "DEV": "DEVELOPMENT",
    "ELEC": "ELECTRIC",
    "ENT": "ENTERPRISES",
    "COMM": "COMMUNICATIONS",
    "FINL": "FINANCIAL",
    "MGMT": "MANAGEMENT",
    "SVCS": "SERVICES",
    "HLTH": "HEALTH",
    "MED": "MEDICAL",
    "PHARM": "PHARMACEUTICAL",
    "RES": "RESEARCH",
}


def normalize(name: str) -> str:
    """Aggressive normalization for fuzzy matching."""
    n = name.upper().strip()
    # Class designations
    n = re.sub(r"\b(CL(ASS)?|CL)\.?\s+[A-Z]\b", " ", n)
    n = re.sub(r",.*", "", n)
    n = re.sub(r"\(.*?\)", "", n)
    # Punctuation -> space
    n = re.sub(r"[^\w\s]", " ", n)
    # Tokenize, expand abbreviations, drop suffix tokens, dedupe consecutively
    tokens = [_ABBREV.get(t, t) for t in n.split()]
    tokens = [t for t in tokens if t and t not in _SUFFIXES]
    return " ".join(tokens).strip()


def parse_13f_list(text: str) -> list[tuple[str, str]]:
    """Parse fixed-width SEC 13F list -> [(cusip, issuer_name), ...]"""
    rows = []
    for line in text.splitlines():
        if len(line) < 67:
            continue
        cusip = line[0:9].strip()
        issuer = line[10:40].strip()
        descr = line[40:67].strip()
        status = line[67:70].strip() if len(line) >= 70 else ""
        # Skip deletions
        if status == "D":
            continue
        # Skip puts/calls
        if "CALL" in descr.upper() or "PUT" in descr.upper():
            continue
        if not cusip or not issuer:
            continue
        rows.append((cusip, issuer))
    return rows


def main():
    headers = {"User-Agent": require_env("SEC_EDGAR_USER_AGENT")}
    print(f"Downloading {SEC_URL}...")
    r = requests.get(SEC_URL, headers=headers, timeout=30)
    r.raise_for_status()
    print(f"  {len(r.text):,} bytes")

    sec_rows = parse_13f_list(r.text)
    print(f"Parsed {len(sec_rows):,} 13F securities (excl. options/deletions)")

    # Build name -> CUSIPs index
    name_to_cusips: dict[str, list[str]] = {}
    for cusip, issuer in sec_rows:
        n = normalize(issuer)
        if not n:
            continue
        name_to_cusips.setdefault(n, []).append((cusip, issuer))

    # Match against universe (exact normalized first, then fuzzy)
    from rapidfuzz import process, fuzz
    sec_keys = list(name_to_cusips.keys())
    cfg = load()
    uni_path = project_path(cfg["universe"]["output_csv"])
    matches = []
    unmatched = []
    with open(uni_path) as f:
        for r in csv.DictReader(f):
            ticker = r["ticker"]
            name = r["name"]
            n = normalize(name)
            hits = name_to_cusips.get(n)
            if not hits and n:
                # Token-set ratio fuzzy match, threshold 90
                best = process.extractOne(n, sec_keys, scorer=fuzz.token_set_ratio,
                                           score_cutoff=90)
                if best:
                    hits = name_to_cusips.get(best[0])
            if hits:
                for cusip, issuer in hits:
                    matches.append({
                        "cusip": cusip,
                        "ticker": ticker,
                        "source_name": issuer,
                    })
            else:
                unmatched.append((ticker, name, n))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as g:
        w = csv.DictWriter(g, fieldnames=["cusip", "ticker", "source_name"])
        w.writeheader()
        w.writerows(matches)

    print(f"\nMatched: {len(matches)} CUSIP rows for {len({m['ticker'] for m in matches})} unique tickers")
    print(f"Unmatched universe tickers: {len(unmatched)}")
    if unmatched[:10]:
        print("First 10 unmatched (ticker, raw name, normalized):")
        for t, n, nn in unmatched[:10]:
            print(f"  {t:8s}  {n[:35]:35s}  ->  {nn[:30]}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
