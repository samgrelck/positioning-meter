#!/usr/bin/env python3
"""One-time migration: dedupe insider_form4 and repair its primary key.

THE BUG
-------
`insider_form4`'s primary key was (accession, filer_cik, transaction_date,
transaction_code, shares) — but the openinsider provider never populates
`filer_cik`, so that column is NULL in 100% of rows. SQLite (unlike the SQL
standard) treats NULLs in a primary key as DISTINCT from each other, so the PK
never matched an existing row and `INSERT OR REPLACE` in
setup/05_ingest_insider.py APPENDED a fresh copy of every transaction on every
daily run instead of replacing it. Result as of 2026-07-31: 2,736,968 rows of
which only 76,874 are distinct — 97.2% duplicates, growing by one full copy per
day, and inflating the `insider_net_90d_*` / `insider_buying_90d` signals by a
per-ticker factor of ~36x-76x (non-uniform, so it distorts the cross-section,
not just the scale).

THE FIX
-------
Rebuild the table with a PK made only of columns that are actually populated:
(accession, ticker, transaction_date, transaction_code, shares, price_per_share,
filer_name). `filer_cik` and `direct_indirect` stay as data columns but are out
of the key, so a future NULL there can never re-open this hole. Duplicate rows
collapse to the most recently ingested copy (MAX(rowid)).

Idempotent: safe to re-run; a clean table just reports 0 duplicates removed.

Usage:
  python3 tools/fix_insider_dupes.py --dry-run    # report only, no writes
  python3 tools/fix_insider_dupes.py              # migrate (+ VACUUM)
  python3 tools/fix_insider_dupes.py --no-vacuum  # skip the space reclaim
  python3 tools/fix_insider_dupes.py --fix-sentinels   # also null out the
      # value_usd of rows sitting at exactly 2147483647 (INT32_MAX), which is a
      # source-side overflow sentinel, not a real dollar amount. Off by default.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.db import connect  # noqa: E402

SENTINEL = 2147483647

# Identity of a Form 4 transaction line, using only columns openinsider fills.
KEY = ("accession", "ticker", "transaction_date", "transaction_code",
       "shares", "price_per_share", "filer_name")

NEW_TABLE = """
CREATE TABLE insider_form4_new (
    accession      TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    filer_cik      TEXT,
    filer_name     TEXT NOT NULL,
    relationship   TEXT,
    transaction_date TEXT NOT NULL,
    transaction_code TEXT NOT NULL,
    shares         REAL NOT NULL,
    price_per_share REAL NOT NULL,
    value_usd      REAL,
    direct_indirect TEXT,
    PRIMARY KEY (accession, ticker, transaction_date, transaction_code,
                 shares, price_per_share, filer_name)
);
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-vacuum", action="store_true")
    ap.add_argument("--fix-sentinels", action="store_true")
    args = ap.parse_args()

    conn = connect()
    total = conn.execute("SELECT COUNT(*) FROM insider_form4").fetchone()[0]
    keycols = ", ".join(KEY)
    distinct = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT {keycols} FROM insider_form4)"
    ).fetchone()[0]
    nulls = conn.execute(
        "SELECT COUNT(*) FROM insider_form4 WHERE filer_cik IS NULL").fetchone()[0]
    sentinels = conn.execute(
        "SELECT COUNT(*) FROM insider_form4 WHERE ABS(value_usd) = ?",
        (SENTINEL,)).fetchone()[0]

    print(f"insider_form4: {total:,} rows, {distinct:,} distinct -> "
          f"{total - distinct:,} duplicates ({100 * (total - distinct) / max(total, 1):.1f}%)")
    print(f"  rows with NULL filer_cik (the root cause): {nulls:,}")
    print(f"  rows at INT32_MAX sentinel value_usd:      {sentinels:,}")

    if args.dry_run:
        print("\n--dry-run: no changes written.")
        conn.close()
        return

    print("\nRebuilding table with a PK of only-populated columns...")
    conn.executescript("DROP TABLE IF EXISTS insider_form4_new;" + NEW_TABLE)
    # Keep the most recently ingested copy of each transaction.
    conn.execute(f"""
        INSERT INTO insider_form4_new
            (accession, ticker, filer_cik, filer_name, relationship,
             transaction_date, transaction_code, shares, price_per_share,
             value_usd, direct_indirect)
        SELECT accession, ticker, filer_cik, filer_name, relationship,
               transaction_date, transaction_code, shares, price_per_share,
               value_usd, direct_indirect
        FROM insider_form4
        WHERE rowid IN (SELECT MAX(rowid) FROM insider_form4 GROUP BY {keycols})
    """)
    kept = conn.execute("SELECT COUNT(*) FROM insider_form4_new").fetchone()[0]
    print(f"  kept {kept:,} rows")
    if kept != distinct:
        conn.rollback()
        conn.close()
        sys.exit(f"ABORT: kept {kept:,} != expected distinct {distinct:,}; nothing changed.")

    if args.fix_sentinels:
        n = conn.execute(
            "UPDATE insider_form4_new SET value_usd = NULL WHERE ABS(value_usd) = ?",
            (SENTINEL,)).rowcount
        print(f"  nulled value_usd on {n:,} INT32_MAX sentinel rows")

    conn.execute("DROP TABLE insider_form4")
    conn.execute("ALTER TABLE insider_form4_new RENAME TO insider_form4")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_insider_ticker_date "
                 "ON insider_form4(ticker, transaction_date)")
    conn.commit()
    print(f"  swapped in. {total:,} -> {kept:,} rows.")

    if not args.no_vacuum:
        print("\nVACUUM (reclaiming space; this takes a few minutes on a large DB)...")
        conn.execute("VACUUM")
        print("  done.")

    conn.close()
    print("\nNext: re-run setup/06_compute_signals.py then setup/08_render_dashboard.py "
          "so the insider signals and dashboard reflect the deduped data.")


if __name__ == "__main__":
    main()
