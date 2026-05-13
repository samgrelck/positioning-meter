# Positioning Meter — Backtest Report

Generated: 2026-05-13 07:12:03.272638

Universe: 366 TMT names (mcap >= $1.5B)

Forward horizons: ['1w', '1m', '3m']

## Per-signal results

| Signal | Kind | Horizon | N | IC (Spearman) | Decile spread | Top dec hit (% neg fwd) | Bot dec hit (% pos fwd) |
|---|---|---|---|---|---|---|---|
| ret_1m | pct_self | 1w | 615,923 | -0.0227 | -0.0036 | 47.02% | 56.83% |
| ret_1m | pct_self | 1m | 610,160 | -0.0324 | -0.0095 | 45.67% | 58.34% |
| ret_1m | pct_self | 3m | 595,171 | -0.0226 | -0.0236 | 42.58% | 60.36% |
| ret_1m | pct_peer | 1w | 653,796 | -0.0024 | — | 46.68% | 52.70% |
| ret_1m | pct_peer | 1m | 648,135 | -0.0002 | — | 45.03% | 54.62% |
| ret_1m | pct_peer | 3m | 633,471 | 0.0092 | — | 42.91% | 55.65% |
| ret_3m | pct_self | 1w | 600,588 | -0.0220 | -0.0059 | 47.49% | 56.17% |
| ret_3m | pct_self | 1m | 594,881 | -0.0281 | -0.0138 | 45.10% | 59.37% |
| ret_3m | pct_self | 3m | 580,051 | -0.0372 | -0.0325 | 45.13% | 59.95% |
| ret_3m | pct_peer | 1w | 639,096 | 0.0056 | — | 46.10% | 52.21% |
| ret_3m | pct_peer | 1m | 633,502 | 0.0112 | — | 44.53% | 53.38% |
| ret_3m | pct_peer | 3m | 618,936 | 0.0171 | — | 42.41% | 55.44% |
| ret_6m | pct_self | 1w | 578,366 | -0.0102 | -0.0010 | 46.86% | 54.68% |
| ret_6m | pct_self | 1m | 572,730 | -0.0106 | -0.0009 | 45.01% | 56.73% |
| ret_6m | pct_self | 3m | 558,030 | 0.0166 | 0.0216 | 41.32% | 56.39% |
| ret_6m | pct_peer | 1w | 617,430 | 0.0083 | — | 45.86% | 52.18% |
| ret_6m | pct_peer | 1m | 611,925 | 0.0111 | — | 44.28% | 53.88% |
| ret_6m | pct_peer | 3m | 597,626 | 0.0196 | — | 42.47% | 55.80% |
| dist_200ma | pct_self | 1w | 550,488 | -0.0120 | -0.0018 | 47.40% | 54.77% |
| dist_200ma | pct_self | 1m | 544,930 | -0.0087 | -0.0026 | 44.97% | 56.89% |
| dist_200ma | pct_self | 3m | 530,495 | 0.0008 | 0.0008 | 43.50% | 57.26% |
| dist_200ma | pct_peer | 1w | 590,203 | 0.0078 | — | 45.83% | 51.76% |
| dist_200ma | pct_peer | 1m | 584,843 | 0.0133 | — | 44.37% | 53.07% |
| dist_200ma | pct_peer | 3m | 570,889 | 0.0196 | — | 42.98% | 54.89% |
| rsi_14 | pct_self | 1w | 621,279 | -0.0265 | -0.0038 | 48.32% | 55.55% |
| rsi_14 | pct_self | 1m | 615,411 | -0.0297 | -0.0081 | 47.15% | 57.28% |
| rsi_14 | pct_self | 3m | 600,261 | -0.0279 | -0.0189 | 46.09% | 57.76% |
| rsi_14 | pct_peer | 1w | 657,154 | -0.0032 | — | 46.16% | 52.89% |
| rsi_14 | pct_peer | 1m | 651,440 | -0.0026 | — | 44.22% | 54.92% |
| rsi_14 | pct_peer | 3m | 636,757 | 0.0086 | — | 41.86% | 55.99% |
| pct_from_52w_high | pct_self | 1w | 617,363 | -0.0177 | -0.0045 | 47.89% | 54.93% |
| pct_from_52w_high | pct_self | 1m | 611,587 | -0.0193 | -0.0083 | 45.72% | 57.51% |
| pct_from_52w_high | pct_self | 3m | 596,580 | -0.0165 | -0.0164 | 45.12% | 58.48% |
| pct_from_52w_high | pct_peer | 1w | 655,205 | 0.0052 | — | 45.37% | 51.99% |
| pct_from_52w_high | pct_peer | 1m | 649,505 | 0.0111 | — | 43.02% | 53.96% |
| pct_from_52w_high | pct_peer | 3m | 634,829 | 0.0166 | — | 40.94% | 55.47% |
| ret_12m | pct_self | 1w | 534,748 | 0.0055 | 0.0023 | 45.88% | 53.56% |
| ret_12m | pct_self | 1m | 529,208 | 0.0109 | 0.0124 | 44.54% | 54.14% |
| ret_12m | pct_self | 3m | 514,902 | 0.0044 | 0.0130 | 44.90% | 55.89% |
| ret_12m | pct_peer | 1w | 575,489 | 0.0080 | — | 46.27% | 51.87% |
| ret_12m | pct_peer | 1m | 570,118 | 0.0107 | — | 45.24% | 53.19% |
| ret_12m | pct_peer | 3m | 556,240 | 0.0156 | — | 44.45% | 55.19% |
| rs_vs_qqq_3m | pct_self | 1w | 600,588 | 0.0055 | 0.0005 | 45.93% | 53.24% |
| rs_vs_qqq_3m | pct_self | 1m | 594,881 | 0.0158 | 0.0096 | 43.52% | 54.32% |
| rs_vs_qqq_3m | pct_self | 3m | 580,051 | 0.0117 | 0.0157 | 43.04% | 54.34% |
| rs_vs_qqq_3m | pct_peer | 1w | 639,096 | 0.0056 | — | 46.10% | 52.21% |
| rs_vs_qqq_3m | pct_peer | 1m | 633,502 | 0.0112 | — | 44.53% | 53.38% |
| rs_vs_qqq_3m | pct_peer | 3m | 618,936 | 0.0171 | — | 42.41% | 55.44% |
| rs_vs_xlk_3m | pct_self | 1w | 600,588 | 0.0068 | 0.0014 | 45.98% | 53.33% |
| rs_vs_xlk_3m | pct_self | 1m | 594,881 | 0.0187 | 0.0132 | 43.35% | 53.78% |
| rs_vs_xlk_3m | pct_self | 3m | 580,051 | 0.0234 | 0.0276 | 42.51% | 53.08% |
| rs_vs_xlk_3m | pct_peer | 1w | 639,096 | 0.0056 | — | 46.10% | 52.21% |
| rs_vs_xlk_3m | pct_peer | 1m | 633,502 | 0.0112 | — | 44.53% | 53.38% |
| rs_vs_xlk_3m | pct_peer | 3m | 618,936 | 0.0171 | — | 42.41% | 55.44% |
| insider_net_90d_signed | pct_self | 1w | 240,440 | -0.0049 | — | 45.31% | 55.44% |
| insider_net_90d_signed | pct_self | 1m | 238,356 | -0.0039 | — | 42.60% | 58.82% |
| insider_net_90d_signed | pct_self | 3m | 232,954 | 0.0074 | — | 38.66% | 62.13% |
| insider_net_90d_signed | pct_peer | 1w | 179,426 | -0.0116 | — | 45.49% | 56.42% |
| insider_net_90d_signed | pct_peer | 1m | 178,068 | -0.0193 | — | 44.15% | 59.57% |
| insider_net_90d_signed | pct_peer | 3m | 174,535 | -0.0215 | — | 40.27% | 63.81% |
| short_volume_ratio_14d | pct_self | 1w | 496,150 | -0.0050 | -0.0023 | 46.56% | 52.98% |
| short_volume_ratio_14d | pct_self | 1m | 490,495 | -0.0139 | -0.0089 | 45.27% | 55.56% |
| short_volume_ratio_14d | pct_self | 3m | 475,790 | -0.0247 | -0.0268 | 44.14% | 55.67% |
| short_volume_ratio_14d | pct_peer | 1w | 542,035 | -0.0093 | — | 47.86% | 52.83% |
| short_volume_ratio_14d | pct_peer | 1m | 536,524 | -0.0193 | — | 47.00% | 55.29% |
| short_volume_ratio_14d | pct_peer | 3m | 522,239 | -0.0254 | — | 45.91% | 56.42% |
| si_true_dtc | pct_peer | 1w | 46,185 | -0.0190 | — | 47.41% | 53.40% |
| si_true_dtc | pct_peer | 1m | 43,105 | -0.0360 | — | 44.48% | 58.19% |
| si_true_dtc | pct_peer | 3m | 35,015 | -0.0640 | — | 45.52% | 56.25% |
| insider_net_90d_abs | pct_self | 1w | 240,440 | 0.0085 | 0.0036 | 45.05% | 55.13% |
| insider_net_90d_abs | pct_self | 1m | 238,356 | 0.0158 | 0.0191 | 40.47% | 57.29% |
| insider_net_90d_abs | pct_self | 3m | 232,954 | 0.0126 | 0.0561 | 36.29% | 61.80% |
| insider_net_90d_abs | pct_peer | 1w | 179,426 | 0.0081 | — | 43.71% | 54.76% |
| insider_net_90d_abs | pct_peer | 1m | 178,068 | 0.0102 | — | 40.57% | 57.56% |
| insider_net_90d_abs | pct_peer | 3m | 174,535 | 0.0080 | — | 36.21% | 62.18% |
| hf_count_13f | pct_self | 1w | 546,409 | 0.0127 | — | 46.00% | 52.96% |
| hf_count_13f | pct_self | 1m | 541,142 | 0.0232 | — | 44.12% | 54.50% |
| hf_count_13f | pct_self | 3m | 527,425 | 0.0235 | — | 42.41% | 56.15% |
| hf_count_13f | pct_peer | 1w | 583,571 | 0.0044 | — | 45.69% | 53.08% |
| hf_count_13f | pct_peer | 1m | 578,455 | 0.0065 | — | 43.71% | 55.58% |
| hf_count_13f | pct_peer | 3m | 565,131 | 0.0064 | — | 41.46% | 58.65% |
| hf_top_concentration | pct_self | 1w | 546,409 | -0.0061 | — | 46.97% | 52.86% |
| hf_top_concentration | pct_self | 1m | 541,142 | -0.0063 | — | 45.57% | 54.04% |
| hf_top_concentration | pct_self | 3m | 527,425 | 0.0019 | — | 43.27% | 56.39% |
| hf_top_concentration | pct_peer | 1w | 583,571 | -0.0034 | — | 46.74% | 54.01% |
| hf_top_concentration | pct_peer | 1m | 578,455 | -0.0045 | — | 45.31% | 56.22% |
| hf_top_concentration | pct_peer | 3m | 565,131 | -0.0052 | — | 44.10% | 58.37% |
| hf_count_change_4q | pct_self | 1w | 436,146 | 0.0022 | 0.0019 | 46.06% | 53.81% |
| hf_count_change_4q | pct_self | 1m | 431,181 | 0.0040 | 0.0070 | 43.65% | 56.95% |
| hf_count_change_4q | pct_self | 3m | 418,259 | 0.0034 | 0.0208 | 42.38% | 58.79% |
| hf_count_change_4q | pct_peer | 1w | 476,912 | 0.0014 | — | 46.68% | 53.07% |
| hf_count_change_4q | pct_peer | 1m | 472,062 | 0.0012 | — | 45.18% | 54.74% |
| hf_count_change_4q | pct_peer | 3m | 459,437 | 0.0014 | — | 43.41% | 56.76% |

## Composite (temperature) results

| Signal | Horizon | N | IC | Decile spread | Top dec hit | Bot dec hit |
|---|---|---|---|---|---|---|
| COMPOSITE_TEMPERATURE | 1w | 634,504 | -0.0127 | -0.0042 | 47.80% | 53.71% |
| COMPOSITE_TEMPERATURE | 1m | 628,419 | -0.0235 | -0.0169 | 47.68% | 55.78% |
| COMPOSITE_TEMPERATURE | 3m | 612,719 | -0.0337 | -0.0379 | 46.22% | 56.91% |

## Interpretation guide

- **IC** = Spearman correlation of signal percentile vs forward return. Negative IC means high signal → low forward return (contrarian/late signal). Positive IC means high signal → high forward return (trend-confirming/early signal).
- **Decile spread** = mean fwd return of top decile − bottom decile. Sign matches IC.
- **Top dec hit rate** = % of top-decile observations followed by negative forward return. >55% means the extreme is reliably 'too hot'.
- **Bot dec hit rate** = % of bottom-decile observations followed by positive forward return. >55% means the extreme is reliably 'too cold'.
- For our 'temperature' interpretation to work as a contrarian signal, we want **negative IC** and high top-dec/bot-dec hit rates.