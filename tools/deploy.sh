#!/bin/bash
# Deploy: re-render dashboard, copy to docs/, commit, push to GitHub.
# Configure remote first:  git remote add origin git@github.com:USERNAME/positioning-meter.git

set -e
cd "$(dirname "$0")/.."

echo "==> Computing signals..."
python3 setup/06_compute_signals.py | tail -3

echo "==> Running backtest..."
python3 setup/07_run_backtest.py 2>&1 | grep COMPOSITE | tail -3

echo "==> Rendering dashboard..."
python3 setup/08_render_dashboard.py | tail -1

echo "==> Copying to docs/index.html..."
cp data/dashboard.html docs/index.html

echo "==> Committing..."
git add docs/index.html
TIMESTAMP=$(date +"%Y-%m-%d %H:%M")
git commit -m "Dashboard refresh: ${TIMESTAMP}" || echo "(no changes to commit)"

echo "==> Pushing..."
git push origin main

echo "Done. Pages URL: https://USERNAME.github.io/positioning-meter/ (replace USERNAME)"
