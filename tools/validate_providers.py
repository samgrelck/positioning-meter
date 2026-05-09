"""Validate each concrete provider on a 5-name sample before full ingestion.

Run: python -m tools.validate_providers prices
     python -m tools.validate_providers all
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SAMPLE = ["NVDA", "MSFT", "MDB", "NET", "ANET"]


def validate_prices():
    from providers.polygon_prices import PolygonPricesProvider
    p = PolygonPricesProvider()
    end = date.today()
    start = end - timedelta(days=10 * 365)
    print(f"Pulling {start} -> {end} for {len(SAMPLE)} names via Polygon...")
    for t in SAMPLE:
        rows = p.fetch_prices(t, start, end)
        if not rows:
            print(f"  {t:6s} FAIL — no rows returned")
            continue
        first, last = rows[0], rows[-1]
        print(
            f"  {t:6s} OK   {len(rows):>5} bars  "
            f"first={first['date']} (close={first['close']:.2f})  "
            f"last={last['date']} (close={last['close']:.2f})"
        )


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m tools.validate_providers <prices|all>")
        sys.exit(1)
    target = sys.argv[1]
    if target in ("prices", "all"):
        validate_prices()


if __name__ == "__main__":
    main()
