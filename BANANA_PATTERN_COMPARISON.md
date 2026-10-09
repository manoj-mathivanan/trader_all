# Banana Patterns versus our breakout signals

Checked 8 October 2026. This is a read-only comparison; no screen settings,
paper checkpoints, data caches or orders were changed.

## Scope and evidence

Compare the production Swing paper portfolio's actual custom **Blue sky**
configuration with Banana Patterns' built-in **Blue sky** screen. The Banana
screen was inspected in the signed-in browser at https://bananapatterns.com/screens,
showing Updated EOD 07/10/2026. Its Fresh breakouts view was filtered by breakout
day to 1 and 5 October. These are the signal dates for our processed next-open
paper sessions of 5 and 6 October respectively.

Important limitation: Banana's list is its 7 October stage classification filtered
by historical breakout date, not an archived screen captured on 1 or 5 October.
Stocks may since have changed stage or failed. The comparison proves different
displayed selections and explains concrete local rejections; it is not a measured
historical recall rate or complete parity audit of all four screens.

Production cached eligible daily history ended on 6 October. An empty local result
for 7 October would mean missing input, not a completed scan with no signals.
No new provider fetch or paper cycle was submitted for this investigation.

## Observed selections

Our results below are raw pattern matches, before breadth, account sizing and
position limits. They were recomputed read-only inside the deployed container from
the portfolio's frozen Nifty 500 membership, listing-filtered cached history and
corporate-action-adjusted context as of each signal date.

| Signal date | Banana Blue sky Fresh list, viewed 7 October | Our custom Blue sky matches |
| --- | --- | --- |
| 1 October | D.P. Abhushan (DPABHUSHAN), Ram Ratna Wires (RAMRAT) | STLTECH, WELSPUNLIV |
| 5 October | Aditya Infotech, Marine Electricals, India Homes, TD Power Systems, Precision Wires India, Shukra Pharmaceuticals, Jaykay Enterprises, One Point One Solutions, Leela Palaces Hotels & Resorts | LGEINDIA, STLTECH |

There was no overlap in these displayed date-filtered lists. Both names on
1 October are outside our portfolio universe. On 5 October only Aditya Infotech
(CPPLUS) and TD Power Systems (TDPOWERSYS) belong to the portfolio's eligible
membership; the remaining seven names are outside it.

The two in-universe discrepancies have specific local causes:

| Stock, 5 October | Our close | Prior loaded-history intraday high | Volume / prior 50-session average | Local rejection |
| --- | ---: | ---: | ---: | --- |
| CPPLUS | 3,989.50 | 4,094.00 | 1.01 | Close does not exceed prior high |
| TDPOWERSYS | 812.90 | 817.55 | 4.17 | Close does not exceed prior high |

Both passed our trend/liquidity predicate and volume threshold. Banana listed
both as base-pivot breakouts. Thus universe differences alone cannot explain the
mismatch: our breakout threshold also differs.

Our other raw matches were CUPID on 30 September, and AETHER, BHEL and STLTECH
on 6 October. These are research signals, not new committed paper orders.

## Rules that differ

1. **Universe.** Banana covers liquid NSE and BSE stocks. Its current Blue sky
   drawer showed market cap at least 300 crore and median turnover at least
   1 crore/day. Our portfolio uses frozen Nifty 500 membership, no market-cap
   predicate and a minimum of 5 crore/day calculated as the prior 50-session
   mean of close times volume. Mean versus median and NSE-only versus combined
   exchange turnover are different measurements. Older Banana guides still
   mention a 500 crore / 5 crore floor; use dated observed settings rather than
   assuming those guides describe today's defaults.
2. **Breakout threshold and base identity.** Banana describes its pivot as a
   base's highest close, tracks bases and assigns stages. Its live Blue sky
   preset showed Structure level at most L1 and pre-breakout position between
   20% below the pivot and the pivot. Our `blue_sky` predicate requires today's
   close strictly above the highest prior intraday high within up to 5,000
   loaded sessions. It does not identify a proper base or its lifecycle. A close
   above a base pivot can remain below an older intraday wick, as the two local
   rejection examples demonstrate. Conversely a new high on several consecutive
   days can qualify repeatedly locally rather than represent one tracked base
   breakout. Limited loaded history is not proof of a lifetime all-time high.
3. **Relative strength.** Banana's observed preset requires RS at least 70.
   The paper portfolio has `min_rs_rating=0`, disabling this filter. Our optional
   RS implementation ranks 126-session price returns in the run's eligible
   universe; equivalence to Banana's RS recipe is unverified.
4. **Volume.** Our active rule requires signal volume at least 1x the prior
   50-session mean. Banana's displayed breakout-volume measure is relative to
   the prior 20-session median. Its Blue sky drawer had volume dry-up unrestricted;
   a displayed volume statistic is not by itself proof of a mandatory entry
   threshold. Do not invent an unobserved Banana volume gate.
5. **Dates, stages and execution.** A Fresh list includes up to five sessions;
   a raw local scan evaluates one signal day. Paper fills at the next session
   open, starts 5 October and advances only through unprocessed completed sessions.
   A screen match is not automatically an account fill. The old breadth gate
   blocked our four candidates for the two processed paper sessions. It is now
   disabled and applies to subsequent sessions, without replaying skipped ones.
6. **Data.** Banana identifies NSE/BSE and Accord as its feeds; ours uses Upstox
   daily candles plus explicit sourced listing/corporate-action reconciliation.
   Adjustment conventions and history coverage can change pivots. No full
   cross-provider candle reconciliation was performed, so data differences are
   a possible additional cause, not a demonstrated explanation for every name.

VCP is also an approximation: our predicate uses three fixed windows with
strictly falling high-low ranges and mean volumes. Banana's published anatomy
uses a detected base and an ATR contraction ratio between its halves. Identical
screen names do not establish equivalent algorithms. Multi-year and IPO screens
also lack verified reference-site parity; they were not stock-list audited here.

## Implication and next comparison

Our current screen names describe inspiration, not reproduced Banana outputs.
Changing only the weak-market setting cannot make the selections match. A fuller
comparison needs a chosen reference preset, the same universe and completed
signal dates, archived stage lists including failures, and documented base/pivot,
RS, liquidity and adjustment definitions. Record candidate-level rejection reasons
before comparing account trades. Any base-detector change would materially change
the research strategy and requires fresh backtests; do not silently rewrite the
running portfolio or historical ledger to force agreement.

Sources: [live screens](https://bananapatterns.com/screens),
[Blue sky guide](https://bananapatterns.com/learn/blue-sky-breakout-pattern),
[method](https://bananapatterns.com/how-it-works),
[site and pivot definition](https://bananapatterns.com/).
Local source: `strategies/swing_patterns/patterns/signals.py`,
`core/portfolio/paper.py`, and the deployed portfolio's configuration/cycle snapshots.
