"""Run the full backtest suite and write a markdown + JSON report."""
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.backtest import (
    HORIZONS,
    load_prices_wide,
    load_returns_panel,
    run_backtest_all_signals,
    run_backtest_composite,
)
from lib.config import project_path


SIGNALS = [
    # technical (composite)
    "ret_1m", "ret_3m", "ret_6m",
    "dist_200ma", "rsi_14", "pct_from_52w_high",
    # technical (overlay — trend signals)
    "ret_12m", "rs_vs_qqq_3m", "rs_vs_xlk_3m",
    # positioning (composite)
    "insider_net_90d_signed", "short_volume_ratio_14d", "si_true_dtc",
    # positioning (overlay — trend / weak signals)
    "insider_net_90d_abs", "hf_count_13f", "hf_top_concentration", "hf_count_change_4q",
    # V1.5: ttm_pe, ev_sales removed (no TTM multiples used)
]

REPORT_JSON = project_path("data/backtest_results.json")
REPORT_MD = project_path("data/backtest_report.md")


def fmt_metric(v, fmt: str = ".4f") -> str:
    if v is None:
        return "—"
    return f"{v:{fmt}}"


def main():
    print("Loading prices for forward-return panel...")
    closes = load_prices_wide()
    fwd_panels = load_returns_panel(closes)
    print(f"Forward panels built: {list(fwd_panels.keys())}")

    print("\nRunning per-signal backtest...")
    t0 = time.time()
    sig_results = run_backtest_all_signals(SIGNALS, fwd_panels)
    print(f"  ({time.time()-t0:.1f}s) {len(sig_results)} signal-runs")

    print("Running composite backtest...")
    comp_results = run_backtest_composite(fwd_panels)

    all_results = sig_results + comp_results

    # Persist JSON
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(all_results, indent=2, default=str))

    # Render markdown
    df = pd.DataFrame(all_results)
    print("\n=== Backtest summary ===\n")
    print(df[["signal", "kind", "horizon", "n", "ic", "decile_spread",
              "top_hit_rate", "bot_hit_rate"]].to_string(index=False))

    md_lines = [
        "# Positioning Meter — Backtest Report",
        f"\nGenerated: {pd.Timestamp.now()}",
        f"\nUniverse: 366 TMT names (mcap >= $1.5B)",
        f"\nForward horizons: {list(HORIZONS.keys())}",
        "\n## Per-signal results",
        "",
        "| Signal | Kind | Horizon | N | IC (Spearman) | Decile spread | Top dec hit (% neg fwd) | Bot dec hit (% pos fwd) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sig_results:
        md_lines.append(
            f"| {r['signal']} | {r['kind']} | {r['horizon']} | {r['n']:,} | "
            f"{fmt_metric(r.get('ic'))} | {fmt_metric(r.get('decile_spread'))} | "
            f"{fmt_metric(r.get('top_hit_rate'), '.2%')} | {fmt_metric(r.get('bot_hit_rate'), '.2%')} |"
        )

    md_lines.append("\n## Composite (temperature) results\n")
    md_lines.append("| Signal | Horizon | N | IC | Decile spread | Top dec hit | Bot dec hit |")
    md_lines.append("|---|---|---|---|---|---|---|")
    for r in comp_results:
        md_lines.append(
            f"| {r['signal']} | {r['horizon']} | {r['n']:,} | "
            f"{fmt_metric(r.get('ic'))} | {fmt_metric(r.get('decile_spread'))} | "
            f"{fmt_metric(r.get('top_hit_rate'), '.2%')} | {fmt_metric(r.get('bot_hit_rate'), '.2%')} |"
        )

    md_lines.append("\n## Interpretation guide\n")
    md_lines.append("- **IC** = Spearman correlation of signal percentile vs forward return. Negative IC means high signal → low forward return (contrarian/late signal). Positive IC means high signal → high forward return (trend-confirming/early signal).")
    md_lines.append("- **Decile spread** = mean fwd return of top decile − bottom decile. Sign matches IC.")
    md_lines.append("- **Top dec hit rate** = % of top-decile observations followed by negative forward return. >55% means the extreme is reliably 'too hot'.")
    md_lines.append("- **Bot dec hit rate** = % of bottom-decile observations followed by positive forward return. >55% means the extreme is reliably 'too cold'.")
    md_lines.append("- For our 'temperature' interpretation to work as a contrarian signal, we want **negative IC** and high top-dec/bot-dec hit rates.")

    REPORT_MD.write_text("\n".join(md_lines))
    print(f"\nWrote {REPORT_JSON}")
    print(f"Wrote {REPORT_MD}")


if __name__ == "__main__":
    main()
