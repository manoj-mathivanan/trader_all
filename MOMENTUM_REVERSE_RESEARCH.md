# Reversed intraday momentum experiment

Original net return **-50.356%**; reversed net return **-54.422%**. Difference: -4.066 percentage points. These are reduced-universe, modeled-cost results.

Requested window: **2024-10-08–2026-10-07**. Observed sessions: 496, 2024-10-08–2026-10-07.

Original signals, opening-volume ranking and next-bar entry timing are preserved. Reverse execution shorts buy signals and buys sell signals. Protective stops/targets use the actual position direction. Fees and adverse slippage are recalculated; this is not a sign flip of old P&L.

Universe: current nifty500; 444 eligible daily symbols. Explicit event exclusions: HEGAM, SIEMENS, TMPV, VEDL. The unfiltered attempt failed its price-gap audit (job `77fdb4d0c2a5`); these four exclusions apply to both runs before liquidity ranking. Another 52 symbols lacked eligible daily inputs. This reduced-universe result does not establish the full-universe result.

Control `836c4463d21b`; reverse `84ac8b96d58b`. Daily manifests, minute snapshot hashes, costs and all configuration fields except name/execution mode/reference are identical.

Regular-opening candle exclusions: ITC:2025-01-06, HINDUNILVR:2025-12-05. Both runs skip these stock-sessions and any candidate whose opening-volume history uses them; the rest of each stock’s history remains eligible.

Matched entries: 1316; control-only: 0; reverse-only: 0.

| Measure | Original | Reversed |
|---|---:|---:|
| Starting capital (INR) | 1,000,000.00 | 1,000,000.00 |
| Final equity (INR) | 496,441.40 | 455,782.83 |
| Net return (%) | -50.356 | -54.422 |
| Maximum session-end drawdown (%) | 51.725 | 54.422 |
| Trades | 1,316 | 1,316 |
| Win rate (%) | 35.71 | 33.13 |
| Profit factor | 0.546 | 0.476 |
| Expectancy (R) | -0.285 | -0.314 |
| Modeled fees (INR) | 289,457.72 | 256,036.83 |
| Modeled slippage (INR) | 289,457.79 | 256,036.80 |

| Calendar portion | Original return | Reversed return | Original / reversed trades |
|---|---:|---:|---:|
| 2024 | +0.286% | -9.126% | 125 / 125 |
| 2025 | -32.328% | -32.484% | 667 / 667 |
| 2026 | -26.850% | -25.713% | 524 / 524 |

![Matched equity curves](artifacts/momentum_reversal_equity.png)

Cost attribution on actual trades: P&L with modeled fees/slippage added back is INR 75,356.91 for the original and INR -32,143.55 for the reversed strategy. This adds costs back to recorded fills, not a separate zero-cost backtest; costs also influence sizing and stops.

Parameters: five-minute opening range/confirmation; relative opening volume ≥1.5; top 50 prior-turnover stocks; up to five positions; 0.25% risk; 0.5 ATR stop; no profit target; last entry 11:30; square-off 15:00 IST. Starting capital INR 1,000,000. Slippage 10 bps each side; buy and sell charges 10 bps each.

Special sessions are omitted from normal-clock momentum eligibility, including any candidate whose 14-session opening-volume context contains one. Added 1 November 2024 Muhurat timing from [NSE circular CMTR64628](https://nsearchives.nseindia.com/content/circulars/CMTR64628.pdf); the existing 21 October 2025 special-session policy also applies. These days remain in the equity calendar with zero trading activity where ineligible.

Exploratory results: current constituents and retrospective exclusions introduce bias; corporate-action checks remain incomplete. Costs are assumptions, short eligibility/circuits/participation are unverified, and drawdown is measured at session ends. The entire historical window is exploratory. Defaults and live/paper behavior remain unchanged.

Reproduce the report: `.venv/Scripts/python.exe scripts/report_momentum_reversal.py 836c4463d21b 84ac8b96d58b`.
