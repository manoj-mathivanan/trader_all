# Stronger momentum entries — 8 October 2026

This variant addresses the marginal TCS breakout discussed in the recorded March trade. Stronger means stricter evidence at entry, not a proven increase in profitability. Existing saved runs remain unchanged and the default ORB config remains the control.

## Fixed candidate rules

- Keep the five-minute opening range and prior liquidity/ATR selection.
- Wait for a complete hourly confirmation candle, aligned to 09:15 IST. Earliest fill is 10:15; entries remain allowed through 11:30.
- Require a close beyond the opening high/low **plus 0.1 prior daily ATR** in the trade direction.
- Require the close above cumulative session VWAP for longs, below for shorts. VWAP uses five-minute typical-price/volume inputs.
- Require a close in the **top 30% of the completed hour's range** for longs, bottom 30% for shorts. This discourages buying after a large retracement from the hour's high or shorting after a large rebound.
- Require directional movement from the hourly open to its close of at least **0.1 prior daily ATR**. This rejects a negative long candle or a tiny positive body despite a nominal breakout.
- Keep five-minute fills and protective exits, 0.5 daily ATR stop, existing risk/capital limits, mandatory 15:00 exit and the reference's modeled charges/slippage. No leverage, re-entry or target changes.

The two new candle-quality fields default to disabled. Aggregate hourly open/high/low/close come only from the twelve completed five-minute constituents. Future candles cannot alter them. Filters can defer an entry to a later eligible hour; rejecting one signal does not necessarily eliminate that stock's whole session.

## Predeclared comparison

Seven trials: reference replay; hourly control; hourly + VWAP; hourly + buffer; hourly + close-position filter; hourly + directional-body filter; combined stronger hourly rules. Run the same seven trials on both frozen reference windows, retaining every result. No threshold sweep or winner selection.

Dashboard: **Test stronger entries** on a baseline report. CLI:

```powershell
.venv\Scripts\python.exe scripts/run_momentum.py --compare 28d677c85493 --suite stronger
.venv\Scripts\python.exe scripts/run_momentum.py --compare ebef4eacf96f --suite stronger
```

Limitations remain: just two short periods, current-constituent bias, approximate VWAP, assumed costs, unverified short/circuit/participation constraints and session-end drawdown. Filtering away trades can reduce losses merely by reducing exposure. Inspect trade counts and expectancy as well as return; zero trades is not evidence of an edge.

## Completed results

Frozen-input comparison IDs: March `e9723b9dbb6f`; August/September `aeb6eab8c0cf`. All fourteen trials are retained in the dashboard.

| Trial | March return | March trades | Aug/Sep return | Aug/Sep trades |
|---|---:|---:|---:|---:|
| Baseline replay | -5.1040% | 54 | -1.0548% | 21 |
| Hourly control | -2.7755% | 34 | -0.5955% | 17 |
| Hourly + VWAP | -2.2892% | 32 | -0.5955% | 17 |
| Hourly + 0.1 ATR buffer | -0.9464% | 19 | -0.4188% | 14 |
| Hourly + close in trend-side 30% | -1.4501% | 25 | -0.5955% | 17 |
| Hourly + directional body >= 0.1 ATR | -2.4605% | 32 | -0.5955% | 17 |
| Stronger hourly confirmation | -1.2620% | 17 | -0.4356% | 12 |

All variants remain negative in both windows. The combined filters reduce loss and activity relative to the original control, but hourly + buffer alone has better net return than the combined variant in both windows. The combined March trial also has negative expectancy (-0.3639 R), not merely a smaller total loss. Additional filters cannot be described as a proven improvement in edge.

Carry forward hourly + 0.1 ATR buffer as the simpler research candidate alongside the full-quality variant, preserving the original control. No default changes or live/paper enablement follow from these short samples. Tests do not include hourly EMA/ADX context, verified catalysts, broader stock selection or calibrated broker fills.

For the TCS 30 March 10:15 signal, the completed-hour open/high/low/close were 2375.10 / 2398.00 / 2355.00 / 2379.80. The new long buffer requires a close above 2384.46; VWAP was 2383.06; close position was 57.67% versus the required 70%; directional body was 0.0802 ATR versus 0.1. All four gates fail. No TCS trade was taken that day by the combined variant. This is a retrospective explanation of that recorded example, not the basis for optimizing thresholds.
