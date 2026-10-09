# Scalping research

Scalping supports historical research and a separate forward paper portfolio.
Open **Scalping → Scalping backtest** for research.
Daily history supplies prior turnover selection; Upstox one-minute history supplies
signals and simulated fills. The existing five-minute cache remains separate.
**Forward scalping paper** uses completed candles for signals and fresh streamed
bid/ask quotes for simulated fills. Live broker orders are not implemented.

## First run

1. Fetch daily history in Market data and save a valid Upstox token in Settings.
2. Choose a short completed-session window, initially one week, and a small scan size.
3. Set capital, direction, entry confirmation and explicit costs.
4. Select **Check minute coverage** to estimate sessions and candles, including warmup.
5. Select **Fetch missing & backtest**. Inspect Jobs & logs, then open the report.
6. Select a trade to see its frozen one-minute candles, stop, target and indicator lines.
7. **Compare confirmations** runs candles only, EMA confirmation and EMA + VWAP
   on identical frozen candles and cost settings. Every success or failure is retained.
   **Adjust & rerun** also uses the selected run's frozen reference.

## Declared baseline

These are editable research hypotheses, not optimized settings or evidence of an edge.

| Component | Default and exact rule |
|---|---|
| Selection | Up to 20 stocks ranked by the previous 20 sessions' mean close × volume, at least ₹5 crore average turnover. Current universe membership remains survivorship biased. |
| Trend | Five-minute EMA9 above EMA20, fast EMA rising, completed five-minute close above the fast EMA for longs. Reverse all comparisons for shorts. |
| Warmup | SMA-seeded EMAs; fetch at least five slow-EMA periods of prior-session complete five-minute bars. Each regular session has 375 one-minute bars. Corporate-action crossings halt pending minute price-basis verification. |
| Pullback | A directional one-minute candle followed by exactly two immediately preceding adverse candles. At least one adverse candle's range overlaps EMA9, allowing 5 bps tolerance. |
| Trigger | A directional completed one-minute close beyond the adverse candles' high/low plus 1 bp buffer, and back on the trend side of the one-minute EMA. |
| Entry | Next one-minute bar's open, with adverse slippage. Signals never use incomplete five-minute candles or future volume. |
| Optional VWAP | EMA + VWAP requires signal close above/below cumulative session typical-price × volume VWAP. |
| Candle comparison | Use consecutive completed five-minute closes for trend direction; retain the directional candle/pullback/breakout rules, without EMA touch/alignment or VWAP gates. |
| Stop | Pullback low/high with 1 bp outward buffer. Reject entries whose slipped fill-to-stop distance is outside 0.05–0.5%. |
| Target / time | 1.5 initial price-risk R target; exit after 15 minutes or at 15:15 IST, whichever occurs first. Stops/targets may exit sooner. |
| Risk | 0.1% marked equity per trade, including modeled stop-exit costs; maximum three concurrent positions. |
| Re-entry | Five-minute cooldown after exit; up to three trades per symbol per session. No same-bar re-entry after an intrabar exit. |
| Daily loss pause | At 1% loss from session-start equity, latch a pause on new entries. Existing protective exits continue; gaps can exceed the threshold. |
| Liquidity proxy | Quantity at most 1% of the completed signal-minute volume. This does not establish executable liquidity at the next open. |
| Hours | Entries from 09:45 through 14:30 IST; mandatory exit at the 15:15 bar open. Special sessions are skipped. |
| Costs | Initially 10 bps slippage per side and 10 bps buy/sell charges. Supply assumptions appropriate to the experiment; these are not a verified broker/tax schedule. |

## Accounting and timing

One shared cash pool is processed minute by minute, in prior-turnover candidate order
(symbol order breaks ties). Each long or short reserves its full entry notional plus
entry fee. Short-sale proceeds never increase buying power. Open-price exits can fund
open-price entries; intrabar stop/target proceeds can only fund subsequent minutes.
Capital is reused after exits; leverage is unavailable.

Stop gaps fill at the open. Favorable target gaps fill at the open. Within a candle,
stop takes precedence when both stop and target are touched. New positions' stops
and targets apply during the entry minute. Time/cutoff exits use the bar open before
the candle's high/low is examined. Stops stay fixed for this first setup.

Position size is limited by modeled stop risk, available cash, marked equity divided
by the position cap, and the volume proxy. Trade R uses initial fill-to-price-stop
risk; net P&L includes both transaction fees and slipped entry/exit prices.

Drawdown tracks minute-close marked equity, including entry fees but excluding
estimated liquidation costs and intraminute extrema. The daily equity curve shows
session-end cash. Reports include long/short and morning/midday/afternoon attribution,
holding time, turnover, cost impact and daily loss pauses. Earlier/later segments are
diagnostics on a known sample, not an untouched holdout.

