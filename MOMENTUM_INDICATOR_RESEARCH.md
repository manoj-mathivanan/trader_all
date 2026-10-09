# Momentum indicator loop — declared 8 October 2026

Existing opening-range variants have no reliable positive after-cost result. The March 2026 and August–September 2026 windows are already inspected; results from them are development diagnostics, not independent validation.

## Primary-source research

- [Ross Cameron's MACD video](https://www.youtube.com/watch?v=mfGQr2tHoX0) was located through web search. Accessible video metadata does not provide a full transcript; this research does not claim to have watched or reproduced every rule.
- [Warrior Trading's own indicator documentation](https://support.warriortrading.com/support/solutions/articles/19000141884-4-chart-indicators-wt) lists 9/20 EMAs and MACD. It motivates explicit trend/momentum hypotheses; the particular filters below are our adaptations, not a verified Cameron system.
- [SMB's Fashionably Late Scalp rules](https://www.smbtraining.com/blog/wp-content/uploads/2024/04/The-Fashionably-Late-Scalp-Cheat-Sheet.pdf) describe a rising EMA9 crossing VWAP with measured-move risk/target rules. This is a different entry setup, worth a separate experiment. Its advertised success figures are not evidence for NSE returns.
- [StockCharts MACD histogram documentation](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/macd-histogram) supplies the indicator definition: EMA12 minus EMA26, signal EMA9 of MACD, histogram MACD minus signal.

## Fixed experiments before results

Seven trials: original control; 10-minute confirmation with 0.1 prior-ATR buffer; that control plus EMA9/20; plus MACD; plus both; hourly buffered control; hourly control plus EMA9/20. All other selection, stops, sizing, cutoff, and cost assumptions stay inherited from the reference. Run the suite on original baseline references to avoid inheriting unrelated tuned fields.

EMA gate for long: completed candle close above EMA9, EMA9 above EMA20, EMA9 rising from its previous completed candle. Reverse every inequality for shorts. MACD gate: directional MACD, directional positive histogram, and histogram increasing in the trade direction. The two-filter trial requires both gates.

Aggregate cached five-minute OHLC into bins aligned to 09:15 IST, separately per session. Only full bins update the indicator; incomplete bins cannot signal. Carry EMA state across regular sessions, with SMA seeds and at least 60 prior candles for EMA or 100 for MACD. Warmup uses the existing prior opening-volume sessions, bars through 15:00, dropping terminal partial bins. This deliberately omits the final half hour from warmup; do not compare directly with broker charts using full-session inputs. Price-basis verification for corporate-action crossings is required, so these trials halt rather than infer adjustment factors. Entry remains next five-minute open and stops remain five-minute; indicator and confirmation timeframes are separate.

## Validation criteria and next windows

Before viewing new-period minute results: test February 2025, then May 2025 and November 2025, subject to source coverage and daily data audit. Keep every trial including operational or data-quality failures. New periods become research data once inspected; reserve another untouched period for any selected candidate. Start with the same prior-turnover top-50 scan to isolate indicators; broaden selection separately.

A candidate is eligible for further validation only if net return is positive in each of at least three additional windows, aggregate trades number at least 100, no window's session-end drawdown exceeds 5%, and aggregate net return stays positive with 50% higher assumed charges and slippage. These are screening thresholds, not statistical proof. Fewer trades, mixed periods, or failure after costs means no good indicator yet. Do not optimize these thresholds after seeing results. An eligible candidate still needs an untouched final period, liquidity/fill checks, and paper observation before deployment.

No strategy is promoted automatically and no live orders are authorized.

## Audit log and additional windows

May 2025 halted before minute testing: SIEMENS's 7 April 2025 discontinuity is in the daily warmup. [NSE's official circular](https://nsearchives.nseindia.com/content/circulars/FAOP67393.pdf) confirms a demerger on that date. A demerger is not a simple share split; this code does not invent a price adjustment. November 2025 halted for TMPV's 14 October 2025 discontinuity. Both blocked windows remain in the research log and do not count as successful tests.

Before inspecting their minute returns, add June 2025 (2–30 June) and January 2026 (2–30 January) as further windows using the same seven declared trials and assumptions. Their daily audits pass. The initial February 2025 control downloaded 1,895 missing stock-sessions, reused five, and returned approximately −4.06% after costs over 53 trades. Every indicator variant in February also loses money; the hourly EMA variant returns approximately −0.99% over 14 trades. No candidate passes the screening gate.

March comparison: `497e425172e6`. February comparison: `2560dd357cdd`. Full precision, individual run IDs, frozen data, and all trial metrics are saved in the dashboard's local reports.

## Next loop: fixed pullback setup

Declared before any pullback results: seven trials on the original February, June and January controls. Original replay; 10-minute buffered control; flag with ATR stop; flag with pullback-extreme stop; flag with pullback stop and 2R target; the latter plus EMA; the latter with opening relative volume >=2. Same costs, stock-selection framework, cutoff, capital and frozen data throughout.

[Cameron's published momentum discussion](https://www.warriortrading.com/momentum-day-trading-strategy/) describes a directional move, a short pullback, then renewed buying, with the pullback low as a stop. Our mechanical India adaptation requires a completed directional impulse body >=0.25 prior ATR, exactly two adverse candles with declining directional closes, a pullback retracement <=50% of the impulse body, and a directional resumption close beyond both pullback candles and the buffered opening range. Mirror for shorts. These numeric definitions are our research choices; the US float/news/small-cap selection is not reproduced. Optional pullback stops are known at signal close and risk sizing uses the actual next-open slipped fill-to-stop distance; a gap leaving nonpositive risk distance cancels entry.

These windows have already been inspected for other strategies. Pullback results are exploratory too; they cannot become an untouched final validation merely because this pattern is new.

## Results of these two loops

All 28 indicator trial runs lose after the modeled costs across March 2026, February 2025, June 2025 and January 2026. The three newly downloaded windows reused existing cached inputs and fetched 1,895, 1,964 and 1,865 missing stock-sessions respectively (5,724 total). The seven-rule suite always uses matching inputs within each window.

| Rule | March 2026 | February 2025 | June 2025 | January 2026 |
|---|---:|---:|---:|---:|
| Original control | −5.10% | −4.06% | −5.72% | −3.62% |
| 10-minute buffered control | −2.91% | −3.50% | −2.68% | −1.65% |
| 10-minute EMA9/20 | −1.88% | −2.61% | −2.10% | −1.54% |
| 10-minute MACD | −1.26% | −2.49% | −2.38% | −1.64% |
| 10-minute EMA + MACD | −1.26% | −2.49% | −2.38% | −1.64% |
| Hourly buffered control | −0.95% | −1.86% | −2.38% | −3.32% |
| Hourly EMA9/20 | −0.46% | −0.99% | −1.35% | −3.33% |

The 10-minute EMA variant totals 125 trades and −₹81,371.77 net across the four independent capital resets; its before-cost attribution is still −₹6,717.41. The MACD variant totals 109 trades and −₹77,687.58 net, with −₹12,088.63 before-cost attribution. The hourly EMA variant totals 65 trades and −₹61,218.78 net, with −₹21,728.04 before-cost attribution. Adding independent-window rupee P&L is a diagnostic, not a compounded portfolio simulation. The negative aggregate before-cost attribution means assumed charges alone do not explain these losses; it is not a zero-cost rerun.

All five active flag variants make zero trades in each of February, June and January. Thus the 21 pullback-suite runs consist of six losing control replays and fifteen zero-trade trials. Zero trades is insufficient evidence. Rejection-funnel replays retain the same signal logic and save separate diagnostics: most candidate candles fail the fixed impulse threshold (177 February, 157 June, 215 January); others fail two adverse candles or have insufficient completed current-session candles. Counts are evaluated candidate candles, not distinct stocks or independent trades.

Pullback comparisons: `36fd1389ee15`, `80caf606e4a8`, `ca6498746fc0`. The first CLI briefly showed interrupted after another dashboard process restarted; its worker finished and all seven reports were saved successfully. The CLI now waits for its actual worker rather than trusting a transient persisted interruption marker.

Next declared experiment: expand the prior-turnover scan from 50 to 200 stocks on the same three additional windows, then repeat the fixed suites on each new frozen reference. This tests selection coverage separately; it does not relax the impulse threshold to manufacture trades. A distinct EMA/VWAP crossover setup remains a separate research direction. No candidate has passed the validation gate or been promoted.
