# Intraday stock-selection comparison

Frozen reference: 836c4463d21b

## Completed results

Saved 36 completed trials and 0 failures. Fee model and all entry/exit rules are identical within each comparison.

| Month / direction | 50 stocks, 2 bps | 200 stocks, 2 bps | 50 stocks, 5 bps | 200 stocks, 5 bps |
|---|---:|---:|---:|---:|
| 2025-02 / both | -2.08% (52 trades) | -1.39% (54 trades) | -2.46% (52 trades) | -1.67% (54 trades) |
| 2025-02 / long | -1.67% (35 trades) | -3.95% (50 trades) | -1.88% (35 trades) | -4.12% (50 trades) |
| 2025-02 / short | +0.38% (44 trades) | -1.47% (61 trades) | -0.01% (44 trades) | -1.82% (61 trades) |
| 2025-06 / both | -3.51% (59 trades) | -3.12% (58 trades) | -4.24% (59 trades) | -3.52% (58 trades) |
| 2025-06 / long | -1.44% (45 trades) | -3.75% (65 trades) | -2.05% (45 trades) | -4.17% (65 trades) |
| 2025-06 / short | -1.33% (38 trades) | -2.38% (68 trades) | -1.68% (38 trades) | -2.89% (68 trades) |
| 2026-01 / both | -1.25% (50 trades) | -3.86% (41 trades) | -1.66% (50 trades) | -4.13% (41 trades) |
| 2026-01 / long | -0.82% (54 trades) | -3.62% (51 trades) | -1.30% (54 trades) | -3.93% (51 trades) |
| 2026-01 / short | -0.23% (39 trades) | +1.09% (54 trades) | -0.57% (39 trades) | +0.40% (54 trades) |

## Aggregate diagnostic

| Direction / slippage | 50 stocks: total P&L / PF / trades | 200 stocks: total P&L / PF / trades |
|---|---:|---:|
| both / 2 bps | Rs -68,362.37 / 0.567 / 161 | Rs -83,693.55 / 0.550 / 153 |
| both / 5 bps | Rs -83,622.98 / 0.497 / 161 | Rs -93,314.93 / 0.508 / 153 |
| long / 2 bps | Rs -39,239.45 / 0.695 / 134 | Rs -113,173.10 / 0.477 / 166 |
| long / 5 bps | Rs -52,316.22 / 0.612 / 134 | Rs -122,259.14 / 0.444 / 166 |
| short / 2 bps | Rs -11,755.36 / 0.879 / 121 | Rs -27,588.10 / 0.845 / 183 |
| short / 5 bps | Rs -22,575.53 / 0.778 / 121 | Rs -43,072.89 / 0.766 / 183 |

Aggregates combine independent monthly capital resets, not a compounded portfolio. PF pools trade profits and losses. Compare expectancy, trade count and drawdown as well as total P&L.

## Assessment

The broader scan is not supported by this pilot: pooled combined, buy-only and short-only P&L remain negative at both slippage assumptions. The 200-stock buy portfolio is worse in all three months. Its short portfolio improves in January, but worsens in February and June; one positive month is insufficient.

The current selection already uses opening relative volume. Expanding the pool selects more unusually active stocks, but unusual activity alone does not establish continuation. In these three windows at 2 bps/side, mean relative volume rises from 3.12 to 6.73 for buys and from 3.90 to 7.04 for shorts, while average net trade P&L worsens. These are descriptive results, not a causal explanation or new selection thresholds.

Keep the up-to-50-stock control for subsequent comparisons. Next test a separate VWAP trend-pullback/rejection entry, with completed-candle resumption and a defined structural stop, against the current ORB. Evaluate longs and shorts separately, preserve cost stress, and predeclare the setup before looking at outcomes. No settings are promoted and no live or paper trading behavior changes.
