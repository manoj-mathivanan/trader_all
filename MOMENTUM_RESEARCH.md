# Intraday momentum baseline

Implemented 8 October 2026. This is research on NSE cash equities, with real Upstox five-minute history. Momentum paper/streaming/live execution remains pending.

## Research comparison

There is no defensible universal “best” momentum strategy across markets, time horizons and costs. The first choice is a transparent, testable baseline suitable for this project's intraday strategy slot.

| Candidate | Evidence and fit | Decision |
|---|---|---|
| Opening-range breakout with stocks-in-play relative volume | [Zarattini, Barbon and Aziz's original paper](https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf) studies US stocks and compares ordinary ORB against volume-selected ORB. The stock-selection/volume filter matters materially. | Implement an India adaptation, then validate locally. Published returns do not transfer to this universe. |
| Practical ORB replication | [QuantConnect's own implementation](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/p1) provides explicit same-opening-interval relative volume, prior ATR, rank selection and capital limits. | Reusable baseline structure, with conservative completed-close/next-open entries. |
| Time-series momentum | [AQR's original research](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum) supports longer-horizon own-return momentum across futures/forwards. | Useful research alternative; does not directly establish an intraday NSE equity strategy. |
| Data capability | [Upstox V3 historical documentation](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/) specifies minute history from January 2022 and one-month retrieval limits for intervals of 1–15 minutes. | Shared five-minute session cache; missing downloads batched into at most 28 calendar days. |

## Deterministic rules

The broader [momentum research review](MOMENTUM_DEEP_RESEARCH.md) compares twelve research/practitioner approaches and records further experiments. Opening ranges now include 10 minutes. Completed breakout confirmation has its own 5/10/15/30/60-minute control, aligned to 09:15 IST; five-minute fills and protective exits remain in effect. Defaults stay at five minutes. Hourly confirmation is not an hourly EMA/ADX trend filter.

1. Use prior-session mean rupee turnover to pick up to 50 liquid stocks daily from the selected current constituent universe. Require at least ₹5 crore average turnover and a prior arithmetic-mean 14-session true range of at least 1% of prior close. Daily-history coverage and listing evidence remain validated through the existing preparation pipeline.
2. Observe a completed 5-minute opening range starting at 09:15 IST (15/30 minutes are configurable). Divide opening volume by the average volume in the same interval over the preceding 14 observed sessions. Verified special sessions cannot substitute for regular openings. Explicit raw-volume corporate actions rebase earlier volume into the current share units.
3. Require relative volume at least 1.5 by default. Select at most five stocks by descending opening relative volume, with symbol as the tie-breaker. A positive opening candle qualifies for longs; a negative candle qualifies for shorts; a flat opening candle does not qualify. Direction is configurable.
4. After the opening range, require a completed five-minute close strictly above the opening high for longs or below the opening low for shorts. Enter at the next five-minute bar open, no later than 11:30 IST. One trade per selected stock/session, with no replacement stock or re-entry. This differs from the source paper's stop-market entry; it resolves entry/stop ordering at the cost of delayed entries.
5. Default stop distance is 0.5 prior daily ATR from the slipped execution price. Optional target is a configured multiple of initial price-stop risk; default zero means stop/cutoff only. Gaps through a stop fill at the adverse bar open. When stop and target appear in the same candle, assume stop first. No intrabar trail or implied tick ordering.
6. Risk budget defaults to 0.25% of session-opening equity per trade, including modeled costs in sizing. Each selected stock receives at most one fifth of opening equity including entry fees; unused budgets are not redistributed. Shorts reserve full notional plus entry fees. No leverage or same-day capital recycling. P&L and two-sided fees/slippage reconcile to session-end cash.
7. Exit at the open of the 15:00 IST candle unless stopped/targeted earlier. Cutoff high/low/close cannot change the exit. All trades close the same day. Stop/target timestamps identify five-minute intervals, not exact tick times.

The model, thresholds, ATR definition, close confirmation, India timings and rupee filters are documented research choices. They have not been optimized to maximize this sample's returns. Fees and slippage are configurable aggregate estimates rather than a verified brokerage/tax schedule.

## Dashboard and reproducibility

The **Momentum** view has a schema-driven form, coverage estimate, automatic missing-data fetch, experiment list, report exports and Adjust & rerun. Shared report charts read frozen five-minute candles and show execution markers at the recorded intraday timestamps. Daily volume rankings/selections are retained in each report's `selections` list.

Inputs remain under ignored `data/`: daily input snapshot, minute snapshot, universe membership, prepared daily manifest and hashes, minute snapshot hash, configuration, source-tree provenance, complete trade ledger and equity curve. Downloads retain no token in cache or report. Missing/incomplete expected intraday sessions halt the experiment; no daily or synthetic price substitute is used.

The CLI `scripts/run_momentum.py --config <local JSON file>` submits the same tracked job as the dashboard, within the common one-job-at-a-time rule.

## First real-data backtest

Run ID: `ebef4eacf96f`. Dates: **26 August–4 September 2026**, eight observed sessions. Universe: current Nifty 500, 499 symbols with sufficient daily warmup and 50 selected daily by prior turnover. One symbol was excluded for daily warmup. The run needed 1,289 stock-sessions including volume context; 33 were already cached and 1,256 were downloaded in 103 batches.

| Measure | Result |
|---|---:|
| Starting capital | ₹10,00,000 |
| Final equity | ₹9,89,451.85 |
| Net P&L | −₹10,548.15 |
| Net return | −1.0548% |
| Maximum session-end drawdown | 1.7382% |
| Trades | 21 (12 long / 9 short) |
| Win rate | 38.0952% |
| Expectancy | −0.2802 R |
| Profit factor | 0.5460 |
| Modeled fees | ₹6,665.77 |
| Modeled slippage impact | ₹6,665.78 |
| Overnight positions | 0 |

Parameters were the documented defaults: 5-minute range, relative volume ≥1.5, 0.5 ATR stop, no target, 0.25% risk per trade, five stocks, 10 bps slippage and 10 bps buy/sell charges each. This short sample checks ingestion, execution and report wiring. It neither proves nor rejects a durable edge. Its annualized Sharpe is too unstable to use for strategy selection.

A proposed September-through-1-October window failed the data diagnostic because **HEGAM on 7 September 2026** had an unresolved −64.30% daily-open discontinuity versus its previous close. The initial run ends before that event; prices were not repaired or silently replaced. Later windows need verified event/provider adjustment evidence before proceeding.

## Validation and next research gate

### Refinement comparison — 8 October 2026

The dashboard now shows cost attribution, long/short breakdowns, signal rejections, and an earlier/later chronological diagnostic. The form groups experiment, selection, entry/protection and cost controls with explanations. Optional refinements are **VWAP confirmation**, a **prior-ATR breakout buffer**, and a **cost breakeven stop activated after a completed close reaches the chosen R threshold**. They default to disabled. VWAP is approximated from cumulative five-minute typical-price × volume; it is not tick VWAP. This is an ORB research adaptation, informed by the authors' [additional intraday momentum/VWAP research](https://concretumgroup.com/wp-content/uploads/2026/02/Beat-the-Market.pdf), not a reproduction of that SPY strategy.

**Compare refinements** runs six predeclared trials on a saved run's frozen daily/minute/universe inputs, preserving its capital and cost assumptions. Frozen hashes, date bounds and warmup are checked. Missing required frozen sessions halt comparison; no current-cache replacement or download is permitted. Adjust & rerun also uses the reference snapshot. All trials are saved; no default changes or automatic winner selection occur.

Comparison ID `84e4b600e868`, reference `ebef4eacf96f`, same 26 August–4 September 2026 dates:

| Trial | Net return | Max drawdown | Trades | Earlier 5 sessions | Later 3 sessions |
|---|---:|---:|---:|---:|---:|
| Baseline replay | −1.0548% | 1.7382% | 21 | +0.1470% | −1.2000% |
| VWAP confirmation | −1.0548% | 1.7382% | 21 | +0.1470% | −1.2000% |
| VWAP + 0.1 ATR buffer | −0.5560% | 1.1407% | 18 | +0.4857% | −1.0366% |
| VWAP + breakeven at 1R | −1.0548% | 1.7382% | 21 | +0.1470% | −1.2000% |
| VWAP + 0.75 ATR stop | −0.6953% | 1.2123% | 21 | +0.2218% | −0.9151% |
| VWAP + 2R target | −0.8666% | 1.5563% | 21 | +0.0781% | −0.9439% |

The buffer reduces losses and drawdown on this sample; all trials remain negative overall and in the later segment. The earlier/later split uses an already known sample and is a diagnostic, **not an untouched holdout**. Before-cost attribution adds recorded fee/slippage impact back to actual net P&L; it is not a separate zero-cost simulation, since costs also affect sizing and protective stops.

Focused tests cover completed-bar timing, long/short exits, adverse gaps, conservative stop/target ambiguity, cutoff future-price exclusion, no future daily selection data, reserved capital, fee reconciliation, missing-history failure, cache reuse and batch downloads, report chart levels, UI routing and intraday markers. Existing Swing/paper tests remain intact.

Next: resolve the HEGAM discontinuity with source evidence, extend to multiple market regimes with historical membership where available, and reserve untouched later dates. Compare long/short components, opening ranges, relative-volume filters and cost sensitivities using fixed predeclared experiments. Report all trials rather than choose a flattering historical curve. Circuit limits, short-sale eligibility, participation, real broker fills, exchange calendars and intraday drawdown still need validation before paper/live decisions.
