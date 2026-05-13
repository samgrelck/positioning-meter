#!/bin/bash
# Refresh source data: runs the daily-cadence ingestion scripts in sequence,
# then runs deploy.sh to recompute + render + push.
#
# Total wall-clock: ~70 minutes (mostly Yahoo estimates and options, which
# are rate-limited by the source).
#
# What this DOES run (daily-cadence data):
#   - Polygon prices               (~4 min)
#   - Yahoo options chains         (~18 min)
#   - Yahoo estimates              (~35 min)
#   - Yahoo ETF AUM                (~2 min)
#   - openinsider Form 4           (~10 min)
#
# What this does NOT run (weekly / quarterly cadence — run those manually
# when you remember, see README.md):
#   - FINRA short volume           — biweekly settlement, run weekly
#   - NASDAQ true SI               — biweekly settlement
#   - Polygon financials           — quarterly
#   - EDGAR 13F                    — quarterly (filings 45d post quarter-end)
#
# Usage:
#   ./tools/refresh_data.sh            # full daily refresh + deploy
#   ./tools/refresh_data.sh nodeploy   # data only, skip deploy.sh
#   ./tools/refresh_data.sh fast       # skip slow ones (estimates, options)

set -e
cd "$(dirname "$0")/.."

MODE="${1:-full}"

echo "============================================================"
echo "Positioning Meter — data refresh ($(date +'%Y-%m-%d %H:%M'))"
echo "Mode: $MODE"
echo "============================================================"

run_step() {
    local label="$1"
    local cmd="$2"
    echo ""
    echo "==> $label"
    eval "$cmd" 2>&1 | tail -3
}

run_step "Polygon prices (~4 min)"               "python3 setup/02_ingest_prices.py"
run_step "Yahoo ETF AUM (~2 min)"                 "python3 setup/14_ingest_etf_flows.py"
run_step "openinsider Form 4 (~10 min)"           "python3 setup/05_ingest_insider.py"

if [ "$MODE" != "fast" ]; then
    run_step "Yahoo options chains (~18 min)"     "python3 setup/15_ingest_options_yahoo.py"
    run_step "Yahoo estimates (~35 min)"           "python3 setup/13_ingest_estimates.py"
fi

if [ "$MODE" = "nodeploy" ]; then
    echo ""
    echo "Data refresh done. Skipping deploy.sh per nodeploy mode."
    echo "Run ./tools/deploy.sh manually to push the dashboard."
else
    echo ""
    echo "============================================================"
    echo "Data refresh complete. Running deploy.sh..."
    echo "============================================================"
    ./tools/deploy.sh
fi

echo ""
echo "✅ Done — $(date +'%Y-%m-%d %H:%M')"
