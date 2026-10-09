# Intraday momentum: research and experiment review

Research date: 8 October 2026. Scope: improve the existing NSE equity opening-range strategy. Practitioner descriptions are hypotheses; empirical papers establish results only for their own data and execution assumptions. This review uses authors' papers, their own websites and first-person interviews, rather than treating social-media popularity as evidence.

## Assessment

Our implementation has useful safeguards: same-clock relative volume, prior-session liquidity/ATR, completed-bar signals, conservative fills, costs, frozen inputs and compulsory intraday exits. It has not demonstrated a profitable edge. Its principal research gaps are stock selection beyond the top 50 by turnover, event context, higher-timeframe context, and execution realism. Adding more indicators alone does not resolve those gaps.

The earlier eight-session experiment lost 1.0548%; a 0.1 ATR buffer reduced that to a 0.5560% loss. VWAP entry confirmation made no difference. These observations motivate investigation, not a new default.

## Ideas from researchers and practitioners

| People / source | What the source actually proposes or finds | What it means for ours |
|---|---|---|
| Carlo Zarattini, Andrea Barbon, Andrew Aziz — [original ORB paper](https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf) | US stock ORB research, 2016–2023, uses opening direction, stop entries and relative opening volume. Ordinary ORB is substantially weaker than volume-selected stocks in play. The paper includes delisted stocks. Its illustrated protective distance is 0.1 daily ATR. | Our 0.5 ATR stop, completed-close entry, current constituents and narrow liquid scan are material departures. Test selection and timing; do not call ours a reproduction or transplant US returns. Copying the tight stop under our costs could be especially harmful. |
| Derek Melchin / QuantConnect — [replication and code](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/p1) | Uses 1,000 liquid stocks and the top 20 by relative opening volume. Examines opening durations and ATR thresholds; its displayed backtest covers 2016. | Our top-50 prefilter may remove the very unusual stocks the method seeks. A broader scan needs additional frozen minute data. This replication shares the original hypothesis; it is not wholly independent evidence for India. |
| Ross Cameron — [Warrior Trading's own rules](https://www.warriortrading.com/momentum-day-trading-strategy/) | Emphasizes elevated relative volume, low float, strong daily structure, catalysts, bull flags/flat-top breaks, defined stops and partial profit-taking. | Relative volume thresholds are immediately testable. Historical float and time-stamped news are missing. US small-cap and premarket rules cannot be assumed to fit liquid NSE stocks; partial exits require separate accounting and execution tests. |
| Mike Bellafiore — [SMB first-person momentum example](https://www.smbtraining.com/blog/i-see-momentum-buying) | Describes aggressive buying on a news day and why an unusual stock can offer intraday and later opportunities. The description relies on observing offers and the tape. | Five-minute volume is only a proxy for participation. OHLCV cannot reconstruct aggressive buyers, order-book absorption or liquidity at the offer. Keep such claims outside our simulated signal until appropriate data exists. |
| Kristjan Kullamägi, crediting Pradeep Bonde — [episodic pivots](https://qullamaggie.com/how-to-master-a-setup-episodic-pivots/) | Describes large gaps, exceptional early volume, a surprising catalyst and opening-range-high entries. He discusses different opening durations, daily-low stops and stocks quiet for several months. | Catalyst continuation is a distinct hypothesis. A gap is not proof of news; a retrospective winner gallery is not an unbiased backtest. Intraday forced exits capture only part of the multiday repricing thesis. Need point-in-time event and earnings data. |
| Brian Shannon — [multiple-timeframe guidance](https://alphatrends.net/market-structure-chart-thank-you/) and [VWAP/pullback interview](https://alphatrends.net/archives/podcast/secrets-from-30-years-of-day-trading-trader-interview-08-06-23/) | Uses broader market structure for context, shorter charts for entries, and VWAP/anchored VWAP around meaningful price events. His timeframe guidance distinguishes context, risk assessment and execution. | Supports testing 10-minute signals with hourly context, not a mandatory timeframe. Event anchors must be selected using information available at entry; choosing a future low as the anchor creates look-ahead. Session VWAP confirmation alone is already redundant on our initial sample. |
| Linda Bradford Raschke — [first-person Active Trader interview](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf) | Describes trend pullbacks to a 20-period EMA after strong momentum, with a 14-bar ADX above 30 on the relevant timeframe; discusses a sequence across 15-, 30-, 60- and 120-minute charts. | A trend-pullback strategy is different from entering the first opening breakout. ADX measures strength, not long/short direction. Requires warmed-up indicators and an explicit resumption trigger; use a separate strategy hypothesis rather than stacking every filter on ORB. |
| Lei Gao, Yufeng Han, Sophia Zhengzi Li, Guofu Zhou — [author publication page and paper link](https://sites.google.com/site/szlwebpage/) | Market intraday momentum concerns prediction of the last half-hour from the return measured from the previous close through the first half-hour. | Overnight and opening returns must remain separate in any implementation. This is a market-level late-session strategy, not evidence that the first five-minute stock breakout works. Our 15:00 cutoff prevents testing the NSE final half-hour. |
| Guido Baltussen, Zhi Da, Sten Lammers, Martin Martens — [published author-hosted paper](https://academicweb.nd.edu/~zda/intramom.pdf) | Across more than 60 futures, 1974–2020, the return from the previous close up to the final half-hour predicts that half-hour. It generally outperforms the early-return predictor and links the effect to hedging demand. | A late-session index strategy deserves its own experiment. Individual equities, NSE closing arrangements, product choice and fees differ. Do not infer an option-dealer gamma state from equity candles. |
| Steven Heston, Robert Korajczyk, Ronnie Sadka — [intraday cross-sectional patterns](https://arxiv.org/abs/1005.3535) | Finds same-clock half-hour return continuation across days alongside reversals over intervals shorter than an hour. | Supports accounting for clock time and cautions against assuming every short-term price rise persists. Same-clock historical return ranking differs from today's ORB and today's relative volume. |
| Tobias Moskowitz, Yao Hua Ooi, Lasse Pedersen — [AQR original research](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum) | Own-return momentum across futures/forwards at longer horizons differs from cross-sectional stock momentum. | Useful context, but a monthly trend result does not validate intraday RSI, ROC or MACD. Match each indicator's horizon to the return horizon being predicted. |
| David Bailey, Jonathan Borwein, Marcos López de Prado, Qiji Zhu — [backtest-overfitting paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) | Selecting among many historical trials creates selection bias; a holdout alone does not account for how many configurations were tried. | Declare the trials, keep failures and count repeated tests. Neither eight sessions nor one additional month supports reliable Sharpe-based model selection. |

These sources converge on a useful hypothesis: unusual participation plus a coherent trend/catalyst can matter more than the name of an oscillator. They do not establish a universally best momentum strategy.

## The 10-minute and hourly candle question

Three concepts need separate controls:

1. **Opening range:** the first 5/10/15/30 minutes determines the initial high, low, direction and relative-volume interval.
2. **Signal confirmation:** a completed 5/10/15/30/60-minute close confirms a break of that range. Larger candles can reject short spikes but enter later and give up movement. This is now implemented independently of the opening range.
3. **Trend context:** for example, the last completed hourly close relative to a warmed-up hourly EMA, its slope, or ADX plus directional confirmation. This remains a research proposal, not an implemented EMA/ADX filter.

We can derive larger OHLCV candles from complete five-minute inputs: first open, maximum high, minimum low, final close, summed volume. Volume-weighted measures should retain their original five-minute calculation rather than change solely because the display timeframe changes. [Upstox's V3 documentation](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/) also supports minute/hour intervals; local aggregation gives comparisons a common input source and avoids unnecessary downloads.

Session alignment is explicit: a 10-minute candle starts 09:15 and closes 09:25; an hourly candle starts 09:15 and closes 10:15. Neither is usable before its close. Our confirmation implementation checks the final five-minute constituent at those boundaries and fills at the next five-minute open. It retains five-minute stop/target handling throughout. It does not use the eventual high/low of an unfinished hour.

A 20-bar hourly EMA needs prior sessions; twenty five-minute bars are a different horizon. Define whether shortened final-session candles are included, how missing/special sessions are handled and how much initialization history is required. Until that is implemented and tested, hourly breakout confirmation must not be described as hourly trend confirmation.

## Experiments declared before reviewing new trial outcomes

Twelve one-factor trials: baseline replay; 10-minute confirmation; hourly confirmation; 10-, 15- and 30-minute opening ranges; relative volume thresholds 2 and 3; last entry 10:00; long only; short only; 0.1 ATR breakout buffer. All preserve the reference capital, risk, universe, cost assumptions and frozen daily/minute inputs. There is no parameter grid or automatic best-configuration promotion.

The Momentum dashboard's **Research ideas** button runs this suite; **Compare refinements** retains the earlier six-trial suite. The CLI equivalent is:

```powershell
.venv\Scripts\python.exe scripts/run_momentum.py --compare <reference-id> --suite research
```

March 2026 was chosen as an additional calendar-month check after daily data passed the quality audit, before inspecting intraday returns. It is a separate exploratory period, not a statistically sufficient untouched holdout. Current Nifty 500 membership remains a survivorship limitation. The unresolved September 2026 HEGAM discontinuity is not silently patched or excluded to make a later test pass.

## Completed local results

Two frozen-input suites completed: `85ae3e8075b3` against March control `28d677c85493`, and `3781a3169343` against initial control `ebef4eacf96f`. All 24 trials are retained as dashboard reports. Requested March dates were 2–31 March 2026; the input contains 19 observed sessions, 2–30 March. The original window contains eight observed sessions, 26 August–4 September. No annualized performance claim is made.

| Trial | March net return | March drawdown | March trades | Aug/Sep net return | Aug/Sep trades |
|---|---:|---:|---:|---:|---:|
| Baseline replay | -5.1040% | 5.1040% | 54 | -1.0548% | 21 |
| 10-minute confirmation | -4.6059% | 4.6059% | 50 | -1.1040% | 21 |
| Hourly confirmation | -2.7755% | 2.7755% | 34 | -0.5955% | 17 |
| 10-minute opening range | -2.7584% | 3.1472% | 52 | -0.7702% | 24 |
| 15-minute opening range | -2.5789% | 2.5789% | 50 | -1.0089% | 21 |
| 30-minute opening range | -2.9235% | 2.9235% | 45 | -0.7668% | 15 |
| Opening relative volume >= 2 | -4.8319% | 4.8319% | 36 | -0.5605% | 16 |
| Opening relative volume >= 3 | -2.7804% | 2.7804% | 17 | +0.1494% | 8 |
| Entries through 10:00 | -4.3863% | 4.3863% | 45 | -1.2241% | 18 |
| Long only | -1.9760% | 1.9760% | 30 | -0.9738% | 18 |
| Short only | -3.8862% | 3.9482% | 44 | -1.3909% | 15 |
| 0.1 ATR breakout buffer | -3.7189% | 3.7189% | 43 | -0.5560% | 18 |

Every March variant is negative overall and in both chronological segments. Relative volume >=3 is positive in the eight-session window but negative in March: a concrete example of why we must not promote the best short-sample result. Ten-minute confirmation is slightly worse than baseline in the original window despite improving March. Hourly confirmation and the ATR buffer reduce losses in both windows, but have not demonstrated positive expectancy.

March control: 489 daily symbols eligible (11 excluded by preparation), at most 50 scanned daily. 1,917 stock-sessions were required including relative-volume context; 30 were reused and 1,887 missing sessions were fetched in 125 batches. Net P&L was -₹51,040.14; modeled fees plus slippage were ₹28,680.37. Adding their recorded impact back leaves -₹22,359.77. This is attribution on actual fills, not a separate zero-cost simulation. Costs matter, but removing them does not explain away the control loss.

Long-only/short-only trials reselect and rank candidates under the direction restriction; they are not simply sums of the baseline long/short ledger. Fewer trades also changes exposure. Compare expectancy, opportunity counts and drawdown alongside return, rather than interpreting a smaller loss as greater alpha.

The first comparison attempt (`47dc781a74ed`) failed on its second trial with the generic local-integrity error; its completed control remains recorded. Frozen hashes subsequently verified and the entire suite completed on retry. A server restart temporarily marked the March download job failed while its CLI worker continued; the worker ultimately saved a successful report. Neither operational interruption was hidden as a strategy result.

The two windows total only 27 observed sessions and use present-day constituents. They establish implementation behavior and reject a confident profitability claim; they do not establish the absence of an edge across all regimes. Full exchange-calendar completeness, intraday equity drawdown and executable short/circuit behavior remain unverified. Defaults remain unchanged.

## Priorities after these checks

| Priority | Proposed experiment | Required evidence/data | Decision rule |
|---|---|---|---|
| 1 | Wider eligible scan, then same-clock RV ranking | Minute warmup for the broader daily liquidity universe; historical constituents/delistings where available | Compare against the narrow scan on identical dates and costs. Check participation and concentration. |
| 2 | Ten-minute confirmation plus independent hourly trend context | Session-aligned hourly history, initialized EMA/ADX, missing-bar checks | Test each component separately before combinations. Verify all feature timestamps precede entry. |
| 3 | Catalyst/gap continuation | Historical announcement timestamps and earnings surprises; corporate-action verification | Separate verified catalysts from price-only gap proxies. Include failed events, not only winners. |
| 4 | Cost/stop and capacity gates | Broker charge model, spread/fill observations and interval volume | Reject economically too-small moves; retain conservative cost stresses. Lowering assumed costs is not a discovered signal edge. |
| 5 | Noise-band trend with completed-bar VWAP exits | Same-clock historical movements; explicit entry/exit cadence | A separate Concretum-style strategy, not simply another ORB checkbox. Their [SPY paper](https://concretumgroup.com/wp-content/uploads/2026/02/Beat-the-Market.pdf) uses time-varying bands, half-hour decisions and different sizing, including leverage in its final version. |
| 6 | Final-half-hour market momentum | Tradable index/ETF/futures minute history, product costs, close/auction and cutoff rules | Separate signal research from executable returns. Do not extend equity short holding assumptions implicitly. |

Default strategy settings should change only after repeatable positive net expectancy across additional periods, tolerable drawdowns, realistic costs and operational validation. The minimum meaningful improvement is better evidence; fewer trades or a smaller historical loss alone does not establish a profitable strategy.
