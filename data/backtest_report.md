# Positioning Meter — Backtest Report

Generated: 2026-05-10 15:23:57.380233

Universe: 366 TMT names (mcap >= $1.5B)

Forward horizons: ['1w', '1m', '3m']

## Per-signal results

| Signal | Kind | Horizon | N | IC (Spearman) | Decile spread | Top dec hit (% neg fwd) | Bot dec hit (% pos fwd) |
|---|---|---|---|---|---|---|---|
| ret_1m | pct_self | 1w | 615,235 | -0.0232 | -0.0038 | 47.09% | 56.84% |
| ret_1m | pct_self | 1m | 609,474 | -0.0326 | -0.0099 | 45.74% | 58.32% |
| ret_1m | pct_self | 3m | 594,490 | -0.0232 | -0.0243 | 42.60% | 60.46% |
| ret_1m | pct_peer | 1w | 653,136 | -0.0027 | — | 46.69% | 52.72% |
| ret_1m | pct_peer | 1m | 647,475 | -0.0002 | — | 45.04% | 54.61% |
| ret_1m | pct_peer | 3m | 632,816 | 0.0090 | — | 42.92% | 55.66% |
| ret_3m | pct_self | 1w | 599,906 | -0.0225 | -0.0060 | 47.52% | 56.19% |
| ret_3m | pct_self | 1m | 594,201 | -0.0282 | -0.0140 | 45.15% | 59.35% |
| ret_3m | pct_self | 3m | 579,373 | -0.0378 | -0.0334 | 45.19% | 60.00% |
| ret_3m | pct_peer | 1w | 638,439 | 0.0054 | — | 46.10% | 52.23% |
| ret_3m | pct_peer | 1m | 632,847 | 0.0112 | — | 44.54% | 53.36% |
| ret_3m | pct_peer | 3m | 618,283 | 0.0168 | — | 42.43% | 55.45% |
| ret_6m | pct_self | 1w | 577,688 | -0.0108 | -0.0011 | 46.90% | 54.71% |
| ret_6m | pct_self | 1m | 572,054 | -0.0107 | -0.0009 | 45.06% | 56.65% |
| ret_6m | pct_self | 3m | 557,354 | 0.0160 | 0.0207 | 41.38% | 56.43% |
| ret_6m | pct_peer | 1w | 616,780 | 0.0080 | — | 45.87% | 52.21% |
| ret_6m | pct_peer | 1m | 611,278 | 0.0111 | — | 44.30% | 53.86% |
| ret_6m | pct_peer | 3m | 596,984 | 0.0193 | — | 42.49% | 55.82% |
| dist_200ma | pct_self | 1w | 549,818 | -0.0128 | -0.0020 | 47.46% | 54.81% |
| dist_200ma | pct_self | 1m | 544,260 | -0.0088 | -0.0028 | 45.04% | 56.85% |
| dist_200ma | pct_self | 3m | 529,833 | -0.0000 | -0.0003 | 43.58% | 57.32% |
| dist_200ma | pct_peer | 1w | 589,569 | 0.0075 | — | 45.84% | 51.79% |
| dist_200ma | pct_peer | 1m | 584,211 | 0.0133 | — | 44.39% | 53.05% |
| dist_200ma | pct_peer | 3m | 570,261 | 0.0193 | — | 43.00% | 54.91% |
| rsi_14 | pct_self | 1w | 620,583 | -0.0269 | -0.0039 | 48.35% | 55.56% |
| rsi_14 | pct_self | 1m | 614,719 | -0.0300 | -0.0084 | 47.20% | 57.25% |
| rsi_14 | pct_self | 3m | 599,572 | -0.0284 | -0.0196 | 46.10% | 57.85% |
| rsi_14 | pct_peer | 1w | 656,492 | -0.0035 | — | 46.17% | 52.92% |
| rsi_14 | pct_peer | 1m | 650,780 | -0.0027 | — | 44.24% | 54.91% |
| rsi_14 | pct_peer | 3m | 636,099 | 0.0085 | — | 41.87% | 55.99% |
| pct_from_52w_high | pct_self | 1w | 616,675 | -0.0182 | -0.0047 | 47.95% | 54.97% |
| pct_from_52w_high | pct_self | 1m | 610,901 | -0.0196 | -0.0087 | 45.78% | 57.49% |
| pct_from_52w_high | pct_self | 3m | 595,898 | -0.0171 | -0.0175 | 45.21% | 58.53% |
| pct_from_52w_high | pct_peer | 1w | 654,545 | 0.0050 | — | 45.38% | 52.01% |
| pct_from_52w_high | pct_peer | 1m | 648,845 | 0.0112 | — | 43.03% | 53.94% |
| pct_from_52w_high | pct_peer | 3m | 634,173 | 0.0165 | — | 40.95% | 55.48% |
| ret_12m | pct_self | 1w | 534,079 | 0.0049 | 0.0021 | 45.94% | 53.60% |
| ret_12m | pct_self | 1m | 528,542 | 0.0104 | 0.0116 | 44.64% | 54.13% |
| ret_12m | pct_self | 3m | 514,246 | 0.0038 | 0.0121 | 44.95% | 55.94% |
| ret_12m | pct_peer | 1w | 574,857 | 0.0077 | — | 46.28% | 51.90% |
| ret_12m | pct_peer | 1m | 569,488 | 0.0106 | — | 45.26% | 53.17% |
| ret_12m | pct_peer | 3m | 555,610 | 0.0154 | — | 44.46% | 55.21% |
| rs_vs_qqq_3m | pct_self | 1w | 599,906 | 0.0050 | 0.0004 | 45.94% | 53.28% |
| rs_vs_qqq_3m | pct_self | 1m | 594,201 | 0.0157 | 0.0095 | 43.58% | 54.28% |
| rs_vs_qqq_3m | pct_self | 3m | 579,373 | 0.0111 | 0.0147 | 43.14% | 54.38% |
| rs_vs_qqq_3m | pct_peer | 1w | 638,439 | 0.0054 | — | 46.10% | 52.23% |
| rs_vs_qqq_3m | pct_peer | 1m | 632,847 | 0.0112 | — | 44.54% | 53.36% |
| rs_vs_qqq_3m | pct_peer | 3m | 618,283 | 0.0168 | — | 42.43% | 55.45% |
| rs_vs_xlk_3m | pct_self | 1w | 599,906 | 0.0062 | 0.0012 | 46.01% | 53.40% |
| rs_vs_xlk_3m | pct_self | 1m | 594,201 | 0.0186 | 0.0130 | 43.40% | 53.77% |
| rs_vs_xlk_3m | pct_self | 3m | 579,373 | 0.0228 | 0.0265 | 42.58% | 53.10% |
| rs_vs_xlk_3m | pct_peer | 1w | 638,439 | 0.0054 | — | 46.10% | 52.23% |
| rs_vs_xlk_3m | pct_peer | 1m | 632,847 | 0.0112 | — | 44.54% | 53.36% |
| rs_vs_xlk_3m | pct_peer | 3m | 618,283 | 0.0168 | — | 42.43% | 55.45% |
| insider_net_90d_signed | pct_self | 1w | 240,192 | -0.0047 | — | 45.31% | 55.42% |
| insider_net_90d_signed | pct_self | 1m | 238,110 | -0.0036 | — | 42.60% | 58.80% |
| insider_net_90d_signed | pct_self | 3m | 232,708 | 0.0078 | — | 38.65% | 62.13% |
| insider_net_90d_signed | pct_peer | 1w | 179,264 | -0.0116 | — | 45.49% | 56.42% |
| insider_net_90d_signed | pct_peer | 1m | 177,906 | -0.0192 | — | 44.14% | 59.55% |
| insider_net_90d_signed | pct_peer | 3m | 174,373 | -0.0215 | — | 40.27% | 63.81% |
| short_volume_ratio_14d | pct_self | 1w | 495,462 | -0.0050 | -0.0023 | 46.56% | 52.97% |
| short_volume_ratio_14d | pct_self | 1m | 489,807 | -0.0139 | -0.0089 | 45.29% | 55.55% |
| short_volume_ratio_14d | pct_self | 3m | 475,106 | -0.0248 | -0.0271 | 44.14% | 55.68% |
| short_volume_ratio_14d | pct_peer | 1w | 541,373 | -0.0092 | — | 47.86% | 52.83% |
| short_volume_ratio_14d | pct_peer | 1m | 535,864 | -0.0192 | — | 47.02% | 55.28% |
| short_volume_ratio_14d | pct_peer | 3m | 521,581 | -0.0255 | — | 45.92% | 56.43% |
| si_true_dtc | pct_peer | 1w | 45,799 | -0.0183 | — | 47.35% | 53.35% |
| si_true_dtc | pct_peer | 1m | 42,719 | -0.0349 | — | 44.62% | 57.96% |
| si_true_dtc | pct_peer | 3m | 34,629 | -0.0642 | — | 45.54% | 56.29% |
| insider_net_90d_abs | pct_self | 1w | 240,192 | 0.0084 | 0.0036 | 45.05% | 55.14% |
| insider_net_90d_abs | pct_self | 1m | 238,110 | 0.0156 | 0.0190 | 40.49% | 57.30% |
| insider_net_90d_abs | pct_self | 3m | 232,708 | 0.0123 | 0.0557 | 36.30% | 61.82% |
| insider_net_90d_abs | pct_peer | 1w | 179,264 | 0.0081 | — | 43.70% | 54.77% |
| insider_net_90d_abs | pct_peer | 1m | 177,906 | 0.0100 | — | 40.58% | 57.57% |
| insider_net_90d_abs | pct_peer | 3m | 174,373 | 0.0080 | — | 36.20% | 62.17% |
| hf_count_13f | pct_self | 1w | 545,759 | 0.0126 | — | 45.98% | 52.97% |
| hf_count_13f | pct_self | 1m | 540,494 | 0.0229 | — | 44.14% | 54.48% |
| hf_count_13f | pct_self | 3m | 526,783 | 0.0233 | — | 42.42% | 56.17% |
| hf_count_13f | pct_peer | 1w | 582,943 | 0.0044 | — | 45.68% | 53.08% |
| hf_count_13f | pct_peer | 1m | 577,829 | 0.0065 | — | 43.72% | 55.56% |
| hf_count_13f | pct_peer | 3m | 564,509 | 0.0066 | — | 41.45% | 58.65% |
| hf_top_concentration | pct_self | 1w | 545,759 | -0.0061 | — | 46.97% | 52.87% |
| hf_top_concentration | pct_self | 1m | 540,494 | -0.0060 | — | 45.59% | 54.03% |
| hf_top_concentration | pct_self | 3m | 526,783 | 0.0020 | — | 43.26% | 56.39% |
| hf_top_concentration | pct_peer | 1w | 582,943 | -0.0034 | — | 46.74% | 54.02% |
| hf_top_concentration | pct_peer | 1m | 577,829 | -0.0045 | — | 45.33% | 56.21% |
| hf_top_concentration | pct_peer | 3m | 564,509 | -0.0053 | — | 44.11% | 58.38% |
| hf_count_change_4q | pct_self | 1w | 435,528 | 0.0020 | 0.0019 | 46.07% | 53.82% |
| hf_count_change_4q | pct_self | 1m | 430,571 | 0.0036 | 0.0065 | 43.71% | 56.96% |
| hf_count_change_4q | pct_self | 3m | 417,649 | 0.0032 | 0.0210 | 42.37% | 58.80% |
| hf_count_change_4q | pct_peer | 1w | 476,310 | 0.0013 | — | 46.67% | 53.06% |
| hf_count_change_4q | pct_peer | 1m | 471,466 | 0.0012 | — | 45.20% | 54.73% |
| hf_count_change_4q | pct_peer | 3m | 458,841 | 0.0014 | — | 43.41% | 56.76% |

## Composite (temperature) results

| Signal | Horizon | N | IC | Decile spread | Top dec hit | Bot dec hit |
|---|---|---|---|---|---|---|
| COMPOSITE_TEMPERATURE | 1w | 544,851 | -0.0115 | -0.0032 | 47.72% | 53.40% |
| COMPOSITE_TEMPERATURE | 1m | 539,111 | -0.0200 | -0.0124 | 47.57% | 55.29% |
| COMPOSITE_TEMPERATURE | 3m | 524,229 | -0.0257 | -0.0264 | 45.88% | 55.58% |

## Interpretation guide

- **IC** = Spearman correlation of signal percentile vs forward return. Negative IC means high signal → low forward return (contrarian/late signal). Positive IC means high signal → high forward return (trend-confirming/early signal).
- **Decile spread** = mean fwd return of top decile − bottom decile. Sign matches IC.
- **Top dec hit rate** = % of top-decile observations followed by negative forward return. >55% means the extreme is reliably 'too hot'.
- **Bot dec hit rate** = % of bottom-decile observations followed by positive forward return. >55% means the extreme is reliably 'too cold'.
- For our 'temperature' interpretation to work as a contrarian signal, we want **negative IC** and high top-dec/bot-dec hit rates.