## Reproducibility and boundaries

Saved runs freeze daily candles, one-minute sessions, universe, configuration,
input hashes and source provenance. Replays fail on missing/changed inputs rather
than fetching substitutes. Increasing scan size or warmup can require unavailable
frozen stock-sessions and therefore fail deliberately. Trade charts use the frozen
session and show indicator values known at each candle's open; the signal records
its actual completed-close indicators separately.

One-minute OHLCV cannot establish seconds-level fill quality, spreads, queue priority,
intraminute ordering, circuit restrictions or short-sale eligibility. Minute corporate
action adjustments and historical membership remain unverified. An adverse cost
stress and a genuinely untouched date window are required before judging an edge.

## Forward paper workflow

1. Load daily history and save an Upstox access token in Settings.
2. On **Scalping**, select **Create paper portfolio**, enter allocated capital,
   choose direction and confirmations, and acknowledge the simulation assumptions.
   Capital has no default and remains fixed after creation. The captured universe
   also remains fixed. No portfolio or runner is created automatically.
3. Select **Start quote runner**. The separate Python process waits for the first
   eligible weekday after creation, then freezes prior-session selection and minute
   warmup. Refresh daily coverage before each new session; stale daily history blocks
   preparation. A valid token and Upstox full-feed permission are required.
4. **Pause entries** takes effect immediately while protective exits continue.
   **Flatten & stop runner** requests liquidation on fresh regular-session quotes
   before the process exits. If markets are closed or the feed is unavailable, open
   positions remain recorded and the runner reports that it needs attention.
5. Inspect open positions, closed trade portions and observed simulated fills.
   **Export full ledger** includes every fill's book, signal, context hash and costs.
6. Configuration changes apply when the next session context is frozen. Existing
   positions keep their recorded stop, target and holding/cutoff rules. Exit costs use
   the current session's frozen assumptions. Optional automatic startup launches this
   runner when the dashboard starts; the default is off.

The runner uses the Upstox V3 binary protobuf full feed and subscribes to selected
equities plus held instruments. Initial snapshots cannot fill trades. NSE equity
`NORMAL_OPEN` status and a valid, uncrossed book are required. Quotes must be no more
than three seconds old by default and cannot be future-dated. Closed-market and stale
quotes cannot enter, mark or liquidate positions.

Completed one-minute REST candles, requested in background threads after a two-second
publication grace, drive the same candle/EMA/VWAP rules as research. Feed OHLC and
sampled ticks do not construct signal candles. Full regular-session prefixes must be
continuous from 09:15; revised processed candles latch an entry block. Default entries
expire eight seconds after signal close. REST/feed delays skip opportunities rather
than recording historical or next-open fills after the fact. This latency makes paper
results different from the idealized research next-open model.

Long entries use observed ask and exits use bid; shorts use the reverse. Adverse
configured slippage and positive charges apply to both sides. Each fill is capped by
the displayed quantity at that side of the book. Entry sizing also applies the completed
signal-minute volume cap, stop risk, cash and position limits. Both directions reserve
full notional plus fees. An exit may be partial; once triggered, its intent remains
latched until the remaining shares can exit on subsequent fresh quotes. Repeated depth
updates do not prove replenishment or executable liquidity, and queue position,
circuits, fees and short eligibility remain unverified.

Atomic portfolio replacement commits cash, positions, trades, fills and the fill
watermark together. Cross-process locks protect controls and portfolio mutations and
permit one runner per data directory. Restart/reconnect discards pending entries and
retains exposure and committed fills. Previous-day exposure, or exposure with a broken
session context, enters recovery liquidation before new signals/history preparation.
No missed historical exits are fabricated. A holiday, suspended symbol, feed outage or
missing depth can therefore leave a paper position open beyond its intended cutoff.

Marks checkpoint every ten seconds and may become stale during outages; the dashboard
reports stale held symbols. Paper drawdown is based on processed quote marks/checkpoints,
not all exchange ticks. This implementation has synthetic transport/recovery tests;
an authenticated market-hours observation run and untouched research validation remain
necessary before judging execution quality or an edge.

Implementation: `core/research/scalping.py`, parameterized
`core/research/intraday_data.py`, API endpoints and shared dashboard reporting.
Streaming implementation: `core/market_data/upstox_stream.py`,
`core/portfolio/scalping_paper.py`, `scalping_runner.py`, `scalping_control.py`
and `locking.py`. Tests: `tests/test_scalping.py`, `tests/test_scalping_paper.py`
and `tests/test_scalping.cjs`.
