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
# What this does NOT run (handled by their own cron entries — see `crontab -l`):
#   - FINRA short volume + biweekly SI   — Sunday 3:00am (scripts 04, 17, 18)
#   - EDGAR 13F                          — quarterly, 17th of Feb/May/Aug/Nov (script 12)
#     (NASDAQ true SI, script 09, is RETIRED — replaced by FINRA full-universe in V1.11)
#   - Polygon financials                 — quarterly, run manually as needed (script 03)
#
# Error handling: each ingest step is independent — a single failing source
# (e.g. a Yahoo rate-limit) is logged and counted but does NOT abort the run,
# so the dashboard still deploys with whatever fresh data succeeded. The script
# exits non-zero if any step failed, so cron logs / the staleness alert can see it.
#
# Usage:
#   ./tools/refresh_data.sh            # full daily refresh + deploy
#   ./tools/refresh_data.sh nodeploy   # data only, skip deploy.sh
#   ./tools/refresh_data.sh fast       # skip slow ones (estimates, options)

set -o pipefail
cd "$(dirname "$0")/.."

MODE="${1:-full}"
FAILED=()

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
    local rc=${PIPESTATUS[0]}
    if [ "$rc" -ne 0 ]; then
        echo "  ⚠️  STEP FAILED (exit $rc): $label"
        FAILED+=("$label")
    fi
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
    deploy_rc=$?
    if [ "$deploy_rc" -ne 0 ]; then
        echo "  ⚠️  DEPLOY FAILED (exit $deploy_rc)"
        FAILED+=("deploy")
    fi
fi

echo ""
if [ ${#FAILED[@]} -eq 0 ]; then
    echo "✅ Done — all steps succeeded — $(date +'%Y-%m-%d %H:%M')"
else
    echo "⚠️  Done WITH ${#FAILED[@]} FAILED STEP(S) — $(date +'%Y-%m-%d %H:%M'):"
    for f in "${FAILED[@]}"; do echo "     - $f"; done
    exit 1
fi
