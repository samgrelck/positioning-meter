"""Compute within-bucket signal weights from backtest IC.

Currently signals within a bucket are equal-weighted, which gives weak
signals (e.g. ret_6m IC −0.011) the same influence as strong ones
(e.g. ret_3m IC −0.038). This tool computes weights proportional to |IC|
so stronger signals dominate.

Output: data/signal_weights.json with per-signal weights, normalized
within each bucket to sum to 1.0.

Usage: python3 tools/tune_signal_weights.py
"""
import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import project_path


# Pull bucket assignments from compute_signals (in-composite signals only)
import importlib.util
spec = importlib.util.spec_from_file_location("compute_signals", project_path("setup/06_compute_signals.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SIGNAL_TO_BUCKET = m.SIGNAL_TO_BUCKET


def main(horizon: str = "3m", kind: str = "pct_self"):
    bt_path = project_path("data/backtest_results.json")
    if not bt_path.exists():
        print(f"No backtest results at {bt_path} — run setup/07_run_backtest.py first.")
        sys.exit(1)
    results = json.loads(bt_path.read_text())

    # Use the BLENDED IC = mean of pct_self IC and pct_peer IC at the chosen
    # horizon. This matches how the composite actually scores each signal
    # (0.5 × pct_self + 0.5 × pct_peer per dual_percentile_weights config).
    # If only one kind exists (e.g. si_true_dtc has only peer due to short
    # history), use it alone.
    sig_ics = defaultdict(list)
    for r in results:
        sig = r.get("signal")
        if sig not in SIGNAL_TO_BUCKET:
            continue
        if r.get("horizon") != horizon:
            continue
        if r.get("kind") not in ("pct_self", "pct_peer"):
            continue
        ic = r.get("ic")
        if ic is None:
            continue
        sig_ics[sig].append(ic)
    sig_best_ic = {sig: sum(ics) / len(ics) for sig, ics in sig_ics.items()}

    # Group by bucket
    by_bucket = defaultdict(dict)
    for sig, ic in sig_best_ic.items():
        bucket = SIGNAL_TO_BUCKET[sig]
        by_bucket[bucket][sig] = ic

    # Compute weights — proportional to |IC|, normalized within bucket
    weights = {}
    print(f"\nSignal weights computed from |IC| at {horizon} fwd ({kind} or peer, best of both):")
    print("=" * 76)
    for bucket in sorted(by_bucket.keys()):
        sigs = by_bucket[bucket]
        # Only include signals with CONTRARIAN (negative) IC. Positive-IC signals
        # in the composite would push it the wrong direction; if any sneak in
        # they get weight 0.
        contrarian = {s: abs(ic) for s, ic in sigs.items() if ic < 0}
        if not contrarian:
            # Fallback: keep equal weights if no contrarian signals (shouldn't happen)
            n = len(sigs)
            weights.update({s: 1.0 / n for s in sigs})
            continue
        total = sum(contrarian.values())
        bucket_weights = {s: contrarian.get(s, 0) / total for s in sigs}
        weights.update(bucket_weights)

        # Report
        print(f"\n  Bucket: {bucket}")
        for sig in sorted(sigs.keys(), key=lambda x: -abs(sigs[x])):
            ic = sigs[sig]
            w = bucket_weights[sig]
            note = " (positive IC — zero weight)" if ic > 0 else ""
            print(f"    {sig:28s}  IC={ic:+.4f}  weight={w:.3f}{note}")

    # For options bucket signals, we don't have backtest IC. Equal-weight.
    options_signals = [s for s, b in SIGNAL_TO_BUCKET.items() if b == "options" and s not in weights]
    if options_signals:
        n = len(options_signals)
        print(f"\n  Bucket: options (no backtest history — equal-weighted)")
        for sig in options_signals:
            weights[sig] = 1.0 / n
            print(f"    {sig:28s}  weight={1.0/n:.3f}")

    out = project_path("data/signal_weights.json")
    out.write_text(json.dumps({
        "horizon": horizon,
        "kind": kind,
        "note": "Weights computed from |IC| at given horizon, normalized within bucket. "
                "Positive-IC signals (trend-following) get weight 0.",
        "weights": weights,
    }, indent=2))
    print(f"\nWrote {out}")
    print(f"Re-run setup/06_compute_signals.py to apply these weights.")


if __name__ == "__main__":
    main()
